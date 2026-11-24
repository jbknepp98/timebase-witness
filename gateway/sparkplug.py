"""Sparkplug B payload decoding for the Witness gateway (standard library only).

Decodes the Eclipse Tahu `sparkplug_b.proto` Payload: metrics, aliases, properties, metadata,
templates (definitions and instances, nested), DataSets, arrays and the compression envelope.
Values follow what Timebase Collector stores: Float and Double as numbers (a Float keeps its
32-bit decimal value), DateTime as an ISO 8601 string, DataSets as {columns, types, rows}, arrays
as lists.

DATA messages usually send only aliases and leave the datatype out, so a value cannot be
interpreted until it is matched with the birth. `parse()` keeps raw values; `NodeSessions.apply()`
resolves names and datatypes from the births of that Edge Node and then finishes the values.
`decode()` finishes a payload on its own, for births or when no session is available.
"""
import base64
import gzip
import struct
import zlib
from datetime import datetime, timezone

NAMESPACE = "spBv1.0"
COMPRESSED_UUID = "SPBV1.0_COMPRESSED"

DATATYPES = {
    0: "Unknown", 1: "Int8", 2: "Int16", 3: "Int32", 4: "Int64", 5: "UInt8", 6: "UInt16", 7: "UInt32", 8: "UInt64",
    9: "Float", 10: "Double", 11: "Boolean", 12: "String", 13: "DateTime", 14: "Text", 15: "UUID", 16: "DataSet",
    17: "Bytes", 18: "File", 19: "Template", 20: "PropertySet", 21: "PropertySetList",
    22: "Int8Array", 23: "Int16Array", 24: "Int32Array", 25: "Int64Array", 26: "UInt8Array", 27: "UInt16Array",
    28: "UInt32Array", 29: "UInt64Array", 30: "FloatArray", 31: "DoubleArray", 32: "BooleanArray",
    33: "StringArray", 34: "DateTimeArray",
}
# packed little-endian element formats for the fixed-width array types
ARRAY_FORMATS = {"Int8Array": "b", "Int16Array": "h", "Int32Array": "i", "Int64Array": "q", "UInt8Array": "B",
                 "UInt16Array": "H", "UInt32Array": "I", "UInt64Array": "Q", "FloatArray": "f", "DoubleArray": "d",
                 "DateTimeArray": "q"}


class DecodeError(ValueError):
    pass


# ---------------------------------------------------------------------- protobuf wire format
def _varint(buf, i):
    shift = result = 0
    while True:
        if i >= len(buf):
            raise DecodeError("truncated varint")
        b = buf[i]
        i += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, i
        shift += 7
        if shift > 70:
            raise DecodeError("varint too long")


def fields(buf):
    """Yield (field number, wire type, value): int for varints, bytes for everything else."""
    i, n = 0, len(buf)
    while i < n:
        tag, i = _varint(buf, i)
        field, wt = tag >> 3, tag & 7
        if wt == 0:
            v, i = _varint(buf, i)
        elif wt == 1:
            v, i = buf[i:i + 8], i + 8
        elif wt == 2:
            ln, i = _varint(buf, i)
            v, i = buf[i:i + ln], i + ln
        elif wt == 5:
            v, i = buf[i:i + 4], i + 4
        else:
            raise DecodeError(f"unsupported wire type {wt}")
        if i > n:
            raise DecodeError("truncated field")
        yield field, wt, v


def _signed(n, bits):
    n &= (1 << bits) - 1
    return n - (1 << bits) if n >> (bits - 1) else n


def _f32(b):
    return float(f"{struct.unpack('<f', b)[0]:.7g}")


def _f64(b):
    return struct.unpack("<d", b)[0]


def _text(b):
    return bytes(b).decode("utf-8", "replace")


def iso_ms(ms):
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{int(ms) % 1000:03d}Z"


def dtype_name(n):
    return DATATYPES.get(n, f"Unknown({n})")


