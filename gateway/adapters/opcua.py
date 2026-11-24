"""OPC UA server -> SourceModel: objects are OPC UA Objects, signals are Variables, paths are browse paths."""
import hints
from source_model import SourceModel, clean_description, security_text, units_of, var_stats


def tag_name(info):
    """Historian tag name Collector's OPCUA plugin gives a variable: the dot-joined browse path."""
    return info["path"].replace("/", ".")


def build(server):
    st = server.status()
    m = SourceModel("opcua", {
        "server": {"name": st["name"], "endpoint": st["endpoint"], "product": st["serverInfo"], "user": st["user"],
                   "security": security_text(st)},
        "browseRoots": st.get("browseRoots") or "everything under Objects",
        "bindingPathTemplate": "{CONNECTOR}/{DATASET}/{dot-joined browse path under Objects}",
        "dataPath": "Collector historizes the server into the dataset you propose; a Connect Historian connector serves it to Atlas. Keep {CONNECTOR} and {DATASET} literal.",
    }, connected_at=st["connectedAt"])
    for n in server.nodes.values():
        common = {"origin": {"kind": "opcua", "nodeId": n["id"]}}
        if n["nodeClass"] == "Object":
            m.add_object(n["id"], n["path"], n["name"], n.get("parent"), typeDefinition=n.get("typeDefinition"),
                         description=n.get("description"), **common)
        else:
            val = server.values.get(n["id"], {})
            sig = {"dataType": n.get("dataType"), "units": units_of(n), "description": clean_description(n),
                   "writable": bool(n.get("writable")), "value": val.get("v"), "quality": (val.get("q") or {}).get("name"),
                   "observed": var_stats(server.stats.get(n["id"])), "tag": tag_name(n), "statKey": n["id"]}
            if "dataType" not in n:
                sig.pop("dataType")
            m.add_signal(n["id"], n["path"], n["name"], n.get("parent"), **sig, **common)
    m.extra = {"types": hints.summarize_types(hints.from_opcua(server.nodes, getattr(server, "types", {}) or {})),
               "hintSources": ["opcua-typedefinition"]}
    return m
