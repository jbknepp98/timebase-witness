"""Handoff documents for Gage: the Collector handoff (one or more instances) and the Connect handoff.

Both are written from the checked Collector plan (collector_plan.validate): its settings documents and
`owner`, the predicted tags with where each comes from. Standard library only.
"""
import json
import os
from collections import defaultdict

HISTORIAN_HOST = os.environ.get("CONNECT_HISTORIAN_HOST", "historian")
HISTORIAN_PORT = int(os.environ.get("CONNECT_HISTORIAN_PORT", "4512"))
HISTORIAN_TLS = os.environ.get("CONNECT_HISTORIAN_TLS", "true").lower() not in ("0", "false", "no")

NAMING = {
    "OPCUA": "the OPC UA browse path from under Objects, joined with dots",
    "MQTT": "the MQTT topic and, for JSON payloads, the JSON keys, joined with the subscription's delimiter "
            "(less any Ignore Parts); a metrics array gives one tag per element, named from its Tagname Fields",
    "SparkplugB": "`Group/Node[/Device]/<metric>` with the metric's own folders; template members are `<instance>.<member>`",
}


# ---------------------------------------------------------------------- tag names for signals
def pred_key(source):
    """Key of a predicted tag's source, matching signal_key() of the model signal it comes from."""
    if "metric" in source:
        scope = "/".join(x for x in (source.get("group"), source.get("node"), source.get("device")) if x)
        return ("spb", scope, source["metric"])
    if "topic" in source:
        return ("mqtt", source["topic"], source.get("jsonPath") or ("#" + source["element"] if source.get("element") else None))
    return ("tag", source.get("tag"))


def signal_key(node):
    o = node.get("origin") or {}
    if o.get("kind") == "sparkplug":
        scope = "/".join(x for x in (o.get("group"), o.get("node"), o.get("device")) if x)
        return ("spb", scope, o.get("metric"))
    if o.get("kind") == "mqtt":
        return ("mqtt", o.get("topic"), o.get("jsonPath") or ("#" + o["element"] if o.get("element") else None))
    return ("tag", node.get("tag"))


def tag_index(owner):
    """{source key: tag name} for every predicted tag (optional ones too)."""
    return {pred_key(i.get("source") or {"tag": t}): t for t, i in owner.items()}


# ---------------------------------------------------------------------- Connect plan
def connect_plan(model, collector, owner):
    """The Connect handoff: one Historian connector for the plan's dataset, and what that dataset holds."""
    dataset = collector["dataset"]
    signals = {signal_key(n): n for n in model.signals()}
    insts = collector["instances"]
    tags = []
    for tag, info in sorted(owner.items()):
        if info.get("optional"):
            continue
        sig = signals.get(pred_key(info.get("source") or {"tag": tag})) or {}
        parent = model.nodes.get(sig.get("parent")) if sig else None
        tags.append({"name": tag, "dataType": info.get("dataType") or sig.get("dataType") or "?", "units": info.get("uom") or sig.get("units"),
                     "fields": info.get("fields") or {}, "instance": info.get("instance", 0), "subscription": info.get("subscription", 0),
                     "parent": parent["path"] if parent else tag.rsplit(".", 1)[0], "parentType": (parent or {}).get("typeDefinition"),
                     "signal": sig.get("name") or tag.rsplit(".", 1)[-1]})
    types, units = defaultdict(int), defaultdict(int)
    for t in tags:
        types[t["dataType"]] += 1
        if t["units"]:
            units[t["units"]] += 1
    fields = []
    for ii, inst in enumerate(insts):
        for si, sub in enumerate(inst["Settings"].get("Subscriptions") or []):
            mine = [t for t in tags if t["instance"] == ii and t["subscription"] == si]
            values = defaultdict(set)
            for t in mine:
                for k, v in t["fields"].items():
                    values[k].add(v)
            fields.append({"instance": inst["name"], "plugin": inst["type"], "topics": sub.get("Topics", []),
                           "topicDefinition": sub.get("TopicDefinition") or "", "tags": len(mine),
                           "fields": [{"name": k, "distinct": len(v), "examples": sorted(v)[:6]} for k, v in values.items()]})
    groups = defaultdict(list)
    for t in tags:
        groups[t["parent"]].append(t)
    patterns = defaultdict(list)
    for parent, ts in groups.items():
        patterns[tuple(sorted(x["signal"] for x in ts))].append(parent)
    samples = []
    for sig, parents in sorted(patterns.items(), key=lambda kv: -len(kv[1]))[:8]:
        first = sorted(parents)[0]
        samples.append({"objects": len(parents), "example": first, "type": groups[first][0]["parentType"],
                        "tags": sorted(groups[first], key=lambda x: x["name"])[:12]})
    optional = [t for t, i in owner.items() if i.get("optional")]
    settings = {"Host": HISTORIAN_HOST, "Port": HISTORIAN_PORT, "UseTls": HISTORIAN_TLS,
                "ClientName": f"Timebase.Connect.{dataset}", "Auth": {"Mode": "Host"},
                "Datasets": {dataset: {"Dataset": dataset}}, "DefaultLookback": "01:00:00"}
    naming = [{"instance": i["name"], "plugin": i["type"], "rule": NAMING.get(i["type"], ""),
               "example": next((t["name"] for t in tags if t["instance"] == ii), None)} for ii, i in enumerate(insts)]
    return {"name": f"Historian {dataset}", "type": "Timebase.Historian", "dataset": dataset,
            "collectors": [i["name"] for i in insts], "Settings": settings, "tagCount": len(tags), "dataTypes": dict(types),
            "units": dict(units), "fields": fields, "samples": samples, "naming": naming, "optionalTags": optional[:10],
            "predictedTags": [{"name": t["name"], "dataType": t["dataType"], "units": t["units"]} for t in tags]}


