# Issue #26 — Kimi K2.6 Final Published-Rate Reconciliation

## 1. Final Verdict

**LOCAL FRESHNESS VERIFIED。** 2026-10-09 实际核验后，stale=0、85/85 主来源检查通过、Freshness exit=0；最终完整 548 tests PASS、相关 172 tests PASS。范围限于 Kimi K2.6 的 published-rate 纠错与必要说明/生成物；没有重新开展 32 模型全量人工研究。

**BILLING PRECISION UNCONFIRMED** 单独保留。这个结论验证官方公布价格，不声称验证真实账单结算精度。依本轮明确的字段语义和来源优先级，上轮 unresolved 表格/折扣差异现在用于说明 published price 与数学推导的区别，不被伪装成内部结算算法。

首先完整读取上一轮 `reports/issue26-final-blockers-2026-10-09/report.md`。启动时保存工作区所有 tracked 与 non-ignored untracked 文件的本轮前副本和 hash，保护已有 OCR 修复。HEAD 始终 `80c2ec4991bcaaf795fe9192946f5ec770d57f48`；origin/main 本地引用及实际 GitHub API main/candidate 均 `4d4f32d971dc1d79bffc7ffd12a71049fbd701f6`。SSH 代理与一次 HTTPS ls-remote 失败后，使用只读 GitHub API 成功验证真实引用，没有假设远程包含修复。

## 2. Official Kimi Published Price Evidence

