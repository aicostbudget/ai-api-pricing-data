from __future__ import annotations

import argparse
import json
from pathlib import Path


def key(model: dict) -> tuple[str, str]:
    return model["provider_id"], model["model_id"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two prices.json files.")
    parser.add_argument("old")
    parser.add_argument("new")
    args = parser.parse_args()
    old = {key(model): model for model in json.loads(Path(args.old).read_text(encoding="utf-8"))["models"]}
    new = {key(model): model for model in json.loads(Path(args.new).read_text(encoding="utf-8"))["models"]}
    for item in sorted(new.keys() - old.keys()):
        print(f"added {item[0]}/{item[1]}")
    for item in sorted(old.keys() - new.keys()):
        print(f"removed {item[0]}/{item[1]}")
    for item in sorted(old.keys() & new.keys()):
        if old[item]["pricing"] != new[item]["pricing"]:
            print(f"changed {item[0]}/{item[1]}")


if __name__ == "__main__":
    main()

