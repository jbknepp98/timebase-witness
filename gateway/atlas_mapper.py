"""Handoffs: profile an OPC UA namespace and have Claude plan the move into Timebase.

The gateway already holds each server's browsed address space and live values. This module
  1. profiles it deterministically (tree, repeated equipment patterns, types, units, observed values),
  2. runs a Claude tool loop over read-only tools so the model can drill into the namespace, and
  3. streams the run (status, reasoning summary, tool calls, the plan) to the browser as events.

The data path is source -> Collector -> Historian dataset -> Connect -> Atlas, and one run yields
a handoff for each step:
  - Collector: a logging instance that historizes the server. The model proposes the dataset, topics,
    topic definition, fields and exclusion filter with propose_collector_instance; Witness validates them
    against the namespace and fills in the connection settings itself (never the password).
  - Connect: a Timebase.Historian connector that serves that dataset to Atlas, plus a description of
    the dataset (tag naming, hierarchy fields, data types, units, sample tags). Witness writes it from
    the validated Collector plan; the model is not involved.
  - Atlas: a brief for Gage in Atlas (Domain Summary in Gage's interview format, source bindings through
    the Connect connector for the mapper step, prerequisites outside Atlas).
Nothing is written to Atlas, Connect, Collector or Historian from here.
"""
import asyncio
import json
import os
import re
import time
from collections import defaultdict

import anthropic

import hints

MODEL = os.environ.get("LOOKOUT_AGENT_MODEL", "claude-opus-5-5")
EFFORT = os.environ.get("LOOKOUT_AGENT_EFFORT", "high")
MAX_TURNS = int(os.environ.get("LOOKOUT_AGENT_MAX_TURNS", "12"))

# Snapshot of the shared Atlas vocabulary (atlas-common, isa95-equipment) the plan should reuse.
# Gage's architect re-checks the live libraries before it builds, so this only steers the draft.
ATLAS_VOCABULARY = {
    "note": "Snapshot of shared Atlas libraries. Gage's architect re-inspects the live libraries before building.",
    "atlas-common": {
        "dataTypes": {"TVQ": {"fields": ["Timestamp: xsd:dateTime (time axis)", "Value: open - pin to xsd:double | xsd:string | xsd:boolean", "Quality: xsd:integer"],
                              "use": "Every live/historian signal. Pin Value per property (TVQ{Value=xsd:double})."}},
        "entityTypes": {"Tag": "Abstract-ish signal entity with Data (TVQ), Description, Format, UOM. Use only when signals are first-class things; prefer TVQ properties on equipment.",
                        "Folder": "Plain grouping node, with folderContains."},
        "relationships": ["contains (containment, NodeBase->NodeBase)", "connectsTo", "relatesTo", "sameAs", "feeds (abstract, derive your own)"],
    },
    "isa95-equipment": {
        "entityTypes": {
            "Equipment": "abstract root", "Enterprise": "Equipment", "Site": "Equipment", "Area": "Equipment",
            "WorkCenter": "abstract, Equipment", "ProductionLine": "WorkCenter", "ProductionUnit": "WorkCenter (continuous/batch process unit)",
            "StorageZone": "WorkCenter", "WorkUnit": "abstract, Equipment", "Unit": "WorkUnit (process equipment such as a tank, pasteurizer)",
            "WorkCell": "WorkUnit (discrete station such as a filler, capper, conveyor)", "StorageUnit": "WorkUnit",
        },
        "relationships": {
            "equipmentContains": "abstract Equipment->Equipment", "enterpriseContains": "Enterprise->Site", "siteContains": "Site->Area",
            "areaContains": "Area->WorkCenter", "productionLineContains": "ProductionLine->WorkCell", "productionUnitContains": "ProductionUnit->Unit",
            "storageZoneContains": "StorageZone->StorageUnit", "equipmentContainsTag": "Equipment->Tag",
        },
        "rule": "Derive equipment from the ISA-95 level it sits at; narrow the level's containment relationship rather than inventing parallel ones.",
    },
}

