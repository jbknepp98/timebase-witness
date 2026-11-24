"""Type and unit hints for Handoffs (standard library only).

Sources rarely say everything about a signal in the message that carries its value, so Witness
collects what else they publish and attaches it to the signals and objects it describes:

  opcua-typedefinition  OPC UA objects' TypeDefinition and the members each ObjectType declares
  sparkplug-template    Sparkplug B template definitions (UDTs) and the instances of them in births
  metadata-topic        topics that mirror the data topics with metadata, e.g. _meta/<topic> as the
                        OPC UA -> MQTT mirror publishes: typeDefinition, dataType, units, description,
                        static properties, and a _types/<Type> catalog
  json-keys             units and dataType carried in the value payload itself

Signal hints are keyed like the gateway's observation keys: the topic for one value per topic,
topic\\x1f<name> for metrics arrays, spb:<group/node[/device]>\\x1f<metric> for Sparkplug B, and the
browse path for OPC UA. When sources disagree the most specific wins (PRECEDENCE) and the
disagreement is kept in "conflicts".
"""
import json

PRECEDENCE = ["sparkplug-template", "opcua-typedefinition", "metadata-topic", "json-keys"]
SKIP_TYPES = {"BaseObjectType", "FolderType", "BaseDataVariableType", "PropertyType", "BaseVariableType"}
SIGNAL_KEYS = {"dataType": ("dataType", "datatype", "DataType", "type"), "units": ("units", "unit", "uom", "UOM", "engUnit", "EngineeringUnits"),
               "description": ("description", "Description"), "typeDefinition": ("typeDefinition",)}


def _pick(d, names):
    for n in names:
        v = d.get(n)
        if v not in (None, ""):
            return v
    return None


def _json(entry):
    try:
        v = json.loads(entry.get("p") or "")
        return v if isinstance(v, dict) else None
    except ValueError:
        return None


def _ancestors(topics):
    out = set()
    for t in topics:
        parts = t.split("/")
        for i in range(1, len(parts)):
            out.add("/".join(parts[:i]))
    return out


# ---------------------------------------------------------------------- metadata topics
def find_metadata_segment(payloads, topics):
    """(position, segment) such that removing that topic level from a JSON topic gives a data topic
    or one of its parents for most such topics, e.g. (0, "_meta") for _meta/DemoPlant/... ."""
    data, anc = set(topics), _ancestors(topics)
    hits, total = {}, {}
    for t in payloads:
        parts = t.split("/")
        for i in range(min(3, len(parts) - 1)):
            key = (i, parts[i])
            total[key] = total.get(key, 0) + 1
            rest = "/".join(parts[:i] + parts[i + 1:])
            if rest in data or rest in anc or parts[i + 1] == "_types":
                hits[key] = hits.get(key, 0) + 1
    best = None
    for key, h in hits.items():
        if h >= 2 and (h >= 20 or h / total[key] >= 0.5) and (best is None or h > hits[best]):
            best = key
    return best


def from_metadata_topics(cache, topics=None):
    """cache: {topic: gateway entry}. Returns {"metadata", "types", "signals", "objects", "metadataTopics"}."""
    topics = set(topics if topics is not None else cache)
    payloads = {t: d for t, e in cache.items() if (d := _json(e)) is not None}
    out = {"metadata": None, "types": [], "signals": {}, "objects": {}, "metadataTopics": set()}
    seg = find_metadata_segment(payloads, topics)
    if not seg:
        return out
    i, name = seg
    in_meta = lambda t: len(t.split("/")) > i + 1 and t.split("/")[i] == name  # noqa: E731
    meta = {t: d for t, d in payloads.items() if in_meta(t)}
    out["metadataTopics"] = {t for t in topics | set(cache) if in_meta(t)}   # non-JSON ones too (e.g. a status flag)
    data = topics - out["metadataTopics"]
    anc = _ancestors(data)
    types = {}
    for t, d in meta.items():
        parts = t.split("/")
        rest = parts[:i] + parts[i + 1:]
        if len(parts) > i + 1 and parts[i + 1] == "_types":
            tname = parts[-1]
            members = d.get("variables") or d.get("members") or {}
            types[tname] = {"name": tname, "source": "metadata-topic", "description": d.get("description") or None,
                            "members": [{"name": m, **{k: v for k, v in (spec or {}).items() if k in ("dataType", "units", "description")}}
                                        for m, spec in (members.items() if isinstance(members, dict) else [])],
                            "properties": d.get("properties") if isinstance(d.get("properties"), list) else [],
                            "instances": []}
            continue
        path = d.get("valueTopic") or "/".join(rest)
        if path in data:
            h = {k: _pick(d, names) for k, names in SIGNAL_KEYS.items()}
            h = {k: v for k, v in h.items() if v is not None and not (k == "typeDefinition" and v in SKIP_TYPES)}
            if "writable" in d:
                h["writable"] = bool(d["writable"])
            if h:
                out["signals"][path] = {**h, "source": "metadata-topic"}
        elif path in anc:
            td = d.get("typeDefinition")
            o = {"typeDefinition": td if td not in SKIP_TYPES else None, "description": d.get("description") or None}
            if isinstance(d.get("properties"), dict) and d["properties"]:
                o["properties"] = d["properties"]
            out["objects"][path] = {k: v for k, v in o.items() if v not in (None, "")}
    for path, o in sorted(out["objects"].items()):
        tn = o.get("typeDefinition")
        if tn and tn not in SKIP_TYPES:
            types.setdefault(tn, {"name": tn, "source": "metadata-topic", "members": [], "properties": [], "instances": []})["instances"].append(path)
    out["types"] = sorted(types.values(), key=lambda x: x["name"])
    out["metadata"] = {"segment": name, "position": i, "example": next(iter(sorted(meta))), "topics": len(meta),
                       "signals": len(out["signals"]), "objects": len(out["objects"]), "types": len(types)}
    return out


