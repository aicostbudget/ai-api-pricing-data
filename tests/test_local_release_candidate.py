import json, subprocess, unittest
from pathlib import Path
from scripts import build_release_bundle as bundle
ROOT=Path(__file__).resolve().parents[1]
from tests.website_source import resolve_release_website_source
WEBSITE=resolve_release_website_source(ROOT)
class LocalCandidateTests(unittest.TestCase):
 def test_local_candidate_integrity_and_repeated_bytes(self):
  first=bundle.build_contents('WORKTREE',WEBSITE,'WORKTREE','2026-10-09')
  second=bundle.build_contents('WORKTREE',WEBSITE,'WORKTREE','2026-10-09')
  self.assertEqual(first,second)
  manifest=bundle.verify_contents(first)
  self.assertEqual(manifest['source_scope'],'LOCAL_CANDIDATE')
  self.assertIsNone(manifest['git_commit']);self.assertIsNone(manifest['website_source']['git_commit'])
  self.assertEqual(manifest['base_commits']['dataset'],subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT).decode().strip())
  self.assertEqual(manifest['projections']['github_pages_v1']['records'],len(json.loads((ROOT/'data/canonical/models.json').read_text(encoding='utf-8'))))
  self.assertEqual(manifest['projections']['pricing_v2']['records'],len(json.loads((ROOT/'huggingface/prices.json').read_text(encoding='utf-8'))['records']))
 def test_local_candidate_cannot_claim_release_or_mix_committed_input(self):
  with self.assertRaisesRegex(ValueError,'local candidate'):
   bundle.build_contents('WORKTREE',WEBSITE,'HEAD','2026-10-09')
  with self.assertRaisesRegex(ValueError,'local candidate'):
   bundle.build_contents('WORKTREE',WEBSITE,'WORKTREE','2026-10-09','vfake','2026-10-09')
 def test_local_candidate_tampered_source_commit_fails(self):
  files=bundle.build_contents('WORKTREE',WEBSITE,'WORKTREE','2026-10-09')
  manifest=json.loads(files['release-manifest.json']);manifest['git_commit']='f'*40
  files['release-manifest.json']=json.dumps(manifest).encode()
  with self.assertRaisesRegex(ValueError,'published source commits'):bundle.verify_contents(files)
 def test_snapshot_timestamp_matches_public_source(self):
  api=json.loads((ROOT/'api/v1/prices.json').read_text(encoding='utf-8'))
  snapshot=json.loads((ROOT/'data/snapshots/2026-10-09/prices.json').read_text(encoding='utf-8'))
  self.assertEqual(api,snapshot)
if __name__=='__main__':unittest.main()
