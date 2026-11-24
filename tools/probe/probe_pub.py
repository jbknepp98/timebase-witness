"""Witness probe publisher: test fixtures for every payload shape Timebase Collector logs.

Publishes to a throwaway probe broker (never the shared one) so a Collector instance can show exactly
which tag names, types and units it produces for each shape:

  probe/simple/...            Simple (primitives): the payload is the bare value
  probe/jsonsimple/...        JSON (Simple): nested records, arrays, timestamps
  probe/structured/...        JSON (Structured), one value object per topic
  probe/structuredarray/...   JSON (Structured), an array of name/value metrics
  probe/csv/...               not JSON: Witness should report it as unsupported
  probe/_meta/...             metadata topics mirroring the structured topics (hints only)
  timebase/probe-domain/...   a Bridge-shaped record: must be excluded from Handoffs
  spBv1.0/ProbeGroup/...      Sparkplug B: births, data, aliases, templates (nested), DataSet, arrays

Usage:
  python probe_pub.py                     publish every second for DURATION seconds (env PROBE_HOST, DURATION)
  python probe_pub.py --once              publish one round and exit
  python probe_pub.py --record out.json   also write one round of every message to out.json
  python probe_pub.py --dry --record f    encode one round without a broker (no paho needed)
"""
import argparse
import base64
import json
import math
import os
import struct
import time
from datetime import datetime, timezone

HOST = os.environ.get("PROBE_HOST", "witness-probe-broker")
DURATION = int(os.environ.get("DURATION", "900"))
G, N, D = "ProbeGroup", "Gateway1", "Filler01"


# ---------------------------------------------------------------- minimal protobuf encoder
def varint(n):
    out = bytearray()
    n &= (1 << 64) - 1
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def key(field, wt):
    return varint((field << 3) | wt)


def f_varint(field, n):
    return key(field, 0) + varint(int(n))


def f_bytes(field, b):
    if isinstance(b, str):
        b = b.encode()
    return key(field, 2) + varint(len(b)) + b


def f_double(field, x):
    return key(field, 1) + struct.pack("<d", x)


def f_float(field, x):
    return key(field, 5) + struct.pack("<f", x)


# Sparkplug B datatypes
INT32, INT64, FLOAT, DOUBLE, BOOLEAN, STRING, DATETIME = 3, 4, 9, 10, 11, 12, 13
DATASET, TEMPLATE, INT32ARRAY = 16, 19, 24


def propset(props):
    """{name: (type, value)} -> PropertySet bytes"""
    b = b""
    for k in props:
        b += f_bytes(1, k)
    for k, (t, v) in props.items():
        pv = f_varint(1, t)
        if t == STRING:
            pv += f_bytes(8, v)
        elif t == INT32:
            pv += f_varint(3, v)
        elif t == DOUBLE:
            pv += f_double(6, v)
        b += f_bytes(2, pv)
    return b


def dataset(columns, types, rows):
    b = f_varint(1, len(columns))
    for c in columns:
        b += f_bytes(2, c)
    for t in types:
        b += f_varint(3, t)
    for row in rows:
        r = b""
        for t, v in zip(types, row):
            if t == INT32:
                r += f_bytes(1, f_varint(1, v))
            elif t == DOUBLE:
                r += f_bytes(1, f_double(4, v))
            elif t == STRING:
                r += f_bytes(1, f_bytes(6, v))
        b += f_bytes(4, r)
    return b