SYSTEM_PROMPT = """You are the Witness namespace mapper for Timebase. You study the live address space of an industrial OPC UA server and write a modeling brief that Gage, the Timebase Atlas assistant, can build into an Atlas domain without interviewing anyone.

## How Gage will use your brief
Gage runs its model-domain pipeline: architect (plans the ontology from a Domain Summary), builder (creates types), mapper (writes .map.json instance maps with property bindings), reviewer (compiles and checks). Your Domain Summary replaces Gage's interview, so it must use Gage's exact Domain Summary format. Your Source Bindings section is what Gage's mapper uses to bind each property to live data.

## Work method
1. Call get_namespace_profile first. It lists the object tree, repeated patterns (objects that share the same set of variables) and observed values.
2. Call inspect_branch on representative objects (one per pattern, plus anything unusual) to see each variable's data type, units, writability, description and observed values. Do not inspect every object when a pattern already covers it.
3. Call get_atlas_vocabulary once to see which shared types to reuse.
4. Call propose_collector_instance with the logging plan (see "Collector instance" below). It answers with how many variables each subscription matches and sample tag names; if it reports problems, fix them and call it again.
5. Write the brief. Stop calling tools once you have what you need: be efficient, a typical server needs 4-7 tool calls.

## Modeling rules (from Gage's architect)
- Master data is an Entity Type (sites, areas, lines, equipment). Transactional/streaming data is never an entity: every live variable becomes a property ranged at atlas-common:TVQ with Value pinned: Double/Float/Int -> xsd:double, Boolean -> xsd:boolean, String -> xsd:string.
- Objects that share the same variable set are one Entity Type, derived from the ISA-95 level they sit at (process equipment such as tanks, pasteurizers, boilers -> isa95-equipment:Unit; discrete stations such as fillers, cappers, conveyors -> isa95-equipment:WorkCell; plant -> Site; functional groupings such as Processing/Packaging/Utilities -> Area or a WorkCenter, say which and why). Name types in PascalCase without instance numbers (MixTank, not MixTank101). Name properties in PascalCase too, keeping the server's browse name where it is already a good name (LevelPct, TempSetpointC); relationships are camelCase.
- Variables that are configuration rather than measurement (setpoints, writable values) are still TVQ properties when they come from the server; say they are setpoints in the note.
- String variables whose observed values form a small closed set (states such as Filling/Mixing/Draining) are candidates for an Enumeration Type: list the observed values and say the list may be incomplete.
- Units come from EngineeringUnits or a trailing [unit] in the description. Record them as a static UOM-style property only if the type needs it; otherwise put the unit in the property note.
- Only real hierarchy uses containment. Use the ISA-95 level relationships (siteContains, areaContains, productionUnitContains, productionLineContains) where they fit. When a level is missing, narrow `isa95-equipment:equipmentContains` and name the new relationship for its containing level (e.g. `areaContainsUnit`), never after a verb unrelated to the hierarchy and never after both endpoints.
- Simulator or diagnostic nodes (heartbeats, counters about the server itself) are not plant equipment: list them under Open Questions or leave them out and say so.
- Never invent equipment, variables or values that are not in the namespace. If something is ambiguous, put it in Open Questions.
- Do not raise connection credentials or security settings as open questions: the profile states the user and security policy the gateway connects with, and the Prerequisites section should repeat them.
- The profile says how long Witness has observed the server. State lists and value ranges come only from that window: say so where it matters, without guessing at values you did not see.

## Collector instance
Besides the Atlas brief you plan a Timebase Collector OPC UA instance that logs this server's live measurements into Timebase Historian. Witness fills in the connection (URL, user, security) itself; you decide only:
- name: the Collector instance name, PascalCase, e.g. DemoPlantOpcUa.
- dataset: the Historian dataset to write to, PascalCase, normally the same as the name.
- subscriptions: usually one. topics are dot-joined browse paths from under Objects with `+` (one level) and `#` (everything below, last only), e.g. `DemoPlant.#` or `DemoPlant.Processing.#`. Cover exactly the branches the profile shows; do not reach outside them.
- topicDefinition: dot-delimited lowercase names for the leading path segments, matching the hierarchy you found, e.g. `plant.area.equipment.signal`. It must have as many segments as the typical variable path.
- fields: metadata on every tag. Use `[Topic:key]` placeholders for the hierarchy levels (Plant, Area, Equipment...) and a constant Source naming the server product.
- excludeRegex: a case-sensitive regex on the tag name (the dot-joined path) for variables that should not be historized: static nameplate or configuration values that never changed during observation, and simulator or server diagnostics. Use "" when everything should be logged. Setpoints that operators change are kept.
- intervalMs: publishing interval, normally 1000.
- notes: short bullets a reviewer should check (what you excluded and why, anything uncertain).

## Binding paths
Atlas never reads the server directly. The data path is: the Collector instance you propose historizes the server into a Timebase Historian dataset, a Timebase Connect Historian connector serves that dataset, and Atlas binds through that connector. A binding path is `{CONNECTOR}/{DATASET}/{TagName}` where TagName is the Historian tag name, which is the dot-joined browse path from under Objects, e.g. `{CONNECTOR}/{DATASET}/DemoPlant.Processing.MixTank101.LevelPct`. The tools give you each variable's binding path; write `{CONNECTOR}` and `{DATASET}` literally - Witness fills in the dataset from your Collector plan, and the connector id exists only after Gage creates the connector. For a series of instances, write one binding template per property using the instance-map column placeholder, e.g. `{CONNECTOR}/{DATASET}/DemoPlant.Processing.[Unit].LevelPct`.
Only variables your Collector plan logs exist in Historian. Never bind a property to a variable your excludeRegex removes: leave such a property out of the model, or keep it unbound and say so in Mapping Notes.

## Output
Reply with the brief only, as Markdown, with exactly these top-level sections in this order (no preamble):

# Domain Summary: {domain name}
Use Gage's format exactly:
## Overview, ## Entity Types (master data) with ### {Type} (derived from {Base}) - write the Base type's prefixed name in the parentheses, no braces and - **{Property}**: {xsd type | TVQ{Value=xsd:...}} - note, ## Data Types (transactional records) (write "None - every signal is a TVQ property" if none), ## Relationship Types with ### {name} (contains|relates) and - {Source} --{name}--> {Target}, ## Library Reuse Candidates, ## Instance Patterns (### {grouping} then - {Type}: {count} instances, told apart by ...), ## Hierarchies, ## Open Questions.

# Source Bindings
Written for Gage's mapper, which authors every definition as a map (one-item maps for single instances) and keeps instance ids fully qualified.
- One table for entity definitions: Definition id | Type | instanceId template | label template | map columns (name: data) | property -> binding template. instanceId templates are the full dot path mirroring the browse path (`DemoPlant.Processing.[Unit]`); label templates are short human-readable names from a Label column (`Mix Tank 101`), never the raw browse name and never the ancestor path.
- One table for relationship definitions: Definition id | relationship | source template | target template | map columns. Every parent -> child series gets a row, on the same columns as the child series.
- Then the single root instance (a plain definition with no map).

# Prerequisites Outside Atlas
What must exist before mapper's bindings resolve: the Collector instance logging into the dataset, and the Connect Historian connector serving it (Witness writes handoffs for both, so just name them in order); anything else you found.

# Mapping Notes
Up to 8 bullets on decisions a reviewer should check (type choices, skipped nodes, enum candidates, anything that looked inconsistent).

Do not repeat the Collector plan in the brief: Witness writes the Collector handoff from your propose_collector_instance call."""

