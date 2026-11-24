"""Sparkplug B on a broker -> objects and signals in the broker's SourceModel.

Objects: the group, each Edge Node and device, template instances (nested ones too) and metric
folders. Signals: every metric and template member Collector would log, with the tag name Collector
gives it (Group/Node[/Device]/<metric>, template members <instance>.<member>). Template definitions
and transient metrics are left out, as Collector leaves them out by default.
"""
import json

from source_model import var_stats

SPB = "spBv1.0/"


def _latest_values(cache):
    """{scope: {collector metric name: value}} from the cached BIRTH and DATA messages (DATA wins)."""
    out = {}
    for topic in sorted(cache, key=lambda t: "DATA" in t):
        if not topic.startswith(SPB):
            continue
        e = cache[topic]
        info = e.get("spb") or {}
        if info.get("type") not in ("NBIRTH", "DBIRTH", "NDATA", "DDATA"):
            continue
        scope = "/".join(x for x in (info.get("group"), info.get("node"), info.get("device")) if x)
        try:
            metrics = json.loads(e["p"]).get("metrics", [])
        except (ValueError, KeyError):
            continue
        vals = out.setdefault(scope, {})
        for name, v in _flat(metrics):
            vals[name] = v
    return out


def _flat(metrics, prefix=""):
    for m in metrics:
        name = m.get("name")
        if not name:
            continue
        t = m.get("template")
        if t is not None:
            if not t.get("definition"):
                yield from _flat(t.get("metrics", []), f"{prefix}{name}.")
        else:
            yield prefix + name, m.get("value")


def add(model, sessions, cache, stats, hinted):
    values = _latest_values(cache)
    for g, n, d, birth in sessions.births():
        scope = "/".join(x for x in (g, n, d) if x)
        origin = {"kind": "sparkplug", "group": g, "node": n, "device": d}
        model.ensure_path(scope, {"kind": "sparkplug"})
        for m in birth.get("metrics", []):
            name = m.get("name")
            if not name or m.get("transient"):
                continue
            t = m.get("template")
            if t is not None:
                if not t.get("definition"):
                    _instance(model, scope, name, name, t, origin, values, stats, hinted)
                continue
            _signal(model, scope, name, name, m, origin, values, stats, hinted)


def _signal(model, scope, metric, tree_path, m, origin, values, stats, hinted):
    """metric: Collector's metric name (Motor1.Speed); tree_path: slash path below the scope (Motor1/Speed)."""
    path = f"{scope}/{tree_path}"
    parent = model.ensure_path(path.rsplit("/", 1)[0], {"kind": "sparkplug"})
    key = f"spb:{scope}\x1f{metric}"
    housekeeping = metric == "bdSeq" or metric.startswith(("Node Control/", "Device Control/"))
    sig = {"dataType": m.get("datatype"), "units": (m.get("properties") or {}).get("engUnit"),
           "value": values.get(scope, {}).get(metric, m.get("value")), "observed": var_stats(stats.get(key)),
           "tag": f"{scope}/{metric}", "statKey": key,
           "origin": {**origin, "metric": metric, **({"housekeeping": True} if housekeeping else {})}}
    model.add_signal(path, path, path.rsplit("/", 1)[-1], parent, **hinted(sig, key))


def _instance(model, scope, metric, tree_path, t, origin, values, stats, hinted):
    obj = model.ensure_path(f"{scope}/{tree_path}", {"kind": "sparkplug"})
    node = model.nodes[obj]
    node["typeDefinition"] = t.get("ref")
    node["origin"] = {**origin, "templateInstance": metric}
    if t.get("parameters"):
        node["hint"] = {"parameters": {k: v.get("value") for k, v in t["parameters"].items()}, "source": "sparkplug-template"}
    for sub in t.get("metrics", []):
        sname = sub.get("name")
        if not sname:
            continue
        st = sub.get("template")
        if st is not None:
            _instance(model, scope, f"{metric}.{sname}", f"{tree_path}/{sname}", st, origin, values, stats, hinted)
        else:
            _signal(model, scope, f"{metric}.{sname}", f"{tree_path}/{sname}", sub, origin, values, stats, hinted)
