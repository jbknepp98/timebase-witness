"""Sparkplug B decoding against the probe fixtures (tools/probe/fixtures.json).

Run from the repo root: python3 -m unittest discover -s gateway/tests
"""
import base64
import json
import sys
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gateway"))
sys.path.insert(0, str(ROOT / "tools" / "probe"))

import probe_pub as pp  # noqa: E402  (encoder, for hand-built payloads)
import sparkplug as spb  # noqa: E402

FIXTURES = json.loads((ROOT / "tools" / "probe" / "fixtures.json").read_text())
NB = "spBv1.0/ProbeGroup/NBIRTH/Gateway1"
DB = "spBv1.0/ProbeGroup/DBIRTH/Gateway1/Filler01"
DD = "spBv1.0/ProbeGroup/DDATA/Gateway1/Filler01"
ND = "spBv1.0/ProbeGroup/NDATA/Gateway1"


def raw(topic):
    return base64.b64decode(FIXTURES[topic]["payload"])


def by_name(p):
    return {m.get("name"): m for m in p["metrics"]}


class TopicTests(unittest.TestCase):
    def test_parse_topic(self):
        self.assertEqual(spb.parse_topic(DB), {"namespace": "spBv1.0", "group": "ProbeGroup", "type": "DBIRTH",
                                               "node": "Gateway1", "device": "Filler01"})
        self.assertEqual(spb.parse_topic(NB)["device"], None)
        self.assertEqual(spb.parse_topic("spBv1.0/STATE/host1")["type"], "STATE")
        self.assertIsNone(spb.parse_topic("probe/simple/x"))
        self.assertIsNone(spb.parse_topic("spBv1.0/ProbeGroup"))


