from __future__ import annotations

import argparse
import shutil
from collections import defaultdict
from pathlib import Path

from lib import ROOT, append_history_if_changed, build_dataset, history_entry, load_models, load_providers, utc_now, utc_today, write_csv, write_json


def build_outputs(output_root: Path) -> None:
    data = output_root / "data"
    api = output_root / "api" / "v1"
    for path in [data / "prices.json", data / "prices.csv", data / "providers", data / "models", api]:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    providers = load_providers()
    models = load_models()
    generated_at = utc_now()
    dataset = build_dataset(generated_at)

    write_json(data / "prices.json", dataset)
    write_csv(data / "prices.csv", models)

    provider_models = defaultdict(list)
    for model in models:
        provider_models[model["provider_id"]].append(model)

    for provider in providers:
        provider_id = provider["provider_id"]
        payload = {
            **provider,
            "models": sorted(provider_models[provider_id], key=lambda item: item["model_id"]),
        }
        write_json(data / "providers" / f"{provider_id}.json", payload)

    for model in models:
        provider_id = model["provider_id"]
        model_id = model["model_id"]
        write_json(data / "models" / provider_id / f"{model_id}.json", model)
        history_path = data / "history" / provider_id / f"{model_id}.jsonl"
        append_history_if_changed(history_path, history_entry(model, generated_at))

    snapshot_dir = data / "snapshots" / utc_today()
    write_json(snapshot_dir / "prices.json", dataset)
    write_csv(snapshot_dir / "prices.csv", models)

    write_json(api / "prices.json", dataset)
    write_csv(api / "prices.csv", models)
    write_json(
        api / "meta.json",
        {
            "dataset_name": dataset["dataset_name"],
            "dataset_version": dataset["dataset_version"],
            "generated_at": dataset["generated_at"],
            "provider_count": dataset["provider_count"],
            "model_count": dataset["model_count"],
            "official_source_count": dataset["official_source_count"],
            "last_verified_at": dataset["last_verified_at"],
            "homepage": dataset["homepage"],
        },
    )
    for provider in providers:
        source = data / "providers" / f"{provider['provider_id']}.json"
        write_json(api / "providers" / source.name, __import__("json").loads(source.read_text(encoding="utf-8")))
    for model in models:
        write_json(api / "models" / model["provider_id"] / f"{model['model_id']}.json", model)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build public dataset artifacts.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=ROOT,
        help="Root directory for generated data/ and api/v1/ outputs (defaults to the repository root).",
    )
    args = parser.parse_args()
    build_outputs(args.output_root.resolve())


if __name__ == "__main__":
    main()
