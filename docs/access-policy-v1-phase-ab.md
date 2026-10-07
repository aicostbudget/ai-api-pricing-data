# Access Policy V1 — Phase A + B

## Baseline

Dataset main/HEAD/origin-main: c77c90819d2cb570668f79899e881316705fe9a5. Website main/HEAD/origin-main: 64adba20735ee089044da8bdfaa274cbe505375a. Both task-start trees were clean. Before/after: 85 canonical / 97 identities / 94 V2 models / 248 prices / 83 HF records.

## Access and binding contract

Access enum: public / existing_users_only / invite_only / restricted / unknown. Non-unknown requires an official provider hostname, exact official model/version ID, an access-specific claim scope and successful UTC access_checked_at. Unknown cannot assert fabricated evidence or a successful checked date. Future timestamps, pricing-only evidence and provider-hostname substring tricks fail validation. Access is independent of lifecycle, stage, pricing confidence and public exposure.

Existing identityType/canonicalOfficialId/officialIds describe identity shape/spelling, not an independent reviewed approval decision. The three flagged identities were canonical_model without a machine-readable review gate. Minimal binding_status (approved/unresolved) and binding_evidence were therefore added. An unresolved binding does not erase independently verified public access.

Canonical records win even if access is absent/unknown; a conflicting Website seed fails. Only canonical-absent Website-only seeds supply access, with a pinned Website baseRevision and SHA-256 fact digest. BaseRevision is a pre-edit provenance anchor, not a claim that uncommitted seeds already exist in that commit. The digest pins actual fact content. Aliases may inherit only with approved binding, exact target and explicit identical-entitlement scope proof; billing targets confer no access. Remaining identities stay unknown/unresolved.

## Generation and public compatibility

Use generate_pricing_v2_preview.py --access-metadata-only with the Website seed file. This preserves existing price/lifecycle/release/eligibility facts rather than reevaluating them. Full generation also understands the new contract. The full regeneration initially exposed an existing Opus 4.1 verification drift; only 17 task-generated outputs proven clean at task start by SHA-256 were reverted before metadata-only generation. Final price objects equal HEAD exactly.

Existing sources retain identity, URL, title and price checked/verified timestamps; only supports gains access/binding. Fifteen new access/binding sources explain registry count 154 -> 169. None enters price sourceRefs. Website projection keeps the prior effectiveAt 2026-10-05T02:47:26Z and existing selections; generatedAt is 2026-10-07T04:26:40Z. V1/API generation ran in a temporary root; only existing current artifacts were copied. Historical snapshots/history remain unchanged. API meta modelAccess exposes all identities including Website-only seeds.

HF JSON adds access_status, access_checked_at, access_evidence, binding_status, binding_evidence. CSV appends access_status, access_checked_at, access_evidence_json, binding_status, binding_evidence_json after every existing column. Named-column consumers remain compatible; fixed-width consumers must accept these additions. Older pinned JSON/CSV exports without access facts retain original features and columns and remain byte-reproducible. Metadata does not filter factual HF/API records.

## Official backfill

Mythos 5/5.1 restricted classification was explicitly authorized by the user after current organization-verification/tier/grant evidence superseded invitation-only wording. Gemini 2.5 scope is users who previously actively used the exact model, not all old projects. DeepSeek first-call refresh timed out; a successful current official exact-model/base-URL/balance/concurrency table supports the claim. Failed refreshes do not advance successful checked timestamps.