TOOLS = [
    {
        "name": "get_namespace_profile",
        "description": "Overview of the OPC UA server's address space: server identity, binding path template, object tree with variable counts, repeated patterns (objects sharing the same variable set, which usually means one entity type), data type and unit statistics. Call this first.",
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
        "eager_input_streaming": True,
    },
    {
        "name": "inspect_branch",
        "description": "Every variable under one object (recursively, up to 120): NodeId, browse path, Connect binding path, data type, units, writable or read-only, description, current value and quality, and what Witness observed (update count, rate, min/max, distinct string values). Use on representative objects.",
        "input_schema": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Object browse path as shown in the profile, slash-separated, e.g. DemoPlant/Processing/MixTank101"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        "strict": True,
        "eager_input_streaming": True,
    },
    {
        "name": "propose_collector_instance",
        "description": "Propose the Timebase Collector OPC UA instance that logs this server into Historian. Witness validates the topics and exclusion filter against the namespace and answers with matched and excluded variable counts and sample tag names. Call again with fixes if it reports problems.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Collector instance name, PascalCase"},
                "dataset": {"type": "string", "description": "Historian dataset name, PascalCase"},
                "subscriptions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "topics": {"type": "array", "items": {"type": "string"}, "description": "Dot-joined browse paths with + and # wildcards"},
                            "topicDefinition": {"type": "string", "description": "Dot-delimited names for the leading path segments"},
                            "intervalMs": {"type": "integer", "description": "Publishing interval in ms"},
                            "excludeRegex": {"type": "string", "description": "Case-sensitive regex on the tag name; empty for none"},
                            "fields": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "value": {"type": "string"}}, "required": ["name", "value"], "additionalProperties": False}},
                        },
                        "required": ["topics", "topicDefinition", "intervalMs", "excludeRegex", "fields"],
                        "additionalProperties": False,
                    },
                },
                "notes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name", "dataset", "subscriptions", "notes"],
            "additionalProperties": False,
        },
        "strict": True,
        "eager_input_streaming": True,
    },
    {
        "name": "get_atlas_vocabulary",
        "description": "Shared Atlas library types to reuse (atlas-common TVQ/Tag/Folder and the ISA-95 equipment levels with their containment relationships).",
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        "strict": True,
        "eager_input_streaming": True,
    },
]

from source_model import UNIT_RE, clean_description, security_text, units_of  # noqa: E402,F401  (shared helpers)
import adapters  # noqa: E402


def tag_name(info):
    """Historian tag name Collector gives a variable: the dot-joined browse path."""
    return info["path"].replace("/", ".")


def binding_path(info):
    return "{CONNECTOR}/{DATASET}/" + tag_name(info)


class NamespaceView:
    """What the agent's tools read: the source model of one connection (OPC UA server or MQTT broker)."""

    def __init__(self, server):
        self.s = server

    def model(self):
        return adapters.build(self.s)

    def profile(self):
        return self.model().profile()

    def inspect(self, path):
        return self.model().inspect(path)


