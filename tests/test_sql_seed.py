import json
import re
import unittest
from pathlib import Path
from scripts.sql_seed import (render_sql_seed, parse_seed, reconcile_astra_ultrafast,
                              target_records, drift_report, conflict_clause, PRICE_IDS, CREATE_STATEMENTS)

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / 'data' / 'pricing-v2-preview'


class SqlSeedContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = [json.loads((PREVIEW / name).read_text(encoding='utf-8'))
                      for name in ('sources.json', 'models.json', 'prices.json')]
        cls.sql = render_sql_seed(*cls.inputs)
        cls.lines = cls.sql.splitlines()

    def test_single_transaction_covers_all_writes(self):
        self.assertEqual(self.lines[0], 'begin;')
        self.assertEqual(self.lines[-1], 'commit;')
        self.assertEqual(self.lines.count('begin;'), 1)
        self.assertEqual(self.lines.count('commit;'), 1)
        for line in self.lines[1:-1]:
            self.assertTrue(line.startswith(('create table if not exists ', 'insert into ')))

    def test_all_records_preserved_without_duplicate_keys(self):
        tables = ('sources', 'models', 'prices')
        fields = ('sourceId', 'internalId', 'pricingId')
        for table, field, records in zip(tables, fields, self.inputs):
            lines = [line for line in self.lines if line.startswith(f'insert into pricing_v2_preview_{table} ')]
            keys = [re.search(r"values \('([^']+)'", line).group(1) for line in lines]
            self.assertEqual(keys, [record[field] for record in records])
            self.assertEqual(len(keys), len(set(keys)))
            for line, record in zip(lines, records):
                encoded = json.dumps(record, sort_keys=True).replace("'", "''")
                self.assertIn(f"'{encoded}'::jsonb", line)

    def test_every_record_has_existing_upsert_contract(self):
        for line in self.lines:
            if line.startswith('insert into '):
                key = 'pricing_id' if '_prices ' in line else 'internal_id' if '_models ' in line else 'source_id'
                self.assertIn(f'on conflict ({key}) do update set ', line)
                self.assertTrue(line.endswith('payload = excluded.payload;'))
                if key == 'pricing_id':
                    self.assertIn('model_internal_id = excluded.model_internal_id, ', line)

    def test_ultrafast_records_and_source_inside_transaction(self):
        expected = [
            'source:openai:developers-openai-com-api-docs-guides-ultrafast-mode',
            'price:openai/gpt-6-astra:ultrafast:short:current',
            'price:openai/gpt-6-astra:ultrafast:long:current',
        ]
        for key in expected:
            matches = [index for index, line in enumerate(self.lines) if f"values ('{key}'" in line]
            self.assertEqual(len(matches), 1)
            self.assertGreater(matches[0], 0)
            self.assertLess(matches[0], len(self.lines)-1)

    def test_price_model_and_source_relations_preserved(self):
        sources, models, prices = self.inputs
        model_ids = {row['internalId'] for row in models}
        source_ids = {row['sourceId'] for row in sources}
        for price in prices:
            self.assertIn(price['modelInternalId'], model_ids)
            self.assertTrue(set(price['sourceRefs']).issubset(source_ids))

    def test_render_repeat_is_identical_and_matches_artifact(self):
        self.assertEqual(self.sql, render_sql_seed(*self.inputs))
        self.assertEqual(self.sql, (PREVIEW / 'generated/seed-pricing.preview.sql').read_text(encoding='utf-8'))
        generator = (ROOT / 'scripts/generate_pricing_v2_preview.py').read_text(encoding='utf-8')
        self.assertIn('sql_seed = render_sql_seed(sources, models, prices)', generator)
        self.assertIn('write_text_with_retry(GENERATED / "seed-pricing.preview.sql", sql_seed)', generator)

    def test_json_apostrophe_escaping(self):
        sql = render_sql_seed([{'sourceId': 'source:test', 'note': "organization's access"}], [], [])
        self.assertIn("organization''s access", sql)


class TargetedSqlSeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.inputs = [json.loads((PREVIEW / name).read_text(encoding='utf-8'))
                      for name in ('sources.json', 'models.json', 'prices.json')]
        cls.baseline = (PREVIEW / 'generated/seed-pricing.preview.sql').read_text(encoding='utf-8')
        cls.source, cls.prices = target_records(cls.inputs[0], cls.inputs[2])
        cls.targets = {('sources', cls.source['sourceId']), *(('prices', p['pricingId']) for p in cls.prices)}
        cls.candidate = reconcile_astra_ultrafast(cls.baseline, cls.inputs[0], cls.inputs[2])
        cls.before = {(r.table, r.key): r for r in parse_seed(cls.baseline)}
        cls.after = {(r.table, r.key): r for r in parse_seed(cls.candidate)}

    def test_actual_artifact_is_already_reconciled_and_transactional(self):
        self.assertEqual(self.baseline, self.candidate)
        self.assertTrue(all(r.in_transaction and r.upsert for r in parse_seed(self.baseline)))

    def test_exact_target_identities_payloads_and_relations(self):
        self.assertEqual(self.source['url'], 'https://developers.openai.com/api/docs/guides/ultrafast-mode')
        self.assertEqual({p['pricingId'] for p in self.prices}, set(PRICE_IDS))
        self.assertEqual(self.prices, [p for p in self.inputs[2] if p['pricingId'] in PRICE_IDS])
        self.assertEqual(self.after[('sources', self.source['sourceId'])].payload, self.source)
        for p in self.prices:
            row = self.after[('prices', p['pricingId'])]
            self.assertEqual(row.payload, p)
            self.assertEqual(row.model_key, 'openai/gpt-6-astra')
            self.assertIn(self.source['sourceId'], row.payload['sourceRefs'])
        self.assertIn(('models', 'openai/gpt-6-astra'), self.after)

    def test_all_records_inside_single_transaction_and_original_tables(self):
        rows = parse_seed(self.candidate)
        self.assertTrue(all(r.in_transaction for r in rows))
        self.assertEqual(self.candidate.splitlines().count('begin;'), 1)
        self.assertEqual(self.candidate.splitlines().count('commit;'), 1)
        self.assertEqual(self.candidate.splitlines()[1:4], CREATE_STATEMENTS)
        self.assertEqual(self.candidate.splitlines()[-1], 'commit;')

    def test_actual_target_upsert_columns_and_assignments(self):
        for key in self.targets:
            row = self.after[key]
            self.assertTrue(row.upsert)
            self.assertEqual(row.raw, next(r.raw for r in parse_seed(render_sql_seed(
                [self.source] if row.table == 'sources' else [], [],
                [row.payload] if row.table == 'prices' else [])) if r.key == row.key))
        self.assertTrue(all(r.upsert for r in self.after.values()))

    def test_all_existing_keys_and_nontarget_payload_bytes_preserved(self):
        self.assertEqual(set(self.before), set(self.after))
        for key, before in self.before.items():
            self.assertEqual(before.payload, self.after[key].payload)
            if key not in self.targets:
                self.assertEqual(before.raw, self.after[key].raw)
                self.assertEqual(before.model_key, self.after[key].model_key)
        self.assertEqual(len(self.after), sum(len(rows) for rows in self.inputs))

    def test_original_group_order_and_target_dependency_order(self):
        ranks = {'sources': 0, 'models': 1, 'prices': 2}
        rows = parse_seed(self.candidate)
        self.assertEqual([ranks[r.table] for r in rows], sorted(ranks[r.table] for r in rows))
        for table in ranks:
            old = [r.key for r in self.before.values() if r.table == table and (r.table, r.key) not in self.targets]
            new = [r.key for r in rows if r.table == table and (r.table, r.key) not in self.targets]
            self.assertEqual(old, new)
        self.assertLess(self.after[('sources', self.source['sourceId'])].line,
                        self.after[('models', 'openai/gpt-6-astra')].line)
        for price in self.prices:
            self.assertLess(self.after[('models', 'openai/gpt-6-astra')].line,
                            self.after[('prices', price['pricingId'])].line)

    def test_two_reconciliations_identical_no_duplicate_append(self):
        second = reconcile_astra_ultrafast(self.candidate, self.inputs[0], self.inputs[2])
        self.assertEqual(second, self.candidate)
        self.assertEqual(len(parse_seed(second)), len(self.before))

    def test_repair_original_outside_transaction_fixture(self):
        records = parse_seed(self.candidate)
        old_lines = ['begin;', *CREATE_STATEMENTS]
        old_lines.extend(r.raw for r in records if (r.table, r.key) not in self.targets)
        old_lines.append('commit;')
        for key in [('sources', self.source['sourceId']), *(('prices', p['pricingId']) for p in self.prices)]:
            row = self.after[key]
            old_lines.append(row.raw.replace(conflict_clause(row.table), '').replace('::jsonb', ''))
        malformed = '\n'.join(old_lines) + '\n'
        self.assertEqual(sum(not r.in_transaction for r in parse_seed(malformed)), 3)
        self.assertEqual(reconcile_astra_ultrafast(malformed, self.inputs[0], self.inputs[2]), self.candidate)

    def test_duplicate_primary_key_rejected(self):
        fixture = self.candidate.replace('commit;', self.after[('prices', PRICE_IDS[0])].raw+'\ncommit;')
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            reconcile_astra_ultrafast(fixture, self.inputs[0], self.inputs[2])

    def test_unrelated_outside_write_rejected(self):
        row = next(r for key, r in self.after.items() if key not in self.targets)
        fixture = self.candidate.replace(row.raw+'\n', '').rstrip()+'\n'+row.raw+'\n'
        with self.assertRaisesRegex(ValueError, 'Non-target write'):
            reconcile_astra_ultrafast(fixture, self.inputs[0], self.inputs[2])

    def test_unsupported_statement_or_second_transaction_rejected(self):
        for suffix in ('delete from pricing_v2_preview_prices;\n', 'begin;\ncommit;\n'):
            with self.assertRaises(ValueError):
                reconcile_astra_ultrafast(self.candidate+suffix, self.inputs[0], self.inputs[2])

    def test_wrong_conflict_key_or_model_association_rejected(self):
        row = self.after[('prices', PRICE_IDS[0])]
        for broken in (row.raw.replace('on conflict (pricing_id)', 'on conflict (source_id)'),
                       row.raw.replace("'openai/gpt-6-astra',", "'openai/wrong-model',", 1)):
            with self.assertRaises(ValueError):
                reconcile_astra_ultrafast(self.candidate.replace(row.raw, broken), self.inputs[0], self.inputs[2])

    def test_authoritative_payload_mismatch_or_missing_target_rejected(self):
        fixture_prices = json.loads(json.dumps(self.inputs[2]))
        next(p for p in fixture_prices if p['pricingId'] == PRICE_IDS[0])['billingNote'] = 'Wrong note'
        with self.assertRaisesRegex(ValueError, 'payload differs'):
            reconcile_astra_ultrafast(self.candidate, self.inputs[0], fixture_prices)
        missing = self.candidate.replace(self.after[('prices', PRICE_IDS[0])].raw+'\n', '')
        with self.assertRaisesRegex(ValueError, 'target INSERT is missing'):
            reconcile_astra_ultrafast(missing, self.inputs[0], self.inputs[2])

    def test_source_url_ambiguous_or_target_dependency_missing_rejected(self):
        with self.assertRaisesRegex(ValueError, 'resolve exactly once'):
            reconcile_astra_ultrafast(self.candidate, self.inputs[0]+[self.source], self.inputs[2])
        ref = next(ref for ref in self.prices[0]['sourceRefs'] if ref != self.source['sourceId'])
        fixture = self.candidate.replace(self.after[('sources', ref)].raw+'\n', '')
        with self.assertRaisesRegex(ValueError, 'unresolved source'):
            reconcile_astra_ultrafast(fixture, self.inputs[0], self.inputs[2])

    def test_escaping_handles_quotes_semicolons_and_newlines(self):
        payload = {'sourceId': 'source:test', 'note': "organization's ; COMMIT;\n verification"}
        record = parse_seed(render_sql_seed([payload], [], []))[0]
        self.assertEqual(record.payload, payload)
        self.assertTrue(record.in_transaction and record.upsert)

    def test_full_historical_parity_and_drift_reporting_remain_strict(self):
        report = drift_report(self.candidate, *self.inputs)
        self.assertEqual(report, {'fieldChanges': [], 'missingRecords': [], 'unresolvedReferences': []})
        self.assertEqual(self.candidate, render_sql_seed(*self.inputs))
        sources, models, prices = json.loads(json.dumps(self.inputs))
        sources[0]['supports'] = []
        models[0]['accessStatus'] = 'unknown'
        omitted = sources.pop()
        fixture = render_sql_seed(sources, models, prices)
        report = drift_report(fixture, *self.inputs)
        self.assertEqual(report['fieldChanges'], [
            {'table': 'sources', 'key': self.inputs[0][0]['sourceId'], 'fields': ['supports']},
            {'table': 'models', 'key': self.inputs[1][0]['internalId'], 'fields': ['accessStatus']},
        ])
        self.assertEqual(report['missingRecords'], [{'table': 'sources', 'key': omitted['sourceId']}])

    def test_drift_report_detects_missing_reference_without_importing_it(self):
        ref = self.prices[0]['sourceRefs'][0]
        fixture = self.candidate.replace(self.after[('sources', ref)].raw+'\n', '')
        report = drift_report(fixture, *self.inputs)
        self.assertTrue(any(r.get('missingSource') == ref for r in report['unresolvedReferences']))

    def test_round1_notes_and_ten_astra_record_payloads_preserved(self):
        cohere = self.after[('prices', 'price:cohere/command-a-plus:standard:short:current')].payload
        self.assertIn('$32.50', cohere['billingNote'])
        self.assertIn('$17.50', cohere['billingNote'])
        self.assertNotIn('$57.50', cohere['billingNote'])
        mythos = self.after[('prices', 'price:anthropic/claude-mythos-5-1:standard:short:current')].payload
        self.assertIn('verification required', mythos['billingNote'])
        self.assertNotIn('Glasswing', mythos['billingNote'])
        astra = [r for r in self.after.values() if r.table == 'prices' and r.model_key == 'openai/gpt-6-astra']
        self.assertEqual(len(astra), 10)
        expected = {p['pricingId']: p for p in self.inputs[2] if p['modelInternalId'] == 'openai/gpt-6-astra'}
        self.assertEqual({r.key: r.payload for r in astra}, expected)

    def test_targeted_cli_check_and_full_check_distinct(self):
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory(prefix='targeted-sql-test-') as temp:
            candidate = Path(temp)/'seed.sql'
            candidate.write_text(self.candidate, encoding='utf-8', newline='\n')
            targeted = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/sql_seed.py'),
                                       '--targeted-astra-ultrafast', '--check', '--seed-file', str(candidate)],
                                      capture_output=True, text=True)
            self.assertEqual(targeted.returncode, 0, targeted.stderr)
            original = candidate.read_bytes()
            for _ in range(2):
                run = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/sql_seed.py'),
                                      '--targeted-astra-ultrafast', '--write', '--seed-file', str(candidate)],
                                     capture_output=True, text=True)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertEqual(candidate.read_bytes(), original)
        full = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/sql_seed.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(full.returncode, 0, full.stderr)
        # A non-target metadata mutation must fail full check while targeted check
        # deliberately preserves it; the two checks cannot replace each other.
        with tempfile.TemporaryDirectory(prefix='full-sql-negative-') as temp:
            mutated = json.loads(json.dumps(self.inputs))
            mutated[1][0]['availability'] = 'SQL metadata drift fixture'
            fixture = Path(temp)/'seed.sql'
            fixture.write_text(render_sql_seed(*mutated), encoding='utf-8', newline='\n')
            command = [sys.executable, '-B', str(ROOT/'scripts/sql_seed.py'), '--check', '--seed-file', str(fixture)]
            rejected = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn('differs from persisted preview inputs', rejected.stderr)
            targeted = subprocess.run(command+['--targeted-astra-ultrafast'], capture_output=True, text=True)
            self.assertEqual(targeted.returncode, 0, targeted.stderr)


if __name__ == '__main__':
    unittest.main()
