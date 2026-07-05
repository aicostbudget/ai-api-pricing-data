from __future__ import annotations

import shutil

from lib import API, DATA


def main() -> None:
    if API.exists():
        shutil.rmtree(API)
    shutil.copytree(DATA / "providers", API / "providers")
    shutil.copytree(DATA / "models", API / "models")
    shutil.copy2(DATA / "prices.json", API / "prices.json")
    shutil.copy2(DATA / "prices.csv", API / "prices.csv")


if __name__ == "__main__":
    main()

