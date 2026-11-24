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

PROMPT_CORE = """You are the Witness namespace mapper for Timebase. You study the live data of an industrial source - an OPC UA server, or an MQTT broker that may carry Sparkplug B - and write a modeling brief that Gage, the Timebase Atlas assistant, can build into an Atlas domain without interviewing anyone.

## How Gage will use your brief
Gage runs its model-domain pipeline: architect (plans the ontology from a Domain Summary), builder (creates types), mapper (writes .map.json instance maps with property bindings), reviewer (compiles and checks). Your Domain Summary replaces Gage's interview, so it must use Gage's exact Domain Summary format. Your Source Bindings section is what Gage's mapper uses to bind each property to live data.

## Work method
1. Call get_namespace_profile first. It lists the object tree, repeated patterns (objects that share the same set of variables), types the source declares (`types`), and observed values. For a broker it also lists topic groups with their payload shape and what is left out.
2. Call inspect_branch on representative objects (one per pattern, plus anything unusual) to see each variable's data type, units, writability, description and observed values. Do not inspect every object when a pattern already covers it.
3. Call get_atlas_vocabulary once to see which shared types to reuse.
4. Call propose_collector_instance with the Collector plan (see "Collector plan" below). Witness checks it and predicts every Historian tag it will write; if it reports problems, fix them and call it again.
5. Write the brief. Stop calling tools once you have what you need: be efficient, a typical server needs 4-7 tool calls.

## Modeling rules (from Gage's architect)
- Master data is an Entity Type (sites, areas, lines, equipment). Transactional/streaming data is never an entity: every live variable becomes a property ranged at atlas-common:TVQ with Value pinned: Double/Float/Int -> xsd:double, Boolean -> xsd:boolean, String -> xsd:string.
- Objects that share the same variable set are one Entity Type, derived from the ISA-95 level they sit at (process equipment such as tanks, pasteurizers, boilers -> isa95-equipment:Unit; discrete stations such as fillers, cappers, conveyors -> isa95-equipment:WorkCell; plant -> Site; functional groupings such as Processing/Packaging/Utilities -> Area or a WorkCenter, say which and why). Name types in PascalCase without instance numbers (MixTank, not MixTank101). Name properties in PascalCase too, keeping the server's browse name where it is already a good name (LevelPct, TempSetpointC); relationships are camelCase.
- Variables that are configuration rather than measurement (setpoints, writable values) are still TVQ properties when they come from the server; say they are setpoints in the note.
- String variables whose observed values form a small closed set (states such as Filling/Mixing/Draining) are candidates for an Enumeration Type: list the observed values and say the list may be incomplete.
- Types the source declares are the strongest evidence for entity types: OPC UA TypeDefinitions, Sparkplug B templates, and types from metadata topics, all listed in the profile's `types` with their members and instances. Name the entity type after the declared type without a `Type` suffix (AirCompressorType -> AirCompressor), keep its members as properties, use static properties from object hints (`hint.properties`, e.g. SiteCode) as static properties, and say in Mapping Notes where a declared type and the observed signals disagree.
- Units come from EngineeringUnits, a trailing [unit] in the description, Sparkplug engUnit or metadata topics. Record them as a static UOM-style property only if the type needs it; otherwise put the unit in the property note.
- Only real hierarchy uses containment. Use the ISA-95 level relationships (siteContains, areaContains, productionUnitContains, productionLineContains) where they fit. When a level is missing, narrow `isa95-equipment:equipmentContains` and name the new relationship for its containing level (e.g. `areaContainsUnit`), never after a verb unrelated to the hierarchy and never after both endpoints.
- Simulator or diagnostic nodes (heartbeats, counters about the server itself) are not plant equipment: list them under Open Questions or leave them out and say so.
- Never invent equipment, variables or values that are not in the namespace. If something is ambiguous, put it in Open Questions.
- Do not raise connection credentials or security settings as open questions: the profile states the user and security policy the gateway connects with, and the Prerequisites section should repeat them.
- The profile says how long Witness has observed the server. State lists and value ranges come only from that window: say so where it matters, without guessing at values you did not see.

{SOURCE}

## Binding paths
Atlas never reads the source directly. The data path is: the Collector plan you propose historizes the source into one Timebase Historian dataset, a Timebase Connect Historian connector serves that dataset, and Atlas binds through that connector. A binding path is `{CONNECTOR}/{DATASET}/<Historian tag name>`. Witness predicts every tag name from your Collector plan: inspect_branch gives each signal's `bindingPath` (before your plan passes it assumes default settings; once propose_collector_instance passes it is exact, and signals your plan does not log have `bindingPath` null and `logged` false). The passing plan's report also gives `bindingExamples`. Write `{CONNECTOR}` and `{DATASET}` literally - Witness fills in the dataset, and the connector id exists only after Gage creates the connector. For a series of instances, write one binding template per property using the instance-map column placeholder in place of the part that varies, e.g. `{CONNECTOR}/{DATASET}/DemoPlant.Processing.[Unit].LevelPct` or `{CONNECTOR}/{DATASET}/Plant1/Line1/[Device]/Motor1.Speed`.
Only signals your Collector plan logs exist in Historian. Never bind a property to a signal the plan leaves out: leave such a property out of the model, or keep it unbound and say so in Mapping Notes.

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
What must exist before mapper's bindings resolve: the Collector instance(s) logging into the dataset, and the Connect Historian connector serving it (Witness writes handoffs for both, so just name them in order); anything else you found.

# Mapping Notes
Up to 8 bullets on decisions a reviewer should check (type choices, skipped nodes, enum candidates, anything that looked inconsistent).

Do not repeat the Collector plan in the brief: Witness writes the Collector handoff from your propose_collector_instance call."""

