# Issue #26 — Freshness Closure Sprint / Phase A

## 1. Final Verdict

**BLOCKED**。本地事实修复和生成物已完成，但 stale=2、补充来源 HTTP 403 及外部 parity 未满足发布验收；不声称 Issue 已解决或 PRODUCTION VERIFIED。

## 2. Repository Baseline

- 分支：`codex/issue26-dataset-candidate`。
- 初始 HEAD：`3e75fa51bc1f7af01745345d03bc1a525e353158`，初始工作区干净。
- HTTPS 两次在线确认 main/candidate 都为 `4d4f32d971dc1d79bffc7ffd12a71049fbd701f6`。SSH 查询受现有 ProxyCommand 在 PowerShell 中无法执行 `exec` 影响；HTTPS 查询成功。
- 已有 GPT‑4.1 mini 生命周期修复提交 `3e75fa5` 保留，并作为本次候选提交的父提交一起交付；独立 authority 与 review_required/不默认计算门禁保留。
- 后续用户指令授权本地 commit；未 push、创建 PR、部署或关闭 Issue。最终提交 SHA 见交付消息/git log，本报告在该提交中。
- 最终预期工作区干净；完整变更清单见 `files-changed.txt`。`dist/release-candidate/issue26-audit` 为 Git 忽略的本地原始证据目录。
- V1 生成物 `source_commit_sha` 是构建时的父提交 HEAD；这是本地候选，不是最终已发布 provenance。批准发布后须按最终提交重新构建/验证 release bundle。

## 3. Freshness Inventory

- 实际 UTC 起点：`2026-10-09T06:17:22.193486+00:00`；报告时间：`2026-10-09T07:04:45.890028+00:00`。
- 使用原规则 `(now-last_verified_at).days > 30`，未修改阈值或退出码。
- 全量 85 条：初始 stale=19、未来7天到期=13，目标32条；未发现额外 stale。
- 完成30条支持字段核验；最终 stale=2、未来7天到期=0。两条失败记录保留原价格和原核验日期。

## 4. 32-Record Evidence Matrix

以下价格为 USD，token 数值均按 1M tokens；例外单位已注明。表列主官方 URL，全部补充 URL、响应、hash 和完整 price_records 见 `evidence.json`；原始 body 保存在该文件指向的本地证据目录。

