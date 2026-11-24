"""The common source model: an MQTT broker (plain and Sparkplug B) from the probe fixtures, and a small OPC UA server."""
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gateway"))

import adapters  # noqa: E402
import bridge_lookup  # noqa: E402
import payload_shapes as ps  # noqa: E402
import sparkplug as spb  # noqa: E402
from test_payload_shapes import entries  # noqa: E402
from test_sparkplug import raw  # noqa: E402


class FakeBroker:
    kind = "mqtt"

    def __init__(self):
        self.cache = entries()
        self.spb = spb.NodeSessions()
        for t in ("spBv1.0/ProbeGroup/NBIRTH/Gateway1", "spBv1.0/ProbeGroup/DBIRTH/Gateway1/Filler01"):
            self.spb.apply(spb.parse_topic(t), spb.parse(raw(t)))
        self.shapes = {t: ps.classify(t, e) for t, e in self.cache.items()}
        self.settings = {"host": "witness-probe-broker", "handoffExclude": ["$SYS/#"]}

    def profile_inputs(self):
        return {"cache": self.cache, "stats": {}, "shapes": self.shapes, "spb": self.spb, "connectedAt": time.time() - 60,
                "statsTruncated": False, "exclude": bridge_lookup.effective_excludes(self.settings)}

    def status(self):
        return {"name": "probe", "endpoint": "mqtt://witness-probe-broker:1883", "user": None, "topics": ["#"],
                "security": {"tls": False}}


class FakeServer:
    kind = "opcua"

    def __init__(self):
        self.nodes = {
            "ns=2;s=P": {"id": "ns=2;s=P", "path": "P", "name": "P", "nodeClass": "Object", "parent": None, "typeDefinition": "FolderType"},
            "ns=2;s=P.T1": {"id": "ns=2;s=P.T1", "path": "P/T1", "name": "T1", "nodeClass": "Object", "parent": "ns=2;s=P", "typeDefinition": "TankType"},
            "ns=2;s=P.T1.Level": {"id": "ns=2;s=P.T1.Level", "path": "P/T1/Level", "name": "Level", "nodeClass": "Variable", "parent": "ns=2;s=P.T1",
                                  "dataType": "Double", "units": "%", "writable": False},
            "ns=2;s=P.T2": {"id": "ns=2;s=P.T2", "path": "P/T2", "name": "T2", "nodeClass": "Object", "parent": "ns=2;s=P", "typeDefinition": "TankType"},
            "ns=2;s=P.T2.Level": {"id": "ns=2;s=P.T2.Level", "path": "P/T2/Level", "name": "Level", "nodeClass": "Variable", "parent": "ns=2;s=P.T2",
                                  "dataType": "Double", "description": "Level [%]", "writable": True},
        }
        self.values, self.stats = {"ns=2;s=P.T1.Level": {"v": 42.0, "q": {"name": "Good"}}}, {}
        self.types = {"TankType": {"supertype": "BaseObjectType", "members": [{"name": "Level", "dataType": "Double"}], "properties": []}}

    def status(self):
        return {"name": "sim", "endpoint": "opc.tcp://sim:4840", "serverInfo": "Sim 1", "user": None, "security": {"policy": "None"},
                "connectedAt": time.time() - 30}


class MqttModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.m = adapters.build(FakeBroker())
        cls.p = cls.m.profile()

    def node(self, nid):
        return self.m.nodes[nid]

    def test_value_topics(self):
        s = self.node("probe/structured/DemoPlant/Utilities/Boiler/SteamPressureBar")
        self.assertEqual((s["kind"], s["parent"], s["units"], s["tag"]), ("signal", "probe/structured/DemoPlant/Utilities/Boiler", "bar",
                                                                          "probe.structured.DemoPlant.Utilities.Boiler.SteamPressureBar"))
        self.assertEqual(s["description"], "Steam header pressure")           # from the metadata topic
        self.assertEqual(self.node("probe/structured/DemoPlant/Utilities/Boiler")["typeDefinition"], "BoilerType")
        self.assertEqual(self.node("probe/simple/Line1/Motor1/Run")["value"], True)

    def test_records_and_arrays(self):
        self.assertEqual(self.node("probe/jsonsimple/Assets/MixTank/MX-101/Orders[1].Id")["tag"], "probe.jsonsimple.Assets.MixTank.MX-101.Id")
        self.assertEqual(self.node("probe/jsonsimple/Line1/Motors/data[0].motor2.rpm")["tag"], "probe.jsonsimple.Line1.Motors.motor2.rpm")
        t3 = self.node("probe/structuredarray/Edge1/Tag 3")
        self.assertEqual((t3["tag"], t3["units"], t3["dataType"]), ("Tag 3", "kW", "Float"))

    def test_sparkplug(self):
        motor1 = self.node("ProbeGroup/Gateway1/Filler01/Motor1")
        self.assertEqual((motor1["kind"], motor1["typeDefinition"]), ("object", "Motor"))
        self.assertEqual(self.node("ProbeGroup/Gateway1/Filler01/Pump1/Motor")["typeDefinition"], "Motor")
        sp = self.node("ProbeGroup/Gateway1/Filler01/Pump1/Motor/Speed")
        self.assertEqual((sp["tag"], sp["units"], sp["dataType"]), ("ProbeGroup/Gateway1/Filler01/Pump1.Motor.Speed", "rpm", "Double"))
        ls = self.node("ProbeGroup/Gateway1/Filler01/Line/Speed")
        self.assertEqual((ls["tag"], ls["parent"]), ("ProbeGroup/Gateway1/Filler01/Line/Speed", "ProbeGroup/Gateway1/Filler01/Line"))
        self.assertNotIn("ProbeGroup/Gateway1/Filler01/Scratch", self.m.nodes)        # transient
        self.assertTrue(self.node("ProbeGroup/Gateway1/bdSeq")["origin"]["housekeeping"])
        self.assertFalse(any("_types_" in n for n in self.m.nodes))                    # definitions are not signals

    def test_left_out(self):
        self.assertFalse(any(n.startswith(("timebase/", "probe/_meta", "probe/csv")) for n in self.m.nodes))
        self.assertEqual(self.p["unsupported"], [{"topic": "probe/csv/Line1", "reason": "comma- or semicolon-separated text (CSV)"}])
        self.assertEqual(self.p["sourceKind"], "mqtt")
        self.assertEqual({t["name"] for t in self.p["types"]}, {"BoilerType", "Motor", "Pump"})

    def test_inspect(self):
        r = self.m.inspect("ProbeGroup/Gateway1/Filler01/Pump1")
        self.assertEqual(r["typeDefinition"], "Pump")
        self.assertEqual({row["browsePath"] for row in r["variables"]},
                         {"ProbeGroup/Gateway1/Filler01/Pump1/Flow", "ProbeGroup/Gateway1/Filler01/Pump1/Motor/Speed",
                          "ProbeGroup/Gateway1/Filler01/Pump1/Motor/Running", "ProbeGroup/Gateway1/Filler01/Pump1/Motor/Status/Code"})
        self.assertIn("didYouMean", self.m.inspect("ProbeGroup/Nope"))


class OpcUaModelTests(unittest.TestCase):
    def test_profile_and_inspect(self):
        m = adapters.build(FakeServer())
        p = m.profile()
        self.assertEqual(p["totals"], {"objects": 3, "variables": 2, "writableVariables": 1})
        self.assertEqual(p["repeatedPatterns"][0], {"objects": ["P/T1", "P/T2"], "count": 2, "variables": ["Level:Double"]})
        self.assertEqual([t.get("typeDefinition") for t in p["objectTree"]], [None, "TankType", "TankType"])
        self.assertEqual(p["units"], {"%": 2})
        r = m.inspect("P.T2")                                      # dotted paths still work for OPC UA
        row = r["variables"][0]
        self.assertEqual((row["bindingPath"], row["units"], row["description"], row["writable"]), ("{CONNECTOR}/{DATASET}/P.T2.Level", "%", None, True))   # "Level [%]" only repeats the name
        self.assertEqual(r["typeDefinition"], "TankType")


if __name__ == "__main__":
    unittest.main()
