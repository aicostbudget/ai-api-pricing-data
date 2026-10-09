"""Render the preview seed from persisted inputs without refreshing other artifacts."""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


def render_sql_seed(sources: list[dict], models: list[dict], prices: list[dict]) -> str:
    def sql_json(value: dict) -> str:
        return json.dumps(value, sort_keys=True).replace("'", "''")

    sql_lines = [
        "begin;",
        "create table if not exists pricing_v2_preview_sources (source_id text primary key, payload jsonb not null);",
        "create table if not exists pricing_v2_preview_models (internal_id text primary key, payload jsonb not null);",
        "create table if not exists pricing_v2_preview_prices (pricing_id text primary key, model_internal_id text not null, payload jsonb not null);",
    ]
    for source in sources:
        sql_lines.append(
            "insert into pricing_v2_preview_sources (source_id, payload) values "
            + f"('{source['sourceId']}', '{sql_json(source)}'::jsonb) "
            + "on conflict (source_id) do update set payload = excluded.payload;"
        )
    for model in models:
        sql_lines.append(
            "insert into pricing_v2_preview_models (internal_id, payload) values "
            + f"('{model['internalId']}', '{sql_json(model)}'::jsonb) "
            + "on conflict (internal_id) do update set payload = excluded.payload;"
        )
    for price in prices:
        sql_lines.append(
            "insert into pricing_v2_preview_prices (pricing_id, model_internal_id, payload) values "
            + f"('{price['pricingId']}', '{price['modelInternalId']}', '{sql_json(price)}'::jsonb) "
            + "on conflict (pricing_id) do update set model_internal_id = excluded.model_internal_id, payload = excluded.payload;"
        )
    sql_lines.extend(["commit;", ""])

    return "\n".join(sql_lines)



TABLE_KEYS = {"sources": "sourceId", "models": "internalId", "prices": "pricingId"}
CREATE_STATEMENTS = render_sql_seed([], [], []).splitlines()[1:4]
PRICE_IDS = ("price:openai/gpt-6-astra:ultrafast:short:current",
             "price:openai/gpt-6-astra:ultrafast:long:current")
SOURCE_URL = "https://developers.openai.com/api/docs/guides/ultrafast-mode"
SQL_LITERAL = r"'((?:[^']|'')*)'"
INSERT = re.compile(
    r"insert into pricing_v2_preview_(sources|models|prices) "
    r"\((source_id, payload|internal_id, payload|pricing_id, model_internal_id, payload)\) values \("
    + SQL_LITERAL + r", (?:" + SQL_LITERAL + r", )?" + SQL_LITERAL
    + r"(::jsonb)?\)(.*);"
)


@dataclass(frozen=True)
class SeedRecord:
    table: str
    key: str
    model_key: str | None
    payload: dict
    raw: str
    line: int
    in_transaction: bool
    upsert: bool


def conflict_clause(table: str) -> str:
    key = {"sources": "source_id", "models": "internal_id", "prices": "pricing_id"}[table]
    assignment = "model_internal_id = excluded.model_internal_id, " if table == "prices" else ""
    return f" on conflict ({key}) do update set {assignment}payload = excluded.payload"