| Provider | Local ID | Official ID | Lifecycle | Stage | Access | Evidence URL | CheckedAt | Binding | Confidence |
|---|---|---|---|---|---|---|---|---|---|
| anthropic | claude-fable-5 | claude-fable-5 | active | stable | public | https://platform.claude.com/docs/en/models/fable-5/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| anthropic | claude-fable-5-1 | claude-fable-5-1 | active | stable | public | https://platform.claude.com/docs/en/models/fable-5-1/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| anthropic | claude-haiku-4.5 | claude-haiku-4-5 | active | stable | public | https://platform.claude.com/docs/en/models/haiku-4-5/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| anthropic | claude-mythos-5 | claude-mythos-5 | active | stable | restricted | https://platform.claude.com/docs/en/models/mythos-5/overview<br>https://support.claude.com/en/articles/14604842-cyber-verification-program | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| anthropic | claude-mythos-5-1 | claude-mythos-5-1 | active | stable | restricted | https://platform.claude.com/docs/en/models/mythos-5-1/overview<br>https://support.claude.com/en/articles/14604842-cyber-verification-program | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| anthropic | claude-opus-4.8 | claude-opus-4-8 | active | stable | public | https://platform.claude.com/docs/en/models/opus-4-8/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| anthropic | claude-opus-5 | claude-opus-5 | active | stable | public | https://platform.claude.com/docs/en/models/opus-5/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| anthropic | claude-opus-5-5 | claude-opus-5-5 | active | stable | public | https://platform.claude.com/docs/en/models/opus-5-5/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| anthropic | claude-sonnet-4.6 | claude-sonnet-4-6 | active | stable | public | https://platform.claude.com/docs/en/models/sonnet-4-6/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| anthropic | claude-sonnet-5 | claude-sonnet-5 | active | stable | public | https://platform.claude.com/docs/en/models/sonnet-5/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| anthropic | claude-sonnet-5-5 | claude-sonnet-5-5 | active | stable | public | https://platform.claude.com/docs/en/models/sonnet-5-5/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| cohere | aya-expanse-32b | c4ai-aya-expanse-32b | active | stable | public | https://docs.cohere.com/docs/aya-expanse<br>https://docs.cohere.com/docs/going-live | 2026-10-07T04:26:40Z | unresolved | official access verified; binding unresolved |
| cohere | command-r-plus-08-2024 | command-r-plus-08-2024 | active | stable | public | https://docs.cohere.com/docs/command-r-plus<br>https://docs.cohere.com/docs/going-live | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| deepseek | deepseek-flash | deepseek-flash | active | stable | public | https://api-docs.deepseek.com/quick_start/pricing | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| deepseek | deepseek-v4-pro | deepseek-v4-pro | active | stable | public | https://api-docs.deepseek.com/quick_start/pricing | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-2.5-flash | gemini-2.5-flash | active | legacy | existing_users_only | https://ai.google.dev/gemini-api/docs/deprecations | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-2.5-pro | gemini-2.5-pro | active | legacy | existing_users_only | https://ai.google.dev/gemini-api/docs/deprecations | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-3-flash-preview | gemini-3-flash-preview | active | preview | public | https://ai.google.dev/gemini-api/docs/models | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-3.1-flash-lite | gemini-3.1-flash-lite | active | stable | public | https://ai.google.dev/gemini-api/docs/models | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-3.1-pro-preview | gemini-3.1-pro-preview | active | preview | public | https://ai.google.dev/gemini-api/docs/models | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-3.5-flash | gemini-3.5-flash | active | stable | public | https://ai.google.dev/gemini-api/docs/models | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-3.5-flash-lite | gemini-3.5-flash-lite | active | stable | public | https://ai.google.dev/gemini-api/docs/models | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-3.6-flash | gemini-3.6-flash | active | stable | public | https://ai.google.dev/gemini-api/docs/models | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-3.7-flash | gemini-3.7-flash | active | stable | public | https://ai.google.dev/gemini-api/docs/models | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-3.8-flash | gemini-3.8-flash | active | stable | public | https://ai.google.dev/gemini-api/docs/models | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-3.8-live | gemini-3.8-live | active | stable | public | https://ai.google.dev/gemini-api/docs/models | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| google-gemini | gemini-3.8-live-extended-thinking | gemini-3.8-live-extended-thinking | active | stable | public | https://ai.google.dev/gemini-api/docs/models | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| mistral-ai | codestral-2508 | codestral-2508 | active | stable | public | https://docs.mistral.ai/models/codestral-25-08<br>https://docs.mistral.ai/getting-started/quickstarts/developer/first-api-request | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| mistral-ai | ministral-14b-2512 | ministral-14b-2512 | active | stable | public | https://docs.mistral.ai/models/ministral-3-14b-25-12<br>https://docs.mistral.ai/getting-started/quickstarts/developer/first-api-request | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| mistral-ai | ministral-3b-2512 | ministral-3b-2512 | active | stable | public | https://docs.mistral.ai/models/ministral-3-3b-25-12<br>https://docs.mistral.ai/getting-started/quickstarts/developer/first-api-request | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| mistral-ai | ministral-8b-2512 | ministral-8b-2512 | active | stable | public | https://docs.mistral.ai/models/ministral-3-8b-25-12<br>https://docs.mistral.ai/getting-started/quickstarts/developer/first-api-request | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| mistral-ai | mistral-large | mistral-large-2512 | active | stable | public | https://docs.mistral.ai/models/mistral-large-3-25-12<br>https://docs.mistral.ai/getting-started/quickstarts/developer/first-api-request | 2026-10-07T04:26:40Z | unresolved | official access verified; binding unresolved |
| mistral-ai | mistral-medium-3-5 | mistral-medium-3-5 | active | stable | public | https://docs.mistral.ai/models/mistral-medium-3-5-26-04<br>https://docs.mistral.ai/getting-started/quickstarts/developer/first-api-request | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| mistral-ai | mistral-small-2603 | mistral-small-2603 | active | stable | public | https://docs.mistral.ai/models/mistral-small-4-0-26-03<br>https://docs.mistral.ai/getting-started/quickstarts/developer/first-api-request | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| moonshot-ai | kimi-k2.6 | kimi-k2.6 | active | stable | public | https://platform.kimi.ai/docs/models<br>https://platform.kimi.ai/docs/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| moonshot-ai | kimi-k2.7-code | kimi-k2.7-code | active | stable | public | https://platform.kimi.ai/docs/models<br>https://platform.kimi.ai/docs/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| moonshot-ai | kimi-k3 | kimi-k3 | active | stable | public | https://platform.kimi.ai/docs/models<br>https://platform.kimi.ai/docs/overview | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | chatgpt-chat-latest | chat-latest | active | specialized | public | https://developers.openai.com/api/docs/models/chat-latest | 2026-10-07T04:26:40Z | unresolved | official access verified; binding unresolved |
| openai | gpt-5.3-codex | gpt-5.3-codex | deprecated | specialized | public | https://developers.openai.com/api/docs/models/gpt-5.3-codex | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-5.4 | gpt-5.4 | active | stable | public | https://developers.openai.com/api/docs/models/gpt-5.4 | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-5.4-mini | gpt-5.4-mini | active | stable | public | https://developers.openai.com/api/docs/models/gpt-5.4-mini | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-5.4-pro | gpt-5.4-pro | active | stable | public | https://developers.openai.com/api/docs/models/gpt-5.4-pro | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-5.5 | gpt-5.5 | active | stable | public | https://developers.openai.com/api/docs/models/gpt-5.5 | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-5.5-pro | gpt-5.5-pro | active | stable | public | https://developers.openai.com/api/docs/models/gpt-5.5-pro | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-5.6-luna | gpt-5.6-luna | active | stable | public | https://developers.openai.com/api/docs/models/gpt-5.6-luna | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-5.6-sol | gpt-5.6-sol | active | stable | public | https://developers.openai.com/api/docs/models/gpt-5.6-sol | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-5.6-terra | gpt-5.6-terra | active | stable | public | https://developers.openai.com/api/docs/models/gpt-5.6-terra | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-6-astra | gpt-6-astra | active | stable | public | https://developers.openai.com/api/docs/models/gpt-6-astra | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-6-luna | gpt-6-luna | active | stable | public | https://developers.openai.com/api/docs/models/gpt-6-luna | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-6-sol | gpt-6-sol | active | stable | public | https://developers.openai.com/api/docs/models/gpt-6-sol | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| openai | gpt-6.1-sol | gpt-6.1-sol | active | stable | public | https://developers.openai.com/api/docs/models/gpt-6.1-sol | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| xai | grok-4.20-0309-non-reasoning | grok-4.20-0309-non-reasoning | active | stable | public | https://docs.x.ai/developers/rate-limits | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| xai | grok-4.20-0309-reasoning | grok-4.20-0309-reasoning | active | stable | public | https://docs.x.ai/developers/rate-limits | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| xai | grok-4.20-multi-agent-0309 | grok-4.20-multi-agent-0309 | active | preview | public | https://docs.x.ai/developers/rate-limits | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| xai | grok-4.3 | grok-4.3 | active | stable | public | https://docs.x.ai/developers/rate-limits | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| xai | grok-4.5 | grok-4.5 | active | stable | public | https://docs.x.ai/developers/rate-limits | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| xai | grok-4.6 | grok-4.6 | active | stable | public | https://docs.x.ai/developers/rate-limits | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| xai | grok-4.7 | grok-4.7 | active | stable | public | https://docs.x.ai/developers/rate-limits | 2026-10-07T04:26:40Z | approved | official access and binding verified |
| xai | grok-build-0.1 | grok-build-0.1 | active | stable | public | https://docs.x.ai/developers/rate-limits<br>https://docs.x.ai/developers/models/grok-build-0.1 | 2026-10-07T04:26:40Z | approved | official access and binding verified |