SOURCE_OPCUA = """## Collector plan
Besides the Atlas brief you plan the Timebase Collector logging that historizes this server's live measurements: one instance with plugin `OPCUA`. Witness fills in the connection (URL, user, security) itself; you decide only:
- dataset: the Historian dataset to write to, PascalCase, normally the same as the instance name.
- the instance: plugin `OPCUA`, name in PascalCase (e.g. DemoPlantOpcUa), notes (short bullets a reviewer should check: what you excluded and why, anything uncertain).
- subscriptions: usually one. topics are dot-joined browse paths from under Objects with `+` (one level) and `#` (everything below, last only), e.g. `DemoPlant.#` or `DemoPlant.Processing.#`. Cover exactly the branches the profile shows; do not reach outside them.
- topicDefinition: dot-delimited lowercase names for the leading path segments, matching the hierarchy you found, e.g. `plant.area.equipment.signal`. It must have as many segments as the typical variable path.
- fields: metadata on every tag. Use `[Topic:key]` placeholders for the hierarchy levels (Plant, Area, Equipment...) and a constant Source naming the server product.
- excludeRegex: a case-sensitive regex on the tag name (the dot-joined path) for variables that should not be historized: static nameplate or configuration values that never changed during observation, and simulator or server diagnostics. Use "" when everything should be logged. Setpoints that operators change are kept.
- intervalMs: publishing interval, normally 1000.
Tag names are the dot-joined browse path, e.g. `DemoPlant.Processing.MixTank101.LevelPct`."""