# ---------------------------------------------------------------------- messages
def _property_value(buf):
    out = {"type": None, "value": None}
    for f, wt, v in fields(buf):
        if f == 1:
            out["type"] = dtype_name(v)
        elif f == 2 and v:
            out["null"] = True
        elif f == 3:
            out["value"] = v
        elif f == 4:
            out["value"] = v
        elif f == 5:
            out["value"] = _f32(v)
        elif f == 6:
            out["value"] = _f64(v)
        elif f == 7:
            out["value"] = bool(v)
        elif f == 8:
            out["value"] = _text(v)
        elif f == 9:
            out["value"] = _property_set(v)
        elif f == 10:
            out["value"] = [_property_set(x) for ff, _, x in fields(v) if ff == 1]
    t = out["type"]
    if isinstance(out["value"], int) and t in ("Int8", "Int16", "Int32"):
        out["value"] = _signed(out["value"], 32)
    elif isinstance(out["value"], int) and t == "Int64":
        out["value"] = _signed(out["value"], 64)
    elif isinstance(out["value"], int) and t == "DateTime":
        out["value"] = iso_ms(out["value"])
    return out


def _property_set(buf):
    keys, values = [], []
    for f, _, v in fields(buf):
        if f == 1:
            keys.append(_text(v))
        elif f == 2:
            values.append(_property_value(v))
    return {k: (pv["value"] if not pv.get("null") else None) for k, pv in zip(keys, values)}


def _metadata(buf):
    names = {1: "multiPart", 2: "contentType", 3: "size", 4: "seq", 5: "fileName", 6: "fileType", 7: "md5", 8: "description"}
    out = {}
    for f, wt, v in fields(buf):
        if f in names:
            out[names[f]] = _text(v) if wt == 2 else (bool(v) if f == 1 else v)
    return out


def _dataset(buf):
    columns, types, rows = [], [], []
    for f, wt, v in fields(buf):
        if f == 2:
            columns.append(_text(v))
        elif f == 3:
            if wt == 2:  # packed
                i = 0
                while i < len(v):
                    t, i = _varint(v, i)
                    types.append(t)
            else:
                types.append(v)
        elif f == 4:
            row = []
            for rf, _, rv in fields(v):
                if rf != 1:
                    continue
                cell = None
                for cf, cwt, cv in fields(rv):
                    if cf in (1, 2):
                        cell = cv
                    elif cf == 3:
                        cell = _f32(cv)
                    elif cf == 4:
                        cell = _f64(cv)
                    elif cf == 5:
                        cell = bool(cv)
                    elif cf == 6:
                        cell = _text(cv)
                row.append(cell)
            rows.append(row)
    names = [dtype_name(t) for t in types]
    for row in rows:
        for j, cell in enumerate(row):
            t = names[j] if j < len(names) else None
            if isinstance(cell, int) and not isinstance(cell, bool):
                if t in ("Int8", "Int16", "Int32"):
                    row[j] = _signed(cell, 32)
                elif t == "Int64":
                    row[j] = _signed(cell, 64)
                elif t == "DateTime":
                    row[j] = iso_ms(cell)
    return {"columns": columns, "types": names, "rows": rows}


def _parameter(buf):
    name, ptype, value = None, None, None
    for f, wt, v in fields(buf):
        if f == 1:
            name = _text(v)
        elif f == 2:
            ptype = dtype_name(v)
        elif f in (3, 4):
            value = v
        elif f == 5:
            value = _f32(v)
        elif f == 6:
            value = _f64(v)
        elif f == 7:
            value = bool(v)
        elif f == 8:
            value = _text(v)
    if isinstance(value, int) and not isinstance(value, bool) and ptype in ("Int8", "Int16", "Int32"):
        value = _signed(value, 32)
    return name, {"type": ptype, "value": value}


def _template(buf):
    out = {"ref": None, "version": None, "definition": False, "parameters": {}, "metrics": []}
    for f, _, v in fields(buf):
        if f == 1:
            out["version"] = _text(v)
        elif f == 2:
            out["metrics"].append(_metric(v))
        elif f == 3:
            name, p = _parameter(v)
            out["parameters"][name] = p
        elif f == 4:
            out["ref"] = _text(v)
        elif f == 5:
            out["definition"] = bool(v)
    return out


def _metric(buf):
    m = {"name": None, "alias": None, "timestamp": None, "datatype": None, "_raw": None}
    for f, wt, v in fields(buf):
        if f == 1:
            m["name"] = _text(v)
        elif f == 2:
            m["alias"] = v
        elif f == 3:
            m["timestamp"] = v
        elif f == 4:
            m["datatype"] = dtype_name(v)
        elif f == 5 and v:
            m["historical"] = True
        elif f == 6 and v:
            m["transient"] = True
        elif f == 7 and v:
            m["null"] = True
        elif f == 8:
            m["metadata"] = _metadata(v)
        elif f == 9:
            m["properties"] = _property_set(v)
        elif f == 10:
            m["_raw"] = ("int", v)
        elif f == 11:
            m["_raw"] = ("long", v)
        elif f == 12:
            m["_raw"] = ("float", v)
        elif f == 13:
            m["_raw"] = ("double", v)
        elif f == 14:
            m["_raw"] = ("bool", v)
        elif f == 15:
            m["_raw"] = ("string", v)
        elif f == 16:
            m["_raw"] = ("bytes", bytes(v))
        elif f == 17:
            m["_raw"] = ("dataset", v)
        elif f == 18:
            m["template"] = _template(v)
    return m