## Coverage

- public: 55; `anthropic/claude-fable-5`, `anthropic/claude-fable-5-1`, `anthropic/claude-haiku-4.5`, `anthropic/claude-opus-4.8`, `anthropic/claude-opus-5`, `anthropic/claude-opus-5-5`, `anthropic/claude-sonnet-4.6`, `anthropic/claude-sonnet-5`, `anthropic/claude-sonnet-5-5`, `cohere/aya-expanse-32b`, `cohere/command-r-plus-08-2024`, `deepseek/deepseek-flash`, `deepseek/deepseek-v4-pro`, `google-gemini/gemini-3-flash-preview`, `google-gemini/gemini-3.1-flash-lite`, `google-gemini/gemini-3.1-pro-preview`, `google-gemini/gemini-3.5-flash`, `google-gemini/gemini-3.5-flash-lite`, `google-gemini/gemini-3.6-flash`, `google-gemini/gemini-3.7-flash`, `google-gemini/gemini-3.8-flash`, `google-gemini/gemini-3.8-live`, `google-gemini/gemini-3.8-live-extended-thinking`, `mistral-ai/codestral-2508`, `mistral-ai/ministral-14b-2512`, `mistral-ai/ministral-3b-2512`, `mistral-ai/ministral-8b-2512`, `mistral-ai/mistral-large`, `mistral-ai/mistral-medium-3-5`, `mistral-ai/mistral-small-2603`, `moonshot-ai/kimi-k2.6`, `moonshot-ai/kimi-k2.7-code`, `moonshot-ai/kimi-k3`, `openai/chatgpt-chat-latest`, `openai/gpt-5.3-codex`, `openai/gpt-5.4`, `openai/gpt-5.4-mini`, `openai/gpt-5.4-pro`, `openai/gpt-5.5`, `openai/gpt-5.5-pro`, `openai/gpt-5.6-luna`, `openai/gpt-5.6-sol`, `openai/gpt-5.6-terra`, `openai/gpt-6-astra`, `openai/gpt-6-luna`, `openai/gpt-6-sol`, `openai/gpt-6.1-sol`, `xai/grok-4.20-0309-non-reasoning`, `xai/grok-4.20-0309-reasoning`, `xai/grok-4.20-multi-agent-0309`, `xai/grok-4.3`, `xai/grok-4.5`, `xai/grok-4.6`, `xai/grok-4.7`, `xai/grok-build-0.1`
- existing_users_only: 2; `google-gemini/gemini-2.5-flash`, `google-gemini/gemini-2.5-pro`
- invite_only: 0; none
- restricted: 2; `anthropic/claude-mythos-5`, `anthropic/claude-mythos-5-1`
- unknown: 0; none
- approved: 56; `anthropic/claude-fable-5`, `anthropic/claude-fable-5-1`, `anthropic/claude-haiku-4.5`, `anthropic/claude-mythos-5`, `anthropic/claude-mythos-5-1`, `anthropic/claude-opus-4.8`, `anthropic/claude-opus-5`, `anthropic/claude-opus-5-5`, `anthropic/claude-sonnet-4.6`, `anthropic/claude-sonnet-5`, `anthropic/claude-sonnet-5-5`, `cohere/command-r-plus-08-2024`, `deepseek/deepseek-flash`, `deepseek/deepseek-v4-pro`, `google-gemini/gemini-2.5-flash`, `google-gemini/gemini-2.5-pro`, `google-gemini/gemini-3-flash-preview`, `google-gemini/gemini-3.1-flash-lite`, `google-gemini/gemini-3.1-pro-preview`, `google-gemini/gemini-3.5-flash`, `google-gemini/gemini-3.5-flash-lite`, `google-gemini/gemini-3.6-flash`, `google-gemini/gemini-3.7-flash`, `google-gemini/gemini-3.8-flash`, `google-gemini/gemini-3.8-live`, `google-gemini/gemini-3.8-live-extended-thinking`, `mistral-ai/codestral-2508`, `mistral-ai/ministral-14b-2512`, `mistral-ai/ministral-3b-2512`, `mistral-ai/ministral-8b-2512`, `mistral-ai/mistral-medium-3-5`, `mistral-ai/mistral-small-2603`, `moonshot-ai/kimi-k2.6`, `moonshot-ai/kimi-k2.7-code`, `moonshot-ai/kimi-k3`, `openai/gpt-5.3-codex`, `openai/gpt-5.4`, `openai/gpt-5.4-mini`, `openai/gpt-5.4-pro`, `openai/gpt-5.5`, `openai/gpt-5.5-pro`, `openai/gpt-5.6-luna`, `openai/gpt-5.6-sol`, `openai/gpt-5.6-terra`, `openai/gpt-6-astra`, `openai/gpt-6-luna`, `openai/gpt-6-sol`, `openai/gpt-6.1-sol`, `xai/grok-4.20-0309-non-reasoning`, `xai/grok-4.20-0309-reasoning`, `xai/grok-4.20-multi-agent-0309`, `xai/grok-4.3`, `xai/grok-4.5`, `xai/grok-4.6`, `xai/grok-4.7`, `xai/grok-build-0.1`
- unresolved: 3; `cohere/aya-expanse-32b`, `mistral-ai/mistral-large`, `openai/chatgpt-chat-latest`

