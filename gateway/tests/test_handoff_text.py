"""Connect plan and handoff documents from a checked broker plan (probe fixtures)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gateway"))

import adapters  # noqa: E402
import collector_plan as cp  # noqa: E402
import handoff_text as ht  # noqa: E402
from test_collector_plan import MQTT_FULL, SPB, Broker, plan  # noqa: E402


def clean_mqtt():
    m = {**MQTT_FULL, "subscriptions": [dict(s) for s in MQTT_FULL["subscriptions"]]}
    m["subscriptions"][1]["excludeRegex"] = r"MX-101\.(Id|Hours)$"     # the Orders[] array would collide
    return m


class HandoffTextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.broker = Broker()
        cls.r = cp.validate(cls.broker, plan(clean_mqtt(), SPB))
        cls.collector = {"dataset": "WitnessProbe", "instances": cls.r["instances"], "tagsPredicted": cls.r["report"]["tagsPredicted"]}
        cls.model = adapters.build(cls.broker)
        cls.connect = ht.connect_plan(cls.model, cls.collector, cls.r["owner"])

    def test_plan_passes(self):
        self.assertEqual(self.r["problems"], [])
        self.assertEqual(self.r["report"]["tagsPredicted"], 40)

    def test_every_tag_maps_to_a_signal(self):
        idx = ht.tag_index(self.r["owner"])
        signals = {ht.signal_key(n) for n in self.model.signals()}
        unmatched = [t for k, t in idx.items() if k not in signals and not self.r["owner"][t].get("optional")]
        self.assertEqual(unmatched, [])
        motor = self.model.nodes["ProbeGroup/Gateway1/Filler01/Pump1/Motor/Speed"]
        self.assertEqual(idx[ht.signal_key(motor)], "ProbeGroup/Gateway1/Filler01/Pump1.Motor.Speed")
        boiler = self.model.nodes["probe/structured/DemoPlant/Utilities/Boiler/SteamPressureBar"]
        self.assertEqual(idx[ht.signal_key(boiler)], "DemoPlant.Utilities.Boiler.SteamPressureBar")

    def test_connect_plan(self):
        c = self.connect
        self.assertEqual((c["dataset"], c["tagCount"], c["collectors"]), ("WitnessProbe", 40, ["ProbeMqtt", "ProbeSpb"]))
        self.assertEqual(len(c["fields"]), 5)                                  # 4 MQTT subscriptions + 1 Sparkplug
        spb = c["fields"][-1]
        self.assertEqual(spb["plugin"], "SparkplugB")
        self.assertIn("TemplateRootRef", {f["name"] for f in spb["fields"]})
        self.assertEqual(c["optionalTags"], ["ProbeGroup/NCMD/Gateway1/Node Control/Rebirth"])
        self.assertTrue(any(s.get("type") == "Motor" for s in c["samples"]))
        self.assertEqual({t["name"] for t in c["predictedTags"]} & {"probe.jsonsimple.Assets.MixTank.MX-101.Id"}, set())

    def test_documents(self):
        conn_md = ht.connect_brief("probe", self.connect, "http://x/c.json")
        self.assertIn("`ProbeMqtt` (MQTT)", conn_md)
        self.assertIn("{CONNECTOR}/WitnessProbe/ProbeGroup/Gateway1/Filler01/Motor1.Speed", conn_md)
        col_md = ht.collector_brief("probe", self.collector, "http://x/s.json", lambda i, u: "OPCUA SECTION")
        self.assertIn("## 2. Collector Instance: ProbeSpb (SparkplugB)", col_md)
        self.assertIn("Ask the user for the broker password", col_md)
        self.assertNotIn('"Password"', col_md)


if __name__ == "__main__":
    unittest.main()
