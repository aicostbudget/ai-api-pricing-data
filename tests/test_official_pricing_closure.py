import copy, hashlib, json, subprocess, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(row):return hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
def pinned(path):return json.loads(subprocess.check_output(['git','show',SCOPE['baseline_ref']+':'+path],cwd=ROOT))
SCOPE=read('tests/fixtures/official-pricing-repair-scope.json')

EVENTS_PATH='data/price-change-events/events.jsonl'
def normalize_event_newlines(raw):
    """Only uniform LF or uniform CRLF is equivalent; preserve every other byte."""
    if b'\r' in raw:
        remainder=raw.replace(b'\r\n',b'')
        assert b'\r' not in remainder and b'\n' not in remainder, 'invalid or mixed event newlines'
        raw=raw.replace(b'\r\n',b'\n')
    assert raw and raw.endswith(b'\n'), 'invalid event final newline'
    assert all(raw[:-1].split(b'\n')), 'invalid blank event line'
    return raw
def verify_event_bytes(raw):
    normalized=normalize_event_newlines(raw)
    assert hashlib.sha256(normalized).hexdigest()==SCOPE['events_sha256'], 'unapproved event content'
    return normalized
def approved_event_bytes():
    return subprocess.check_output(['git','show',SCOPE['events_source_commit']+':'+EVENTS_PATH],cwd=ROOT)

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
  normalized=verify_event_bytes((ROOT/EVENTS_PATH).read_bytes())
  events=[json.loads(line) for line in normalized.decode('utf-8').split('\n')[:-1]]
  self.assertFalse(any(e['model_id']=='gemini-2.5-flash-image' and e['detected_at']=='2026-10-09' for e in events))
 def test_event_digest_pinned_to_approved_commit(self):
  self.assertRegex(SCOPE['events_source_commit'],r'^[0-9a-f]{40}$')
  self.assertEqual(SCOPE['events_newline_policy'],'uniform-lf-or-crlf-to-lf')
  raw=approved_event_bytes()
  self.assertNotIn(b'\r',raw)
  self.assertEqual(hashlib.sha256(raw).hexdigest(),SCOPE['events_sha256'])
  self.assertEqual(len(raw.splitlines()),35)
 def test_event_lf_and_crlf_have_same_approved_digest(self):
  lf=approved_event_bytes()
  self.assertEqual(verify_event_bytes(lf),lf)
  self.assertEqual(verify_event_bytes(lf.replace(b'\n',b'\r\n')),lf)
 def test_event_field_mutations_rejected(self):
  lf=approved_event_bytes()
  rows=[json.loads(line) for line in lf.splitlines()]
  def encode(items):
   return (''.join(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n' for row in items)).encode('utf-8')
  # Ensure rejection is caused by the mutation, not by test serialization.
  self.assertEqual(encode(rows),lf)
  def fields(value,path=()):
   if isinstance(value,dict):
    for name,child in value.items():
     yield path+(name,)
     yield from fields(child,path+(name,))
   elif isinstance(value,list):
    for index,child in enumerate(value):
     yield path+(index,)
     yield from fields(child,path+(index,))
  for index,row in enumerate(rows):
   for path in fields(row):
    changed=copy.deepcopy(rows);parent=changed[index]
    for part in path[:-1]:parent=parent[part]
    parent[path[-1]]='P09_UNAPPROVED_MUTATION'
    for newline in (b'\n',b'\r\n'):
     with self.subTest(event=index,field=path,newline=newline):
      with self.assertRaisesRegex(AssertionError,'unapproved event content'):
       verify_event_bytes(encode(changed).replace(b'\n',newline))
 def test_event_add_delete_duplicate_and_reorder_rejected(self):
  lines=approved_event_bytes().splitlines(keepends=True)
  added=json.loads(lines[0]);added['event_id']='p09-unapproved-event'
  extra=json.dumps(added,sort_keys=True,separators=(',',':')).encode()+b'\n'
  cases={'delete':b''.join(lines[1:]),'add':b''.join(lines)+extra,
         'duplicate':b''.join(lines)+lines[0],'reorder':b''.join(list(reversed(lines)))}
  for name,raw in cases.items():
   for newline in (b'\n',b'\r\n'):
    with self.subTest(case=name,newline=newline):
     with self.assertRaisesRegex(AssertionError,'unapproved event content'):
      verify_event_bytes(raw.replace(b'\n',newline))
 def test_event_invalid_or_mixed_newlines_rejected(self):
  lf=approved_event_bytes();crlf=lf.replace(b'\n',b'\r\n')
  cases={'mixed-lf':lf.replace(b'\n',b'\r\n',1),
         'mixed-crlf':crlf.replace(b'\r\n',b'\n',1),
         'bare-cr':lf.replace(b'\n',b'\r'),
         'crcrlf':lf.replace(b'\n',b'\r\r\n'),
         'missing-final':lf[:-1],'blank-line':lf+b'\n',
         'unicode-separator':lf.replace(b'\n',b'\xe2\x80\xa8',1)}
  for name,raw in cases.items():
   with self.subTest(case=name):
    with self.assertRaises(AssertionError):verify_event_bytes(raw)
 def test_conflict_is_persistent_and_historical_assertion_retained(self):
  row=next(r for r in read('data/canonical/models.json') if r['model_id']=='gemini-2.5-flash-image')
  conflict=row['lifecycle_conflict'];self.assertEqual(conflict['previous_assertion']['retirement_date'],'2026-10-02')
  self.assertEqual({r['shutdown_date'] for r in conflict['sources']},{'2026-10-02','2027-03-15'})
  self.assertTrue(all(r['url'].startswith('https://ai.google.dev/') for r in conflict['sources']))
  historical=[json.loads(l) for l in (ROOT/'data/history/google-gemini/gemini-2.5-flash-image.jsonl').read_text().splitlines()]
  self.assertTrue(any(r.get('lifecycle',{}).get('retirement_date')=='2026-10-02' for r in historical))
  report=read('data/pricing-v2-preview/phase2-conflict-resolution-report.json');self.assertIn('google-gemini/gemini-2.5-flash-image',report['unresolvedIdentitiesAfter'])
if __name__=='__main__':unittest.main()