def parse_seed(sql: str) -> list[SeedRecord]:
    """Parse only the repository's seed grammar; reject unknown statements and duplicates."""
    records = []
    seen = set()
    active = False
    begin = commit = 0
    creates = []
    for index, raw in enumerate(sql.splitlines(), 1):
        if not raw.strip():
            continue
        if raw == "begin;":
            if active or begin or commit:
                raise ValueError("Invalid BEGIN structure")
            begin += 1
            active = True
            continue
        if raw == "commit;":
            if not active or commit:
                raise ValueError("Invalid COMMIT structure")
            commit += 1
            active = False
            continue
        if raw in CREATE_STATEMENTS:
            if not active or records:
                raise ValueError("Unexpected CREATE TABLE position")
            creates.append(raw)
            continue
        match = INSERT.fullmatch(raw)
        if not match:
            raise ValueError(f"Unsupported seed statement at line {index}")
        table, columns, key, model_key, encoded, cast, suffix = match.groups()
        expected_columns = {"sources": "source_id, payload", "models": "internal_id, payload",
                            "prices": "pricing_id, model_internal_id, payload"}[table]
        if columns != expected_columns or (model_key is not None) != (table == "prices"):
            raise ValueError("Invalid INSERT columns")
        key = key.replace("''", "'")
        model_key = model_key.replace("''", "'") if model_key is not None else None
        payload = json.loads(encoded.replace("''", "'"))
        if not isinstance(payload, dict) or payload.get(TABLE_KEYS[table]) != key:
            raise ValueError("Primary key and payload identity differ")
        if table == "prices" and payload.get("modelInternalId") != model_key:
            raise ValueError("Price/model association differs")
        if (table, key) in seen:
            raise ValueError("Duplicate seed primary key")
        seen.add((table, key))
        upsert = suffix == conflict_clause(table) and cast == "::jsonb"
        if suffix and not upsert:
            raise ValueError("Unexpected conflict clause")
        records.append(SeedRecord(table, key, model_key, payload, raw, index, active, upsert))
    if begin != 1 or commit != 1 or active or creates != CREATE_STATEMENTS:
        raise ValueError("Seed must have exactly one transaction and the existing table schema")
    return records


def target_records(sources: list[dict], prices: list[dict]) -> tuple[dict, list[dict]]:
    matches = [row for row in sources if row.get("url", "").rstrip("/") == SOURCE_URL]
    if len(matches) != 1:
        raise ValueError("Ultrafast official source must resolve exactly once")
    source = matches[0]
    selected = []
    for key in PRICE_IDS:
        rows = [row for row in prices if row.get("pricingId") == key]
        if len(rows) != 1 or rows[0].get("modelInternalId") != "openai/gpt-6-astra":
            raise ValueError("Ultrafast price must resolve exactly once to Astra")
        if source["sourceId"] not in rows[0].get("sourceRefs", []):
            raise ValueError("Ultrafast price must cite the authoritative source")
        selected.append(rows[0])
    # Follow persisted input order, exactly as the shared full renderer does.
    return source, [row for row in prices if row.get("pricingId") in PRICE_IDS]


def reconcile_astra_ultrafast(sql: str, sources: list[dict], prices: list[dict]) -> str:
    baseline = parse_seed(sql)
    source, selected = target_records(sources, prices)
    targets = {("sources", source["sourceId"]), *(('prices', row['pricingId']) for row in selected)}
    old = {(row.table, row.key): row for row in baseline}
    for key in targets:
        if key not in old:
            raise ValueError("Expected existing target INSERT is missing")
    for row in baseline:
        if (row.table, row.key) not in targets and (not row.in_transaction or not row.upsert):
            raise ValueError("Non-target write outside transaction or without upsert")
    if ("models", "openai/gpt-6-astra") not in old:
        raise ValueError("Astra model row missing")
    expected = {("sources", source["sourceId"]): source,
                **{("prices", row["pricingId"]): row for row in selected}}
    for key, payload in expected.items():
        if old[key].payload != payload:
            raise ValueError("Existing target payload differs from authoritative V2")
    generated = parse_seed(render_sql_seed([source], [], selected))
    target_sql = {(row.table, row.key): row.raw for row in generated}
    lines = ["begin;", *CREATE_STATEMENTS]
    ordering = {
        "sources": {row["sourceId"]: index for index, row in enumerate(sources)},
        "prices": {row["pricingId"]: index for index, row in enumerate(prices)},
    }
    for table in TABLE_KEYS:
        rows = [row for row in baseline if row.table == table]
        if table in ordering:
            # Restore canonical positions even when old target INSERTs were outside
            # the transaction, while preserving every non-target INSERT byte.
            rows.sort(key=lambda row: ordering[table].get(row.key, len(ordering[table])))
        lines.extend(target_sql.get((row.table, row.key), row.raw) for row in rows)
    lines.append("commit;")
    result = "\n".join(lines) + "\n"
    candidate = parse_seed(result)
    after = {(row.table, row.key): row for row in candidate}
    if set(old) != set(after):
        raise ValueError("Seed keys changed")
    for key, row in old.items():
        if key not in targets and row.raw != after[key].raw:
            raise ValueError("Non-target INSERT changed")
    if not all(row.in_transaction and row.upsert for row in candidate):
        raise ValueError("Candidate transaction/upsert contract failed")
    # Target references must resolve without importing historical metadata drift.
    known_sources = {row.key for row in candidate if row.table == "sources"}
    for price in selected:
        if not set(price["sourceRefs"]).issubset(known_sources):
            raise ValueError("Target price has unresolved source references")
    return result


