from __future__ import annotations

import argparse

from lib import DATA, build_dataset, load_models, utc_now, utc_today, write_csv, write_json


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a dated data snapshot.")
    parser.add_argument("date", nargs="?", default=None, help="Snapshot date in YYYY-MM-DD format.")
    args = parser.parse_args()
    target = DATA / "snapshots" / (args.date or utc_today())
    write_json(target / "prices.json", build_dataset(utc_now()))
    write_csv(target / "prices.csv", load_models())


if __name__ == "__main__":
    main()