# ---------------------------------------------------------------------- Collector handoff
# Witness's policy names -> Timebase Collector OPC UA plugin names
COLLECTOR_POLICY = {"None": "None", "Basic256Sha256": "Basic256Sha256",
                    "Aes128Sha256RsaOaep": "Aes128_Sha256_RsaOaep", "Aes256Sha256RsaPss": "Aes256_Sha256_RsaPss"}
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


def topic_matches(pattern, path):
    """Collector OPC UA topic match: dot-delimited, case-sensitive, + one level, # the rest (last only)."""
    pat, segs = pattern.split("."), path.split(".")
    for i, p in enumerate(pat):
        if p == "#":
            return i < len(segs)
        if i >= len(segs) or (p != "+" and p != segs[i]):
            return False
    return len(pat) == len(segs)


def validate_collector(server, plan):
    """Check the model's plan against the namespace. Returns (report, problems)."""
    variables = sorted(n["path"].replace("/", ".") for n in server.nodes.values() if n["nodeClass"] == "Variable")
    problems, subs = [], []
    if not NAME_RE.match(plan.get("name") or ""):
        problems.append("name must be PascalCase letters and digits, starting with a letter")
    if not NAME_RE.match(plan.get("dataset") or ""):
        problems.append("dataset must be PascalCase letters and digits, starting with a letter")
    if not plan.get("subscriptions"):
        problems.append("at least one subscription is needed")
    logged = set()
    owner = {}
    for i, sub in enumerate(plan.get("subscriptions") or []):
        topics = [t.strip() for t in sub.get("topics") or [] if t.strip()]
        rep = {"subscription": i + 1, "topics": {}}
        if not topics:
            problems.append(f"subscription {i + 1} has no topics")
        for t in topics:
            if "/" in t:
                problems.append(f"topic '{t}' uses '/'; Collector topics are dot-joined")
            if "#" in t[:-1] or ("#" in t and not t.endswith(".#") and t != "#"):
                problems.append(f"topic '{t}': '#' may only be the last segment")
            n = sum(1 for v in variables if topic_matches(t, v))
            rep["topics"][t] = n
            if n == 0:
                problems.append(f"topic '{t}' matches no variable in the namespace")
        matched = [v for v in variables if any(topic_matches(t, v) for t in topics)]
        rx = sub.get("excludeRegex") or ""
        excluded = []
        if rx:
            try:
                r = re.compile(rx)
                excluded = [v for v in matched if r.search(v)]
            except re.error as e:
                problems.append(f"subscription {i + 1} excludeRegex does not compile: {e}")
        kept = [v for v in matched if v not in excluded]
        logged.update(kept)
        for v in kept:
            owner.setdefault(v, i)
        td = sub.get("topicDefinition") or ""
        keys = [k for k in td.split(".") if k]
        if not keys:
            problems.append(f"subscription {i + 1} needs a topicDefinition")
        for f in sub.get("fields") or []:
            for key in re.findall(r"\[Topic:([^\]]+)\]", f.get("value") or ""):
                if key not in keys:
                    problems.append(f"field {f.get('name')} uses [Topic:{key}] but topicDefinition has no '{key}' segment")
        depths = sorted({len(v.split(".")) for v in kept})
        if keys and depths and len(keys) > max(depths):
            problems.append(f"topicDefinition has {len(keys)} segments but the longest logged path has {max(depths)}")
        if sub.get("intervalMs") is not None and not (50 <= int(sub["intervalMs"]) <= 3_600_000):
            problems.append(f"subscription {i + 1} intervalMs should be between 50 and 3600000")
        rep.update({"matched": len(matched), "excluded": len(excluded), "logged": len(kept),
                    "pathDepths": depths, "sampleExcluded": excluded[:12], "sampleLogged": kept[:8]})
        subs.append(rep)
    report = {"ok": not problems, "problems": problems, "variablesInNamespace": len(variables),
              "variablesLogged": len(logged), "notLogged": [v for v in variables if v not in logged][:25], "subscriptions": subs}
    report["_owner"] = owner      # tag -> subscription index; run_tool strips it before the model sees the report
    return report, problems


