"""Predict what a Timebase Collector subscription writes to Historian (standard library only).

Given a subscription's settings and the messages Witness has seen, each function returns the tags
Collector will create: name, data type, unit and fields. The rules are the ones observed on a real
Collector (2.0.861) with the probe harness, recorded in tools/probe/naming-findings.md and checked
against tools/probe/expected-tags.json by gateway/tests/test_collector_naming.py.

A prediction: {"tag", "dataType", "uom", "fields", "source": {...where it came from}, "optional"?: True}
"""
import re

import payload_shapes as ps

# .NET regex constructs Python's re handles differently or not at all
DOTNET_ONLY = [(re.compile(r"\(\?<[A-Za-z]"), "named groups (?<name>...) are written (?P<name>...) in Python"),
               (re.compile(r"\\p\{"), "Unicode categories \\p{...} are not supported by Python"),
               (re.compile(r"\(\?[imnsx]+-?[imnsx]*:"), "inline option groups behave differently"),
               (re.compile(r"\\[AZz]\b"), "anchors \\A \\Z \\z differ slightly")]

SPB_TYPES = {"Int8": "Int32", "Int16": "Int32", "Int32": "Int32", "Int64": "Int64", "UInt8": "Int64", "UInt16": "Int64",
             "UInt32": "Int64", "UInt64": "Int64", "Float": "Double", "Double": "Double", "Boolean": "Boolean",
             "String": "String", "Text": "String", "UUID": "String", "DateTime": "String", "DataSet": "String"}
SPB_NOT_STORED = {"Bytes", "File"}


# ---------------------------------------------------------------------- shared pieces
def check_regex(rx):
    """(compiled or None, problem or None, [warnings]) for an exclusion filter."""
    if not rx:
        return None, None, []
    warnings = [f"exclusion filter: {why}" for pat, why in DOTNET_ONLY if pat.search(rx)]
    try:
        return re.compile(rx), None, warnings
    except re.error as e:
        return None, f"exclusion filter does not compile: {e}", warnings


def ignore_parts(name, parts, delim):
    """IgnoreParts: each entry removed literally, then delimiters left dangling at either end trimmed."""
    for p in parts or []:
        if p:
            name = name.replace(p, "")
    while delim and name.startswith(delim):
        name = name[len(delim):]
    while delim and name.endswith(delim):
        name = name[:-len(delim)]
    return name


def get_path(obj, path):
    """Dotted JSON path (a.b.c) -> value, or None."""
    cur = obj
    for k in [x for x in (path or "").split(".") if x]:
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def resolve_fields(fields, topic=None, topic_definition="", obj=None, sep="/"):
    """Fields with [Topic:key] (from the slash-delimited topic definition) and [Payload:path] placeholders."""
    keys = [k for k in (topic_definition or "").split(sep) if k]
    segs = (topic or "").split(sep)
    seg = {k: segs[i] for i, k in enumerate(keys) if i < len(segs)}

    def payload(m):
        v = get_path(obj, m.group(1)) if isinstance(obj, (dict, list)) else None
        return "" if v is None else (str(v).lower() if isinstance(v, bool) else str(v))

    out = {}
    for name, val in (fields or {}).items():
        v = re.sub(r"\[Topic:([^\]]+)\]", lambda m: seg.get(m.group(1), ""), str(val))
        out[name] = re.sub(r"\[Payload:([^\]]+)\]", payload, v)
    return out


def _keep(tag, rx):
    return not (rx and rx.search(tag))