SOURCE_BROKER = """## Collector plan
Besides the Atlas brief you plan the Timebase Collector logging that historizes this broker: one or more instances, all writing to the same Historian dataset. Plain MQTT topics need an instance with plugin `MQTT`; Sparkplug B (`spBv1.0/...`) needs a separate instance with plugin `SparkplugB`. Witness fills in the broker connection itself and never exports a password; you decide:
- dataset: the Historian dataset, PascalCase (e.g. PlantMqtt).
- instances: name in PascalCase per instance (e.g. PlantMqtt, PlantSparkplug), plugin, subscriptions, notes (short bullets a reviewer should check).

MQTT subscriptions (topics are slash-delimited MQTT filters with `+` and `#`):
- The profile's `groups` are topic groups that share a payload shape and settings. Propose one subscription per group, or one per branch that covers several groups with the same shape. Topics on the connection's "Not for Handoffs" list (e.g. what Timebase Bridge publishes, $SYS) and metadata topics are already left out; never plan them.
- type: Simple (bare values), JsonStructured (value objects, or arrays of name/value metrics), JsonSimple (other JSON records). Leave type and the payload fields (valueField, qualityField, uomFields, timestampFields, timestampType, tagnameFields, tagnameIncludesTopic) out unless you have a reason: Witness fills them in from the detected shape.
- tagnameDelimiter: leave it out (Witness uses `.`, so tag names are dot-joined like OPC UA browse paths). ignoreParts: literal text removed from every tag name, after the delimiter is applied, e.g. `probe.structured.` to drop a fixed topic prefix.
- topicDefinition: slash-delimited lowercase names for the leading topic levels, e.g. `enterprise/site/area/equipment/signal`; fields use `[Topic:key]` for hierarchy levels, `[Payload:path]` only when the payload carries identity, plus a constant Source.
- excludeRegex: case-sensitive regex on the tag name for signals not worth historizing (diagnostics, simulator heartbeats, static values that never change).
- JSON Simple drops array keys and indexes, so records with arrays of objects make tag names collide. Witness reports collisions as problems: fix them (exclude the array with excludeRegex, or plan those topics differently) - never leave them.
- Unsupported topics (not JSON and not a single value) cannot be logged; mention them under Open Questions.

Sparkplug B subscriptions (plugin SparkplugB):
- topics: `spBv1.0/<group>/#`, one per Sparkplug group you plan. Tag names and fields are automatic: `Group/Node[/Device]/<metric>` with the metric's folders, template members `<instance>.<member>`, fields GroupID, NodeID, DeviceID and Template*.
- Decide only excludeRegex, ignoreParts (e.g. `Group/Node/` to shorten names) and includeHousekeeping (keep it on: written commands let setpoints be compared with process values).
- Sparkplug templates are entity types: use the template's name, members, parameters and nesting."""


def system_prompt(kind):
    return PROMPT_CORE.replace("{SOURCE}", SOURCE_OPCUA if kind == "opcua" else SOURCE_BROKER)