def collector_instance(server, plan, report):
    """The Collector instance as a settings document: connection from Witness, the rest from the plan."""
    st = server.status()
    s = server.rec["settings"]
    policy = s.get("securityPolicy") or "None"
    settings = {"Url": s["endpoint"]}
    if s.get("auth") == "username" and s.get("username"):
        settings["Username"] = s["username"]
    settings["SecurityPolicy"] = COLLECTOR_POLICY.get(policy, policy)
    settings["SecurityMode"] = s.get("securityMode") if policy != "None" else "None"
    if policy != "None":
        # Witness pins the server certificate when the user asked it to; Collector has no pin, so
        # keep the same stance: trust it explicitly instead of auto-accepting.
        settings["AutoAcceptUntrusted"] = not bool(s.get("serverCertThumbprint"))
    subs = []
    for sub in plan["subscriptions"]:
        out = {"Interval": int(sub.get("intervalMs") or 1000),
               "Topics": [t.strip() for t in sub["topics"] if t.strip()],
               "TopicDefinition": sub["topicDefinition"]}
        if sub.get("excludeRegex"):
            out["Filter"] = sub["excludeRegex"]
        out["Fields"] = {f["name"]: f["value"] for f in sub.get("fields") or [] if f.get("name")}
        subs.append(out)
    settings["Subscriptions"] = subs
    return {
        "name": plan["name"], "type": "OPCUA",
        "description": f"{st['name']} ({s['endpoint']}) - planned by Witness",
        "historian": {"dataset": plan["dataset"]},
        "Settings": settings,
        "needsPassword": s.get("auth") == "username",
        "trustServerCertificate": s.get("serverCertThumbprint") or None,
        "variablesLogged": report["variablesLogged"],
        "notes": plan.get("notes") or [],
    }


def collector_brief(server, inst, settings_url):
    st = server.status()
    settings_json = json.dumps({"Settings": inst["Settings"]}, indent=2)
    pw = ("Ask the user for the OPC UA password and set `Password` in the settings yourself: Witness never exports it."
          if inst["needsPassword"] else "The server is read anonymously, so no password is needed.")
    trust = (f"Witness pins this server's certificate (SHA-1 `{inst['trustServerCertificate']}`), so `AutoAcceptUntrusted` is off. "
             "Before starting, trust that certificate in Collector's OPC UA trusted peer store, and make sure the server trusts Collector's application certificate."
             if inst["trustServerCertificate"] else
             ("`AutoAcceptUntrusted` is on because Witness accepts this server's certificate without pinning it. Make sure the server trusts Collector's application certificate."
              if inst["Settings"]["SecurityPolicy"] != "None" else "The channel is unencrypted (security policy None)."))
    notes = "\n".join(f"- {n}" for n in inst["notes"]) or "- None"
    return f"""> **For Gage in Collector:** use the **setup-collector** skill to create a new **OPCUA** collector instance from this handoff. Everything below was checked by Witness against the live namespace of `{st['name']}`; do not ask the user for settings that are given here.

# Collector Instance: {inst['name']}

| Setting | Value |
|---|---|
| Plugin type | OPCUA |
| Instance name | `{inst['name']}` |
| Description | {inst['description']} |
| Historian dataset | `{inst['historian']['dataset']}` (create it if it does not exist) |
| Variables logged | {inst['variablesLogged']} |
| Settings file | {settings_url} |

## Steps
1. `AddCollector` with type **OPCUA**, then `RenameCollector` to `{inst['name']}` and set the description above.
2. `UpdateCollectorSettings` with the settings below. {pw}
3. {trust}
4. `ListHistorians`, then `SetCollectorHistorians` to link the Historian with dataset `{inst['historian']['dataset']}`.
5. `StartCollector`, wait 10 seconds, then check `GetLogs` and `GetPreviewSnapshot`. Expect about {inst['variablesLogged']} tags.

## Settings
```json
{settings_json}
```

## Notes from Witness
{notes}
"""


# ---------------------------------------------------------------------- Connect handoff
HISTORIAN_HOST = os.environ.get("CONNECT_HISTORIAN_HOST", "historian")
HISTORIAN_PORT = int(os.environ.get("CONNECT_HISTORIAN_PORT", "4512"))
HISTORIAN_TLS = os.environ.get("CONNECT_HISTORIAN_TLS", "true").lower() not in ("0", "false", "no")


def tag_fields(tag, sub):
    """The metadata fields Collector writes on a tag, from the subscription's topic definition and fields."""
    keys = [k for k in (sub.get("TopicDefinition") or "").split(".") if k]
    segs = tag.split(".")
    seg = {k: segs[i] for i, k in enumerate(keys) if i < len(segs)}
    return {name: re.sub(r"\[Topic:([^\]]+)\]", lambda m: seg.get(m.group(1), m.group(0)), str(val))
            for name, val in (sub.get("Fields") or {}).items()}