# ---------------------------------------------------------------------- MQTT plugin
def mqtt(sub, topic, text=None, obj=None, rx=None):
    """Predictions for one message on one MQTT subscription. `text` is the raw payload; `obj` the parsed JSON."""
    typ = sub.get("Type") or "Simple"
    delim = sub.get("TagnameDelimiter") if sub.get("TagnameDelimiter") is not None else "/"
    base = topic.replace("/", delim)
    fields = lambda o=None: resolve_fields(sub.get("Fields"), topic, sub.get("TopicDefinition"), o)  # noqa: E731
    out = []
    if typ == "Simple":
        if text is None or text.strip() == "":
            return []
        tag = ignore_parts(base, sub.get("IgnoreParts"), delim)
        if _keep(tag, rx):
            out.append({"tag": tag, "dataType": ps.simple_type(text), "uom": None, "fields": fields(),
                        "source": {"topic": topic}})
        return out
    if not isinstance(obj, (dict, list)):
        return []
    include_topic = sub.get("TagnameIncludesTopic") is not False
    if typ == "JsonSimple":
        ts = set(sub.get("TimestampFields") or [])
        for path, v in ps.flatten(obj):
            lp = ps.path_text(path)
            keys = ps.collector_keys(path)
            if lp in ts or ".".join(keys) in ts or not keys:
                continue
            tag = ignore_parts(delim.join(([base] if include_topic else []) + keys), sub.get("IgnoreParts"), delim)
            if _keep(tag, rx):
                out.append({"tag": tag, "dataType": ps.json_type(v), "uom": None, "fields": fields(obj),
                            "source": {"topic": topic, "jsonPath": lp}})
        return out
    if typ == "JsonStructured":
        vf = sub.get("ValueField") or "value"
        names = sub.get("TagnameFields") or []

        def one(el, where):
            parts = ([base] if include_topic else []) + [str(get_path(el, f)) for f in names if get_path(el, f) is not None]
            tag = ignore_parts(delim.join(parts), sub.get("IgnoreParts"), delim)
            uom = None
            for uf in sub.get("UOMFields") or []:   # the last match wins
                u = get_path(el, uf)
                if u not in (None, ""):
                    uom = str(u)
            if tag and _keep(tag, rx):
                out.append({"tag": tag, "dataType": ps.json_type(get_path(el, vf)), "uom": uom, "fields": fields(obj),
                            "source": {"topic": topic, **where}})

        if isinstance(obj, dict) and get_path(obj, vf) is not None and not isinstance(get_path(obj, vf), (dict, list)):
            one(obj, {})
        else:
            arr = _metrics_array(obj, vf)
            for el in arr or []:
                one(el, {"element": str(get_path(el, names[0])) if names else None})
        return out
    return []


def _metrics_array(obj, vf, depth=0):
    if depth > 3:
        return None
    if isinstance(obj, list) and obj and all(isinstance(e, dict) for e in obj) and any(get_path(e, vf) is not None for e in obj):
        return obj
    if isinstance(obj, dict):
        for v in obj.values():
            found = _metrics_array(v, vf, depth + 1)
            if found:
                return found
    return None