def metric(name=None, dtype=None, value=None, ts=None, alias=None, props=None, template=None, transient=False):
    b = b""
    if name is not None:
        b += f_bytes(1, name)
    if alias is not None:
        b += f_varint(2, alias)
    if ts is not None:
        b += f_varint(3, ts)
    if dtype is not None:
        b += f_varint(4, dtype)
    if transient:
        b += f_varint(6, 1)
    if props:
        b += f_bytes(9, propset(props))
    if template is not None:
        b += f_bytes(18, template)
    elif dtype == INT32:
        b += f_varint(10, value & 0xFFFFFFFF)
    elif dtype in (INT64, DATETIME):
        b += f_varint(11, value)
    elif dtype == FLOAT:
        b += f_float(12, value)
    elif dtype == DOUBLE:
        b += f_double(13, value)
    elif dtype == BOOLEAN:
        b += f_varint(14, 1 if value else 0)
    elif dtype == STRING:
        b += f_bytes(15, value)
    elif dtype == INT32ARRAY:
        b += f_bytes(16, b"".join(struct.pack("<i", x) for x in value))
    elif dtype == DATASET:
        b += f_bytes(17, value)
    return b


def template(metrics, ref=None, definition=False, version=None, params=None):
    b = b""
    if version:
        b += f_bytes(1, version)
    for m in metrics:
        b += f_bytes(2, m)
    for pname, (pt, pv) in (params or {}).items():
        b += f_bytes(3, f_bytes(1, pname) + f_varint(2, pt) + (f_bytes(8, pv) if pt == STRING else f_varint(3, pv)))
    if ref:
        b += f_bytes(4, ref)
    if definition:
        b += f_varint(5, 1)
    return b


def payload(metrics, seq, ts):
    b = f_varint(1, ts)
    for m in metrics:
        b += f_bytes(2, m)
    b += f_varint(3, seq)
    return b


# ---------------------------------------------------------------- fixtures
def now_ms():
    return int(time.time() * 1000)


def iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def motor_members(speed=1450.0, running=True, code=0, ts=None):
    return [metric("Speed", DOUBLE, speed, ts, props={"engUnit": (STRING, "rpm")}), metric("Running", BOOLEAN, running, ts),
            metric("Status/Code", INT32, code, ts)]


