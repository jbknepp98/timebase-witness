"""MQTT payload shapes for Handoffs (standard library only).

Classifies each topic's latest message into the shape a Timebase Collector subscription would use,
with the payload settings that shape needs, and groups topics that one subscription could cover.

  Simple            bare value (number, true/false, short text)  -> MQTT plugin, Type Simple
  JsonValueObject   {"value", "timestamp"?, "quality"?, "units"?} -> MQTT plugin, Type JsonStructured
  JsonMetricsArray  an array of {name, value, ...} objects        -> MQTT plugin, Type JsonStructured + TagnameFields
  JsonRecord        any other JSON object                         -> MQTT plugin, Type JsonSimple
  SparkplugB        decoded by the gateway                        -> SparkplugB plugin
  Unsupported       binary that is not Sparkplug B, or text that is not JSON or a single value

The naming rules these settings lead to are in tools/probe/naming-findings.md.
"""
import json
import re

VALUE_KEYS = ("value", "Value", "v", "val", "Val")
TIME_KEYS = ("timestamp", "Timestamp", "ts", "time", "Time", "t", "dateTime", "datetime")
QUALITY_KEYS = ("quality", "Quality", "q", "qualityCode")
UNIT_KEYS = ("units", "unit", "uom", "UOM", "engUnit", "engineeringUnits", "EngineeringUnits")
NAME_KEYS = ("name", "Name", "id", "tag", "tagName", "metric")
# primitive keys a value object may also carry without becoming a record
EXTRA_KEYS = ("status", "Status", "dataType", "datatype", "type", "description", "Description", "seq")
NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")
ISO_RE = re.compile(r"^\d{4}-\d\d-\d\d[T ]\d\d:\d\d")
TIME_NAME_RE = re.compile(r"(^|[._])(timestamp|ts|time|datetime|emittime|sourcetime|servertime)$", re.I)


def is_primitive(v):
    return v is None or isinstance(v, (bool, int, float, str))


def simple_type(text):
    """Data type Collector's Simple payload gets for a text value."""
    t = text.strip()
    if t.lower() in ("true", "false"):
        return "Boolean"
    if NUM_RE.match(t):
        return "Double"
    return "String"


def json_type(v):
    """Data type Collector stores for a JSON value (numbers are Double)."""
    if isinstance(v, bool):
        return "Boolean"
    if isinstance(v, (int, float)):
        return "Double"
    if v is None:
        return None
    return "String"


def timestamp_type(v):
    if isinstance(v, str):
        return "String"
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return "UNIXMilliseconds" if v > 1e11 else "UNIXSeconds"
    return None


def looks_like_time(name, v):
    if isinstance(v, str):
        return bool(ISO_RE.match(v))
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return bool(TIME_NAME_RE.search(name)) and v > 1e8
    return False


def _first(d, keys):
    return next((k for k in keys if k in d), None)