def connect_brief(source_name, plan, settings_url):
    ds = plan["dataset"]
    settings_json = json.dumps({"Settings": plan["Settings"]}, indent=2)
    types = ", ".join(f"{k} {v}" for k, v in sorted(plan["dataTypes"].items(), key=lambda kv: -kv[1])) or "none"
    units = ", ".join(f"`{k}` ({v})" for k, v in sorted(plan["units"].items(), key=lambda kv: -kv[1])[:15]) or "none reported"
    blocks = []
    for grp in plan["fields"]:
        rows = "\n".join(f"| `{f['name']}` | {f['distinct']} | {', '.join(f'`{e}`' for e in f['examples'])}{' ...' if f['distinct'] > len(f['examples']) else ''} |" for f in grp["fields"]) or "| (none) | | |"
        topics = ", ".join(f"`{t}`" for t in grp["topics"])
        auto = " Collector sets these itself." if grp["plugin"] == "SparkplugB" else ""
        td = f", topic definition `{grp['topicDefinition']}`" if grp["topicDefinition"] else ""
        blocks.append(f"Tags from {topics} on `{grp['instance']}` ({grp['plugin']}, {grp['tags']} tags{td}).{auto}\n\n| Field | Distinct values | Examples |\n|---|---|---|\n{rows}")
    naming = "\n".join(f"- `{n['instance']}` ({n['plugin']}): {n['rule']}" + (f", e.g. `{n['example']}`." if n["example"] else ".") for n in plan["naming"])
    sample_rows = []
    for smp in plan["samples"]:
        kind = f" ({smp['type']})" if smp.get("type") else ""
        sample_rows.append(f"\n**{smp['example']}**{kind} - {smp['objects']} object{'s log' if smp['objects'] != 1 else ' logs'} this set of signals\n\n| Tag name | Data type | Units | Binding path |\n|---|---|---|---|")
        for t in smp["tags"]:
            sample_rows.append(f"| `{t['name']}` | {t['dataType']} | {t['units'] or ''} | `{{CONNECTOR}}/{ds}/{t['name']}` |")
    collectors = ", ".join(f"`{c}`" for c in plan["collectors"])
    optional = (f"\n\nTags that may also appear: {', '.join(f'`{t}`' for t in plan['optionalTags'])} (Collector writes them only "
                "when it had to ask an Edge Node for a rebirth).") if plan["optionalTags"] else ""
    return f"""> **For Gage in Connect:** use the **configure-historian-connector** skill to serve the Historian dataset `{ds}` to Atlas through a **Timebase.Historian** connector. Everything below was worked out by Witness from the Collector plan for `{source_name}`; do not ask the user for settings that are given here.

# Connect Historian Connector: {ds}

| Setting | Value |
|---|---|
| Plugin type | Timebase.Historian |
| Suggested name | `{plan['name']}` |
| Historian | `{plan['Settings']['Host']}:{plan['Settings']['Port']}` ({'TLS' if plan['Settings']['UseTls'] else 'no TLS'}), signing in as this Connect host |
| Dataset entry | key `{ds}` -> dataset `{ds}` |
| Filled by | Collector instance{'s' if len(plan['collectors']) > 1 else ''} {collectors} (Collector handoff) |
| Expected tags | {plan['tagCount']} |
| Settings file | {settings_url} |

## Steps
1. The dataset is written by {collectors}. If {'they are' if len(plan['collectors']) > 1 else 'it is'} not logging yet, set {'them' if len(plan['collectors']) > 1 else 'it'} up from the Collector handoff first: until then the catalog below is empty.
2. `ListConnectors`. If a **Timebase.Historian** connector already reads this Historian, add the `{ds}` entry under its `Datasets` instead of creating a second connector, and use that connector's id below.
3. Otherwise `AddConnector` with type **Timebase.Historian**, rename it to `{plan['name']}`, and `UpdateConnectorSettings` with the settings below.
4. Make sure the connector is enabled for the Atlas that will hold the domain, then `StartConnector`.
5. Wait 10 seconds, then `TestConnector`, `GetLogs` and `GetConnector`. Read the catalog path `<connector id>/{ds}`: expect about {plan['tagCount']} tags named as below. If a tag name contains `/`, check how the catalog shows its per-tag path and tell the user.
6. Report the connector id. The Atlas handoff's bindings start with `{{CONNECTOR}}/{ds}/`, and Gage in Atlas needs that id for `{{CONNECTOR}}`.

## Settings
```json
{settings_json}
```

## What the dataset looks like

**Tag names** come from each Collector instance:
{naming}

**Per-tag binding path** through this connector: `<connector id>/{ds}/<tag name>`. Only per-tag paths can be subscribed; `<connector id>/{ds}` is the catalog (one row per tag).{optional}

**Fields** Collector writes on each tag. Every Collector subscription has its own set:

{chr(10).join(chr(10) + b if i else b for i, b in enumerate(blocks))}

**Data types** (as Collector stores them): {types}.

**Units**: {units}.

## Sample tags
{chr(10).join(sample_rows)}
"""