# ---------------------------------------------------------------------- Sparkplug B
def _members(template, defs):
    out = []
    for m in template.get("metrics", []):
        t = m.get("template")
        if t is not None:
            out.append({"name": m.get("name"), "template": t.get("ref")})
        else:
            u = (m.get("properties") or {}).get("engUnit")
            out.append({k: v for k, v in {"name": m.get("name"), "dataType": m.get("datatype"), "units": u}.items() if v})
    return out


def from_sparkplug(births):
    """births: [(group, node, device|None, finished birth payload)] (sparkplug.NodeSessions.births())."""
    types, signals = {}, {}
    for g, n, d, p in births:
        scope = "/".join(x for x in (g, n, d) if x)
        for m in p.get("metrics", []):
            t = m.get("template")
            name = m.get("name") or ""
            if t is not None and t.get("definition"):
                tn = name.split("/", 1)[1] if name.startswith("_types_/") else name
                types[tn] = {**types.get(tn, {"instances": []}), "name": tn, "source": "sparkplug-template", "version": t.get("version"),
                             "parameters": {k: v.get("value") for k, v in (t.get("parameters") or {}).items()},
                             "members": _members(t, types)}
            elif t is not None:
                _instance(scope, name, t, types, signals)
            elif name:
                _signal(signals, scope, name, m)
    return {"types": sorted(types.values(), key=lambda x: x["name"]), "signals": signals}


def _signal(signals, scope, name, m):
    u = (m.get("properties") or {}).get("engUnit")
    h = {k: v for k, v in {"dataType": m.get("datatype"), "units": u}.items() if v}
    if h:
        signals[f"spb:{scope}\x1f{name}"] = {**h, "source": "sparkplug-template"}


def _instance(scope, path, t, types, signals):
    ref = t.get("ref")
    if ref:
        types.setdefault(ref, {"name": ref, "source": "sparkplug-template", "members": [], "instances": []})["instances"].append(f"{scope}/{path}")
    for sub in t.get("metrics", []):
        st = sub.get("template")
        if st is not None:
            _instance(scope, f"{path}.{sub.get('name')}", st, types, signals)
        elif sub.get("name"):
            _signal(signals, scope, f"{path}.{sub['name']}", sub)


# ---------------------------------------------------------------------- JSON keys
def from_json_values(shapes, cache):
    """Units and data types that value payloads carry themselves."""
    signals = {}
    for topic, sh in shapes.items():
        if not sh:
            continue
        d = sh["detail"]
        if sh["shape"] == "JsonValueObject":
            obj = _json(cache.get(topic) or {}) or {}
            h = {k: v for k, v in {"units": obj.get(d.get("uomField")) if d.get("uomField") else None,
                                   "dataType": _pick(obj, SIGNAL_KEYS["dataType"])}.items() if v not in (None, "")}
            if h:
                signals[topic] = {**h, "source": "json-keys"}
        elif sh["shape"] == "JsonMetricsArray":
            obj = _json(cache.get(topic) or {}) or {}
            arr = obj
            for k in [x for x in d["arrayPath"].split(".") if x]:
                arr = arr.get(k, []) if isinstance(arr, dict) else []
            for el in arr if isinstance(arr, list) else []:
                if not isinstance(el, dict):
                    continue
                h = {k: v for k, v in {"units": el.get(d["uomField"]) if d.get("uomField") else None,
                                       "dataType": _pick(el, SIGNAL_KEYS["dataType"])}.items() if v not in (None, "")}
                if h:
                    signals[f"{topic}\x1f{el.get(d['nameField'])}"] = {**h, "source": "json-keys"}
    return signals


# ---------------------------------------------------------------------- OPC UA
def from_opcua(nodes, types):
    """nodes: the crawl's {nodeId: info} (with typeDefinition); types: {name: {"supertype", "members", "properties"}}."""
    out = {}
    for n in nodes.values():
        tn = n.get("typeDefinition")
        if n.get("nodeClass") == "Object" and tn and tn not in SKIP_TYPES:
            spec = types.get(tn) or {}
            t = out.setdefault(tn, {"name": tn, "source": "opcua-typedefinition", "supertype": spec.get("supertype"),
                                    "description": spec.get("description"), "members": spec.get("members", []),
                                    "properties": spec.get("properties", []), "instances": []})
            t["instances"].append(n["path"])
    return sorted(out.values(), key=lambda x: x["name"])


# ---------------------------------------------------------------------- merging
def merge_signals(*sources):
    """Merge signal-hint dicts; the source earliest in PRECEDENCE wins a field, disagreements are kept."""
    out = {}
    for src in sources:
        for key, h in src.items():
            cur = out.setdefault(key, {"sources": []})
            cur["sources"].append(h["source"])
            for f, v in h.items():
                if f == "source":
                    continue
                if f not in cur:
                    cur[f], cur.setdefault("_by", {})[f] = v, h["source"]
                elif cur[f] != v:
                    winner = min((cur["_by"][f], h["source"]), key=PRECEDENCE.index)
                    cur.setdefault("conflicts", []).append({"field": f, cur["_by"][f]: cur[f], h["source"]: v})
                    if winner == h["source"]:
                        cur[f], cur["_by"][f] = v, h["source"]
    for h in out.values():
        h.pop("_by", None)
    return out


def summarize_types(types, limit=20):
    """Types for a profile: members, instance count and a few instances."""
    return [{**{k: v for k, v in t.items() if k != "instances"}, "instanceCount": len(t.get("instances", [])),
             "instances": t.get("instances", [])[:limit]} for t in types]