SYSTEM_PROMPT = system_prompt("opcua")

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
        "description": "Propose the Timebase Collector plan that historizes this source: the Historian dataset and one or more Collector instances (plugin OPCUA, MQTT or SparkplugB) with their subscriptions. Witness fills in payload settings you leave out from the detected shapes, checks the plan against what the source publishes, and predicts every tag it will write (names, data types, units). It answers with problems to fix, warnings, predicted tag counts, sample tags and binding examples. Call again with fixes if it reports problems.",
        "input_schema": {
            "type": "object",
            "properties": {
                "dataset": {"type": "string", "description": "Historian dataset name, PascalCase"},
                "instances": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "plugin": {"type": "string", "enum": ["OPCUA", "MQTT", "SparkplugB"]},
                            "name": {"type": "string", "description": "Collector instance name, PascalCase"},
                            "subscriptions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "topics": {"type": "array", "items": {"type": "string"}, "description": "OPCUA: dot-joined browse paths; MQTT/SparkplugB: slash-delimited topic filters; + and # wildcards"},
                                        "topicDefinition": {"type": "string", "description": "Names for the leading path levels (OPCUA dot-delimited, MQTT slash-delimited)"},
                                        "fields": {"type": "array", "items": {"type": "object", "properties": {"name": {"type": "string"}, "value": {"type": "string"}}, "required": ["name", "value"]}},
                                        "excludeRegex": {"type": "string", "description": "Case-sensitive regex on the tag name; empty for none"},
                                        "intervalMs": {"type": "integer", "description": "OPCUA only: publishing interval in ms"},
                                        "type": {"type": "string", "enum": ["Simple", "JsonSimple", "JsonStructured"], "description": "MQTT only; leave out to use the detected shape"},
                                        "ignoreParts": {"type": "array", "items": {"type": "string"}},
                                        "tagnameDelimiter": {"type": "string"},
                                        "tagnameIncludesTopic": {"type": "boolean"},
                                        "tagnameFields": {"type": "array", "items": {"type": "string"}},
                                        "timestampFields": {"type": "array", "items": {"type": "string"}},
                                        "timestampType": {"type": "string", "enum": ["String", "UNIXSeconds", "UNIXMilliseconds"]},
                                        "valueField": {"type": "string"},
                                        "qualityField": {"type": "string"},
                                        "uomFields": {"type": "array", "items": {"type": "string"}},
                                        "includeHousekeeping": {"type": "boolean", "description": "SparkplugB only"},
                                        "includeTransient": {"type": "boolean", "description": "SparkplugB only"},
                                    },
                                    "required": ["topics"],
                                },
                            },
                            "notes": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["plugin", "name", "subscriptions"],
                    },
                },
                "notes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["dataset", "instances"],
        },
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
import collector_plan  # noqa: E402
import handoff_text  # noqa: E402
from collector_plan import (COLLECTOR_POLICY, HISTORIAN_HOST, HISTORIAN_PORT, HISTORIAN_TLS, NAME_RE,  # noqa: E402,F401
                            collector_instance, connect_plan, tag_fields, topic_matches, validate_collector)


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
def opcua_section(inst, settings_url):
    """One OPCUA instance in the Collector handoff (handoff_text.collector_brief)."""
    settings_json = json.dumps({"Settings": inst["Settings"]}, indent=2)
    pw = ("Ask the user for the OPC UA password and set `Password` in the settings yourself: Witness never exports it."
          if inst["needsPassword"] else "The server is read anonymously, so no password is needed.")
    trust = (f"Witness pins this server's certificate (SHA-1 `{inst['trustServerCertificate']}`), so `AutoAcceptUntrusted` is off. "
             "Before starting, trust that certificate in Collector's OPC UA trusted peer store, and make sure the server trusts Collector's application certificate."
             if inst["trustServerCertificate"] else
             ("`AutoAcceptUntrusted` is on because Witness accepts this server's certificate without pinning it. Make sure the server trusts Collector's application certificate."
              if inst["Settings"]["SecurityPolicy"] != "None" else "The channel is unencrypted (security policy None)."))
    notes = "\n".join(f"- {n}" for n in inst["notes"]) or "- None"
    return f"""## 1. Collector Instance: {inst['name']} (OPCUA)

| Setting | Value |
|---|---|
| Plugin type | OPCUA |
| Instance name | `{inst['name']}` |
| Description | {inst['description']} |
| Historian dataset | `{inst['historian']['dataset']}` (create it if it does not exist) |
| Variables logged | {inst['variablesLogged']} |
| Settings file | {settings_url} |

### Steps
1. `AddCollector` with type **OPCUA**, then `RenameCollector` to `{inst['name']}` and set the description above.
2. `UpdateCollectorSettings` with the settings below. {pw}
3. {trust}
4. `ListHistorians`, then `SetCollectorHistorians` to link the Historian with dataset `{inst['historian']['dataset']}`.
5. `StartCollector`, wait 10 seconds, then check `GetLogs` and `GetPreviewSnapshot`. Expect about {inst['variablesLogged']} tags.

### Settings
```json
{settings_json}
```

### Notes from Witness
{notes}
"""