def _array(t, b):
    if t in ARRAY_FORMATS:
        fmt = ARRAY_FORMATS[t]
        size = struct.calcsize(fmt)
        vals = list(struct.unpack("<" + fmt * (len(b) // size), b[:len(b) - len(b) % size]))
        if t == "FloatArray":
            return [float(f"{x:.7g}") for x in vals]
        if t == "DateTimeArray":
            return [iso_ms(x) for x in vals]
        return vals
    if t == "BooleanArray":
        if len(b) < 4:
            return []
        count = struct.unpack("<I", b[:4])[0]
        bits = b[4:]
        return [bool(bits[i // 8] >> (7 - i % 8) & 1) for i in range(min(count, len(bits) * 8))]
    if t == "StringArray":
        return [s.decode("utf-8", "replace") for s in b.split(b"\x00")[:-1]] if b else []
    return None


def _value(datatype, raw):
    """A Collector-style value from a raw protobuf value and the Sparkplug datatype."""
    if raw is None:
        return None
    kind, v = raw
    t = datatype or ""
    if kind == "int":
        if t in ("Int8", "Int16", "Int32", "Unknown", ""):
            return _signed(v, 32)
        return v
    if kind == "long":
        if t == "DateTime":
            return iso_ms(v)
        if t == "Int64" or not t:
            return _signed(v, 64)
        return v
    if kind == "float":
        return _f32(v)
    if kind == "double":
        return _f64(v)
    if kind == "bool":
        return bool(v)
    if kind == "string":
        return _text(v)
    if kind == "dataset":
        return _dataset(v)
    if kind == "bytes":
        arr = _array(t, v)
        if arr is not None:
            return arr
        return {"bytes": len(v), "base64": base64.b64encode(v[:64]).decode()}  # Bytes/File: not stored by Collector
    return None


def _finish_metric(m):
    raw = m.pop("_raw", None)
    if m.get("template") is not None:
        if not m.get("datatype"):
            m["datatype"] = "Template"
        for sub in m["template"]["metrics"]:
            _finish_metric(sub)
    elif not m.get("null"):
        m["value"] = _value(m.get("datatype"), raw)
    else:
        m["value"] = None
    for k in ("alias", "timestamp", "datatype"):
        if m.get(k) is None:
            m.pop(k, None)
    return m


# ---------------------------------------------------------------------- payloads
def parse(raw):
    """Payload with raw metric values (see module docstring). Inflates the compression envelope."""
    p = {"timestamp": None, "seq": None, "uuid": None, "metrics": []}
    body = None
    for f, _, v in fields(bytes(raw)):
        if f == 1:
            p["timestamp"] = v
        elif f == 2:
            p["metrics"].append(_metric(v))
        elif f == 3:
            p["seq"] = v
        elif f == 4:
            p["uuid"] = _text(v)
        elif f == 5:
            body = bytes(v)
    if p["uuid"] == COMPRESSED_UUID and body is not None:
        algo = "DEFLATE"
        for m in p["metrics"]:
            if (m.get("name") or "").lower() == "algorithm" and m.get("_raw") and m["_raw"][0] == "string":
                algo = _text(m["_raw"][1]).upper()
        try:
            inner = gzip.decompress(body) if algo == "GZIP" else _inflate(body)
        except (OSError, zlib.error) as e:
            raise DecodeError(f"cannot inflate {algo} payload: {e}") from e
        out = parse(inner)
        out["compressed"] = algo
        return out
    if body is not None:
        p["body"] = {"bytes": len(body)}
    return p


def _inflate(body):
    try:
        return zlib.decompress(body)
    except zlib.error:
        return zlib.decompress(body, -15)  # raw DEFLATE


def finish(p):
    for m in p["metrics"]:
        _finish_metric(m)
    for k in ("timestamp", "seq", "uuid"):
        if p.get(k) is None:
            p.pop(k, None)
    return p


def decode(raw):
    return finish(parse(raw))


def parse_topic(topic):
    """spBv1.0/<group>/<type>/<node>[/<device>] -> dict, STATE topics -> {"type": "STATE"}, anything else None."""
    parts = topic.split("/")
    if len(parts) < 2 or parts[0] != NAMESPACE:
        return None
    if parts[1] == "STATE":
        return {"namespace": NAMESPACE, "type": "STATE", "host": parts[2] if len(parts) > 2 else None}
    if len(parts) < 4:
        return None
    return {"namespace": NAMESPACE, "group": parts[1], "type": parts[2], "node": parts[3],
            "device": parts[4] if len(parts) > 4 else None}


# ---------------------------------------------------------------------- sessions (aliases, datatypes, templates)
def _schema(metric):
    """Birth metric -> what DATA messages leave out: datatype, properties, template members."""
    s = {"name": metric.get("name"), "datatype": metric.get("datatype"), "properties": metric.get("properties") or {}}
    t = metric.get("template")
    if t is not None:
        s["datatype"] = s["datatype"] or "Template"
        s["ref"] = t.get("ref")
        s["members"] = {sub.get("name"): _schema(sub) for sub in t["metrics"] if sub.get("name")}
    return s


class NodeSessions:
    """Per Edge Node: aliases, datatypes and template definitions from the births, plus the births themselves."""

    def __init__(self):
        self.nodes = {}  # (group, node) -> {"aliases", "names", "defs", "devices": {device: {"aliases", "names"}}, "births": {device|None: payload}}

    def _node(self, info):
        return self.nodes.setdefault((info["group"], info["node"]),
                                     {"aliases": {}, "names": {}, "defs": {}, "devices": {}, "births": {}})

    def apply(self, info, p):
        """Resolve a parsed payload against the session, update the session, and finish the values."""
        kind = info.get("type")
        if kind == "STATE" or "group" not in info:
            return finish(p)
        key = (info["group"], info["node"])
        if kind == "NDEATH":
            self.nodes.pop(key, None)
            return finish(p)
        node = self._node(info)
        dev = info.get("device")
        if kind == "NBIRTH":
            node.update({"aliases": {}, "names": {}, "defs": {}, "devices": {}, "births": {}})
            scope = node
        elif kind == "DDEATH":
            node["devices"].pop(dev, None)
            node["births"].pop(dev, None)
            return finish(p)
        elif dev:
            scope = node["devices"].setdefault(dev, {"aliases": {}, "names": {}})
            if kind == "DBIRTH":
                scope.update({"aliases": {}, "names": {}})
        else:
            scope = node
        if kind in ("NBIRTH", "DBIRTH"):
            for m in p["metrics"]:
                s = _schema(m)
                if m.get("name"):
                    scope["names"][m["name"]] = s
                    if m.get("alias") is not None:
                        scope["aliases"][m["alias"]] = m["name"]
                    t = m.get("template")
                    if t is not None and t.get("definition"):
                        node["defs"][m["name"].split("/", 1)[1] if m["name"].startswith("_types_/") else m["name"]] = s
            finish(p)
            node["births"][dev] = p
            return p
        # DATA and CMD: fill in names and datatypes from the birth
        unresolved = []
        for m in p["metrics"]:
            if not m.get("name") and m.get("alias") is not None:
                name = scope["aliases"].get(m["alias"])
                if name is None:
                    unresolved.append(m["alias"])
                    continue
                m["name"] = name
            s = scope["names"].get(m.get("name"))
            if s:
                self._resolve(m, s, node["defs"])
        finish(p)
        if unresolved:
            p["unresolved"] = unresolved
        return p

    def _resolve(self, m, s, defs):
        if not m.get("datatype") and s.get("datatype"):
            m["datatype"] = s["datatype"]
        t = m.get("template")
        if t is None:
            return
        members = s.get("members") or {}
        ref = t.get("ref") or s.get("ref")
        definition = defs.get(ref) if ref else None
        for sub in t["metrics"]:
            ms = members.get(sub.get("name")) or ((definition or {}).get("members") or {}).get(sub.get("name"))
            if ms:
                self._resolve(sub, ms, defs)

    def births(self):
        """[(group, node, device|None, finished birth payload)] for profiles."""
        return [(g, n, d, p) for (g, n), node in self.nodes.items() for d, p in node["births"].items()]