Selectable access/evidence coverage: 59/59. Canonical authorities 54 + Website-only authorities 5 = 59. Website-only IDs: claude-mythos-5, gemini-3-flash-preview, gemini-3.1-pro-preview, chatgpt-chat-latest, grok-build-0.1. The other 38 registry identities are unknown/unresolved and outside this task-start selectable union. mistral-large release date remains absent/null.

## Production freeze and shadow

| Surface | Before | After | Providers | Access-only shadow | Access + binding shadow | Shadow providers |
|---|---:|---:|---:|---:|---:|---:|
| homepage | 56 | 56 | 8 | 52 | 49 | 8 |
| displayed | 27 | 27 | 8 | presentation only | presentation only | - |
| api | 58 | 58 | 8 | 54 | 51 | 8 |
| source | 30 | 30 | 6 | 30 | 29 | 6 |
| target | 29 | 29 | 6 | 28 | 27 | 5 |
| retry | 29 | 29 | 6 | 28 | 27 | 5 |

Default: gpt-6.1-sol. Exact ID sets, provider order and Top4 are unchanged. The shadow helper is not called by production selectors/storage. Targets require active/public/approved; sources allow active or deprecated with public/existing_users_only. Historical facts remain readable.

- homepage removed: `claude-mythos-5` (access_restricted), `claude-mythos-5-1` (access_restricted), `aya-expanse-32b` (binding_unresolved), `gemini-2.5-flash` (access_existing_users_only), `gemini-2.5-pro` (access_existing_users_only), `mistral-large` (binding_unresolved), `chatgpt-chat-latest` (binding_unresolved)
- api removed: `claude-mythos-5` (access_restricted), `claude-mythos-5-1` (access_restricted), `aya-expanse-32b` (binding_unresolved), `gemini-2.5-flash` (access_existing_users_only), `gemini-2.5-pro` (access_existing_users_only), `mistral-large` (binding_unresolved), `chatgpt-chat-latest` (binding_unresolved)
- source removed: `mistral-large` (binding_unresolved)
- target removed: `gemini-2.5-pro` (access_existing_users_only), `mistral-large` (binding_unresolved)
- retry removed: `gemini-2.5-pro` (access_existing_users_only), `mistral-large` (binding_unresolved)