def connect_plan(server, inst, owner):
    """The Connect handoff: a Historian connector for the Collector's dataset, and what that dataset holds."""
    dataset = inst["historian"]["dataset"]
    subs = inst["Settings"]["Subscriptions"]
    by_tag = {n["path"].replace("/", "."): n for n in server.nodes.values() if n["nodeClass"] == "Variable"}
    tags = []
    for tag in sorted(owner):
        n = by_tag.get(tag) or {}
        tags.append({"name": tag, "dataType": n.get("dataType") or "?", "units": units_of(n) if n else None,
                     "fields": tag_fields(tag, subs[owner[tag]]), "parent": tag.rsplit(".", 1)[0], "signal": tag.rsplit(".", 1)[-1]})
    types, units = defaultdict(int), defaultdict(int)
    for t in tags:
        types[t["dataType"]] += 1
        if t["units"]:
            units[t["units"]] += 1
    # fields per subscription: each has its own topic definition, so its tags carry their own field set
    fields = []
    for i, sub in enumerate(subs):
        mine = [t for t in tags if owner[t["name"]] == i]
        values = defaultdict(set)
        for t in mine:
            for k, v in t["fields"].items():
                values[k].add(v)
        fields.append({"topics": sub["Topics"], "topicDefinition": sub.get("TopicDefinition") or "", "tags": len(mine),
                       "fields": [{"name": k, "distinct": len(v), "examples": sorted(v)[:6]} for k, v in values.items()]})
    # one sample object per signal pattern (objects that log the same set of signals)
    groups = defaultdict(list)
    for t in tags:
        groups[t["parent"]].append(t)
    patterns = defaultdict(list)
    for parent, ts in groups.items():
        patterns[tuple(sorted(x["signal"] for x in ts))].append(parent)
    samples = []
    for sig, parents in sorted(patterns.items(), key=lambda kv: -len(kv[1]))[:8]:
        first = sorted(parents)[0]
        samples.append({"objects": len(parents), "example": first, "tags": sorted(groups[first], key=lambda x: x["name"])[:12]})
    settings = {"Host": HISTORIAN_HOST, "Port": HISTORIAN_PORT, "UseTls": HISTORIAN_TLS,
                "ClientName": f"Timebase.Connect.{dataset}", "Auth": {"Mode": "Host"},
                "Datasets": {dataset: {"Dataset": dataset}}, "DefaultLookback": "01:00:00"}
    return {"name": f"Historian {dataset}", "type": "Timebase.Historian", "dataset": dataset, "collector": inst["name"],
            "Settings": settings, "tagCount": len(tags), "dataTypes": dict(types), "units": dict(units),
            "fields": fields, "samples": samples, "maxDepth": max((t["name"].count(".") + 1 for t in tags), default=0)}


def connect_brief(server, plan, settings_url):
    st = server.status()
    ds = plan["dataset"]
    settings_json = json.dumps({"Settings": plan["Settings"]}, indent=2)
    types = ", ".join(f"{k} {v}" for k, v in sorted(plan["dataTypes"].items(), key=lambda kv: -kv[1])) or "none"
    units = ", ".join(f"`{k}` ({v})" for k, v in sorted(plan["units"].items(), key=lambda kv: -kv[1])[:15]) or "none reported by the server"
    blocks = []
    for grp in plan["fields"]:
        rows = "\n".join(f"| `{f['name']}` | {f['distinct']} | {', '.join(f'`{e}`' for e in f['examples'])}{' ...' if f['distinct'] > len(f['examples']) else ''} |" for f in grp["fields"]) or "| (none) | | |"
        topics = ", ".join(f"`{t}`" for t in grp["topics"])
        blocks.append(f"Tags from {topics} ({grp['tags']} tags, topic definition `{grp['topicDefinition']}`):\n\n| Field | Distinct values | Examples |\n|---|---|---|\n{rows}")
    fields = "\n\n".join(blocks)
    sample_rows = []
    for smp in plan["samples"]:
        sample_rows.append(f"\n**{smp['example']}** - {smp['objects']} object{'s log' if smp['objects'] != 1 else ' logs'} this set of signals\n\n| Tag name | Server data type | Units | Binding path |\n|---|---|---|---|")
        for t in smp["tags"]:
            sample_rows.append(f"| `{t['name']}` | {t['dataType']} | {t['units'] or ''} | `{{CONNECTOR}}/{ds}/{t['name']}` |")
    samples = "\n".join(sample_rows)
    return f"""> **For Gage in Connect:** use the **configure-historian-connector** skill to serve the Historian dataset `{ds}` to Atlas through a **Timebase.Historian** connector. Everything below was worked out by Witness from the Collector plan for `{st['name']}`; do not ask the user for settings that are given here.

# Connect Historian Connector: {ds}

| Setting | Value |
|---|---|
| Plugin type | Timebase.Historian |
| Suggested name | `{plan['name']}` |
| Historian | `{plan['Settings']['Host']}:{plan['Settings']['Port']}` ({'TLS' if plan['Settings']['UseTls'] else 'no TLS'}), signing in as this Connect host |
| Dataset entry | key `{ds}` -> dataset `{ds}` |
| Filled by | Collector instance `{plan['collector']}` (Collector handoff) |
| Expected tags | {plan['tagCount']} |
| Settings file | {settings_url} |

## Steps
1. The dataset is written by the Collector instance `{plan['collector']}`. If it is not logging yet, set it up from the Collector handoff first: until it runs, the catalog below is empty.
2. `ListConnectors`. If a **Timebase.Historian** connector already reads this Historian, add the `{ds}` entry under its `Datasets` instead of creating a second connector, and use that connector's id below.
3. Otherwise `AddConnector` with type **Timebase.Historian**, rename it to `{plan['name']}`, and `UpdateConnectorSettings` with the settings below.
4. Make sure the connector is enabled for the Atlas that will hold the domain, then `StartConnector`.
5. Wait 10 seconds, then `TestConnector`, `GetLogs` and `GetConnector`. Read the catalog path `<connector id>/{ds}`: expect about {plan['tagCount']} tags named as below.
6. Report the connector id. The Atlas handoff's bindings start with `{{CONNECTOR}}/{ds}/`, and Gage in Atlas needs that id for `{{CONNECTOR}}`.

## Settings
```json
{settings_json}
```

## What the dataset looks like

**Tag names** are the server's browse path from under Objects, joined with dots, up to {plan['maxDepth']} segments, e.g. `{plan['samples'][0]['tags'][0]['name'] if plan['samples'] else 'Plant.Area.Equipment.Signal'}`.

**Per-tag binding path** through this connector: `<connector id>/{ds}/<tag name>`. Only per-tag paths can be subscribed; `<connector id>/{ds}` is the catalog (one row per tag).

**Fields** Collector writes on each tag. Every Collector subscription has its own topic definition, so each one's tags carry their own set:

{fields}

**Data types** (as the server reports them): {types}.

**Units**: {units}.

## Sample tags
{samples}
"""


