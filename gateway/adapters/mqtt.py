"""MQTT broker -> SourceModel, for plain MQTT payloads and Sparkplug B on the same broker.

  one value per topic (Simple, JSON value object)  the topic is the signal, its levels are objects
  JSON record                                      the topic is an object, each JSON leaf a signal
  JSON metrics array                               the topic is an object, each element a signal
  Sparkplug B                                      group / node / device objects, template instances as
                                                   objects, metrics and template members as signals

Topics on the connection's "Not for Handoffs" list and metadata topics are left out; metadata and
Sparkplug births become hints. Default tag names assume TagnameDelimiter "." and no IgnoreParts
(the Collector plan check predicts the real names from the plan's own settings).
"""
import json

import hints
import payload_shapes as ps
from source_model import SourceModel, var_stats

from . import sparkplug as spb_adapter


def _security(sec):
    if not sec.get("tls"):
        return "None (plain TCP)"
    return "TLS" + (" with the broker certificate verified" if sec.get("verify", True) else " without certificate verification") + \
        (" and a client certificate" if sec.get("clientCert") else "")


def _scalar(text, typ):
    t = text.strip()
    if typ == "Double":
        try:
            return float(t)
        except ValueError:
            return t
    return t.lower() == "true" if typ == "Boolean" else t