## Validation

Dataset validators PASS; full discovery includes governance/release-bundle/parity and 20 access tests. Alias scope, source roundtrip, authoritative conflicts and HF/API propagation have negative fixtures. Website npm test/lint/tsc plus ten specialized suites PASS. 36 arbitrary-ID mutations prove shadow rejection, production freeze and saved workload bytes/IDs/snapshots/write-count preservation. next build --webpack exited 0. Real Chrome/CDP at 1366x768 and 390x844 verified Homepage/API/Switch/Retry enabled IDs, default/provider Top4 and cost switching; console/network/hydration errors 0, overflow none. Only development port 3010 was used; the owned dev process was stopped.

## Semantic integrity

NO PRICE CHANGES / NO LIFECYCLE CHANGES / NO RELEASE DATE CHANGES / NO MODEL UNIVERSE CHANGES / NO ALIAS CHANGES / NO EVENT CHANGES. All 248 price objects, including sourceRefs and verification statuses, equal task-start HEAD. Snapshots and history bytes are unchanged. Only access/binding fields, necessary source registry purpose/count and generation metadata differ.

## Phase C readiness

READY subject to final test/diff gates remaining PASS: selectable evidence 100%, propagation verified, production frozen, nonempty shadow providers, explicit three unresolved bindings, future-safe default and saved-workload regression proof. No automatic selector enforcement.

## Changed-file manifest

### Dataset

