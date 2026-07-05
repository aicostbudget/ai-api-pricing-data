from __future__ import annotations

from lib import DATA, load_models, write_csv


def main() -> None:
    write_csv(DATA / "prices.csv", load_models())


if __name__ == "__main__":
    main()

