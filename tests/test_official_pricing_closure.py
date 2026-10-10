import copy, hashlib, json, subprocess, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(row):return hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
def pinned(path):return json.loads(subprocess.check_output(['git','show',SCOPE['baseline_ref']+':'+path],cwd=ROOT))
SCOPE=read('tests/fixtures/official-pricing-repair-scope.json')
def verify_rows(old,current,targets):
    old={key(row):row for row in old};current={key(row):row for row in current}
    assert set(current)==set(old)|set(targets), 'unapproved identity universe'
    for id,row in current.items():
        assert digest(row)==(targets[id] if id in targets else digest(old[id])), 'unapproved change: '+id
def key(row):return row.get('canonicalInternalId') or row.get('provider_id','')+'/'+row.get('model_id','')
class ClosureScopeTests(unittest.TestCase):
 def test_current_canonical_exact_scope_and_negative_mutation(self):
  old=pinned('data/canonical/models.json');current=read('data/canonical/models.json');verify_rows(old,current,SCOPE['canonical'])
  mutated=copy.deepcopy(current);next(r for r in mutated if r['model_id']=='gpt-6-sol')['pricing']['input']=999
  with self.assertRaisesRegex(AssertionError,'unapproved change'):verify_rows(old,mutated,SCOPE['canonical'])
  with self.assertRaisesRegex(AssertionError,'identity universe'):verify_rows(old,current+[{'provider_id':'fake','model_id':'unapproved'}],SCOPE['canonical'])
 def test_current_projection_exact_scope_and_negative_mutation(self):
  old=pinned('data/pricing-v2-preview/generated/model-pricing.v2.json')['models'];current=read('data/pricing-v2-preview/generated/model-pricing.v2.json')['models'];verify_rows(old,current,SCOPE['projection'])
  mutated=copy.deepcopy(current);next(r for r in mutated if r['id']=='gemini-2.5-flash-image')['retirementDate']='2027-03-15'
  with self.assertRaisesRegex(AssertionError,'unapproved change'):verify_rows(old,mutated,SCOPE['projection'])
 def test_all_current_events_exact_and_correction_is_not_provider_event(self):
  self.assertEqual(hashlib.sha256((ROOT/'data/price-change-events/events.jsonl').read_bytes()).hexdigest(),SCOPE['events_sha256'])
  events=[json.loads(l) for l in (ROOT/'data/price-change-events/events.jsonl').read_text().splitlines()]
  self.assertFalse(any(e['model_id']=='gemini-2.5-flash-image' and e['detected_at']=='2026-10-09' for e in events))
 def test_conflict_is_persistent_and_historical_assertion_retained(self):
  row=next(r for r in read('data/canonical/models.json') if r['model_id']=='gemini-2.5-flash-image')
  conflict=row['lifecycle_conflict'];self.assertEqual(conflict['previous_assertion']['retirement_date'],'2026-10-02')
  self.assertEqual({r['shutdown_date'] for r in conflict['sources']},{'2026-10-02','2027-03-15'})
  self.assertTrue(all(r['url'].startswith('https://ai.google.dev/') for r in conflict['sources']))
  historical=[json.loads(l) for l in (ROOT/'data/history/google-gemini/gemini-2.5-flash-image.jsonl').read_text().splitlines()]
  self.assertTrue(any(r.get('lifecycle',{}).get('retirement_date')=='2026-10-02' for r in historical))
  report=read('data/pricing-v2-preview/phase2-conflict-resolution-report.json');self.assertIn('google-gemini/gemini-2.5-flash-image',report['unresolvedIdentitiesAfter'])
if __name__=='__main__':unittest.main()