# ---------------------------------------------------------------------- SparkplugB plugin
def sparkplug(sub, births, rx=None):
    """Predictions for a SparkplugB subscription from the Edge Nodes' births
    ([(group, node, device|None, finished birth payload)], see sparkplug.NodeSessions.births())."""
    topics = sub.get("Topics") or []
    housekeeping = sub.get("IncludeHousekeepingMetrics", True) is not False
    transient = bool(sub.get("IncludeTransientMetrics"))
    defs = {}
    for g, n, d, p in births:
        for m in p.get("metrics", []):
            t = m.get("template")
            if t is not None and t.get("definition") and m.get("name"):
                defs[(g, n, m["name"].split("/", 1)[-1] if m["name"].startswith("_types_/") else m["name"])] = t
    out = []
    for g, n, d, p in births:
        msg_topic = f"spBv1.0/{g}/{'DBIRTH' if d else 'NBIRTH'}/{n}" + (f"/{d}" if d else "")
        if topics and not ps.any_match(topics, msg_topic):
            continue
        scope = "/".join(x for x in (g, n, d) if x)
        base_fields = {"GroupID": g, "NodeID": n, **({"DeviceID": d} if d else {})}

        def add(metric, dtype, units, extra):
            if dtype in SPB_NOT_STORED:
                return
            tag = ignore_parts(f"{scope}/{metric}", sub.get("IgnoreParts"), "/")
            if _keep(tag, rx):
                out.append({"tag": tag, "dataType": SPB_TYPES.get(dtype, "String" if dtype and dtype.endswith("Array") else dtype),
                            "uom": units, "fields": {**base_fields, **extra},
                            "source": {"group": g, "node": n, "device": d, "metric": metric}})

        def walk(t, inst, ref, root_inst, root_ref, inherited_params):
            definition = defs.get((g, n, ref)) or {}
            dmembers = {x.get("name"): x for x in definition.get("metrics", [])}
            params = {k: v.get("value") for k, v in (definition.get("parameters") or {}).items()}
            params.update({k: v.get("value") for k, v in (t.get("parameters") or {}).items()})
            version = t.get("version") or definition.get("version")
            for sub_m in t.get("metrics", []):
                name = sub_m.get("name")
                if not name:
                    continue
                dm = dmembers.get(name) or {}
                st = sub_m.get("template")
                if st is not None:
                    walk(st, f"{inst}.{name}", st.get("ref") or (dm.get("template") or {}).get("ref"), root_inst, root_ref, params)
                    continue
                units = (sub_m.get("properties") or {}).get("engUnit") or (dm.get("properties") or {}).get("engUnit")
                extra = {"TemplateInstance": inst, "TemplateMember": name, "TemplateRef": ref,
                         "TemplateRootInstance": root_inst, "TemplateRootRef": root_ref}
                if version:
                    extra["TemplateVersion"] = version
                extra.update({f"TemplateParam.{k}": "" if v is None else str(v) for k, v in params.items()})
                add(f"{inst}.{name}", sub_m.get("datatype") or dm.get("datatype"), units, extra)

        for m in p.get("metrics", []):
            name = m.get("name")
            if not name:
                continue
            t = m.get("template")
            if t is not None:
                if not t.get("definition"):
                    walk(t, name, t.get("ref"), name, t.get("ref"), {})
                continue
            if m.get("transient") and not transient:
                continue
            if (name == "bdSeq" or name.startswith(("Node Control/", "Device Control/"))) and not housekeeping:
                continue
            add(name, m.get("datatype"), (m.get("properties") or {}).get("engUnit"), {})
        if not d and housekeeping:
            # Collector historizes its own rebirth request when it had to ask for one
            tag = f"{g}/NCMD/{n}/Node Control/Rebirth"
            if _keep(tag, rx):
                out.append({"tag": tag, "dataType": "Boolean", "uom": None, "fields": {"Command": "NCMD", "GroupID": g, "NodeID": n},
                            "source": {"group": g, "node": n, "metric": "Node Control/Rebirth", "command": True}, "optional": True})
    return out


# ---------------------------------------------------------------------- OPCUA plugin
def opcua(sub, signals, rx=None):
    """signals: [(dot tag name, dataType, units)]. Topics are dot-delimited with + and #."""
    keys = [k for k in (sub.get("TopicDefinition") or "").split(".") if k]
    out = []
    for tag, dtype, units in signals:
        if not any(opcua_topic_match(t, tag) for t in sub.get("Topics") or []):
            continue
        if not _keep(tag, rx):
            continue
        segs = tag.split(".")
        seg = {k: segs[i] for i, k in enumerate(keys) if i < len(segs)}
        fields = {n: re.sub(r"\[Topic:([^\]]+)\]", lambda m: seg.get(m.group(1), m.group(0)), str(v)) for n, v in (sub.get("Fields") or {}).items()}
        out.append({"tag": tag, "dataType": dtype, "uom": units, "fields": fields, "source": {"tag": tag}})
    return out


def opcua_topic_match(pattern, path):
    """Collector OPC UA topic match: dot-delimited, case-sensitive, + one level, # the rest (last only)."""
    pat, segs = pattern.split("."), path.split(".")
    for i, p in enumerate(pat):
        if p == "#":
            return i < len(segs)
        if i >= len(segs) or (p != "+" and p != segs[i]):
            return False
    return len(pat) == len(segs)
