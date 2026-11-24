"""The source model Handoffs plans from, the same for every kind of source (standard library only).

A source (an OPC UA server, an MQTT broker, Sparkplug B on a broker) becomes a tree of objects and
signals. Adapters in gateway/adapters/ build it; the agent's tools (profile, inspect) read only this.

Each node is a dict, kept in source order:
  object  {id, path, name, kind: "object", parent, typeDefinition?, description?, origin, hint?}
  signal  {id, path, name, kind: "signal", parent, dataType, units, description, writable, value,
           quality, observed, origin, hint?, tag, statKey}
`path` is slash-separated; `tag` is the Historian tag name Collector gives the signal by default and
`bindingPath` in inspect is {CONNECTOR}/{DATASET}/<tag>.
"""
import re
import time
from collections import defaultdict

UNIT_RE = re.compile(r"\[([^\]]+)\]\s*$")
SKIP_TYPES = {"BaseObjectType", "FolderType", "BaseDataVariableType", "PropertyType", "BaseVariableType"}


def units_of(info):
    if info.get("units"):
        return info["units"]
    m = UNIT_RE.search(info.get("description") or "")
    return m.group(1) if m else None


def clean_description(info):
    d = UNIT_RE.sub("", info.get("description") or "").strip()
    return d if d and d not in (info.get("name"), info.get("displayName")) else None


def security_text(st):
    sec = st.get("security") or {}
    if (sec.get("policy") or "None") == "None":
        return "None (unencrypted channel)" + (" with a user name and password" if st.get("user") else ", anonymous")
    return f"{sec['policy']} / {sec.get('mode')}" + (" with the server certificate pinned" if sec.get("pinned") else "") + (f", user {st['user']}" if st.get("user") else ", anonymous")


def var_stats(st):
    """What Witness observed for one value (gateway observation record -> profile form)."""
    if not st:
        return {}
    span = max(1e-6, st["last"] - st["first"])
    out = {"updates": st["n"], "ratePerMin": round(st["n"] / span * 60, 2) if st["n"] > 1 else 0}
    if st["min"] is not None:
        out["min"], out["max"] = st["min"], st["max"]
    if st["distinct"]:
        out["distinctValues"] = sorted(st["distinct"])[:20]
        if st["distinctOverflow"]:
            out["distinctValuesTruncated"] = True
    return out


class SourceModel:
    def __init__(self, kind, header, connected_at=None):
        self.kind = kind            # "opcua" | "mqtt"
        self.header = header        # profile keys that describe the source (server, browseRoots, bindingPathTemplate, dataPath)
        self.extra = {}             # profile keys only some sources have (types, groups, exclusions, metadata, ...)
        self.nodes = {}             # id -> node, in source order
        self.connected_at = connected_at

    # building ------------------------------------------------------------
    def add_object(self, nid, path, name, parent, **kw):
        if nid not in self.nodes:
            self.nodes[nid] = {"id": nid, "path": path, "name": name, "kind": "object", "parent": parent, **kw}
        else:
            self.nodes[nid].update({k: v for k, v in kw.items() if v is not None})
        return self.nodes[nid]

    def ensure_path(self, path, origin=None):
        """Objects for every level of a slash path (MQTT topics, Sparkplug scopes); returns the last id."""
        parent = None
        parts = path.split("/")
        for i in range(len(parts)):
            p = "/".join(parts[:i + 1])
            if p not in self.nodes:
                self.add_object(p, p, parts[i], parent, origin=origin)
            parent = p
        return parent

    def add_signal(self, nid, path, name, parent, **kw):
        n = {"id": nid, "path": path, "name": name, "kind": "signal", "parent": parent, "dataType": None, "units": None,
             "description": None, "writable": None, "value": None, "quality": None, "observed": {}, "origin": {}, "tag": None}
        n.update(kw)
        self.nodes[nid] = n
        return n

    def objects(self):
        return [n for n in self.nodes.values() if n["kind"] == "object"]

    def signals(self):
        return [n for n in self.nodes.values() if n["kind"] == "signal"]

    # reading -------------------------------------------------------------
    def profile(self):
        kids = defaultdict(list)
        for n in self.nodes.values():
            kids[n.get("parent")].append(n)
        objects, signals = self.objects(), self.signals()

        def signature(obj):
            return tuple(sorted((k["name"], k.get("dataType") or "?") for k in kids[obj["id"]] if k["kind"] == "signal"))

        patterns = defaultdict(list)
        tree = []
        for o in objects:
            sig = signature(o)
            if sig:
                patterns[sig].append(o["path"])
            v = [k for k in kids[o["id"]] if k["kind"] == "signal"]
            c = [k for k in kids[o["id"]] if k["kind"] == "object"]
            item = {"path": o["path"], "depth": o["path"].count("/"), "childObjects": len(c), "variables": len(v),
                    "variableNames": [k["name"] for k in v][:40]}
            if o.get("typeDefinition") and o["typeDefinition"] not in SKIP_TYPES:
                item["typeDefinition"] = o["typeDefinition"]
            tree.append(item)
        dtypes, units = defaultdict(int), defaultdict(int)
        for s in signals:
            dtypes[s.get("dataType") or "?"] += 1
            if s.get("units"):
                units[s["units"]] += 1
        out = dict(self.header)
        out.update({
            "sourceKind": self.kind,
            "totals": {"objects": len(objects), "variables": len(signals), "writableVariables": sum(1 for s in signals if s.get("writable"))},
            "objectTree": tree,
            "repeatedPatterns": [{"objects": paths, "count": len(paths), "variables": [f"{n}:{t}" for n, t in sig]}
                                 for sig, paths in sorted(patterns.items(), key=lambda kv: -len(kv[1]))],
            "dataTypes": dict(dtypes),
            "units": dict(units),
            "observedForSeconds": round(time.time() - (self.connected_at or time.time())),
        })
        out.update(self.extra)
        return out

    def inspect(self, path):
        path = path.strip().strip("/")
        if self.kind == "opcua":
            path = path.replace(".", "/")
        root = next((n for n in self.nodes.values() if n["path"] == path), None)
        if not root:
            close = [n["path"] for n in self.objects() if path.lower() in n["path"].lower()][:10]
            return {"error": f"No node at '{path}'.", "didYouMean": close}
        out = []
        for n in self.nodes.values():
            if n["kind"] != "signal" or not (n["path"] == path or n["path"].startswith(path + "/")):
                continue
            row = {"browsePath": n["path"], "nodeId": n["id"], "bindingPath": "{CONNECTOR}/{DATASET}/" + (n.get("tag") or ""),
                   "dataType": n.get("dataType"), "units": n.get("units"), "writable": bool(n.get("writable")),
                   "description": n.get("description"), "value": n.get("value"), "quality": n.get("quality"),
                   "observed": n.get("observed") or {}, "origin": n.get("origin") or {}}
            if n.get("hint"):
                row["hint"] = n["hint"]
            out.append(row)
            if len(out) >= 120:
                break
        res = {"object": path, "nodeId": root["id"], "variables": out, "truncated": len(out) >= 120}
        if root.get("typeDefinition") and root["typeDefinition"] not in SKIP_TYPES:
            res["typeDefinition"] = root["typeDefinition"]
        if root.get("hint"):
            res["hint"] = root["hint"]
        return res