def preface(server, domain):
    st = server.status()
    bind = ("For **mapper**, use the Source Bindings section. Atlas reads the historized data through Connect: replace `{CONNECTOR}` with the id of "
            "the Timebase.Historian connector set up from the Connect handoff (ask the user for it if you do not have it). "
            "The Collector and Connect handoffs must be done first, or the bindings will not resolve.")
    return f"""> **For Gage:** use the **model-domain** skill in **Build** mode for a new domain named `{domain}`.
> The Domain Summary below was drafted by Witness from the live OPC UA server `{st['name']}` ({st['endpoint']}) and reviewed by the user - treat it as the confirmed interview output and **skip Step 1**.
> Hand the Domain Summary to **architect**, then **builder**. {bind} Then run **reviewer** post-change.

"""


def finish(server, domain, text, dataset=None):
    """Preface plus the model's brief, with the Historian dataset filled in from the Collector plan."""
    if dataset:
        text = text.replace("{DATASET}", dataset)
    return preface(server, domain) + text


def summarize_result(name, result):
    if name == "get_namespace_profile":
        t = result.get("totals", {})
        return f"{t.get('objects', 0)} objects, {t.get('variables', 0)} variables, {len(result.get('repeatedPatterns', []))} variable patterns"
    if name == "inspect_branch":
        if "error" in result:
            return result["error"]
        return f"{len(result.get('variables', []))} variables under {result.get('object')}"
    if name == "propose_collector_instance":
        if result.get("problems"):
            return f"{len(result['problems'])} problem(s): {result['problems'][0]}"
        return f"{result['variablesLogged']} of {result['variablesInNamespace']} variables logged"
    return "isa95-equipment and atlas-common types"


