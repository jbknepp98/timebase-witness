"""Bridge exclusion helpers (no network)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "gateway"))

import bridge_lookup as bl  # noqa: E402

LIST = """ID                       Type                           Status            Queue   Target
--------------------------------------------------------------------------------------------------------------
brg_5c1f28               Microsoft.SqlServer            Stopped           0       host.docker.internal,1433 · TimebaseErpDemo
brg_a7e301               MQTT                           Running           0       MQTT
"""
SETTINGS = """Settings for 'brg_a7e301' (credential values masked):
```json
{"Settings": {"Host": "mosquitto", "Port": 1883, "Password": "***", "Subscriptions": {
  "mix-tanks": {"Topic": "timebase/bluebird-bev/[type.@name]/[instance.@name]"},
  "mix-tanks-state": {"Topic": "timebase/bluebird-bev/[type.@name]/[instance.@name]/state"}}}}
```"""


class BridgeLookupTests(unittest.TestCase):
    def test_prefix_filter(self):
        self.assertEqual(bl.topic_prefix_filter("timebase/bluebird-bev/[type.@name]/[instance.@name]"), "timebase/bluebird-bev/#")
        self.assertEqual(bl.topic_prefix_filter("plant/[type.@name]-x"), "plant/#")
        self.assertEqual(bl.topic_prefix_filter("[domain]/x"), "#")
        self.assertEqual(bl.topic_prefix_filter("fixed/topic"), "fixed/topic")

    def test_parse(self):
        self.assertEqual(bl.parse_instances(LIST), [("brg_5c1f28", "Microsoft.SqlServer"), ("brg_a7e301", "MQTT")])
        subs = bl.parse_settings(SETTINGS)["Settings"]["Subscriptions"]
        self.assertEqual({bl.topic_prefix_filter(s["Topic"]) for s in subs.values()}, {"timebase/bluebird-bev/#"})

    def test_fallback_and_effective(self):
        old = dict(bl.STATE)
        try:
            bl.STATE.update({"configured": False, "byHost": {}, "error": None, "checkedAt": None})
            eff = bl.effective_excludes({"host": "mosquitto", "handoffExclude": ["$SYS/#"]})
            self.assertEqual(eff["filters"], ["$SYS/#", "timebase/#"])
            self.assertEqual(eff["bridge"]["source"], "fallback")
            bl.STATE.update({"configured": True, "byHost": {"mosquitto": ["timebase/bluebird-bev/#"]}, "checkedAt": 1})
            self.assertEqual(bl.effective_excludes({"host": "Mosquitto"})["filters"], ["$SYS/#", "timebase/bluebird-bev/#"])
            self.assertEqual(bl.effective_excludes({"host": "other"})["filters"], ["$SYS/#"])
        finally:
            bl.STATE.clear()
            bl.STATE.update(old)


if __name__ == "__main__":
    unittest.main()