class Fixtures:
    """Builds every message. Each method returns [(topic, payload bytes|str, retain)]."""

    def __init__(self):
        self.seq = 0
        self.bdseq = 0

    def _spb(self, topic, metrics, ts):
        p = payload(metrics, self.seq, ts)
        self.seq = (self.seq + 1) % 256
        return (topic, p, False)

    def metadata(self):
        """Retained metadata topics that mirror the structured topics, in the OPC UA mirror's style."""
        m = "probe/_meta"
        return [
            (f"{m}/structured/DemoPlant/Utilities/Boiler", json.dumps({"typeDefinition": "BoilerType", "description": "Boiler 1", "children": ["SteamPressureBar", "State"]}), True),
            (f"{m}/structured/DemoPlant/Utilities/Boiler/SteamPressureBar", json.dumps({"dataType": "Double", "units": "bar", "description": "Steam header pressure", "typeDefinition": "BaseDataVariableType"}), True),
            (f"{m}/structured/DemoPlant/Utilities/Boiler/State", json.dumps({"dataType": "String", "description": "Boiler state", "typeDefinition": "BaseDataVariableType"}), True),
            (f"{m}/_types/BoilerType", json.dumps({"description": "Fire-tube boiler", "variables": {"SteamPressureBar": {"dataType": "Double"}, "State": {"dataType": "String"}}}), True),
        ]

    def births(self):
        self.seq = 0
        ts = now_ms()
        motor_def = template(motor_members(0.0, False, 0), definition=True, version="1.0", params={"Rated": (STRING, "5kW")})
        pump_def = template([metric("Flow", DOUBLE, 0.0, props={"engUnit": (STRING, "m3/h")}),
                             metric("Motor", TEMPLATE, template=template(motor_members(0.0, False, 0), ref="Motor"))],
                            definition=True, version="2.1", params={"Service": (STRING, "CIP supply")})
        out = [self._spb(f"spBv1.0/{G}/NBIRTH/{N}", [
            metric("bdSeq", INT64, self.bdseq, ts),
            metric("Node Control/Rebirth", BOOLEAN, False, ts),
            metric("_types_/Motor", TEMPLATE, ts=ts, template=motor_def),
            metric("_types_/Pump", TEMPLATE, ts=ts, template=pump_def),
            metric("Uptime", INT64, 0, ts, alias=1),
            metric("Diagnostics/CPU", DOUBLE, 12.5, ts, alias=2, props={"engUnit": (STRING, "%")}),
        ], ts)]
        out.append(self._spb(f"spBv1.0/{G}/DBIRTH/{N}/{D}", [
            metric("Line/Speed", DOUBLE, 120.0, ts, alias=10, props={"engUnit": (STRING, "bpm")}),
            metric("Line/State", STRING, "Running", ts, alias=11),
            metric("Temperature", FLOAT, 21.5, ts, alias=12, props={"engUnit": (STRING, "degC")}),
            metric("Count", INT32, 0, ts, alias=13),
            metric("Motor1", TEMPLATE, ts=ts, alias=14, template=template(motor_members(), ref="Motor", version="1.0", params={"Rated": (STRING, "7.5kW")})),
            metric("Pump1", TEMPLATE, ts=ts, alias=15, template=template(
                [metric("Flow", DOUBLE, 42.0, props={"engUnit": (STRING, "m3/h")}),
                 metric("Motor", TEMPLATE, template=template(motor_members(980.0), ref="Motor"))], ref="Pump", version="2.1")),
            metric("Scratch", DOUBLE, 1.0, ts, alias=16, transient=True),
            metric("Batch/Steps", DATASET, dataset(["Step", "Setpoint", "Name"], [INT32, DOUBLE, STRING],
                                                   [[1, 72.5, "Heat"], [2, 85.0, "Hold"]]), ts, alias=17),
            metric("Valves/Open", INT32ARRAY, [1, 0, 1, 1], ts, alias=18),
            metric("LastCip", DATETIME, ts - 3_600_000, ts, alias=19),
        ], ts))
        return out

    def json_round(self, i):
        ts = iso()
        x = math.sin(i / 10)
        return [
            # Simple (primitives)
            ("probe/simple/Line1/Motor1/Temp", f"{70 + 5 * x:.2f}", True),
            ("probe/simple/Line1/Motor1/State", "Running" if i % 20 < 15 else "Idle", True),
            ("probe/simple/Line1/Motor1/Run", "true" if i % 20 < 15 else "false", True),
            # JSON (Simple): docs sample shapes, arrays, a record with an array of objects
            ("probe/jsonsimple/Line1/Motors", json.dumps({
                "payload": {"timestamp": ts},
                "motor1": {"rpm": round(23 + x, 3), "location": {"long": 12.3, "lat": 34.7}},
                "data": [{"motor2": {"rpm": round(28 + x, 3)}}],
                "state": "Running", "ok": True}), True),
            ("probe/jsonsimple/Assets/MixTank/MX-101", json.dumps({
                "instanceUri": "MX-101", "emitTime": ts, "Level": {"Value": round(50 + 10 * x, 2), "Quality": 192, "Timestamp": ts},
                "Manufacturer": "Acme", "Orders": [{"Id": "MO-1", "Hours": 2.5}, {"Id": "MO-2", "Hours": 1.0}]}), True),
            ("probe/jsonsimple/Line2/Press", json.dumps({
                "ts": ts, "pressure": {"value": round(4.2 + x / 10, 3), "units": "bar"}, "cycleCount": 17 + i}), True),
            # JSON (Structured), one value object per topic (OPC UA mirror shape)
            ("probe/structured/DemoPlant/Utilities/Boiler/SteamPressureBar", json.dumps({
                "value": round(8 + x, 3), "timestamp": ts, "quality": 192, "status": "Good", "units": "bar"}), True),
            ("probe/structured/DemoPlant/Utilities/Boiler/State", json.dumps({
                "value": "Firing", "timestamp": ts, "quality": 192, "status": "Good"}), True),
            # JSON (Structured), metrics array (docs sample shape)
            ("probe/structuredarray/Edge1", json.dumps({"payload": {"timestamp": now_ms(), "metrics": [
                {"name": "Tag 1", "timestamp": now_ms(), "dataType": "Int32", "properties": {"Quality": {"type": "Int32", "value": 192}}, "value": i},
                {"name": "Tag 2", "timestamp": now_ms(), "dataType": "Boolean", "properties": {"Quality": {"type": "Int32", "value": 192}}, "value": i % 2 == 0},
                {"name": "Tag 3", "timestamp": now_ms(), "dataType": "Float", "uom": "kW", "properties": {"Quality": {"type": "Int32", "value": 192}}, "value": round(1.2 + x, 3)},
            ], "seq": i}}), True),
            # not JSON: unsupported
            ("probe/csv/Line1", f"{72.5 + x:.1f},1450,Running", True),
            # Bridge-shaped record: must be excluded from Handoffs
            ("timebase/probe-domain/MixTank/MX-201", json.dumps({
                "instanceUri": "MX-201", "anchor": ts, "emitTime": ts,
                "Level": {"Value": round(40 + 5 * x, 2), "Timestamp": ts, "Quality": 192}, "Manufacturer": "Acme"}), False),
        ]

    def spb_round(self, i):
        x = math.sin(i / 10)
        ts = now_ms()
        return [
            self._spb(f"spBv1.0/{G}/DDATA/{N}/{D}", [
                metric(alias=10, dtype=DOUBLE, value=120 + 5 * x, ts=ts),
                metric(alias=12, dtype=FLOAT, value=21.5 + x, ts=ts),
                metric(alias=13, dtype=INT32, value=i, ts=ts),
                metric(alias=14, ts=ts, dtype=TEMPLATE, template=template([metric("Speed", DOUBLE, 1450 + 20 * x)], ref="Motor")),
                metric(alias=15, ts=ts, dtype=TEMPLATE, template=template(
                    [metric("Flow", DOUBLE, 42 + x), metric("Motor", TEMPLATE, template=template([metric("Speed", DOUBLE, 980 + 10 * x)], ref="Motor"))], ref="Pump")),
            ], ts),
            self._spb(f"spBv1.0/{G}/NDATA/{N}", [metric(alias=1, dtype=INT64, value=i, ts=ts),
                                                 metric(alias=2, dtype=DOUBLE, value=12.5 + x, ts=ts)], ts),
        ]