def build(conn):
    inp = conn.profile_inputs()
    st = conn.status()
    ex = inp["exclude"]
    shapes = dict(inp["shapes"])
    excluded = sorted(t for t in shapes if ps.any_match(ex["filters"], t))
    kept = {t: sh for t, sh in shapes.items() if t not in set(excluded)}
    cache = {t: e for t, e in inp["cache"].items() if t in kept}
    meta = hints.from_metadata_topics(cache, kept)
    kept = {t: sh for t, sh in kept.items() if t not in meta["metadataTopics"]}
    spbh = hints.from_sparkplug(inp["spb"].births())
    signal_hints = hints.merge_signals(spbh["signals"], meta["signals"], hints.from_json_values(kept, cache))
    types = meta["types"] + spbh["types"]
    stats = inp["stats"]

    m = SourceModel("mqtt", {
        "server": {"name": st["name"], "endpoint": st["endpoint"], "product": "MQTT broker", "user": st["user"],
                   "security": _security(st.get("security") or {})},
        "browseRoots": st.get("topics"),
        "bindingPathTemplate": "{CONNECTOR}/{DATASET}/{Historian tag name: see each signal's bindingPath}",
        "dataPath": "Collector historizes the broker into the dataset you propose; a Connect Historian connector serves it to Atlas. Keep {CONNECTOR} and {DATASET} literal.",
    }, connected_at=inp["connectedAt"])

    def hinted(sig, key):
        """Attach the merged hint; a hinted data type wins (it is the source's own), units and description fill gaps."""
        h = signal_hints.get(key)
        if h:
            sig["hint"] = dict(h)
            if h.get("dataType"):
                sig["dataType"] = h["dataType"]
            for f in ("units", "description"):
                if h.get(f) and not sig.get(f):
                    sig[f] = h[f]
            if "writable" in h:
                sig["writable"] = h["writable"]
        return sig

    for topic in sorted(kept):
        sh = kept[topic]
        kind, d = sh["shape"], sh["detail"]
        if kind in ("Unsupported", "SparkplugB"):
            continue
        entry = cache.get(topic) or {}
        origin = {"kind": "mqtt", "topic": topic, "shape": kind}
        if kind in ("Simple", "JsonValueObject"):
            parent = m.ensure_path(topic.rsplit("/", 1)[0], {"kind": "mqtt"}) if "/" in topic else None
            obj = json.loads(entry["p"]) if kind == "JsonValueObject" and entry.get("p") else {}
            sig = {"dataType": d.get("valueType"), "value": obj.get(d.get("valueField")) if kind == "JsonValueObject" else _scalar(entry.get("p") or "", d.get("valueType")),
                   "units": obj.get(d.get("uomField")) if d.get("uomField") else None,
                   "quality": obj.get(d.get("qualityField")) if d.get("qualityField") else None,
                   "observed": var_stats(stats.get(topic)), "tag": topic.replace("/", "."), "statKey": topic, "origin": origin}
            m.add_signal(topic, topic, topic.rsplit("/", 1)[-1], parent, **hinted(sig, topic))
        elif kind == "JsonRecord":
            oid = m.ensure_path(topic, {"kind": "mqtt"})
            leaves = ps.flatten(json.loads(entry["p"])) if entry.get("p") else []
            skip = set(d.get("timestampKeys") or [])
            for path, v in leaves:
                lp = ps.path_text(path)
                key = f"{topic}\x1f{lp}"
                tag = ".".join([topic.replace("/", ".")] + ps.collector_keys(path))
                sig = {"dataType": ps.json_type(v), "value": v, "observed": var_stats(stats.get(key)), "tag": tag, "statKey": key,
                       "origin": {**origin, "jsonPath": lp, **({"timestampKey": True} if lp in skip else {})}}
                m.add_signal(f"{topic}/{lp}", f"{topic}/{lp}", lp, oid, **hinted(sig, key))
        elif kind == "JsonMetricsArray":
            oid = m.ensure_path(topic, {"kind": "mqtt"})
            arr = json.loads(entry["p"]) if entry.get("p") else {}
            for k in [x for x in d["arrayPath"].split(".") if x]:
                arr = arr.get(k, []) if isinstance(arr, dict) else []
            for el in arr if isinstance(arr, list) else []:
                name = str(el.get(d["nameField"]))
                key = f"{topic}\x1f{name}"
                sig = {"dataType": ps.json_type(el.get(d["valueField"])), "value": el.get(d["valueField"]),
                       "units": el.get(d["uomField"]) if d.get("uomField") else None,
                       "observed": var_stats(stats.get(key)), "tag": name, "statKey": key, "origin": {**origin, "element": name}}
                m.add_signal(f"{topic}/{name}", f"{topic}/{name}", name, oid, **hinted(sig, key))

    spb_adapter.add(m, inp["spb"], cache, stats, hinted)

    # object hints from metadata topics: type, description, static properties
    for path, o in meta["objects"].items():
        if path in m.nodes and m.nodes[path]["kind"] == "object":
            node = m.nodes[path]
            if o.get("typeDefinition"):
                node["typeDefinition"] = o["typeDefinition"]
            if o.get("description"):
                node["description"] = o["description"]
            if o.get("properties"):
                node["hint"] = {"properties": o["properties"], "source": "metadata-topic"}

    by_shape = {}
    for sh in kept.values():
        by_shape[sh["shape"]] = by_shape.get(sh["shape"], 0) + 1
    m.extra = {
        "topics": {"total": len(shapes), "excluded": len(excluded), "planned": len(kept), "byShape": by_shape},
        "groups": ps.group_topics({t: sh for t, sh in kept.items() if sh["shape"] != "Unsupported"}),
        "unsupported": [{"topic": t, "reason": sh["detail"].get("reason")} for t, sh in sorted(kept.items()) if sh["shape"] == "Unsupported"][:50],
        "exclusions": {**ex, "excludedTopics": len(excluded), "examples": excluded[:10]},
        "metadata": {**meta["metadata"], "role": "hints only: these topics describe others and are not planned for logging"} if meta["metadata"] else None,
        "types": hints.summarize_types(types),
        "objectHints": {"count": len(meta["objects"]), "examples": dict(list(sorted(meta["objects"].items()))[:5])},
        "signalHints": {"count": len(signal_hints), "withUnits": sum(1 for h in signal_hints.values() if h.get("units")),
                        "conflicts": sum(1 for h in signal_hints.values() if h.get("conflicts"))},
        "hintSources": sorted({h["source"] for h in types} | {src for h in signal_hints.values() for src in h["sources"]}),
        "observedValues": len(stats), "statsTruncated": inp["statsTruncated"],
    }
    return m
