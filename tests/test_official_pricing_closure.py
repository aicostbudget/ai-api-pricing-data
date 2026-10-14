import copy, hashlib, json, re, subprocess, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(row):return hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def read(path):return json.loads((ROOT/path).read_text(encoding='utf-8'))
SCOPE=read('tests/fixtures/official-pricing-repair-scope.json')
CHECKPOINT=SCOPE['event_checkpoints'][-1]
ARGON_EXTENSION=SCOPE['argon_event_extension']
EVENTS_PATH='data/price-change-events/events.jsonl'

def git_output(*args):
 try:return subprocess.check_output(['git',*args],cwd=ROOT,stderr=subprocess.PIPE)
 except subprocess.CalledProcessError as exc:raise AssertionError('unresolvable git object: '+' '.join(args)) from exc
def pinned(path):return json.loads(git_output('show',SCOPE['baseline_ref']+':'+path))
def normalize_event_newlines(raw):
 """Only uniform LF or uniform CRLF is equivalent; preserve every other byte."""
 if b'\r' in raw:
  remainder=raw.replace(b'\r\n',b'')
  assert b'\r' not in remainder and b'\n' not in remainder,'invalid or mixed event newlines'
  raw=raw.replace(b'\r\n',b'\n')
 assert raw and raw.endswith(b'\n'),'invalid event final newline'
 assert all(raw[:-1].split(b'\n')),'invalid blank event line'
 return raw
def event_lines_rows(raw):
 normalized=normalize_event_newlines(raw);lines=normalized.splitlines(keepends=True)
 try:rows=[json.loads(line) for line in lines]
 except (json.JSONDecodeError,UnicodeDecodeError) as exc:raise AssertionError('invalid event JSONL') from exc
 return normalized,lines,rows
def encode(rows):return (''.join(json.dumps(row,sort_keys=True,separators=(',',':'),ensure_ascii=False)+'\n' for row in rows)).encode('utf-8')
def approved_event_bytes():return git_output('show',SCOPE['events_source_commit']+':'+EVENTS_PATH)
def checkpoint_event_bytes(checkpoint=CHECKPOINT):return git_output('show',checkpoint['source_commit']+':'+EVENTS_PATH)
def verify_event_bytes(raw):
 normalized=normalize_event_newlines(raw)
 assert hashlib.sha256(normalized).hexdigest()==SCOPE['events_sha256'],'unapproved historical event content'
 return normalized
def verify_current_event_bytes(raw,checkpoint=CHECKPOINT):
 normalized,lines,rows=event_lines_rows(raw)
 assert hashlib.sha256(normalized).hexdigest()==checkpoint['full_events_sha256'],'unapproved current event content'
 assert len(rows)==checkpoint['full_event_count'],'unexpected current event count'
 ids=[row['event_id'] for row in rows];keys=[row['dedupe_key'] for row in rows]
 assert len(set(ids))==len(ids),'duplicate event_id'
 assert len(set(keys))==len(keys),'duplicate dedupe_key'
 return normalized,lines,rows
def verify_release_event_bytes(raw):
 normalized,lines,rows=event_lines_rows(raw)
 assert ARGON_EXTENSION['canonical_source_commit']=='19ee35964833714b7891453ad1cb55adcf86a56c','unexpected Argon canonical source'
 assert ARGON_EXTENSION['base_checkpoint_source_commit']==CHECKPOINT['source_commit'],'unexpected Argon base checkpoint'
 assert hashlib.sha256(normalized).hexdigest()==ARGON_EXTENSION['full_events_sha256'],'unapproved release event content'
 assert len(rows)==ARGON_EXTENSION['full_event_count'],'unexpected release event count'
 ids=[row['event_id'] for row in rows];keys=[row['dedupe_key'] for row in rows]
 assert len(set(ids))==len(ids),'duplicate event_id'
 assert len(set(keys))==len(keys),'duplicate dedupe_key'
 appended_ids=ARGON_EXTENSION['appended_event_ids'];appended_keys=ARGON_EXTENSION['appended_dedupe_keys'];id_set=set(appended_ids)
 assert len(appended_ids)==len(id_set)==ARGON_EXTENSION['appended_event_count']==1
 assert len(appended_keys)==len(set(appended_keys))==ARGON_EXTENSION['appended_event_count']
 appended=[(line,row) for line,row in zip(lines,rows) if row['event_id'] in id_set]
 rebuilt=b''.join(line for line,row in zip(lines,rows) if row['event_id'] not in id_set)
 historical=checkpoint_event_bytes(CHECKPOINT);verify_current_event_bytes(historical,CHECKPOINT)
 assert rebuilt==historical,'historical checkpoint bytes or order changed'
 assert [row['event_id'] for _,row in appended]==appended_ids,'unexpected Argon event ID'
 assert [row['dedupe_key'] for _,row in appended]==appended_keys,'unexpected Argon dedupe key'
 assert len(rows)==ARGON_EXTENSION['base_event_count']+ARGON_EXTENSION['appended_event_count']
 assert hashlib.sha256(b''.join(line for line,_ in appended)).hexdigest()==ARGON_EXTENSION['appended_events_sha256']
 row=appended[0][1]
 assert row['provider_id']=='google-gemini' and row['model_id']=='gemini-4-argon'
 assert row['change_type']=='model_added' and row['old_status'] is None and row['new_status']=='active'
 assert row['old_prices']=={'cached_input':None,'input':None,'output':None}
 assert row['new_prices']=={'cached_input':0.1,'input':2,'output':10}
 assert row['source_snapshot_before']=='data/snapshots/2026-10-13/prices.json'
 assert row['source_snapshot_after']=='data/snapshots/2026-10-14/prices.json'
 assert row['official_source_url']=='https://ai.google.dev/gemini-api/docs/pricing'
 return normalized,lines,rows