# ---------------------------------------------------------------------- JSON flattening
def flatten(obj, prefix=()):
    """[(path elements, value)] for every primitive leaf. Elements are ("k", key) or ("i", index)."""
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.extend(flatten(v, prefix + (("k", str(k)),)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(flatten(v, prefix + (("i", i),)))
    else:
        out.append((prefix, obj))
    return out


def path_text(elems):
    """a.b[0].c"""
    s = ""
    for kind, v in elems:
        s += f"[{v}]" if kind == "i" else (f".{v}" if s else v)
    return s


def collector_keys(elems):
    """Key names Collector's JSON (Simple) keeps: an array drops both its own key and the index."""
    out = []
    for kind, v in elems:
        if kind == "i":
            if out:
                out.pop()
        else:
            out.append(v)
    return out


# ---------------------------------------------------------------------- classification
def _value_object(d):
    vk = _first(d, VALUE_KEYS)
    if vk is None or not is_primitive(d[vk]):
        return None
    allowed = set(VALUE_KEYS) | set(TIME_KEYS) | set(QUALITY_KEYS) | set(UNIT_KEYS) | set(EXTRA_KEYS)
    if any(k not in allowed or not is_primitive(v) for k, v in d.items()):
        return None
    tk, qk, uk = _first(d, TIME_KEYS), _first(d, QUALITY_KEYS), _first(d, UNIT_KEYS)
    return {"valueField": vk, "valueType": json_type(d[vk]),
            "timestampField": tk, "timestampType": timestamp_type(d[tk]) if tk else None,
            "qualityField": qk, "uomField": uk, "units": d.get(uk) if uk else None}


def _metrics_array(obj, path=(), depth=0):
    """First array of objects that each carry a name and a value, searched up to 3 levels deep."""
    if depth > 3:
        return None
    if isinstance(obj, dict):
        for k, v in obj.items():
            found = _metrics_array(v, path + (k,), depth + 1)
            if found:
                return found
    elif isinstance(obj, list) and obj and all(isinstance(e, dict) for e in obj):
        nk = next((k for k in NAME_KEYS if all(k in e for e in obj)), None)
        vk = next((k for k in VALUE_KEYS if all(k in e and is_primitive(e[k]) for e in obj)), None)
        if nk and vk:
            e0 = obj[0]
            tk = _first(e0, TIME_KEYS)
            qk = _first(e0, QUALITY_KEYS)
            if qk is None and isinstance(e0.get("properties"), dict):
                pq = _first(e0["properties"], QUALITY_KEYS)
                if pq and isinstance(e0["properties"][pq], dict) and "value" in e0["properties"][pq]:
                    qk = f"properties.{pq}.value"
            uk = next((k for k in UNIT_KEYS if any(k in e for e in obj)), None)
            return {"arrayPath": ".".join(path), "nameField": nk, "valueField": vk,
                    "timestampField": tk, "timestampType": timestamp_type(e0[tk]) if tk else None,
                    "qualityField": qk, "uomField": uk,
                    "names": [str(e[nk]) for e in obj][:50],
                    "valueTypes": {str(e[nk]): json_type(e[vk]) for e in obj[:50]}}
    return None


def _record(obj):
    leaves = flatten(obj)
    time_keys = sorted({path_text(p) for p, v in leaves if p and p[-1][0] == "k" and looks_like_time(p[-1][1], v)})
    by_name = {}
    for p, v in leaves:
        by_name.setdefault(".".join(collector_keys(p)), []).append(path_text(p))
    collisions = [{"name": n, "paths": ps} for n, ps in by_name.items() if len(ps) > 1]
    return {"leaves": [{"path": path_text(p), "name": ".".join(collector_keys(p)), "type": json_type(v)} for p, v in leaves][:200],
            "leafCount": len(leaves), "timestampKeys": time_keys, "arrayCollisions": collisions,
            "hasArrays": any(k == "i" for p, _ in leaves for k, _ in p)}


def classify(topic, entry):
    """Shape of one message (a gateway MQTT entry: t, p, b, spb?). None for an empty payload."""
    if entry.get("spb"):
        return {"shape": "SparkplugB", "detail": dict(entry["spb"])}
    if entry.get("b"):
        why = "Sparkplug B payload that could not be decoded" if entry.get("spbError") else "binary payload that is not Sparkplug B"
        return {"shape": "Unsupported", "detail": {"reason": why}}
    text = entry.get("p") or ""
    if text.strip() == "":
        return None
    t = text.strip()
    if t[0] in "{[\"" or t in ("null",):
        try:
            obj = json.loads(t)
        except ValueError:
            obj = ...
        if obj is not ...:
            if isinstance(obj, dict):
                vo = _value_object(obj)
                if vo:
                    return {"shape": "JsonValueObject", "detail": vo}
                ma = _metrics_array(obj)
                if ma:
                    return {"shape": "JsonMetricsArray", "detail": ma}
                return {"shape": "JsonRecord", "detail": _record(obj)}
            if isinstance(obj, list):
                ma = _metrics_array({"": obj})
                if ma:
                    ma["arrayPath"] = ""
                    return {"shape": "JsonMetricsArray", "detail": ma}
                return {"shape": "JsonRecord", "detail": _record(obj)}
            if isinstance(obj, str):
                return {"shape": "Simple", "detail": {"valueType": "String"}}
    if "\n" not in t and len(t) <= 200 and not re.search(r"[,;\t]", t):
        return {"shape": "Simple", "detail": {"valueType": simple_type(t)}}
    reason = "comma- or semicolon-separated text (CSV)" if re.search(r"[,;\t]", t) else "multi-line or long text that is not JSON"
    return {"shape": "Unsupported", "detail": {"reason": reason}}


def signature(shape):
    """What topics must share to be logged by the same subscription settings."""
    s, d = shape["shape"], shape["detail"]
    # units are optional per message (UOMFields: the last match wins), so they do not split a group
    if s == "JsonValueObject":
        return (d["valueField"], d.get("timestampField"), d.get("timestampType"), d.get("qualityField"))
    if s == "JsonMetricsArray":
        return (d["arrayPath"], d["nameField"], d["valueField"], d.get("timestampField"), d.get("qualityField"))
    if s == "JsonRecord":
        return tuple(sorted({leaf["name"] for leaf in d["leaves"]}))
    if s == "SparkplugB":
        return (d.get("group"),)
    if s == "Unsupported":
        return (d.get("reason"),)
    return ()


# ---------------------------------------------------------------------- topic filters and groups
def topic_filter_match(flt, topic):
    """MQTT topic filter matching: '/' levels, '+' one level, '#' the rest (last only).
    Wildcards at the first level do not match topics starting with '$'."""
    f, t = flt.split("/"), topic.split("/")
    if topic.startswith("$") and f[0] in ("+", "#"):
        return False
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t):
            return False
        if part != "+" and part != t[i]:
            return False
    return len(f) == len(t)


def any_match(filters, topic):
    return any(topic_filter_match(f, topic) for f in filters)


def group_topics(shapes):
    """{topic: shape} -> groups of topics one subscription could cover: same shape, same settings
    signature and same depth (Sparkplug B: one group per Sparkplug group id)."""
    buckets = {}
    for topic, sh in shapes.items():
        if sh is None:
            continue
        depth = 0 if sh["shape"] == "SparkplugB" else topic.count("/") + 1
        buckets.setdefault((sh["shape"], signature(sh), depth), []).append(topic)
    groups = []
    for (shape, _sig, depth), topics in buckets.items():
        topics.sort()
        if shape == "SparkplugB":
            g = shapes[topics[0]]["detail"].get("group")
            flt, prefix, varying = f"spBv1.0/{g}/#", f"spBv1.0/{g}/", []
        else:
            levels = [t.split("/") for t in topics]
            parts, varying = [], []
            for i in range(depth):
                vals = sorted({lv[i] for lv in levels})
                if len(vals) == 1:
                    parts.append(vals[0])
                else:
                    parts.append("+")
                    varying.append({"level": i, "distinct": len(vals), "examples": vals[:6]})
            flt = "/".join(parts)
            fixed = []
            for p in parts:
                if p == "+":
                    break
                fixed.append(p)
            if len(fixed) == depth:       # a single topic: its parent is the prefix
                fixed = fixed[:-1]
            prefix = "/".join(fixed) + ("/" if fixed else "")
        detail = dict(shapes[topics[0]]["detail"])
        if shape in ("JsonValueObject", "JsonMetricsArray"):
            detail["uomField"] = next((shapes[t]["detail"].get("uomField") for t in topics if shapes[t]["detail"].get("uomField")), None)
            detail.pop("units", None)
            detail["valueTypes"] = sorted({shapes[t]["detail"].get("valueType") for t in topics} - {None}) if shape == "JsonValueObject" else detail.get("valueTypes")
        groups.append({"shape": shape, "filter": flt, "prefix": prefix, "topics": len(topics), "depth": depth,
                       "examples": topics[:5], "varyingLevels": varying, "detail": detail})
    groups.sort(key=lambda g: (-g["topics"], g["filter"]))
    return groups
