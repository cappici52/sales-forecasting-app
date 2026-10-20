import tempfile
import unittest
from pathlib import Path

import pandas as pd

from scripts import benchmark_olist


class OlistBenchmarkTests(unittest.TestCase):
    def test_category_selection_uses_training_only_and_zero_days_keep_last_price(self):
        scratch = Path(__file__).resolve().parents[1] / "data" / "uploads"
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as directory:
            folder = Path(directory)
            orders, items, products = [], [], []
            for index, category in enumerate("ABCDEFG"):
                products.append({"product_id": category, "product_category_name": category})
                for number in range(2 if category != "G" else 1):
                    order_id = f"train-{category}-{number}"
                    orders.append({"order_id": order_id, "order_status": "delivered",
                                   "order_purchase_timestamp": "2017-03-01 12:00:00"})
                    items.append({"order_id": order_id, "product_id": category, "price": index + 1})
            for number in range(100):
                order_id = f"holdout-G-{number}"
                orders.append({"order_id": order_id, "order_status": "delivered",
                               "order_purchase_timestamp": "2018-07-01 12:00:00"})
                items.append({"order_id": order_id, "product_id": "G", "price": 7})
            pd.DataFrame(orders).to_csv(folder / "olist_orders_dataset.csv", index=False)
            pd.DataFrame(items).to_csv(folder / "olist_order_items_dataset.csv", index=False)
            pd.DataFrame(products).to_csv(folder / "olist_products_dataset.csv", index=False)

            frame, categories = benchmark_olist.load_frame(folder)

        self.assertEqual(categories, list("ABCDEF"))
        self.assertEqual(len(frame), 6 * len(pd.date_range(benchmark_olist.START, benchmark_olist.TEST_END)))
        absent = frame.loc[frame.sku_id.eq("A") & frame.date.eq(pd.Timestamp("2017-03-02"))].iloc[0]
        self.assertEqual(absent.quantity_sold, 0)
        self.assertEqual(absent.unit_price, 1)
        self.assertEqual(benchmark_olist.wape([(10, 8, 100, 80)], 0, 1), 0.2)


if __name__ == "__main__":
    unittest.main()