| 模型 | 原始核验日期/age | 官方主来源 | 价格/生命周期核验或变化 | 结果/阻断 | 新核验日期 |
|---|---|---|---|---|---|
| openai/gpt-6-astra | 2026-09-04T17:34:11Z / 34d | [官方来源](https://developers.openai.com/api/docs/models/gpt-6-astra) | Standard/Batch/Flex/Fast/Ultrafast、272K 全请求边界和区域规则匹配；价格记录核验日期同步。补充公告页 403，原来源核验日期保留。 | 字段 PASS；补充403阻断 | 2026-10-09T06:29:38Z |
| openai/gpt-live-1 | 2026-09-14T05:04:26Z / 25d | [官方来源](https://developers.openai.com/api/docs/models/gpt-live-1) | $0.05/分钟、按秒计费，不整分钟进位；后端模型及工具另计。 | PASS | 2026-10-09T06:29:38Z |
| openai/gpt-5 | 2026-09-02T11:29:12Z / 36d | [官方来源](https://developers.openai.com/api/docs/models/gpt-5) | active→deprecated；保留 $1.25/$0.125/$10 和 Batch。2026-12-11 停用公告针对 gpt-5-2025-08-07；不推定 alias 已 retired 或自动重定向。 | PASS | 2026-10-09T06:29:38Z |
| openai/gpt-4.1 | 2026-09-02T11:29:12Z / 36d | [官方来源](https://developers.openai.com/api/docs/models/gpt-4.1) | 官方 Default；active 保留，$2/$0.50/$8 与 Batch 匹配；review_required 门禁保留。 | PASS | 2026-10-09T06:29:38Z |
| openai/o3 | 2026-09-02T11:29:12Z / 36d | [官方来源](https://developers.openai.com/api/docs/models/o3) | active→deprecated；保留 $2/$0.50/$8 和 Batch。2026-12-11 公告针对 o3-2025-04-16；不推定 alias 已 retired。 | PASS | 2026-10-09T06:29:38Z |
| anthropic/claude-fable-5-1 | 2026-09-03T13:03:55Z / 35d | [官方来源](https://platform.claude.com/docs/en/about-claude/pricing) | API ID、Active、$10/$0.25/$50、5m/1h 写入 $12.5/$20、Batch 50% 匹配。核对 US inference_geo 1.1x 等可选供应商修饰项，不改变原 Global token 范围。 | PASS | 2026-10-09T06:29:38Z |
| anthropic/claude-mythos-5-1 | 2026-09-03T13:03:55Z / 35d | [官方来源](https://platform.claude.com/docs/en/about-claude/pricing) | 同 Fable 5.1 价格；Active (verification required)，restricted access 及 approved binding 原事实保留，不批准新访问。 | PASS | 2026-10-09T06:29:38Z |
| google-gemini/gemini-3.8-flash | 2026-09-03T18:03:16Z / 35d | [官方来源](https://ai.google.dev/gemini-api/docs/pricing) | 保留 Standard/Batch 及 2026-12-31/2027-01-01 边界；迁入 price_records，新增 Flex、Priority、$0.50→$1.00/MTok/hour cache storage。工具 grounding 及 free tier 不属于此 token/cache 合同。 | PASS | 2026-10-09T06:31:59Z |
| xai/grok-4.6 | 2026-08-31T17:11:58Z / 38d | [官方来源](https://docs.x.ai/developers/models/grok-4.6) | Standard 短/长价保留；新增 Priority 2x 和 US endpoint 1.1x；200K 全请求边界保留，Batch 不支持。区域价格不批准账户访问或全面数据驻留。 | PASS | 2026-10-09T06:31:59Z |
| deepseek/deepseek-flash | 2026-09-13T03:53:37Z / 26d | [官方来源](https://api-docs.deepseek.com/quick_start/pricing) | 当前 V4.1 Flash ID、峰谷价格、UTC 工作日/中国节假日规则匹配，刷新 schedule 证据。 | PASS | 2026-10-09T06:29:38Z |
| deepseek/deepseek-v4-flash | 2026-09-13T03:53:37Z / 26d | [官方来源](https://api-docs.deepseek.com/quick_start/pricing) | 官方历史价格图表支持原峰谷价格；retired、可解析旧 slug、由 deepseek-flash 承接并计费的规则保留，不重写历史日期。 | PASS | 2026-10-09T06:29:38Z |
| deepseek/deepseek-v4-flash-vision-exp | 2026-09-13T03:53:37Z / 26d | [官方来源](https://api-docs.deepseek.com/quick_start/pricing) | retired 和 Flash 计费重定向保留；当前目标峰谷价匹配，原身份不自动变 active。 | PASS | 2026-10-09T06:29:38Z |
| deepseek/deepseek-v4-pro | 2026-09-13T03:53:37Z / 26d | [官方来源](https://api-docs.deepseek.com/quick_start/pricing) | active、V4 Pro 0813、峰谷 input/output/cache 与原 UTC schedule 匹配。 | PASS | 2026-10-09T06:29:38Z |
| mistral-ai/mistral-large | 2026-09-02T11:29:12Z / 36d | [官方来源](https://docs.mistral.ai/inference/pricing) | 明确现有 internal ID 代表 Large 3 / mistral-large-2512；原 Standard/Batch 及现有 price_records 保留。Large 4 单独挂牌，不创建新模型，不把其价格套用到 Large 3。 | PASS | 2026-10-09T06:29:38Z |
| mistral-ai/mistral-medium-3-5 | 2026-09-08T07:53:25Z / 30d | [官方来源](https://docs.mistral.ai/inference/pricing) | 官方 exact API ID、GA、原 Standard/cache/Batch 与现有 price_records 的模式/区域规则匹配；仅刷新实际核验日期，原价格与生效日期保留。 | PASS | 2026-10-09T06:29:38Z |
| mistral-ai/mistral-small-2603 | 2026-09-08T07:53:25Z / 30d | [官方来源](https://docs.mistral.ai/inference/pricing) | 官方 exact API ID、GA、原 Standard/cache/Batch 与现有 price_records 的模式/区域规则匹配；仅刷新实际核验日期，原价格与生效日期保留。 | PASS | 2026-10-09T06:29:38Z |
| mistral-ai/ministral-14b-2512 | 2026-09-08T07:53:25Z / 30d | [官方来源](https://docs.mistral.ai/inference/pricing) | 官方 exact API ID、GA、原 Standard/cache/Batch 与现有 price_records 的模式/区域规则匹配；仅刷新实际核验日期，原价格与生效日期保留。 | PASS | 2026-10-09T06:29:38Z |
| mistral-ai/ministral-8b-2512 | 2026-09-08T07:53:25Z / 30d | [官方来源](https://docs.mistral.ai/inference/pricing) | 官方 exact API ID、GA、原 Standard/cache/Batch 与现有 price_records 的模式/区域规则匹配；仅刷新实际核验日期，原价格与生效日期保留。 | PASS | 2026-10-09T06:29:38Z |
| mistral-ai/ministral-3b-2512 | 2026-09-08T07:53:25Z / 30d | [官方来源](https://docs.mistral.ai/inference/pricing) | 官方 exact API ID、GA、原 Standard/cache/Batch 与现有 price_records 的模式/区域规则匹配；仅刷新实际核验日期，原价格与生效日期保留。 | PASS | 2026-10-09T06:29:38Z |
| mistral-ai/codestral-2508 | 2026-09-08T07:53:25Z / 30d | [官方来源](https://docs.mistral.ai/inference/pricing) | 官方 exact API ID、GA、原 Standard/cache/Batch 与现有 price_records 的模式/区域规则匹配；仅刷新实际核验日期，原价格与生效日期保留。 | PASS | 2026-10-09T06:29:38Z |
| mistral-ai/mistral-ocr-4-0 | 2026-09-08T00:00:00Z / 31d | [官方来源](https://docs.mistral.ai/inference/pricing) | active→deprecated，官方日期 2026-09-29，推荐 OCR 4.1；无 retirement 日期。现有 $4/1000 pages 保留，但当前官方页面不再提供 OCR 4.0 价格，不刷新核验日期。 | BLOCKED | 2026-09-08T00:00:00Z |
| mistral-ai/mistral-ocr-4-1 | 2026-09-08T00:00:00Z / 31d | [官方来源](https://docs.mistral.ai/inference/pricing) | GA exact ID 与 aliases 匹配；Basic OCR $4/1000 pages 匹配；annotated/cached 页面是已记录的非准入范围，不借此加入含混组件。 | PASS | 2026-10-09T06:29:38Z |
| cohere/command-a-plus | 2026-09-02T11:29:12Z / 36d | [官方来源](https://docs.cohere.com/docs/command-a-plus) | 官方 API ID command-a-plus-05-2026；试用免费且有限，token 价仍 null。Vault L/XL $17.50/$32.50 每实例小时匹配，不转换为 token 价；excluded 不变。 | PASS | 2026-10-09T06:29:38Z |
| xai/grok-imagine-image-quality | 2026-09-05T15:40:04Z / 33d | [官方来源](https://docs.x.ai/developers/pricing) | 保留 deprecated、原 ID 和历史/current 价格；补齐 1.5K(1408x1408) $0.06/image。2026-11-02 退役后 quality=low 重定向保持原规则，不提前 retired。 | PASS | 2026-10-09T06:29:38Z |
| xai/grok-4.20-0309-reasoning | 2026-09-06T05:12:08Z / 33d | [官方来源](https://docs.x.ai/developers/models/grok-4.20-0309-reasoning) | 官方 ID、<200K/≥200K Standard、Batch 20% 折扣、Priority 2x 和缓存价匹配，原记录 ID 与区域合同保留。 | PASS | 2026-10-09T06:29:38Z |
| xai/grok-4.20-0309-non-reasoning | 2026-09-06T05:12:08Z / 33d | [官方来源](https://docs.x.ai/developers/models/grok-4.20-0309-non-reasoning) | 同 4.20 reasoning 的计费表，独立 API ID/aliases 保留。 | PASS | 2026-10-09T06:29:38Z |
| xai/grok-4.20-multi-agent-0309 | 2026-09-06T05:12:08Z / 33d | [官方来源](https://docs.x.ai/developers/models/grok-4.20-multi-agent-0309) | 独立 multi-agent ID、beta/preview 及 aliases 保留；Standard/Batch/Priority 与 200K 全请求边界匹配。 | PASS | 2026-10-09T06:29:38Z |
| moonshot-ai/kimi-k2.7-code | 2026-09-08T03:04:30Z / 31d | [官方来源](https://platform.kimi.ai/docs/pricing/chat-k27-code) | 专属页合法重定向到 chat。原始 MDX 表明确 cache $0.19、input $0.95、output $4；Batch $0.114/$0.57/$2.40，字段核验通过。 | PASS | 2026-10-09T06:29:38Z |
| moonshot-ai/kimi-k2.6 | 2026-09-08T03:04:30Z / 31d | [官方来源](https://platform.kimi.ai/docs/pricing/chat-k26) | 专属页重定向到 chat；Standard $0.16/$0.95/$4 匹配，但 Batch cache 表为 $0.10，与 60% 规则及原 $0.096 冲突。保留整个原记录和核验日期，等待官方精度说明。 | BLOCKED | 2026-09-08T03:04:30Z |
| google-cloud/OCR_PROCESSOR | 2026-09-08T00:00:00Z / 31d | [官方来源](https://cloud.google.com/products/document-ai/pricing) | Enterprise Basic OCR exact processor type、monthly graduated 0-1000 免费、1K-5M $1.50/1000、5M+ $0.60/1000 与地区目录匹配。按需范围不扩到可选 Savings Plan/add-ons。 | PASS | 2026-10-09T06:29:38Z |
| aws/DetectDocumentText | 2026-09-09T00:00:00Z / 30d | [官方来源](https://aws.amazon.com/textract/pricing/) | 官方 Price List 16 区域/32 Sync+Async Text SKUs；商业基价 $1.5/$0.6 每1000页、us-west-1 1.4x、GovCloud 1.26x 匹配。新客户 Paid plan 1000 pages/月×3个月条件额度保持。 | PASS | 2026-10-09T06:29:38Z |
| azure/prebuilt-read | 2026-09-09T00:00:00Z / 30d | [官方来源](https://azure.microsoft.com/en-us/pricing/details/document-intelligence/) | 31 个已准入商业区域 62 个 S0 Read SKU 匹配 $1.5/$0.6 每1000页；government 的 1.25x 价不引入。effectiveStartDate 各区不同，原 effective_from=null 保留。 | PASS | 2026-10-09T06:29:38Z |

## 5. Files Changed

- Canonical：仅 `data/canonical/models.json`，32条目标中31条有改动，K2.6 完全不变；其他 canonical 模型与 access/binding 原事实逐字段未变。
- 生成物：V1 `data/prices.*`、`data/models`、`data/providers`、`api/v1`，必要 history 追加与 2026-10-09 快照；V2 价格/来源/身份、SQL、投影和审计报告；本地 HF 候选四个 JSON/CSV/meta 文件。历史已有内容未删除。
- 所有原 V2 price IDs 保留；新增7个 ID（Gemini Flex/Priority当前/未来4个、Grok 4.6 Priority短/长2个、quality 1.5K 1个）。所有原 charge ID/amount/unit 保留，Gemini 在原记录增加 storage charges。
- 所有原 V1 价格完全不变。Gemini/Grok legacy 合同迁入现有 price_records，无 schema 扩展；未知新增模式生效起点为 null，公开未来日期保持。
- 代码：`generate_website_projection_v2.py` 区分 Vault 实例资费、隔离共享 URL 核验日期、保持原编辑状态、阻止 deprecated 默认计算并修正安全审计计数；`sql_seed.py` 保持确定性 INSERT 顺序及非目标字节。
- 通用 deprecated 门禁使两个既有 deprecated 投影（GPT‑5.3 Codex、GPT‑5.4 Nano）从 defaultSafe=true 变 false/标量null；其 canonical 原价格、生命周期、访问事实不变。这是必要门禁修复，不是价格调整。
- 回归：更新受本次旧结构/固定日期影响的断言；历史 GPT‑4.1/mini 定点工具测试改用固定父提交 fixture，生产工具的冻结计数门禁没有放宽；新增 Phase A 价格/访问/来源隔离验证。
- Workflow、Issue 生命周期规则、validate.py、CI 安全检查、Website 仓库均未修改。

## 6. URL Results

- 精确 Freshness workflow 命令：85次逐模型真实请求（41个去重主 URL），85通过、0失败。
- 审计来源集合共107个去重 URL（主来源+目标记录补充+新增历史/区域证据）：106个HTTP200，1个HTTP403；其中7个合法重定向。未出现429、超时、DNS/TLS失败。
- 异常：`https://openai.com/index/gpt-6-astra/` → HTTP403。保留来源与其原核验日期 `2026-09-04T17:34:11Z`，不能认为本轮已核验该页。Astra价格由可读取的官方模型/定价/模式文档支持。
- Kimi两个专属价格 URL→通用 chat 页面；在原始响应的 MDX 表中核对组件，未把200自动当作价格验证。DeepSeek pricing→`/en/quick_start/pricing/`、Anthropic旧站及 OpenAI platform→developers 的重定向已记录。
- 本地环境：Windows/Python urllib，User-Agent `AICostBudget freshness-check/1.0`，timeout20秒，与workflow请求实现相同；真实检测不是mock。
- 只读读取 Issue26：仍 open，2026-10-05 的Actions报告主URL failures=None。未触发新的Actions，不能声称当前GitHub网络已通过；本地与远程这次不能作同时间比较。

## 7. Test Results

| 项目 | 命令/证据 | 结果 |
|---|---|---|
| Build | `python scripts/build.py` | PASS |
| Canonical/V1/HF本地一致性 | `python scripts/validate.py` | PASS |
| 全部单元回归 | `python -m unittest discover -s tests` | PASS：537 tests |
| V2 schema/来源/定价门禁 | `python scripts/validate_pricing_v2_preview.py` | PASS：97 identities /94 models /257 prices /778 charges /172 sources |
| SQL seed | `python scripts/sql_seed.py --check` | PASS |
| Freshness真实检查 | `python scripts/validate.py --freshness-report --max-age-days 30 --check-urls` | FAIL(exit1)：2 stale，URL失败0 |
| Freshness workflow、Source reconciliation、Lifecycle normalization、Pricing governance、V1/V2合同、Release bundle、Website projection、HF export、provenance及Phase A专用回归 | 完整命令见 `final-gates.json` | PASS：132 tests |
| Website/HF候选与真实Website源码 parity | `python scripts/export_huggingface.py --website-repo D:/ai-cost-control-tool/aicostguard-english --website-ref HEAD --check` | FAIL：Website pricing components differ；Website未修改 |
| 真实HF production parity | `python scripts/check_hf_production_parity.py --attempts 1 --timeout 20` | FAIL：DATA_DRIFT；完整明细见 `hf-production-parity.log` |
| diff格式 | `git diff --check` | PASS |

- 本地 HF 候选使用项目既有 build_export/artifact_contents/validate_huggingface_artifacts 函数从 canonical V2 投影生成；CLI外部Website安全门禁保持，单独检查失败已明确列为发布阻断。没有修改生产parity代码或忽略漂移。
- Release bundle回归使用仓库既有固定提交fixture通过；未生成可发布的新bundle，没有把fixture验证当作当前候选生产验证。
- 全部命令及原始结果见同目录日志。未启动任何生产服务，未调用3017端口。

## 8. Remaining Blockers

1. Mistral OCR4.0：当前官方页只有Deprecated/2026-09-29，无原模型价格；需要官方历史价格证据，不能将OCR4.1价格套用到OCR4.0。
2. Kimi K2.6：Batch cached input 显式表$0.10与60%公式$0.096冲突，需官方精度/舍入或计费口径说明。
3. OpenAI补充公告页403：本轮无法读取正文，需该官方来源可访问后重新核验；不删除、不跳过。
4. 外部Website projection及HF生产仍是此前发布数据，与新候选components/metadata不一致。需另行批准的同步发布才能达成真实production parity。

## 9. Release Readiness

**不适合现在批准一次性发布。** 本地候选、证据和回归已整理可审阅，但发布验收尚未达到。先解决两条官方证据阻断和补充URL访问，再在明确批准的Website/HF/Dataset发布范围内按固定最终提交构建、校验provenance与bundle。

## 10. Issue #26 Closure Readiness

**尚不具备通过真实 Freshness Check 自动关闭 Issue 的条件。** 当前精确命令因2 stale返回1；触发workflow预计仍需保留该Issue。未手工关闭Issue，未自行触发workflow或发布。完成本地提交后停止，等待发布审批。
