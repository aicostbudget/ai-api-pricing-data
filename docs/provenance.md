# Provenance: where a price comes from and how to check it

Each release is built from three kinds of commits. Knowing which one a field names tells you what you can check with it.

| Step | Commit or file | What it holds |
| --- | --- | --- |
| 1. Evidence | `reports/price-evidence/<provider_id>/<model_id>/<captured_at>.json` | What the official pages said when we looked: URL, HTTP status, SHA-256 of the page text, the passages the price was read from, and the change since the previous capture. |
| 2. Source commit | `data: prepare pricing source <snapshot id>` | Only `data/canonical/models.json` and that release's snapshot. These are the authoritative facts. |
| 3. Artifact commit | `data: publish pricing artifacts <snapshot id>` | Everything generated from step 2: `api/`, `huggingface/`, the Pricing V2 projection, price-change events. |

A file cannot contain the hash of the commit that holds it. That is why the metadata names the source commit (step 2) and the generated files are committed one step later (step 3).

## Fields in `api/v1/meta.json`

The repository copy, the GitHub Pages copy (`https://aicostbudget.github.io/ai-api-pricing-data/api/v1/meta.json`) and the Website's `pricing-meta.v1.json` carry the same values.

- `source_commit_sha`: the source commit (step 2). The canonical data at this commit is the data the release was built from.
- `generated_at`: the time of that source commit, in UTC. It is fixed by the commit and does not change when the files are rebuilt.
- `last_verified_at`: the most recent evidence capture time among the records.

Do not read generated files at the source commit. At that commit `api/`, `huggingface/` and the events file still hold the previous release. To cite a generated file, use the artifact commit:

```bash
git rev-list --reverse --ancestry-path --first-parent <source_commit_sha>..origin/main | head -n 1
```

## Check a release yourself

1. Read `source_commit_sha` and `generated_at` from the live `meta.json`.
2. Clone the repository and check out the artifact commit (the command above).
3. Confirm the artifact commit did not change the authoritative facts:
   `git diff <source_commit_sha> HEAD -- data/canonical/models.json` prints nothing.
4. Rebuild the public files from the committed identity and confirm they are unchanged:

   ```bash
   SOURCE_COMMIT_SHA=<source_commit_sha> python scripts/build.py --generated-at <generated_at>
   git status --porcelain -- api data
   ```

   No output means the committed `api/` and `data/` files are exactly what the build produces from this source commit.

The Pages workflow runs the same two checks before every deployment (`scripts/public_release_identity.py resolve` and `check-rebuild`) and refuses to publish when the rebuild differs from the committed files. The deployed `meta.json` is therefore the committed one.

## From a price to the page it came from

Every record has `official_source_url` and `last_verified_at`. The evidence capture for a record is the file named after `last_verified_at` without dashes and colons: `2026-11-05T15:05:31Z` is `reports/price-evidence/alibaba-qwen/qwen-flash/20261105T150531Z.json`. For the 2026-11-23 release this name matches an existing capture for 195 of 204 records; the other nine have an adjacent capture or none. This link is by file name, not by hash. The capture itself stores a SHA-256 of each page's text, not the page.

## Known differences

- The Hugging Face `meta.json` has no commit field, and its `generated_at` is the artifact commit's time. Hugging Face commits are labelled with the GitHub artifact commit that published them.
- The 2026-10 research index on aicostbudget.com cites a source commit together with generated file paths such as `huggingface/prices.json`. Read at that commit, `huggingface/prices.json` holds the previous release. Use the artifact commit from the command above.

## Citing

Cite the source commit for the facts and the artifact commit for the generated file paths, together with the access date.