class MapRun:
    """One Handoffs run. Events are queued for every subscriber (SSE)."""

    def __init__(self, server, domain, on_brief=None):
        self.on_brief = on_brief   # called with the run once the brief is complete; returns artifact metadata
        self.server = server
        self.view = NamespaceView(server)
        self.domain = domain
        self.events = []
        self.cond = asyncio.Condition()
        self.done = False
        self.brief = None
        self.collector = None      # Collector instance plan once propose_collector_instance passes
        self.connect = None        # Connect Historian connector plan, derived from the Collector plan
        self.nudged = False
        self.started = time.time()

    async def emit(self, ev):
        ev["t"] = round(time.time() - self.started, 2)
        async with self.cond:
            self.events.append(ev)
            self.cond.notify_all()

    def run_tool(self, name, args):
        if name == "get_namespace_profile":
            return self.view.profile()
        if name == "inspect_branch":
            if not isinstance(args, dict) or not isinstance(args.get("path"), str):
                raise ValueError("inspect_branch needs a string 'path'")
            return self.view.inspect(args["path"])
        if name == "get_atlas_vocabulary":
            return ATLAS_VOCABULARY
        if name == "propose_collector_instance":
            if not isinstance(args, dict):
                raise ValueError("propose_collector_instance needs an object")
            report, problems = validate_collector(self.server, args)
            owner = report.pop("_owner")
            if not problems:
                self.collector = collector_instance(self.server, args, report)
                self.connect = connect_plan(self.server, self.collector, owner)
            return report
        raise ValueError(f"unknown tool {name}")

    async def run(self):
        try:
            await self._run()
        except anthropic.AuthenticationError:
            await self.emit({"type": "error", "message": "The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in ~/mosquitto/lookout-agent.env on the Mini."})
        except anthropic.RateLimitError:
            await self.emit({"type": "error", "message": "Rate limited by the Anthropic API. Try again in a minute."})
        except anthropic.APIStatusError as e:
            await self.emit({"type": "error", "message": f"Anthropic API error {e.status_code}: {e.message}"})
        except anthropic.APIConnectionError:
            await self.emit({"type": "error", "message": "Could not reach the Anthropic API from the Mini."})
        except Exception as e:  # noqa: BLE001
            await self.emit({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            self.done = True
            async with self.cond:
                self.cond.notify_all()

    async def _run(self):
        if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
            await self.emit({"type": "error", "message": "No Anthropic API key is configured for the Witness gateway. Add ANTHROPIC_API_KEY to ~/mosquitto/lookout-agent.env on the Mini and recreate the gateway."})
            return
        if self.server.state != "connected" or not self.server.nodes:
            await self.emit({"type": "error", "message": f"{self.server.cfg['name']} is not connected, so there is no namespace to map."})
            return
        client = anthropic.AsyncAnthropic()
        await self.emit({"type": "status", "text": f"Mapping {self.server.cfg['name']} with {MODEL}"})
        messages = [{"role": "user", "content": f"Plan moving the OPC UA server `{self.server.cfg['name']}` into Timebase: an Atlas domain named `{self.domain}` and a Collector instance that logs it to Historian. Investigate with the tools, propose the Collector instance, then write the brief."}]
        usage = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
        retries = 0
        for turn in range(MAX_TURNS):
            try:
                async with client.beta.messages.stream(
                    model=MODEL,
                    max_tokens=64000,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=messages,
                    thinking={"type": "adaptive", "display": "summarized"},
                    output_config={"effort": EFFORT},
                    cache_control={"type": "ephemeral"},
                    betas=["server-side-fallback-2026-07-01"],
                    fallbacks="default",
                ) as stream:
                    async for event in stream:
                        if event.type == "content_block_start" and event.content_block.type == "thinking":
                            await self.emit({"type": "thinking_start"})
                        elif event.type == "content_block_delta":
                            if event.delta.type == "thinking_delta" and event.delta.thinking:
                                await self.emit({"type": "thinking", "delta": event.delta.thinking})
                            elif event.delta.type == "text_delta":
                                await self.emit({"type": "text", "delta": event.delta.text})
                    response = await stream.get_final_message()
                retries = 0
            except ValueError:
                # tool input JSON the SDK could not parse at all: re-issue the turn (bounded)
                retries += 1
                if retries > 2:
                    raise
                continue
            u = response.usage
            usage["input"] += u.input_tokens or 0
            usage["output"] += u.output_tokens or 0
            usage["cacheRead"] += getattr(u, "cache_read_input_tokens", 0) or 0
            usage["cacheWrite"] += getattr(u, "cache_creation_input_tokens", 0) or 0

            if response.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": response.content})
                continue
            if response.stop_reason == "refusal":
                await self.emit({"type": "error", "message": "The model declined this request."})
                return
            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses and not self.collector and not self.nudged and response.stop_reason == "end_turn":
                self.nudged = True
                await self.emit({"type": "status", "text": "Asking for the Collector plan before finishing"})
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": "Before the brief is final, call propose_collector_instance with the Collector logging plan. Then reply with the full brief again."})
                continue
            if not tool_uses:
                text = "".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    await self.emit({"type": "status", "text": "The brief hit the output limit and may be cut off."})
                self.brief = finish(self.server, self.domain, text, self.collector and self.collector["historian"]["dataset"])
                artifact = None
                if self.on_brief:
                    try:
                        artifact = self.on_brief(self)
                    except OSError as e:
                        await self.emit({"type": "status", "text": f"The brief could not be saved as a file: {e}"})
                await self.emit({"type": "done", "brief": self.brief, "artifact": artifact, "usage": usage, "model": response.model, "turns": turn + 1})
                return
            if response.stop_reason == "max_tokens":
                raise RuntimeError("a tool call was cut off by the output limit")
            results = []
            for b in tool_uses:
                await self.emit({"type": "tool", "name": b.name, "input": b.input if isinstance(b.input, dict) else {}})
                try:
                    res = self.run_tool(b.name, b.input)
                    await self.emit({"type": "tool_result", "name": b.name, "summary": summarize_result(b.name, res)})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(res, default=str)})
                except Exception as e:  # noqa: BLE001
                    await self.emit({"type": "tool_result", "name": b.name, "summary": f"error: {e}", "error": True})
                    results.append({"type": "tool_result", "tool_use_id": b.id, "is_error": True, "content": str(e)})
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": results})
        await self.emit({"type": "error", "message": f"Stopped after {MAX_TURNS} model turns without a finished brief."})
