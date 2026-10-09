import copy
import json
import re
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from scripts.generate_price_change_events import generate_events

ROOT = Path(__file__).resolve().parents[1]
KEY = 'moonshot-ai/kimi-k2.6'
BASE = '80c2ec4991bcaaf795fe9192946f5ec770d57f48'

def read(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))

class KimiPublishedRateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.models = read('data/canonical/models.json')
        cls.current = next(m for m in cls.models if m['provider_id'] + '/' + m['model_id'] == KEY)
        cls.original = next(m for m in json.loads(subprocess.check_output(['git', 'show', BASE + ':data/canonical/models.json'], cwd=ROOT)) if m['provider_id'] + '/' + m['model_id'] == KEY)

    def test_official_saved_table_maps_exact_batch_cache_hit_cell(self):
        doc = (ROOT / 'reports/issue26-kimi-published-rate-2026-10-09/official-batch.md').read_text(encoding='utf-8')
        columns = re.findall(r'title: "([^"]+)"', doc)
        row = json.loads(re.search(r'\["kimi-k2\.6 \(Batch\)"[^\n]*\]', doc).group())
        values = dict(zip(columns, row))
        self.assertEqual(values['Unit'], '1M tokens')
        self.assertEqual(values['Input Price (Cache Hit)'], '$0.10')
        self.assertEqual(values['Input Price (Cache Miss)'], '$0.57')
        self.assertEqual(values['Output Price'], '$2.40')
        self.assertIn('**60%**', doc)
        self.assertIn('1M = 1,000,000', doc)

    def test_only_batch_cached_amount_sources_notes_and_observation_time_change(self):
        before, after = copy.deepcopy(self.original), copy.deepcopy(self.current)
        self.assertEqual(after['pricing'], {**before['pricing'], 'batch_cached_input': .10})
        after['pricing'] = before['pricing']
        for field in ('accessed_at', 'last_verified_at'):
            actual = datetime.fromisoformat(after[field].replace('Z', '+00:00'))
            self.assertLessEqual(actual, datetime.now(timezone.utc))
            self.assertGreater(after[field], before[field])
            after[field] = before[field]
        self.assertTrue(after['notes'].startswith(before['notes']))
        after['notes'] = before['notes']
        self.assertEqual(after['official_source_urls'], before['official_source_urls'])
        after['official_source_urls'] = before['official_source_urls']
        for old, new in zip(before['price_records'], after['price_records']):
            self.assertEqual(new['checked_at'], self.current['accessed_at'])
            self.assertEqual(new['verified_at'], self.current['last_verified_at'])
            new['checked_at'], new['verified_at'] = old['checked_at'], old['verified_at']
            self.assertEqual(new['source_refs'], old['source_refs'])
            new['source_refs'] = old['source_refs']
            if new['processing_mode'] == 'batch':
                charge = next(c for c in new['charges'] if c['component'] == 'cached_input')
                self.assertEqual((charge['amount'], charge['unit']), ('0.10', 'per_1m_tokens'))
                charge['amount'] = '0.096'
                new['billing_note'] = old['billing_note']
        self.assertEqual(after, before)

    def test_precision_is_disclosed_and_effective_dates_not_invented(self):
        batch = next(r for r in self.current['price_records'] if r['processing_mode'] == 'batch')
        for field in ('effective_from', 'effective_until'):
            self.assertIsNone(batch[field])
        self.assertIsNone(self.current['effective_from'])
        note = batch['billing_note']
        for fact in ('60%', '0.16', '0.096', '0.10', 'BILLING PRECISION UNCONFIRMED', 'not a provider price increase', 'No internal rounding algorithm or invoice-verified settlement rate is asserted'):
            self.assertIn(fact, note)

    def test_v1_v2_api_hf_projection_and_history_agree(self):
        for path in ('data/prices.json', 'api/v1/prices.json', 'data/snapshots/2026-10-09/prices.json'):
            m = next(m for m in read(path)['models'] if m['provider_id'] + '/' + m['model_id'] == KEY)
            self.assertEqual(m, self.current)
        self.assertEqual(read('api/v1/models/moonshot-ai/kimi-k2.6.json'), self.current)
        prices = [r for r in read('data/pricing-v2-preview/prices.json') if r['modelInternalId'] == KEY]
        batch = next(r for r in prices if r['processingMode'] == 'batch')
        self.assertEqual(next(c['amount'] for c in batch['charges'] if c['component'] == 'cached_input'), '0.1')
        self.assertEqual(batch['verifiedAt'], self.current['last_verified_at'])
        self.assertIn('BILLING PRECISION UNCONFIRMED', batch['billingNote'])
        row = next(r for r in read('data/pricing-v2-preview/generated/model-pricing.v2.json')['models'] if r['canonicalInternalId'] == KEY)
        hf = next(r for r in read('huggingface/prices.json')['records'] if r['provider_id'] + '/' + r['model_id'] == KEY)
        for components, mode_key in ((row['pricingComponents'], 'processingMode'), (hf['pricing_components'], 'processing_mode')):
            self.assertTrue(any(c['component'] == 'cached_input' and c['condition'][mode_key] == 'batch' and c['amount'] == '0.1' for c in components))
            caveat_field = 'billingNote' if mode_key == 'processingMode' else 'billing_note'
            for charge in components:
                if charge['condition'][mode_key] == 'batch':
                    self.assertIn('BILLING PRECISION UNCONFIRMED', charge[caveat_field])
        history = [json.loads(line) for line in (ROOT/'data/history/moonshot-ai/kimi-k2.6.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(history[-1]['pricing']['batch_cached_input'], .10)
        self.assertTrue(any(r['pricing'].get('batch_cached_input') == .096 for r in history[:-1]))

    def test_reconciliation_does_not_generate_provider_price_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            before, after = Path(tmp)/'2026-10-08/prices.json', Path(tmp)/'2026-10-09/prices.json'
            before.parent.mkdir(); after.parent.mkdir()
            before.write_text(json.dumps({'models':[self.original]}), encoding='utf-8')
            after.write_text(json.dumps({'models':[self.current]}), encoding='utf-8')
            self.assertEqual(generate_events(before, after), [])
        prior = subprocess.check_output(['git','show', BASE+':data/price-change-events/events.jsonl'],cwd=ROOT)
        current = (ROOT/'data/price-change-events/events.jsonl').read_bytes().replace(b'\r\n',b'\n')
        self.assertEqual(current, prior.replace(b'\r\n',b'\n'))

    def test_shared_price_page_does_not_reverify_other_moonshot_models(self):
        original = json.loads(subprocess.check_output(['git','show',BASE+':data/pricing-v2-preview/generated/model-pricing.v2.json'],cwd=ROOT))
        current = {r['canonicalInternalId']: r for r in read('data/pricing-v2-preview/generated/model-pricing.v2.json')['models']}
        for old in original['models']:
            key = old['canonicalInternalId']
            if key.startswith('moonshot-ai/') and key != KEY:
                for field in ('verifiedAt','checkedAt','pricingComponents','priceRecords','accessStatus','bindingStatus'):
                    self.assertEqual(current[key].get(field), old.get(field), (key,field))
