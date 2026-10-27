r"""Export the documented UCI Online Retail demo windows as importable CSV files.

From backend/:
    .\.venv\Scripts\python.exe scripts\prepare_uci_demo_csv.py \
        --source-zip data\uploads\uci_online_retail.zip
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from real_data_e2e import prepare_data


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "ex_sales"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    source = args.source_zip.resolve()
    if not source.is_file():
        parser.error(f"Source ZIP not found: {source}")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    files = {
        "train": output / "uci-online-retail-demo-train.csv",
        "full": output / "uci-online-retail-demo-full.csv",
    }
    if any(path.exists() for path in files.values()):
        parser.error("Output CSV already exists; remove it explicitly before regenerating")

    train, full, details = prepare_data(source)
    expected_columns = ["date", "store_id", "sku_id", "channel", "quantity_sold", "unit_price"]
    assert list(train.columns) == list(full.columns) == expected_columns
    assert len(train) == details["initial_rows"] == 1272
    assert len(full) == details["full_rows"] == 1440
    assert not train.duplicated(["date", "store_id", "sku_id", "channel"]).any()
    assert not full.duplicated(["date", "store_id", "sku_id", "channel"]).any()
    assert not train.isna().any().any() and not full.isna().any().any()
    for frame in (train, full):
        assert frame.quantity_sold.mod(1).eq(0).all()
        frame["quantity_sold"] = frame.quantity_sold.astype("int64")

    train.to_csv(files["train"], index=False, encoding="utf-8")
    full.to_csv(files["full"], index=False, encoding="utf-8")
    print(json.dumps({
        "source_sha256": sha256(source),
        "source": details,
        "outputs": {
            name: {"path": str(path), "sha256": sha256(path), "rows": len(train if name == "train" else full)}
            for name, path in files.items()
        },
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