- `api/v1/meta.json`: current public API/CSV metadata projection
- `api/v1/models/anthropic/claude-fable-5-1.json`: canonical metadata for this model
- `api/v1/models/anthropic/claude-fable-5.json`: canonical metadata for this model
- `api/v1/models/anthropic/claude-haiku-4.5.json`: canonical metadata for this model
- `api/v1/models/anthropic/claude-mythos-5-1.json`: canonical metadata for this model
- `api/v1/models/anthropic/claude-opus-4.8.json`: canonical metadata for this model
- `api/v1/models/anthropic/claude-opus-5-5.json`: canonical metadata for this model
- `api/v1/models/anthropic/claude-opus-5.json`: canonical metadata for this model
- `api/v1/models/anthropic/claude-sonnet-4.6.json`: canonical metadata for this model
- `api/v1/models/anthropic/claude-sonnet-5-5.json`: canonical metadata for this model
- `api/v1/models/anthropic/claude-sonnet-5.json`: canonical metadata for this model
- `api/v1/models/cohere/aya-expanse-32b.json`: canonical metadata for this model
- `api/v1/models/cohere/command-r-plus-08-2024.json`: canonical metadata for this model
- `api/v1/models/deepseek/deepseek-flash.json`: canonical metadata for this model
- `api/v1/models/deepseek/deepseek-v4-pro.json`: canonical metadata for this model
- `api/v1/models/google-gemini/gemini-2.5-flash.json`: canonical metadata for this model
- `api/v1/models/google-gemini/gemini-2.5-pro.json`: canonical metadata for this model
- `api/v1/models/google-gemini/gemini-3.1-flash-lite.json`: canonical metadata for this model
- `api/v1/models/google-gemini/gemini-3.5-flash-lite.json`: canonical metadata for this model
- `api/v1/models/google-gemini/gemini-3.5-flash.json`: canonical metadata for this model
- `api/v1/models/google-gemini/gemini-3.6-flash.json`: canonical metadata for this model
- `api/v1/models/google-gemini/gemini-3.7-flash.json`: canonical metadata for this model
- `api/v1/models/google-gemini/gemini-3.8-flash.json`: canonical metadata for this model
- `api/v1/models/google-gemini/gemini-3.8-live-extended-thinking.json`: canonical metadata for this model
- `api/v1/models/google-gemini/gemini-3.8-live.json`: canonical metadata for this model
- `api/v1/models/mistral-ai/codestral-2508.json`: canonical metadata for this model
- `api/v1/models/mistral-ai/ministral-14b-2512.json`: canonical metadata for this model
- `api/v1/models/mistral-ai/ministral-3b-2512.json`: canonical metadata for this model
- `api/v1/models/mistral-ai/ministral-8b-2512.json`: canonical metadata for this model
- `api/v1/models/mistral-ai/mistral-large.json`: canonical metadata for this model
- `api/v1/models/mistral-ai/mistral-medium-3-5.json`: canonical metadata for this model
- `api/v1/models/mistral-ai/mistral-small-2603.json`: canonical metadata for this model
- `api/v1/models/moonshot-ai/kimi-k2.6.json`: canonical metadata for this model
- `api/v1/models/moonshot-ai/kimi-k2.7-code.json`: canonical metadata for this model
- `api/v1/models/moonshot-ai/kimi-k3.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-5.3-codex.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-5.4-mini.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-5.4-pro.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-5.4.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-5.5-pro.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-5.5.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-5.6-luna.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-5.6-sol.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-5.6-terra.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-6-astra.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-6-luna.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-6-sol.json`: canonical metadata for this model
- `api/v1/models/openai/gpt-6.1-sol.json`: canonical metadata for this model
- `api/v1/models/xai/grok-4.20-0309-non-reasoning.json`: canonical metadata for this model
- `api/v1/models/xai/grok-4.20-0309-reasoning.json`: canonical metadata for this model
- `api/v1/models/xai/grok-4.20-multi-agent-0309.json`: canonical metadata for this model
- `api/v1/models/xai/grok-4.3.json`: canonical metadata for this model
- `api/v1/models/xai/grok-4.5.json`: canonical metadata for this model
- `api/v1/models/xai/grok-4.6.json`: canonical metadata for this model
- `api/v1/models/xai/grok-4.7.json`: canonical metadata for this model
- `api/v1/prices.csv`: current public API/CSV metadata projection
- `api/v1/prices.json`: current public API/CSV metadata projection
- `api/v1/providers/anthropic.json`: canonical metadata for this provider
- `api/v1/providers/cohere.json`: canonical metadata for this provider
- `api/v1/providers/deepseek.json`: canonical metadata for this provider
- `api/v1/providers/google-gemini.json`: canonical metadata for this provider
- `api/v1/providers/mistral-ai.json`: canonical metadata for this provider
- `api/v1/providers/moonshot-ai.json`: canonical metadata for this provider
- `api/v1/providers/openai.json`: canonical metadata for this provider
- `api/v1/providers/xai.json`: canonical metadata for this provider
- `data/canonical/models.json`: authoritative access/binding backfill
- `data/models/anthropic/claude-fable-5-1.json`: canonical metadata for this model
- `data/models/anthropic/claude-fable-5.json`: canonical metadata for this model
- `data/models/anthropic/claude-haiku-4.5.json`: canonical metadata for this model
- `data/models/anthropic/claude-mythos-5-1.json`: canonical metadata for this model
- `data/models/anthropic/claude-opus-4.8.json`: canonical metadata for this model
- `data/models/anthropic/claude-opus-5-5.json`: canonical metadata for this model
- `data/models/anthropic/claude-opus-5.json`: canonical metadata for this model
- `data/models/anthropic/claude-sonnet-4.6.json`: canonical metadata for this model
- `data/models/anthropic/claude-sonnet-5-5.json`: canonical metadata for this model
- `data/models/anthropic/claude-sonnet-5.json`: canonical metadata for this model
- `data/models/cohere/aya-expanse-32b.json`: canonical metadata for this model
- `data/models/cohere/command-r-plus-08-2024.json`: canonical metadata for this model
- `data/models/deepseek/deepseek-flash.json`: canonical metadata for this model
- `data/models/deepseek/deepseek-v4-pro.json`: canonical metadata for this model
- `data/models/google-gemini/gemini-2.5-flash.json`: canonical metadata for this model
- `data/models/google-gemini/gemini-2.5-pro.json`: canonical metadata for this model
- `data/models/google-gemini/gemini-3.1-flash-lite.json`: canonical metadata for this model
- `data/models/google-gemini/gemini-3.5-flash-lite.json`: canonical metadata for this model
- `data/models/google-gemini/gemini-3.5-flash.json`: canonical metadata for this model
- `data/models/google-gemini/gemini-3.6-flash.json`: canonical metadata for this model
- `data/models/google-gemini/gemini-3.7-flash.json`: canonical metadata for this model
- `data/models/google-gemini/gemini-3.8-flash.json`: canonical metadata for this model
- `data/models/google-gemini/gemini-3.8-live-extended-thinking.json`: canonical metadata for this model
- `data/models/google-gemini/gemini-3.8-live.json`: canonical metadata for this model
- `data/models/mistral-ai/codestral-2508.json`: canonical metadata for this model
- `data/models/mistral-ai/ministral-14b-2512.json`: canonical metadata for this model
- `data/models/mistral-ai/ministral-3b-2512.json`: canonical metadata for this model
- `data/models/mistral-ai/ministral-8b-2512.json`: canonical metadata for this model
- `data/models/mistral-ai/mistral-large.json`: canonical metadata for this model
- `data/models/mistral-ai/mistral-medium-3-5.json`: canonical metadata for this model
- `data/models/mistral-ai/mistral-small-2603.json`: canonical metadata for this model
- `data/models/moonshot-ai/kimi-k2.6.json`: canonical metadata for this model
- `data/models/moonshot-ai/kimi-k2.7-code.json`: canonical metadata for this model
- `data/models/moonshot-ai/kimi-k3.json`: canonical metadata for this model
- `data/models/openai/gpt-5.3-codex.json`: canonical metadata for this model
- `data/models/openai/gpt-5.4-mini.json`: canonical metadata for this model
- `data/models/openai/gpt-5.4-pro.json`: canonical metadata for this model
- `data/models/openai/gpt-5.4.json`: canonical metadata for this model
- `data/models/openai/gpt-5.5-pro.json`: canonical metadata for this model
- `data/models/openai/gpt-5.5.json`: canonical metadata for this model
- `data/models/openai/gpt-5.6-luna.json`: canonical metadata for this model
- `data/models/openai/gpt-5.6-sol.json`: canonical metadata for this model
- `data/models/openai/gpt-5.6-terra.json`: canonical metadata for this model
- `data/models/openai/gpt-6-astra.json`: canonical metadata for this model
- `data/models/openai/gpt-6-luna.json`: canonical metadata for this model
- `data/models/openai/gpt-6-sol.json`: canonical metadata for this model
- `data/models/openai/gpt-6.1-sol.json`: canonical metadata for this model
- `data/models/xai/grok-4.20-0309-non-reasoning.json`: canonical metadata for this model
- `data/models/xai/grok-4.20-0309-reasoning.json`: canonical metadata for this model
- `data/models/xai/grok-4.20-multi-agent-0309.json`: canonical metadata for this model
- `data/models/xai/grok-4.3.json`: canonical metadata for this model
- `data/models/xai/grok-4.5.json`: canonical metadata for this model
- `data/models/xai/grok-4.6.json`: canonical metadata for this model
- `data/models/xai/grok-4.7.json`: canonical metadata for this model
- `data/prices.csv`: current public API/CSV metadata projection
- `data/prices.json`: current public API/CSV metadata projection
- `data/pricing-v2-preview/convergence-report.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-preview/generated/model-pricing.v2.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-preview/generated/model-pricing.website-preview.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-preview/model-identity-registry.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-preview/models.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-preview/phase4a-5-context-window-audit.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-preview/phase4a-5-projection-row-reconciliation.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-preview/phase4a-5-safe-price-record-reconciliation.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-preview/phase4a-5-unsafe-difference-audit.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-preview/phase4a-website-projection-report.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-preview/sources.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/providers/anthropic.json`: canonical metadata for this provider
- `data/providers/cohere.json`: canonical metadata for this provider
- `data/providers/deepseek.json`: canonical metadata for this provider
- `data/providers/google-gemini.json`: canonical metadata for this provider
- `data/providers/mistral-ai.json`: canonical metadata for this provider
- `data/providers/moonshot-ai.json`: canonical metadata for this provider
- `data/providers/openai.json`: canonical metadata for this provider
- `data/providers/xai.json`: canonical metadata for this provider
- `huggingface/README.md`: HF metadata propagation/additive contract documentation
- `huggingface/meta.json`: HF metadata propagation/additive contract documentation
- `huggingface/prices.csv`: HF metadata propagation/additive contract documentation
- `huggingface/prices.json`: HF metadata propagation/additive contract documentation
- `huggingface/train.csv`: HF metadata propagation/additive contract documentation
- `schema/model.schema.json`: access/binding schema and evidence pairing
- `schema/pricing-v2-preview.schema.json`: access/binding schema and evidence pairing
- `scripts/build.py`: generator/validator/export propagation
- `scripts/export_huggingface.py`: generator/validator/export propagation
- `scripts/generate_pricing_v2_preview.py`: generator/validator/export propagation
- `scripts/generate_website_projection_v2.py`: generator/validator/export propagation
- `scripts/lib.py`: generator/validator/export propagation
- `scripts/validate.py`: generator/validator/export propagation
- `scripts/validate_pricing_v2_preview.py`: generator/validator/export propagation
- `tests/gemini_verification.py`: access/negative regression or explicit additive metadata compatibility
- `tests/test_grok_4_20_onboarding.py`: access/negative regression or explicit additive metadata compatibility
- `tests/test_grok_4_7_onboarding.py`: access/negative regression or explicit additive metadata compatibility
- `tests/test_huggingface_export.py`: access/negative regression or explicit additive metadata compatibility
- `scripts/access_metadata.py`: generator/validator/export propagation
- `tests/test_access_metadata.py`: access/negative regression or explicit additive metadata compatibility
### Website

