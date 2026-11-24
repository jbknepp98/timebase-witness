"""Payload shapes and topic groups against the probe fixtures.

Run from the repo root: python3 -m unittest discover -s gateway/tests
"""
import base64
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "gateway"))

import payload_shapes as ps  # noqa: E402
import sparkplug as spb  # noqa: E402

FIXTURES = json.loads((ROOT / "tools" / "probe" / "fixtures.json").read_text())


def entries():
    """The fixtures as gateway entries, Sparkplug decoded the way MqttConn does it."""
    sessions = spb.NodeSessions()
    out = {}
    for topic, f in FIXTURES.items():
        info = spb.parse_topic(topic)
        if info:
            p = sessions.apply(info, spb.parse(base64.b64decode(f["payload"])))
            out[topic] = {"t": topic, "p": json.dumps(p), "b": False, "spb": {k: info[k] for k in ("type", "group", "node", "device")}}
        else:
            out[topic] = {"t": topic, "p": f["payload"], "b": f["binary"]}
    return out


class ClassifyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.e = entries()
        cls.shape = {t: ps.classify(t, e) for t, e in cls.e.items()}

    def test_simple(self):
        for topic, typ in (("Temp", "Double"), ("State", "String"), ("Run", "Boolean")):
            sh = self.shape[f"probe/simple/Line1/Motor1/{topic}"]
            self.assertEqual((sh["shape"], sh["detail"]["valueType"]), ("Simple", typ))

    def test_value_object(self):
        sh = self.shape["probe/structured/DemoPlant/Utilities/Boiler/SteamPressureBar"]
        self.assertEqual(sh["shape"], "JsonValueObject")
        d = sh["detail"]
        self.assertEqual((d["valueField"], d["qualityField"], d["uomField"], d["timestampField"], d["timestampType"], d["units"]),
                         ("value", "quality", "units", "timestamp", "String", "bar"))
        self.assertEqual(self.shape["probe/structured/DemoPlant/Utilities/Boiler/State"]["detail"]["valueType"], "String")

    def test_metrics_array(self):
        sh = self.shape["probe/structuredarray/Edge1"]
        self.assertEqual(sh["shape"], "JsonMetricsArray")
        d = sh["detail"]
        self.assertEqual((d["arrayPath"], d["nameField"], d["valueField"], d["timestampField"], d["timestampType"], d["qualityField"], d["uomField"]),
                         ("payload.metrics", "name", "value", "timestamp", "UNIXMilliseconds", "properties.Quality.value", "uom"))
        self.assertEqual(d["names"], ["Tag 1", "Tag 2", "Tag 3"])

    def test_records(self):
        motors = self.shape["probe/jsonsimple/Line1/Motors"]
        self.assertEqual(motors["shape"], "JsonRecord")
        self.assertEqual(motors["detail"]["arrayCollisions"], [])
        self.assertIn("payload.timestamp", motors["detail"]["timestampKeys"])
        self.assertIn("motor2.rpm", {leaf["name"] for leaf in motors["detail"]["leaves"]})   # the 'data' array key is dropped
        mx = self.shape["probe/jsonsimple/Assets/MixTank/MX-101"]["detail"]
        self.assertEqual({c["name"] for c in mx["arrayCollisions"]}, {"Id", "Hours"})
        self.assertEqual(self.shape["probe/jsonsimple/Line2/Press"]["shape"], "JsonRecord")

    def test_unsupported_and_sparkplug(self):
        self.assertEqual(self.shape["probe/csv/Line1"]["shape"], "Unsupported")
        self.assertIn("CSV", self.shape["probe/csv/Line1"]["detail"]["reason"])
        sh = self.shape["spBv1.0/ProbeGroup/DDATA/Gateway1/Filler01"]
        self.assertEqual((sh["shape"], sh["detail"]["group"], sh["detail"]["device"]), ("SparkplugB", "ProbeGroup", "Filler01"))
        self.assertEqual(ps.classify("x", {"t": "x", "p": "AAEC", "b": True})["shape"], "Unsupported")
        self.assertIsNone(ps.classify("x", {"t": "x", "p": "", "b": False}))

    def test_groups(self):
        groups = ps.group_topics(self.shape)
        by_filter = {g["filter"]: g for g in groups}
        self.assertIn("probe/structured/DemoPlant/Utilities/Boiler/+", by_filter)
        self.assertEqual(by_filter["probe/structured/DemoPlant/Utilities/Boiler/+"]["topics"], 2)
        self.assertEqual(by_filter["probe/simple/Line1/Motor1/+"]["shape"], "Simple")
        self.assertEqual(by_filter["spBv1.0/ProbeGroup/#"]["topics"], 4)
        self.assertEqual(by_filter["probe/simple/Line1/Motor1/+"]["prefix"], "probe/simple/Line1/Motor1/")


class FilterTests(unittest.TestCase):
    def test_match(self):
        m = ps.topic_filter_match
        self.assertTrue(m("#", "a/b"))
        self.assertFalse(m("#", "$SYS/broker/load"))
        self.assertTrue(m("$SYS/#", "$SYS/broker/load"))
        self.assertFalse(m("+/broker/load", "$SYS/broker/load"))
        self.assertTrue(m("a/+/c", "a/b/c"))
        self.assertFalse(m("a/+/c", "a/b/c/d"))
        self.assertTrue(m("a/b/#", "a/b"))
        self.assertTrue(m("timebase/#", "timebase/bluebird-bev/MixTank/MX-101"))
        self.assertFalse(m("a/b", "a/b/c"))


if __name__ == "__main__":
    unittest.main()
