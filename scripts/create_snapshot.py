from __future__ import annotations

import argparse

from lib import DATA, load_models, write_csv, write_json, build_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a dated data snapshot.")
    parser.add_argument("date", nargs="?", default="2026-07-05", help="Snapshot date in YYYY-MM-DD format.")
    args = parser.parse_args()
    target = DATA / "snapshots" / args.date
    write_json(target / "prices.json", build_dataset())
    write_csv(target / "prices.csv", load_models())


if __name__ == "__main__":
    main()