- `data/model-pricing.json`: five Website-only authoritative seeds
- `data/pricing-v2-projection/model-pricing.v2.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `data/pricing-v2-projection/pricing-meta.v1.json`: derived access/binding metadata, source registry or generation/source-count metadata
- `package.json`: register shadow regression in pretest
- `src/lib/model-switch-cost.ts`: metadata types/exposure or shadow-only helper; no selector enforcement
- `src/lib/model-switch-pricing.ts`: metadata types/exposure or shadow-only helper; no selector enforcement
- `src/lib/pricing-adapter.ts`: metadata types/exposure or shadow-only helper; no selector enforcement
- `src/lib/pricing.ts`: metadata types/exposure or shadow-only helper; no selector enforcement
- `scripts/test-model-access-browser.mjs`: access/negative regression or explicit additive metadata compatibility
- `scripts/test-model-access-policy.mjs`: access/negative regression or explicit additive metadata compatibility
- `src/lib/model-access-policy.ts`: metadata types/exposure or shadow-only helper; no selector enforcement

Final Dataset discovery: 406/406 PASS, including 20 access tests. Final semantic integrity audit PASS.

- `docs/access-policy-v1-phase-ab.md`: complete official evidence, schema/authority/generation decisions, validation and changed-file manifest.

Git summary: Dataset 159 tracked modified + 3 new; Website 8 tracked modified + 3 new. No staged files.

NO COMMIT / NO PUSH / NO PR / NO DEPLOY.