def drift_report(sql: str, sources: list[dict], models: list[dict], prices: list[dict]) -> dict:
    records = parse_seed(sql)
    existing = {(row.table, row.key): row for row in records}
    expected = {(table, row[TABLE_KEYS[table]]): row
                for table, rows in zip(TABLE_KEYS, (sources, models, prices)) for row in rows}
    changed = [{"table": table, "key": key,
                "fields": sorted(field for field in existing[(table, key)].payload.keys() | payload.keys()
                                 if existing[(table, key)].payload.get(field) != payload.get(field))}
               for (table, key), payload in expected.items()
               if (table, key) in existing and existing[(table, key)].payload != payload]
    missing = [{"table": table, "key": key} for table, key in expected if (table, key) not in existing]
    source_keys = {row.key for row in records if row.table == "sources"}
    model_keys = {row.key for row in records if row.table == "models"}
    references = []
    def source_refs(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "sourceRef" and isinstance(item, str):
                    yield item
                elif key.endswith("SourceRefs") or key == "sourceRefs":
                    if isinstance(item, list):
                        yield from item
                else:
                    yield from source_refs(item)
        elif isinstance(value, list):
            for item in value:
                yield from source_refs(item)
    for row in records:
        for ref in sorted(set(source_refs(row.payload)) - source_keys):
            references.append({"table": row.table, "key": row.key, "missingSource": ref})
        if row.table == "prices" and row.model_key not in model_keys:
            references.append({"table": row.table, "key": row.key, "missingModel": row.model_key})
    return {"fieldChanges": changed, "missingRecords": missing, "unresolvedReferences": references}

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    parser.add_argument("--seed-file", type=Path, help="Existing seed or isolated candidate to reconcile/check")
    parser.add_argument("--targeted-astra-ultrafast", action="store_true")
    parser.add_argument("--drift-report", action="store_true", help="Print historical drift without writing artifacts")
    args = parser.parse_args()
    preview = Path(__file__).resolve().parents[1] / "data" / "pricing-v2-preview"
    inputs = [json.loads((preview / name).read_text(encoding="utf-8"))
              for name in ("sources.json", "models.json", "prices.json")]
    output = args.seed_file or preview / "generated" / "seed-pricing.preview.sql"
    current = output.read_text(encoding="utf-8")
    if args.drift_report:
        if args.write:
            parser.error("--drift-report is read-only; use --check")
        print(json.dumps(drift_report(current, *inputs), indent=2, sort_keys=True))
        return
    expected = (reconcile_astra_ultrafast(current, inputs[0], inputs[2])
                if args.targeted_astra_ultrafast else render_sql_seed(*inputs))
    if args.check:
        if output.read_text(encoding="utf-8") != expected:
            parser.exit(1, "SQL seed differs from persisted preview inputs.\n")
        print("Targeted SQL seed is in sync." if args.targeted_astra_ultrafast
              else "SQL seed matches persisted preview inputs.")
    else:
        output.write_text(expected, encoding="utf-8", newline="\n")
        print(f"Generated SQL seed: {output}")


if __name__ == "__main__":
    main()
