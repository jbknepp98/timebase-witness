"""Hints from metadata topics, Sparkplug B templates and JSON keys, against the probe fixtures."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gateway"))

import hints  # noqa: E402
import payload_shapes as ps  # noqa: E402
import sparkplug as spb  # noqa: E402
from test_payload_shapes import entries  # noqa: E402


class HintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache = entries()
        cls.shapes = {t: ps.classify(t, e) for t, e in cls.cache.items()}

    def test_metadata_topics(self):
        h = hints.from_metadata_topics(self.cache)
        self.assertEqual((h["metadata"]["segment"], h["metadata"]["position"]), ("_meta", 1))
        self.assertEqual(h["metadataTopics"], {t for t in self.cache if t.startswith("probe/_meta/")})
        sig = h["signals"]["probe/structured/DemoPlant/Utilities/Boiler/SteamPressureBar"]
        self.assertEqual((sig["dataType"], sig["units"], sig["description"]), ("Double", "bar", "Steam header pressure"))
        self.assertNotIn("typeDefinition", sig)   # BaseDataVariableType says nothing
        boiler = {t["name"]: t for t in h["types"]}["BoilerType"]
        self.assertEqual({m["name"]: m["dataType"] for m in boiler["members"]}, {"SteamPressureBar": "Double", "State": "String"})
        self.assertEqual(boiler["instances"], ["probe/structured/DemoPlant/Utilities/Boiler"])
        self.assertEqual(h["objects"]["probe/structured/DemoPlant/Utilities/Boiler"]["typeDefinition"], "BoilerType")

    def test_value_topic_link_and_properties(self):
        cache = {
            "_meta/Plant": {"p": json.dumps({"typeDefinition": "SiteType", "properties": {"SiteCode": "DAL"}, "children": ["Line1"]})},
            "_meta/Plant/Line1/Speed": {"p": json.dumps({"dataType": "Double", "units": "bpm", "valueTopic": "Plant/Line1/Speed"})},
            "_meta/Plant/Line1/State": {"p": json.dumps({"dataType": "String", "valueTopic": "Plant/Line1/State"})},
            "Plant/Line1/Speed": {"p": json.dumps({"value": 1})}, "Plant/Line1/State": {"p": json.dumps({"value": "Run"})},
        }
        h = hints.from_metadata_topics(cache)
        self.assertEqual(h["signals"]["Plant/Line1/Speed"]["units"], "bpm")
        self.assertEqual(h["objects"]["Plant"]["properties"], {"SiteCode": "DAL"})
        self.assertEqual({t["name"]: t["instances"] for t in h["types"]}, {"SiteType": ["Plant"]})

    def test_no_metadata(self):
        cache = {t: e for t, e in self.cache.items() if "_meta" not in t}
        self.assertIsNone(hints.from_metadata_topics(cache)["metadata"])

    def test_sparkplug(self):
        from test_sparkplug import raw
        sessions = spb.NodeSessions()
        for t in ("spBv1.0/ProbeGroup/NBIRTH/Gateway1", "spBv1.0/ProbeGroup/DBIRTH/Gateway1/Filler01"):
            sessions.apply(spb.parse_topic(t), spb.parse(raw(t)))
        h = hints.from_sparkplug(sessions.births())
        types = {t["name"]: t for t in h["types"]}
        self.assertEqual(types["Motor"]["parameters"], {"Rated": "5kW"})
        self.assertEqual({m["name"]: m.get("units") for m in types["Motor"]["members"]}, {"Speed": "rpm", "Running": None, "Status/Code": None})
        self.assertEqual(types["Pump"]["version"], "2.1")
        self.assertIn({"name": "Motor", "template": "Motor"}, types["Pump"]["members"])
        self.assertEqual(sorted(types["Motor"]["instances"]), ["ProbeGroup/Gateway1/Filler01/Motor1", "ProbeGroup/Gateway1/Filler01/Pump1.Motor"])
        self.assertEqual(types["Pump"]["instances"], ["ProbeGroup/Gateway1/Filler01/Pump1"])
        self.assertEqual(h["signals"]["spb:ProbeGroup/Gateway1/Filler01\x1fLine/Speed"]["units"], "bpm")
        self.assertEqual(h["signals"]["spb:ProbeGroup/Gateway1/Filler01\x1fPump1.Motor.Speed"]["units"], "rpm")
        self.assertEqual(h["signals"]["spb:ProbeGroup/Gateway1\x1fDiagnostics/CPU"]["dataType"], "Double")

    def test_json_keys(self):
        s = hints.from_json_values(self.shapes, self.cache)
        self.assertEqual(s["probe/structured/DemoPlant/Utilities/Boiler/SteamPressureBar"]["units"], "bar")
        self.assertEqual(s["probe/structuredarray/Edge1\x1fTag 3"], {"units": "kW", "dataType": "Float", "source": "json-keys"})
        self.assertEqual(s["probe/structuredarray/Edge1\x1fTag 1"]["dataType"], "Int32")

    def test_merge(self):
        m = hints.merge_signals({"a": {"units": "bar", "source": "json-keys"}},
                                {"a": {"units": "bar(g)", "dataType": "Double", "source": "metadata-topic"}})
        self.assertEqual((m["a"]["units"], m["a"]["dataType"]), ("bar(g)", "Double"))
        self.assertEqual(m["a"]["conflicts"], [{"field": "units", "json-keys": "bar", "metadata-topic": "bar(g)"}])

    def test_opcua(self):
        nodes = {"1": {"nodeClass": "Object", "path": "Plant/Comp1", "typeDefinition": "AirCompressorType"},
                 "2": {"nodeClass": "Object", "path": "Plant", "typeDefinition": "FolderType"},
                 "3": {"nodeClass": "Variable", "path": "Plant/Comp1/PowerKw", "typeDefinition": "BaseDataVariableType"}}
        t = hints.from_opcua(nodes, {"AirCompressorType": {"supertype": "BaseObjectType", "members": [{"name": "PowerKw", "dataType": "Double"}]}})
        self.assertEqual([(x["name"], x["instances"], x["members"][0]["name"]) for x in t], [("AirCompressorType", ["Plant/Comp1"], "PowerKw")])


if __name__ == "__main__":
    unittest.main()