def preface(server, domain):
    st = server.status()
    kind = "OPC UA server" if server.kind == "opcua" else "MQTT broker"
    bind = ("For **mapper**, use the Source Bindings section. Atlas reads the historized data through Connect: replace `{CONNECTOR}` with the id of "
            "the Timebase.Historian connector set up from the Connect handoff (ask the user for it if you do not have it). "
            "The Collector and Connect handoffs must be done first, or the bindings will not resolve.")
    return f"""> **For Gage:** use the **model-domain** skill in **Build** mode for a new domain named `{domain}`.
> The Domain Summary below was drafted by Witness from the live {kind} `{st['name']}` ({st['endpoint']}) and reviewed by the user - treat it as the confirmed interview output and **skip Step 1**.
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
        n = len(result.get("instances") or [])
        return f"{result.get('tagsPredicted', 0)} tags predicted for dataset {result.get('dataset')}" + (f" from {n} instances" if n > 1 else "")
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
        self.kind = server.kind
        self.name = server.rec["name"]
        self.collector = None      # passing Collector plan: {"dataset", "instances": [settings documents], "tagsPredicted"}
        self.owner = {}            # predicted tag -> where it comes from (collector_plan.validate)
        self.tags = {}             # signal source key -> predicted tag (handoff_text.tag_index)
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
            return self.with_plan_bindings(self.view.inspect(args["path"]))
        if name == "get_atlas_vocabulary":
            return ATLAS_VOCABULARY
        if name == "propose_collector_instance":
            if not isinstance(args, dict):
                raise ValueError("propose_collector_instance needs an object")
            r = collector_plan.validate(self.server, args)
            report = r["report"]
            if not r["problems"]:
                plan = collector_plan.to_v2(args)
                self.collector = {"dataset": plan["dataset"], "instances": r["instances"], "tagsPredicted": report["tagsPredicted"]}
                self.owner, self.tags = r["owner"], handoff_text.tag_index(r["owner"])
                self.connect = handoff_text.connect_plan(self.view.model(), self.collector, self.owner)
                report["bindingExamples"] = [{"object": smp["example"], "type": smp.get("type"),
                                              "bindings": [f"{{CONNECTOR}}/{{DATASET}}/{t['name']}" for t in smp["tags"][:4]]}
                                             for smp in self.connect["samples"][:6]]
            return report
        raise ValueError(f"unknown tool {name}")

    def with_plan_bindings(self, res):
        """Once a plan passes, each signal's binding uses the tag name the plan predicts (null when not logged)."""
        if not self.tags or "variables" not in res:
            return res
        prefix = "{CONNECTOR}/{DATASET}/"
        for row in res["variables"]:
            default = (row.get("bindingPath") or "")[len(prefix):]
            tag = self.tags.get(handoff_text.signal_key({"origin": row.get("origin"), "tag": default}))
            row["bindingPath"] = prefix + tag if tag else None
            row["logged"] = bool(tag)
        return res

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
        what = "OPC UA server" if self.kind == "opcua" else "MQTT broker"
        if self.server.state != "connected":
            await self.emit({"type": "error", "message": f"{self.name} is not connected, so there is nothing to map."})
            return
        if not self.view.model().signals():
            await self.emit({"type": "error", "message": f"Nothing to plan on {self.name}: no signals yet, or every topic is excluded or metadata. Let Witness watch it for a few minutes."})
            return
        client = anthropic.AsyncAnthropic()
        await self.emit({"type": "status", "text": f"Mapping {self.name} with {MODEL}"})
        messages = [{"role": "user", "content": f"Plan moving the {what} `{self.name}` into Timebase: an Atlas domain named `{self.domain}` and the Collector logging that historizes it. Investigate with the tools, propose the Collector plan, then write the brief."}]
        usage = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
        retries = 0
        for turn in range(MAX_TURNS):
            try:
                async with client.beta.messages.stream(
                    model=MODEL,
                    max_tokens=64000,
                    system=system_prompt(self.kind),
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
                messages.append({"role": "user", "content": "Before the brief is final, call propose_collector_instance with the Collector plan until it passes. Then reply with the full brief again, with bindings that use the tag names it predicts."})
                continue
            if not tool_uses:
                text = "".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    await self.emit({"type": "status", "text": "The brief hit the output limit and may be cut off."})
                self.brief = finish(self.server, self.domain, text, self.collector and self.collector["dataset"])
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
