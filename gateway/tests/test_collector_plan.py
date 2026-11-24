"""Collector plans on a broker (the probe fixtures) and the unchanged OPC UA path."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "gateway"))

import collector_plan as cp  # noqa: E402
from test_source_model import FakeBroker, FakeServer  # noqa: E402

EXPECTED = json.loads((ROOT / "tools/probe/expected-tags.json").read_text())


class Broker(FakeBroker):
    def __init__(self, password=True):
        super().__init__()
        self.rec = {"name": "probe", "settings": {"host": "witness-probe-broker", "port": 1883, "tls": False, "username": "viewer"},
                    "secrets": {"password": {"enc": "x"} if password else None}}


def plan(*instances, dataset="WitnessProbe"):
    return {"dataset": dataset, "instances": list(instances), "notes": []}


MQTT_FULL = {"plugin": "MQTT", "name": "ProbeMqtt", "subscriptions": [
    {"type": "Simple", "topics": ["probe/simple/#"], "topicDefinition": "probe/kind/line/equipment",
     "fields": [{"name": "Line", "value": "[Topic:line]"}, {"name": "Equipment", "value": "[Topic:equipment]"}, {"name": "Shape", "value": "Simple"}]},
    {"type": "JsonSimple", "topics": ["probe/jsonsimple/#"], "timestampFields": ["payload.timestamp", "emitTime", "ts"], "timestampType": "String",
     "topicDefinition": "probe/kind/a/b/c", "fields": {"A": "[Topic:a]", "B": "[Topic:b]", "Uri": "[Payload:instanceUri]", "Shape": "JsonSimple"}},
    {"topics": ["probe/structured/#"], "ignoreParts": ["probe.structured."], "topicDefinition": "probe/kind/plant/area/equipment/signal",
     "fields": {"Plant": "[Topic:plant]", "Area": "[Topic:area]", "Equipment": "[Topic:equipment]", "Shape": "JsonStructured"}},
    {"topics": ["probe/structuredarray/#"], "fields": {"Shape": "JsonStructuredArray"}}]}
SPB = {"plugin": "SparkplugB", "name": "ProbeSpb", "subscriptions": [{"topics": ["spBv1.0/ProbeGroup/#"]}]}


class BrokerPlanTests(unittest.TestCase):
    def test_full_probe_plan_predicts_what_collector_wrote(self):
        r = cp.validate(Broker(), plan(MQTT_FULL, SPB))
        expected = {t["name"] for t in EXPECTED["WitnessProbeMqtt"] + EXPECTED["WitnessProbeSpb"]}
        required = {t for t, i in r["owner"].items() if not i.get("optional")}
        self.assertEqual(required | {"ProbeGroup/NCMD/Gateway1/Node Control/Rebirth"}, expected)
        # the MX-101 Orders[] collision is a problem, not a silent loss
        self.assertTrue(any("collide" in p and "MX-101.Id" in p for p in r["problems"]), r["problems"])
        self.assertEqual(len([p for p in r["problems"] if "collide" not in p]), 0, r["problems"])

    def test_defaults_from_shapes(self):
        r = cp.validate(Broker(), plan({"plugin": "MQTT", "name": "M", "subscriptions": [{"topics": ["probe/structured/#"]}]}))
        st = r["instances"][0]["Settings"]["Subscriptions"][0]
        self.assertEqual({k: st.get(k) for k in ("Type", "ValueField", "QualityField", "UOMFields", "TimestampFields", "TimestampType", "TagnameDelimiter", "TagnameIncludesTopic")},
                         {"Type": "JsonStructured", "ValueField": "value", "QualityField": "quality", "UOMFields": ["units"],
                          "TimestampFields": ["timestamp"], "TimestampType": "String", "TagnameDelimiter": ".", "TagnameIncludesTopic": True})
        self.assertIn("probe.structured.DemoPlant.Utilities.Boiler.SteamPressureBar", r["owner"])
        self.assertEqual(r["owner"]["probe.structured.DemoPlant.Utilities.Boiler.SteamPressureBar"]["uom"], "bar")
        state_first = cp.validate(Broker(), plan({"plugin": "MQTT", "name": "M", "subscriptions": [{"topics": ["probe/structured/DemoPlant/Utilities/Boiler/State", "probe/structured/#"]}]}))
        self.assertEqual(state_first["instances"][0]["Settings"]["Subscriptions"][0]["UOMFields"], ["units"])
        arr = cp.validate(Broker(), plan({"plugin": "MQTT", "name": "M", "subscriptions": [{"topics": ["probe/structuredarray/#"]}]}))
        self.assertEqual(sorted(arr["owner"]), ["Tag 1", "Tag 2", "Tag 3"])
        self.assertTrue(r["report"]["ok"])

    def test_problems(self):
        def problems(*subs, plugin="MQTT"):
            return cp.validate(Broker(), plan({"plugin": plugin, "name": "M", "subscriptions": list(subs)}))["problems"]
        self.assertTrue(any("not for Handoffs" in p for p in problems({"topics": ["timebase/#"]})))
        self.assertTrue(any("cannot log" in p for p in problems({"topics": ["probe/csv/#"]})))
        self.assertTrue(any("does not fit" in p for p in problems({"type": "JsonSimple", "topics": ["probe/structured/#"]})))
        self.assertTrue(any("matches no" in p for p in problems({"topics": ["nothing/#"]})))
        self.assertTrue(any("SparkplugB instance" in p for p in problems({"topics": ["spBv1.0/ProbeGroup/#"]})))
        self.assertTrue(any("MQTT instance" in p for p in problems({"topics": ["probe/simple/#"]}, plugin="SparkplugB")))
        self.assertTrue(any("[Topic:area]" in p for p in problems({"topics": ["probe/simple/#"], "fields": {"Area": "[Topic:area]"}})))
        both = cp.validate(Broker(), plan({"plugin": "MQTT", "name": "A", "subscriptions": [{"topics": ["probe/simple/#"]}]},
                                          {"plugin": "MQTT", "name": "B", "subscriptions": [{"topics": ["probe/simple/Line1/#"]}]}))
        self.assertTrue(any("written by both" in p for p in both["problems"]))

    def test_connection_never_exports_the_password(self):
        r = cp.validate(Broker(), plan(SPB))
        inst = r["instances"][0]
        self.assertEqual(inst["Settings"]["Host"], "witness-probe-broker")
        self.assertEqual(inst["Settings"]["Username"], "viewer")
        self.assertNotIn("\"Password\"", json.dumps(inst))
        self.assertTrue(inst["needsPassword"])
        self.assertFalse(cp.validate(Broker(password=False), plan(SPB))["instances"][0]["needsPassword"])


class OpcUaPlanTests(unittest.TestCase):
    def test_v1_plan_unchanged(self):
        srv = FakeServer()
        srv.rec = {"settings": {"endpoint": "opc.tcp://sim:4840", "securityPolicy": "None"}}
        v1 = {"name": "Sim", "dataset": "Sim", "notes": [], "subscriptions": [
            {"topics": ["P.#"], "topicDefinition": "plant.equipment.signal", "intervalMs": 1000, "excludeRegex": "T2", "fields": []}]}
        legacy, problems = cp.validate_collector(srv, v1)
        legacy.pop("_owner")
        r = cp.validate(srv, v1)
        self.assertEqual(problems, [])
        self.assertEqual(r["report"]["instances"][0]["variablesLogged"], legacy["variablesLogged"])
        self.assertEqual(sorted(r["owner"]), ["P.T1.Level"])
        self.assertEqual(r["instances"][0]["type"], "OPCUA")


if __name__ == "__main__":
    unittest.main()