# ---------------------------------------------------------------------- Collector handoff
def broker_section(n, inst, settings_url):
    settings_json = json.dumps({"Settings": inst["Settings"]}, indent=2)
    plugin = inst["type"]
    pw = ("Ask the user for the broker password and set `Password` in the settings yourself: Witness never exports it."
          if inst.get("needsPassword") else "Witness reads this broker without a password; add one only if Collector's broker account needs it.")
    notes = "\n".join(f"   - {x}" for x in inst.get("connectionNotes") or [])
    wait = ("Sparkplug B tags appear after the Edge Nodes' next birth; Collector asks for a rebirth by itself if data arrives first. "
            if plugin == "SparkplugB" else "")
    extra = "\n".join(f"- {x}" for x in inst.get("notes") or []) or "- None"
    return f"""## {n}. Collector Instance: {inst['name']} ({plugin})

| Setting | Value |
|---|---|
| Plugin type | {plugin} |
| Instance name | `{inst['name']}` |
| Description | {inst['description']} |
| Historian dataset | `{inst['historian']['dataset']}` (create it if it does not exist) |
| Tags predicted | {inst.get('tagsPredicted', '?')} |
| Settings file | {settings_url} |

### Steps
1. `AddCollector` with type **{plugin}**, then `RenameCollector` to `{inst['name']}` and set the description above.
2. `UpdateCollectorSettings` with the settings below. {pw}
3. Connection notes:
{notes}
4. `ListHistorians`, then `SetCollectorHistorians` to link the Historian with dataset `{inst['historian']['dataset']}`.
5. `StartCollector`. {wait}Wait 10 seconds, then check `GetLogs` and `GetPreviewSnapshot`. Expect about {inst.get('tagsPredicted', '?')} tags.

### Settings
```json
{settings_json}
```

### Notes from Witness
{extra}
"""


def collector_brief(source_name, collector, settings_url, opcua_section):
    """opcua_section(inst, settings_url) writes an OPCUA instance (atlas_mapper keeps that text)."""
    insts = collector["instances"]
    rows = "\n".join(f"| {i + 1} | `{x['name']}` | {x['type']} | {x.get('tagsPredicted', x.get('variablesLogged', '?'))} |" for i, x in enumerate(insts))
    plugins = sorted({x["type"] for x in insts})
    sections = []
    for i, inst in enumerate(insts):
        sections.append(opcua_section(inst, settings_url) if inst["type"] == "OPCUA" else broker_section(i + 1, inst, settings_url))
    return f"""> **For Gage in Collector:** use the **setup-collector** skill to create the {'instances' if len(insts) > 1 else 'instance'} below ({', '.join(plugins)}). Everything was checked by Witness against what `{source_name}` publishes; do not ask the user for settings that are given here. All of them write to the Historian dataset `{collector['dataset']}`.

# Collector Plan: {collector['dataset']}

| # | Instance | Plugin | Tags |
|---|---|---|---|
{rows}

{chr(10).join(sections)}"""
