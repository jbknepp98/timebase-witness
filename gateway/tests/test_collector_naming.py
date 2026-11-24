"""The naming simulator must reproduce exactly what Collector wrote for the probe (tools/probe/expected-tags.json)."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "gateway"))

import collector_naming as cn  # noqa: E402
import payload_shapes as ps  # noqa: E402
import sparkplug as spb  # noqa: E402
from test_payload_shapes import entries  # noqa: E402
from test_sparkplug import raw  # noqa: E402

SETTINGS = {i["name"]: i for i in json.loads((ROOT / "tools/probe/collector-settings.json").read_text())["instances"]}
EXPECTED = json.loads((ROOT / "tools/probe/expected-tags.json").read_text())


def predict_mqtt(inst, cache):
    out = []
    for sub in inst["Settings"]["Subscriptions"]:
        rx, problem, _ = cn.check_regex(sub.get("Filter"))
        assert problem is None
        for topic, e in sorted(cache.items()):
            if e.get("spb") or not ps.any_match(sub["Topics"], topic):
                continue
            try:
                obj = json.loads(e["p"])
            except ValueError:
                obj = None
            out += cn.mqtt(sub, topic, e["p"], obj, rx)
    return out


def births():
    s = spb.NodeSessions()
    for t in ("spBv1.0/ProbeGroup/NBIRTH/Gateway1", "spBv1.0/ProbeGroup/DBIRTH/Gateway1/Filler01"):
        s.apply(spb.parse_topic(t), spb.parse(raw(t)))
    return s.births()


def as_expected(preds):
    return sorted(({"name": p["tag"], "type": p["dataType"], "uom": p["uom"], "fields": p["fields"]} for p in preds), key=lambda t: t["name"])


class NamingTests(unittest.TestCase):
    def test_mqtt_instance_matches_collector(self):
        got = as_expected(predict_mqtt(SETTINGS["WitnessProbeMqtt"], entries()))
        exp = EXPECTED["WitnessProbeMqtt"]
        # the MX-101 array collision: Collector writes one tag for each colliding name
        names = [g["name"] for g in got]
        self.assertEqual(sorted(set(names)), [t["name"] for t in exp])
        dedup = {g["name"]: g for g in got}
        for t in exp:
            self.assertEqual(dedup[t["name"]], t, t["name"])
        self.assertEqual(names.count("probe.jsonsimple.Assets.MixTank.MX-101.Id"), 2)

    def test_sparkplug_instance_matches_collector(self):
        sub = SETTINGS["WitnessProbeSpb"]["Settings"]["Subscriptions"][0]
        preds = cn.sparkplug(sub, births())
        got = {p["tag"]: p for p in preds}
        exp = {t["name"]: t for t in EXPECTED["WitnessProbeSpb"]}
        required = {t for t, p in got.items() if not p.get("optional")}
        self.assertEqual(required, set(exp) - {"ProbeGroup/NCMD/Gateway1/Node Control/Rebirth"})
        self.assertTrue(got["ProbeGroup/NCMD/Gateway1/Node Control/Rebirth"]["optional"])
        for name, t in exp.items():
            p = got[name]
            self.assertEqual({"name": name, "type": p["dataType"], "uom": p["uom"], "fields": p["fields"]}, t, name)

    def test_sparkplug_toggles_and_filter(self):
        sub = dict(SETTINGS["WitnessProbeSpb"]["Settings"]["Subscriptions"][0])
        sub.update({"IncludeHousekeepingMetrics": False, "IncludeTransientMetrics": True})
        tags = {p["tag"] for p in cn.sparkplug(sub, births())}
        self.assertNotIn("ProbeGroup/Gateway1/bdSeq", tags)
        self.assertIn("ProbeGroup/Gateway1/Filler01/Scratch", tags)
        rx, _, _ = cn.check_regex(r"Pump1\.")
        sub2 = dict(SETTINGS["WitnessProbeSpb"]["Settings"]["Subscriptions"][0], IgnoreParts=["ProbeGroup/Gateway1/"])
        tags2 = {p["tag"] for p in cn.sparkplug(sub2, births(), rx)}
        self.assertIn("Filler01/Motor1.Speed", tags2)
        self.assertFalse(any("Pump1." in t for t in tags2))

    def test_regex_checks(self):
        self.assertIsNotNone(cn.check_regex("(")[1])
        self.assertTrue(cn.check_regex(r"(?<name>a)")[2])
        self.assertEqual(cn.check_regex("")[0:2], (None, None))

    def test_ignore_parts_and_fields(self):
        self.assertEqual(cn.ignore_parts("probe.structured.DemoPlant.X", ["probe.structured."], "."), "DemoPlant.X")
        self.assertEqual(cn.ignore_parts("a.b.c", ["c"], "."), "a.b")
        self.assertEqual(cn.resolve_fields({"S": "[Topic:site]-[Payload:meta.id]", "C": "x"}, "acme/dal/l1", "co/site/line", {"meta": {"id": 7}}),
                         {"S": "dal-7", "C": "x"})

    def test_opcua(self):
        sub = {"Topics": ["DemoPlant.#"], "TopicDefinition": "plant.area.equipment.signal", "Fields": {"Area": "[Topic:area]"}}
        rx, _, _ = cn.check_regex("Simulator")
        p = cn.opcua(sub, [("DemoPlant.Processing.MixTank101.LevelPct", "Double", "%"), ("DemoPlant.Simulator.Heartbeat", "Int64", None),
                           ("Northbeam.X.Y", "Double", None)], rx)
        self.assertEqual([(x["tag"], x["fields"]) for x in p], [("DemoPlant.Processing.MixTank101.LevelPct", {"Area": "Processing"})])


if __name__ == "__main__":
    unittest.main()
