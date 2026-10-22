import unittest

import pandas as pd

from scripts import benchmark_m5_routing as routing


class M5RoutingTests(unittest.TestCase):
    def test_segments_use_history_at_each_origin(self):
        dates = pd.date_range("2026-01-01", periods=84)
        rows = []
        for sku, positives in (("sparse", 7), ("dense", 35)):
            rows.extend({"date": date, "store_id": "store", "sku_id": sku,
                         "channel": "in_store", "quantity_sold": int(index % 56 < positives)}
                        for index, date in enumerate(dates))
        labels = routing.segments_at_origin(pd.DataFrame(rows), dates[55])
        self.assertEqual(labels, {"store/dense/in_store": "dense", "store/sparse/in_store": "sparse"})

    def test_route_preserves_each_series_once(self):
        labels = {"store/a/in_store": "sparse", "store/b/in_store": "dense"}
        rows = {method: [("fold", sku, 1, 2., float(index)) for sku in labels]
                for index, method in enumerate(routing.METHODS)}
        routed = routing.apply_route(rows, labels, {"sparse": "mean4", "dense": "original"})
        self.assertEqual(len(routed), 2)
        self.assertEqual({row[1]: row[4] for row in routed}, {"store/a/in_store": 2., "store/b/in_store": 0.})

    def test_gate_rejects_weak_gain(self):
        base = {"original": {"weekly_wape": .4, "sku_28day_wape": .3, "daily_wape": .5},
                "routed": {"weekly_wape": .39, "sku_28day_wape": .29, "daily_wape": .5}}
        groups = {segment: base for segment in routing.SEGMENTS}
        self.assertFalse(routing.check_gate(base, groups, {"lower": .01})["weekly_gain_2pp"])


if __name__ == "__main__":
    unittest.main()