def verify_checkpoint(checkpoint=CHECKPOINT,current_raw=None):
 assert re.fullmatch(r'[0-9a-f]{40}',checkpoint['source_commit']),'invalid checkpoint source commit'
 assert re.fullmatch(r'[0-9a-f]{40}',checkpoint['parent_commit']),'invalid checkpoint parent commit'
 parent=git_output('rev-parse',checkpoint['source_commit']+'^').decode().strip()
 assert parent==checkpoint['parent_commit'],'incorrect checkpoint parent'
 files=git_output('diff-tree','--no-commit-id','--name-only','-r',checkpoint['source_commit']).decode().splitlines()
 assert files==[EVENTS_PATH],'checkpoint contains unapproved files'
 blob=checkpoint_event_bytes(checkpoint);assert b'\r' not in blob,'checkpoint Git blob must use LF'
 normalized,lines,rows=verify_current_event_bytes(blob,checkpoint);assert normalized==blob
 historical=verify_event_bytes(approved_event_bytes());assert len(historical.splitlines())==checkpoint['base_event_count']
 ids=checkpoint['appended_event_ids'];keys=checkpoint['appended_dedupe_keys'];id_set=set(ids)
 assert len(ids)==len(id_set)==checkpoint['appended_event_count']
 assert len(keys)==len(set(keys))==checkpoint['appended_event_count']
 appended=[(line,row) for line,row in zip(lines,rows) if row['event_id'] in id_set]
 rebuilt=b''.join(line for line,row in zip(lines,rows) if row['event_id'] not in id_set)
 assert rebuilt==historical,'historical event bytes or order changed'
 assert [row['event_id'] for _,row in appended]==ids,'unexpected appended event IDs'
 assert [row['dedupe_key'] for _,row in appended]==keys,'unexpected appended dedupe keys'
 assert len(appended)==checkpoint['appended_event_count']
 assert len(rows)==checkpoint['base_event_count']+checkpoint['appended_event_count']
 assert hashlib.sha256(b''.join(line for line,_ in appended)).hexdigest()==checkpoint['appended_events_sha256']
 expected={'gemini-3.5-flash':('gemini-3.6-flash',ids[0],keys[0]),'gemini-3.7-flash':('gemini-3.8-flash',ids[1],keys[1])}
 assert {row['model_id'] for _,row in appended}==set(expected)
 for _,row in appended:
  successor,event_id,dedupe_key=expected[row['model_id']]
  assert row['event_id']==event_id and row['dedupe_key']==dedupe_key
  assert row['provider_id']=='google-gemini' and row['change_type']=='lifecycle_update'
  assert row['old_status']=='active' and row['new_status']=='deprecated' and row['old_lifecycle'] is None
  assert row['new_lifecycle']=={'deprecation_date':'2026-10-08','replacement_model_id':successor}
  assert 'retirement_date' not in row['new_lifecycle'] and 'shutdown_date' not in row['new_lifecycle']
  assert row['old_prices']==row['new_prices']
  assert row['official_source_url']=='https://ai.google.dev/gemini-api/docs/deprecations'
  assert row['announcement_url']=='https://ai.google.dev/gemini-api/docs/changelog'
  assert row['source_snapshot_before']=='data/snapshots/2026-10-09/prices.json'
  assert row['source_snapshot_after']=='data/snapshots/2026-10-13/prices.json'
 if current_raw is not None:
  current,_,_=verify_current_event_bytes(current_raw,checkpoint)
  assert current==blob,'current events differ from approved checkpoint'
 return blob,rows