class BirthTests(unittest.TestCase):
    def test_node_birth(self):
        p = spb.decode(raw(NB))
        self.assertEqual(p["seq"], 0)
        m = by_name(p)
        self.assertEqual(m["bdSeq"]["datatype"], "Int64")
        self.assertIs(m["Node Control/Rebirth"]["value"], False)
        self.assertEqual(m["Diagnostics/CPU"]["properties"], {"engUnit": "%"})
        motor = m["_types_/Motor"]["template"]
        self.assertTrue(motor["definition"])
        self.assertEqual(motor["version"], "1.0")
        self.assertEqual([x["name"] for x in motor["metrics"]], ["Speed", "Running", "Status/Code"])
        self.assertEqual(motor["parameters"]["Rated"], {"type": "String", "value": "5kW"})
        pump = m["_types_/Pump"]["template"]
        self.assertEqual(by_name(pump)["Motor"]["template"]["ref"], "Motor")

    def test_device_birth(self):
        m = by_name(spb.decode(raw(DB)))
        self.assertEqual(m["Line/Speed"]["properties"]["engUnit"], "bpm")
        self.assertEqual(m["Line/Speed"]["alias"], 10)
        self.assertEqual(m["Temperature"]["value"], 21.5)          # Float keeps its decimal value
        self.assertEqual(m["Temperature"]["datatype"], "Float")
        motor1 = m["Motor1"]["template"]
        self.assertEqual((motor1["ref"], motor1["parameters"]["Rated"]["value"]), ("Motor", "7.5kW"))
        self.assertEqual(by_name(motor1)["Speed"]["properties"]["engUnit"], "rpm")
        pump1 = m["Pump1"]["template"]
        nested = by_name(pump1)["Motor"]["template"]
        self.assertEqual(nested["ref"], "Motor")
        self.assertEqual(by_name(nested)["Speed"]["value"], 980.0)
        self.assertTrue(m["Scratch"]["transient"])
        self.assertEqual(m["Batch/Steps"]["value"], {"columns": ["Step", "Setpoint", "Name"], "types": ["Int32", "Double", "String"],
                                                     "rows": [[1, 72.5, "Heat"], [2, 85.0, "Hold"]]})
        self.assertEqual(m["Valves/Open"]["value"], [1, 0, 1, 1])
        self.assertRegex(m["LastCip"]["value"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$")


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.s = spb.NodeSessions()
        for t in (NB, DB):
            self.s.apply(spb.parse_topic(t), spb.parse(raw(t)))

    def test_device_data_resolves_aliases_and_types(self):
        p = self.s.apply(spb.parse_topic(DD), spb.parse(raw(DD)))
        self.assertNotIn("unresolved", p)
        m = by_name(p)
        self.assertEqual(set(m), {"Line/Speed", "Temperature", "Count", "Motor1", "Pump1"})
        self.assertEqual(m["Temperature"]["datatype"], "Float")
        self.assertIsInstance(m["Count"]["value"], int)
        self.assertEqual(by_name(by_name(m["Pump1"]["template"])["Motor"]["template"])["Speed"]["datatype"], "Double")

    def test_node_data(self):
        m = by_name(self.s.apply(spb.parse_topic(ND), spb.parse(raw(ND))))
        self.assertEqual(set(m), {"Uptime", "Diagnostics/CPU"})
        self.assertEqual(m["Uptime"]["datatype"], "Int64")

    def test_unknown_alias_is_reported(self):
        payload = pp.payload([pp.metric(alias=99, value=5, dtype=None), pp.metric(alias=13, dtype=pp.INT32, value=7)], 3, 1)
        p = self.s.apply(spb.parse_topic(DD), spb.parse(payload))
        self.assertEqual(p["unresolved"], [99])
        self.assertEqual(by_name(p)["Count"]["value"], 7)

    def test_negative_int32_without_datatype(self):
        # DATA without a datatype: metric() only encodes values for a known dtype, so build the field by hand
        m =pp.f_varint(2, 13) + pp.f_varint(10, -5 & 0xFFFFFFFF)
        payload = pp.f_varint(1, 1) + pp.f_bytes(2, m) + pp.f_varint(3, 4)
        self.assertEqual(by_name(self.s.apply(spb.parse_topic(DD), spb.parse(payload)))["Count"]["value"], -5)

    def test_births_are_kept_and_death_clears(self):
        self.assertEqual({(g, n, d) for g, n, d, _ in self.s.births()}, {("ProbeGroup", "Gateway1", None), ("ProbeGroup", "Gateway1", "Filler01")})
        self.s.apply(spb.parse_topic("spBv1.0/ProbeGroup/DDEATH/Gateway1/Filler01"), spb.parse(pp.payload([], 9, 1)))
        self.assertEqual({d for _, _, d, _ in self.s.births()}, {None})
        p = self.s.apply(spb.parse_topic(DD), spb.parse(raw(DD)))
        self.assertTrue(p["unresolved"])
        self.s.apply(spb.parse_topic("spBv1.0/ProbeGroup/NDEATH/Gateway1"), spb.parse(pp.payload([], 0, 1)))
        self.assertEqual(self.s.births(), [])


class CompressionTests(unittest.TestCase):
    def envelope(self, body, algorithm=None):
        metrics = [pp.metric("algorithm", pp.STRING, algorithm)] if algorithm else []
        return pp.payload(metrics, 0, 1) + pp.f_bytes(4, "SPBV1.0_COMPRESSED") + pp.f_bytes(5, body)

    def test_deflate(self):
        p = spb.decode(self.envelope(zlib.compress(raw(DB))))
        self.assertEqual(p["compressed"], "DEFLATE")
        self.assertIn("Pump1", by_name(p))

    def test_gzip(self):
        import gzip
        p = spb.decode(self.envelope(gzip.compress(raw(NB)), "GZIP"))
        self.assertEqual(p["compressed"], "GZIP")
        self.assertIn("_types_/Motor", by_name(p))

    def test_bad_envelope(self):
        with self.assertRaises(spb.DecodeError):
            spb.decode(self.envelope(b"not deflate"))


if __name__ == "__main__":
    unittest.main()
