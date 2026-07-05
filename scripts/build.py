from __future__ import annotations

from collections import defaultdict

from lib import API, DATA, append_history_if_changed, build_dataset, clean_generated, history_entry, load_models, load_providers, utc_now, utc_today, write_csv, write_json


def main() -> None:
    clean_generated()
    providers = load_providers()
    models = load_models()
    generated_at = utc_now()
    dataset = build_dataset(generated_at)

    write_json(DATA / "prices.json", dataset)
    write_csv(DATA / "prices.csv", models)

    provider_models = defaultdict(list)
    for model in models:
        provider_models[model["provider_id"]].append(model)

    for provider in providers:
        provider_id = provider["provider_id"]
        payload = {
            **provider,
            "models": sorted(provider_models[provider_id], key=lambda item: item["model_id"]),
        }
        write_json(DATA / "providers" / f"{provider_id}.json", payload)

    for model in models:
        provider_id = model["provider_id"]
        model_id = model["model_id"]
        write_json(DATA / "models" / provider_id / f"{model_id}.json", model)
        history_path = DATA / "history" / provider_id / f"{model_id}.jsonl"
        append_history_if_changed(history_path, history_entry(model, generated_at))

    snapshot_dir = DATA / "snapshots" / utc_today()
    write_json(snapshot_dir / "prices.json", dataset)
    write_csv(snapshot_dir / "prices.csv", models)

    write_json(API / "prices.json", dataset)
    write_csv(API / "prices.csv", models)
    write_json(
        API / "meta.json",
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
        source = DATA / "providers" / f"{provider['provider_id']}.json"
        write_json(API / "providers" / source.name, __import__("json").loads(source.read_text(encoding="utf-8")))
    for model in models:
        write_json(API / "models" / model["provider_id"] / f"{model['model_id']}.json", model)


if __name__ == "__main__":
    main()