def record(path, msgs):
    out = {}
    for topic, p, retain in msgs:
        binary = isinstance(p, (bytes, bytearray))
        out[topic] = {"payload": base64.b64encode(p).decode() if binary else p, "binary": binary, "retain": retain}
    with open(path, "w") as f:
        json.dump(out, f, indent=1)
    print(f"recorded {len(out)} topics to {path}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true", help="publish one round and exit")
    ap.add_argument("--record", metavar="FILE", help="write one round of every message to FILE (JSON)")
    ap.add_argument("--dry", action="store_true", help="do not connect to a broker (use with --record)")
    args = ap.parse_args()

    fx = Fixtures()
    first = fx.metadata() + fx.births() + fx.json_round(1) + fx.spb_round(1)
    if args.record:
        record(args.record, first)
    if args.dry:
        return

    import paho.mqtt.client as mqtt  # only needed to publish

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="witness-probe-pub")
    rebirth = {"asked": False}

    def on_message(_c, _u, msg):  # a Sparkplug host (Collector) asks for a rebirth after data it cannot decode
        rebirth["asked"] = True

    c.on_message = on_message
    c.connect(HOST, 1883, 30)
    c.subscribe(f"spBv1.0/{G}/NCMD/{N}", qos=1)
    c.loop_start()

    def send(msgs):
        for topic, p, retain in msgs:
            c.publish(topic, p, qos=1, retain=retain)

    send(first)
    if args.once:
        time.sleep(1)
        c.loop_stop()
        return
    t0, i = time.time(), 1
    while time.time() - t0 < DURATION:
        time.sleep(1)
        i += 1
        if rebirth["asked"] or i % 120 == 0:
            rebirth["asked"] = False
            send(fx.births())
        send(fx.json_round(i) + fx.spb_round(i))
    c.loop_stop()


if __name__ == "__main__":
    main()