重新实际下载官方 [Batch 页面](https://platform.kimi.ai/docs/pricing/batch)、[Standard 页面](https://platform.kimi.ai/docs/pricing/chat) 及两页 `.md` 原始来源，均 HTTP 200。可靠提取官方 authored DocTable 的精确 row/column，不依赖第三方。原始 HTML 的编译页面及 Markdown 数据一致。

| 定位字段 | 官方表格定位 / Dataset 规范化 |
|---|---|
| model / mode | `kimi-k2.6 (Batch)` / `batch` |
| component | `Input Price (Cache Hit)` / `cached_input` |
| unit | `1M tokens`，页面定义 1M=1,000,000 / `per_1m_tokens` |
| published price / currency | `$0.10` / Dataset 保留 USD；没有改币种 |
| 同 row input / output | $0.57 / $2.40 |
| Standard row | kimi-k2.6：cached $0.16、input $0.95、output $4.00 |
| Batch 通用说明 | 标准价的 60% |

已保存官方价格表必要摘录 `official-batch.md` / `official-chat.md`；完整原始 HTML/MD、HTTP 状态、目的 URL、UTC 和 SHA256 见 `evidence.json` 指向的 ignored 证据目录。本轮 raw Batch Markdown SHA256：`6bde62235d73213830948fdb7f3fee9d51703e99c325545c9d4e354c57d8aca0`；chat Markdown：`76361351b3e3f3184cbd89f262f4bd8ed212b4d481dd0d527f34221a35a4d079`。

既有 Standard 主来源 `https://platform.kimi.ai/docs/pricing/chat-k26` 实际重定向至上述 `pricing/chat`，最终 HTTP 200，内容 hash 同 chat 页面。保留既有 source identity、全部旧 URL 和 source refs，不为通过检查移除来源；重定向事实与当前真实内容完整记录。

## 3. Updated Fields

本轮相对开始时工作区，canonical **只有** `moonshot-ai/kimi-k2.6` 改动：

- `pricing.batch_cached_input`：0.096 → 0.10。
- `price:moonshot-ai/kimi-k2.6:batch:short:current` 的 cached_input charge amount：`"0.096"` → `"0.10"`；V2/CSV/HF 按既有 decimal 规范化为 `"0.1"`，数值一致。
- Batch `billing_note` 与模型 `notes` 说明公布价优先、60% 推导差异、精度未知及原始数据纠错性质。
- 模型 `accessed_at`、`last_verified_at` 与实际核验 Standard/Batch 两条记录的 checked_at/verified_at：`2026-10-09T08:59:30Z`。
- 来源 registry 仅实际读取的 batch 与 chat-k26 价格来源刷新。模型访问、绑定及未重新核验补充来源的时间未改；其他 Moonshot 记录不会因共享 Batch URL 被自动重新核验。

Standard 全部金额、Batch input/output、币种、单位、IDs、region policy、calculation_default 与 effective_from/until 均保持原样；不发明新价格生效时间。其余模型价格没有漂移。OCR 4.0 canonical 整条与本轮开始时逐对象完全一致；GPT-4.1 mini 历史提交 `3e75fa51bc1f7af01745345d03bc1a525e353158` 经 ancestry 检查仍被 HEAD 包含。

生成顺序：已有 V2 generator → build.py → Website projection generator（保留原 effectiveAt、使用本轮前 projection 做 existing artifact）→ sql_seed --write → 现有 HF build_export/artifact_contents/validator。V1、模型/provider 聚合、API、CSV、V2、SQL、当日 snapshot、append-only history 与本地 HF candidate 均同步。

为避免公开组件丢失说明，仅通过既有可选 billingNote 通道保留显式 `BILLING PRECISION UNCONFIRMED` 的记录；最终 Kimi Batch public components 和 HF billing_note 都保留 caveat，未给其他模型增加说明。既有 OCR 历史展示生成逻辑和测试保留。

## 4. Billing Precision Caveat

**BILLING PRECISION UNCONFIRMED。** 已保留四件独立事实：Standard cached input=0.16；官方 Batch 说明=60%；算术推导=0.096；官方直接公布表格=0.10。没有发票/账单样本验证是否使用三位小数。没有声称厂商内部采用某个舍入算法，也没有把 published rate 当作经账单验证的 settlement rate。公开字段按本轮授权采用直接公布价；这个未知精度不被写成已确认事实。

## 5. Freshness Results

最后一次完整实际执行：

```text
python scripts/validate.py --freshness-report --max-age-days 30 --check-urls
```

**exit code 0；stale 0；Primary URL failures 0；85/85 主来源检查通过，对应 41 个唯一主来源 URL。** validator 本身逐模型检查主 URL；41 是唯一 URL 数，并非跳过了重复来源模型。阈值仍 30 天；没有改 validator、跳过记录、移除基线 URL 或伪造核验时间。当前 freshness-report.md 的 Stale records 和 URL checks 均为 None。

## 6. Full Test Results

| 最终检查 | 实际结果 |
|---|---|
| Dataset/schema `python scripts/validate.py` | PASS |
| V2 validator | PASS：97 identities、94 models、257 prices、778 charges、173 sources |
| `python scripts/sql_seed.py --check` | PASS |
| schema/governance/source reconciliation/Website projection/release bundle/provenance/declarative contract/price events/Kimi/HF/Issue26 等 13 模块 | **172 tests PASS**，准确命令及完整输出见 related-tests.log |
| `python -m unittest discover -s tests` | **548 tests PASS**，116.346s，见 full-tests.log |
| 必要官方价格表摘录的 Kimi 专用回归 | **6 tests PASS**；6 项已包含在上述 548 内，摘录缩减后另行验证字段定位 |
| 精确联网 Freshness 命令 | **PASS / exit 0** |
| canonical/V1/V2/API/HF/history/CSV/SQL 范围与一致性 | PASS |
| 未提交预览资产内容/计数/hash | PASS，V1 85 与 V2 83，分别使用其各自 metadata |
| git diff --check | PASS |
| 已发布 HF 四文件 vs main 字节/hash | PASS；不等于 candidate 外部 parity PASS |
| 正式 pinned release bundle 构建 | **FAIL / exit 1**：Website and Dataset Pricing V2 projections differ，独立发布门禁 |

初次相关回归发现新旧等价价格 URL 引发 semantic source ambiguity，已用既有重定向 source identity 消除重复登记，保留门禁与所有基线 URL。后来补充 public/HF precision caveat，因此对最终代码重新完成上述完整回归，没有沿用中间版本结果。未启动生产服务，未调用 3017。

## 7. Price Event Regression

**PASS：没有虚假的 Kimi 厂商涨价事件。** 使用真实 generate_events 对本次前后的 Kimi 模型 snapshot 比较，返回空数组。data/price-change-events/events.jsonl 与本轮开始时 **逐字节完全相同**，与 HEAD 同语义；事件生成脚本未修改。

审计结果：现有价格事件范围比较 standard input/cached/output、public pricing_components 和 temporal/lifecycle；本次纠正 Batch legacy 字段及 declarative price_records 不生成事件。这是当前生成器实际覆盖范围，不声称已实现通用的所有计费项纠错识别。原生历史保留旧 0.096，按现有 append-only 规范新增包含纠错说明的记录；日期只表达真实观察，不是假造厂商新调价公告。

## 8. Git Diff

相对本轮开始时：只改变 Kimi canonical 的 pricing、price_records、notes、accessed_at、last_verified_at；其余 84 条 canonical 完全不变。相对 HEAD 80c2ec4：保留已有 OCR 4.0 修改，加上本轮 Kimi published-rate 纠错、说明传递及对应生成物/回归。

新增 Kimi 回归文件 6 tests；三个既有 Issue26/Moonshot 测试文件只纠正与新事实冲突的旧断言，仍检查 Standard、其他模型、生命周期与访问边界。生成器在既有 OCR 修改上仅增加精度 caveat 的 public 传递；validator/schema/workflow/event generator 未改。具体全部文件见 files-changed.txt；scope-check.json 保存前后范围证明。

HEAD 保持 80c2ec4，staged diff 空。旧 OCR 报告目录及其证据未覆盖，历史文件旧前缀保留。Website tracked diff 空；已有无关 untracked 文件保留。没有 git add、commit、push、PR、部署或手工关闭 Issue。

## 9. Release Readiness

**NOT READY TO RELEASE；EXPECTED PRE-PUBLICATION DRIFT。** 本地 Freshness 已 PASS，但本地 dirty worktree 未形成可发布不可变 revision，Website/HF 尚未同步。

本轮只读实际核实：远程 main 与 candidate 都为 4d4f32d...；Website HEAD 855eaa2e...；公开 HF prices.json/prices.csv/train.csv/meta.json 四文件与该 main 完全相同，但不同于本地 candidate。金额/计费条件差异为 Gemini 3.8 Flash、OCR 4.0、Kimi K2.6、Grok 4.6、Grok Imagine Image Quality；AWS DetectDocumentText/Astra 是证据元数据差异。没有回滚新价格来制造 parity，也没有声称外部 PARITY PASS。

正式 bundle builder 读取 pinned committed Git blobs，并要求 Dataset/Website projections 一致，本次实际拒绝构建。保留这条发布门禁，不伪造 release-manifest。已在 `dist/release-candidate/issue26-kimi-published-rate/unpublished-assets/` 同步 6 个 projection-qualified 本地预览资产，按各自 projection_stats 校验，并生成 worktree-provenance.json/WORKTREE-SHA256SUMS.txt；明确状态 **UNCOMMITTED_WORKTREE_PREVIEW**、release_eligible=false、not_a_formal_release_bundle=true。

API source_commit_sha 80c2ec4 是 build 的 HEAD/base；不表示未提交的 OCR/Kimi 事实已经包含在这个不可变 SHA 中。worktree provenance 另存 canonical/projection 的实际 hash。正式 release provenance、clean HEAD 与 origin/main、同版本 Website/HF parity 仍待后续授权发布流程。

## 10. Issue #26 Closure Readiness

**本地 Freshness 验收已满足；正式 Issue 关闭尚未就绪。** stale/主来源/exit 与本地回归已达到本轮目标，结算精度未知作为单独 caveat，不把它伪装成确认。正式发布及同版本外部 parity 门禁尚未完成。Issue 本轮只读检查为 OPEN。

已停止：没有暂存、提交、推送、PR、部署或关闭 Issue。上轮的补充 Astra 公告反爬警告不被扩大为本轮 Freshness FAIL；没有为本轮目标重新开展其他模型人工研究。