def verify_rows(old,current,targets):
 old={key(row):row for row in old};current={key(row):row for row in current}
 assert set(current)==set(old)|set(targets),'unapproved identity universe'
 for id,row in current.items():assert digest(row)==(targets[id] if id in targets else digest(old[id])),'unapproved change: '+id
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
  verify_checkpoint(CHECKPOINT)
  _,_,events=verify_release_event_bytes((ROOT/EVENTS_PATH).read_bytes())
  self.assertFalse(any(e['model_id']=='gemini-2.5-flash-image' and e['detected_at']=='2026-10-09' for e in events))
 def test_event_digest_pinned_to_approved_commit(self):
  self.assertEqual(SCOPE['events_source_commit'],'1c7ec3eca94f0bfdc99b7ae18616bdce38be8833')
  self.assertEqual(SCOPE['events_sha256'],'a04e3fbb1d4cb049f2d9cfcadfca3b6383fc1bcdc3df6ca0ee6cfddc38e706ed')
  self.assertEqual(SCOPE['events_newline_policy'],'uniform-lf-or-crlf-to-lf')
  raw=approved_event_bytes();self.assertNotIn(b'\r',raw);self.assertEqual(verify_event_bytes(raw),raw);self.assertEqual(len(raw.splitlines()),35)
 def test_e1_checkpoint_identity_scope_and_increment(self):
  self.assertEqual(len(SCOPE['event_checkpoints']),1);blob,rows=verify_checkpoint();self.assertEqual(len(blob.splitlines()),37);self.assertEqual(len(rows),37)
 def test_argon_release_extension_is_the_only_38th_event(self):
  current=(ROOT/EVENTS_PATH).read_bytes();normalized,_,rows=verify_release_event_bytes(current)
  self.assertEqual(normalized,normalize_event_newlines(current));self.assertEqual(len(rows),38)
 def test_event_lf_and_crlf_have_same_approved_digest(self):
  historical=approved_event_bytes();self.assertEqual(verify_event_bytes(historical),historical);self.assertEqual(verify_event_bytes(historical.replace(b'\n',b'\r\n')),historical)
  current=checkpoint_event_bytes();self.assertEqual(verify_current_event_bytes(current)[0],current);self.assertEqual(verify_current_event_bytes(current.replace(b'\n',b'\r\n'))[0],current)
  release=normalize_event_newlines((ROOT/EVENTS_PATH).read_bytes());self.assertEqual(verify_release_event_bytes(release)[0],release);self.assertEqual(verify_release_event_bytes(release.replace(b'\n',b'\r\n'))[0],release)
 def test_event_field_mutations_rejected(self):
  historical=approved_event_bytes();rows=[json.loads(line) for line in historical.splitlines()];self.assertEqual(encode(rows),historical)
  def fields(value,path=()):
   if isinstance(value,dict):
    for name,child in value.items():yield path+(name,);yield from fields(child,path+(name,))
   elif isinstance(value,list):
    for index,child in enumerate(value):yield path+(index,);yield from fields(child,path+(index,))
  for index,row in enumerate(rows):
   for path in fields(row):
    changed=copy.deepcopy(rows);parent=changed[index]
    for part in path[:-1]:parent=parent[part]
    parent[path[-1]]='P09_UNAPPROVED_MUTATION'
    for newline in (b'\n',b'\r\n'):
     with self.subTest(event=index,field=path,newline=newline):
      with self.assertRaisesRegex(AssertionError,'unapproved historical event content'):verify_event_bytes(encode(changed).replace(b'\n',newline))
 def test_event_add_delete_duplicate_and_reorder_rejected(self):
  lines=approved_event_bytes().splitlines(keepends=True);added=json.loads(lines[0]);added['event_id']='p09-unapproved-event';extra=json.dumps(added,sort_keys=True,separators=(',',':')).encode()+b'\n'
  cases={'delete':b''.join(lines[1:]),'add':b''.join(lines)+extra,'duplicate':b''.join(lines)+lines[0],'reorder':b''.join(list(reversed(lines)))}
  for name,raw in cases.items():
   for newline in (b'\n',b'\r\n'):
    with self.subTest(case=name,newline=newline):
     with self.assertRaisesRegex(AssertionError,'unapproved historical event content'):verify_event_bytes(raw.replace(b'\n',newline))
 def test_current_event_negative_mutations_rejected(self):
  current=(ROOT/EVENTS_PATH).read_bytes();_,lines,rows=event_lines_rows(current);new_ids=set(ARGON_EXTENSION['appended_event_ids'])
  old_indexes=[i for i,row in enumerate(rows) if row['event_id'] not in new_ids];new_index=next(i for i,row in enumerate(rows) if row['event_id'] in new_ids)
  unexpected=copy.deepcopy(rows);extra=copy.deepcopy(unexpected[new_index]);extra['event_id']='google-gemini:unexpected:lifecycle_update:000000000000';extra['dedupe_key']='sha256:'+'0'*64;unexpected.append(extra)
  reordered=list(lines);first,second=old_indexes[:2];reordered[first],reordered[second]=reordered[second],reordered[first]
  old_mutation=copy.deepcopy(rows);old_mutation[old_indexes[0]]['notes']='P09_HISTORICAL_MUTATION'
  new_mutation=copy.deepcopy(rows);new_mutation[new_index]['notes']='P1_APPEND_MUTATION'
  id_mutation=copy.deepcopy(rows);id_mutation[new_index]['event_id']='P1_MUTATED_EVENT_ID'
  key_mutation=copy.deepcopy(rows);key_mutation[new_index]['dedupe_key']='sha256:'+'f'*64
  cases={'delete':b''.join(lines[1:]),'unexpected':encode(unexpected),'duplicate':current+lines[0],'historical-reorder':b''.join(reordered),'historical-field':encode(old_mutation),'appended-field':encode(new_mutation),'event-id':encode(id_mutation),'dedupe-key':encode(key_mutation)}
  for name,raw in cases.items():
   with self.subTest(case=name):
    with self.assertRaises(AssertionError):verify_release_event_bytes(raw)
 def test_checkpoint_metadata_corruption_rejected(self):
  bad=copy.deepcopy(CHECKPOINT);bad['source_commit']='0'*40
  with self.assertRaisesRegex(AssertionError,'unresolvable git object'):verify_checkpoint(bad)
  bad=copy.deepcopy(CHECKPOINT);bad['parent_commit']='0'*40
  with self.assertRaisesRegex(AssertionError,'incorrect checkpoint parent'):verify_checkpoint(bad)
  bad=copy.deepcopy(CHECKPOINT);bad['full_events_sha256']='0'*64
  with self.assertRaisesRegex(AssertionError,'unapproved current event content'):verify_checkpoint(bad)
 def test_event_invalid_or_mixed_newlines_rejected(self):
  for contract,lf,verify in (('historical',approved_event_bytes(),verify_event_bytes),('checkpoint',checkpoint_event_bytes(),verify_current_event_bytes),('release',(ROOT/EVENTS_PATH).read_bytes(),verify_release_event_bytes)):
   crlf=lf.replace(b'\n',b'\r\n');cases={'mixed-lf':lf.replace(b'\n',b'\r\n',1),'mixed-crlf':crlf.replace(b'\r\n',b'\n',1),'bare-cr':lf.replace(b'\n',b'\r'),'crcrlf':lf.replace(b'\n',b'\r\r\n'),'missing-final':lf[:-1],'blank-line':lf+b'\n','unicode-separator':lf.replace(b'\n',b'\xe2\x80\xa8',1)}
   for name,raw in cases.items():
    with self.subTest(contract=contract,case=name):
     with self.assertRaises(AssertionError):verify(raw)
 def test_conflict_is_persistent_and_historical_assertion_retained(self):
  row=next(r for r in read('data/canonical/models.json') if r['model_id']=='gemini-2.5-flash-image')
  conflict=row['lifecycle_conflict'];self.assertEqual(conflict['previous_assertion']['retirement_date'],'2026-10-02')
  self.assertEqual({r['shutdown_date'] for r in conflict['sources']},{'2026-10-02','2027-03-15'})
  self.assertTrue(all(r['url'].startswith('https://ai.google.dev/') for r in conflict['sources']))
  historical=[json.loads(l) for l in (ROOT/'data/history/google-gemini/gemini-2.5-flash-image.jsonl').read_text().splitlines()]
  self.assertTrue(any(r.get('lifecycle',{}).get('retirement_date')=='2026-10-02' for r in historical))
  report=read('data/pricing-v2-preview/phase2-conflict-resolution-report.json');self.assertIn('google-gemini/gemini-2.5-flash-image',report['unresolvedIdentitiesAfter'])
if __name__=='__main__':unittest.main()
