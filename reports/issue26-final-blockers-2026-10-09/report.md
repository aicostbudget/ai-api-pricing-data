# Issue #26 — Final Blocker Resolution

核验日期：2026-10-09 UTC。首先完整读取上轮 `reports/issue26-phase-a-2026-10-09/report.md`，随后重新检查实际工作区、官方来源、生成物、公开 HF 与 Website 消费者。

基线 HEAD：`80c2ec4991bcaaf795fe9192946f5ec770d57f48`；历史 GPT-4.1 mini 生命周期修复：`3e75fa51bc1f7af01745345d03bc1a525e353158`，已在本地基线中。本轮没有重新提交。两次实际远程引用检查：main 与 candidate 仍为 `4d4f32d971dc1d79bffc7ffd12a71049fbd701f6`，没有假设远程已包含本地修复。

## 1. Freshness Verdict

**BLOCKED：stale = 1；Primary URL failures = 0；Freshness exit code = 1。**

85 条 canonical 模型重新核算，stale 从 2 降为 1，仅 `moonshot-ai/kimi-k2.6` 剩余；其最后核验日期仍为 `2026-09-08T03:04:30Z`，当前报告 age 31 days。全部 85 条主来源对应 41 个唯一 URL，经实际联网检查，没有主来源 URL 失败。

实际完整执行：

```text
python scripts/validate.py --freshness-report --max-age-days 30 --check-urls
```

退出 1 的原因是 Kimi stale；补充公告 403 与外部 projection 差异不计入这次 Freshness 的失败原因。原始命令结果见 `freshness.log`，当前 stale 清单见 `freshness-report.md`。

## 2. OCR 4.0 Resolution

**PASS：完成现有 canonical 所声明的历史 Standard Basic OCR 计费范围；不宣称验证了所有可选服务或实际 API 可用性。**

重新检查 [Pricing](https://docs.mistral.ai/inference/pricing)、[OCR 4.0 模型页](https://docs.mistral.ai/models/ocr-4-0)、[Changelog](https://docs.mistral.ai/resources/changelogs)。本次直接下载的当前英文价格页显示 OCR 4.1：标准 $4/1000 pages、cached input $0.40/1000 pages。搜索缓存或旧页面可能仍显示 OCR 4.0，不能把旧缓存当作当前 DOM。

OCR 4.0 页面加载的官方原生模型目录 bundle 则明确保留 `mistral-ocr-4-0`：release 2026-06-23、status Deprecated、标准 $4/1000 Pages、Annotated Pages $5/1000 Annotated Pages，metadata 的 deprecation_date 2026-09-29、retirement_date 2026-09-30、replacement OCR 4.1。来源：

[官方目录 bundle](https://docs.mistral.ai/_next/static/chunks/2894-55d10a7699b0ed26.js?dpl=dpl_CvrtyjMnMmsSXH8BWZNzFedusSRV)

SHA256：`705757de71aee99b21eb00b7ba826543cf9ffac116cc62b7ad273e3e9f70511e`。原始内容与提取记录保存在本报告 `evidence.json` 指定的本地证据目录。Changelog 独立支持 9 月 29 日 deprecated、计划 9 月 30 日 retirement、OCR 4.1 successor/same price。

| 核验项目 | 结论及处理 |
|---|---|
| Standard OCR | 原生 OCR 4.0 官方目录明确 $4/1000 pages；唯一已声明 component 的金额、单位、维度不变 |
| Structured annotations | 官方原生历史目录单列 $5/1000 Annotated Pages；它是独立项目，不是标准 OCR 的附加 $5，也未被添加为当前 canonical component |
| Batch | 功能支持不等于数值价目；未找到足够的 OCR 4.0 独立 Batch 数值计费证据，不添加 component |
| Cached input | 当前 OCR 4.1 $0.40 不移植到 OCR 4.0；本次 OCR 4.0 原生目录未建立该项目 |
| Historical price | Standard component 由 current 改为 historical，effective_from 2026-06-23 保留，effective_until 2026-09-29，遵循现有日期粒度的 inclusive 区间规范 |
| Current API availability | 未执行带凭证真实推理；计划退役日期经过不证明实际 API 返回 404 |

生命周期按现有有日期官方证据标准规范化为 `retired`；新增上述 lifecycle 日期与 successor 字段，不新增自动重定向、aliases 或 approved access。说明保留“官方 Deprecated 标签/计划 retirement”与“真实服务状态未测试”的区别；区间终点不是实际计费系统秒级停服测量。

`accessed_at`、`last_verified_at` 刷新为 `2026-10-09T08:08:15Z`。现有 sole component `ocr_pages` 保持 amount 4、document_page、document、per_1000_pages、standard、calculation_default=false。历史 price_record 为 `price:mistral-ai/mistral-ocr-4-0:standard:short:historical:ocr_pages`，只用于原生 identity 的历史展示；当前安全价格选择拒绝该过期记录。原价及旧区间在基线和 append-only history 中保留。

现有 Basic OCR-only 声明已完整核验。OCR 4.0 cached/Batch 独立数值、可选 annotations 接入与实际 API 访问并未伪装成已验证 component，不能由本次 freshness 结论推出。

## 3. Kimi K2.6 Resolution

**BLOCKED：Batch cached input 的展示值与折扣说明无法确定实际结算口径，整条 canonical 保持不变，不刷新日期。**

实际检查 [主页](https://platform.kimi.ai/)、[Standard pricing](https://platform.kimi.ai/docs/pricing/chat)、[Batch pricing](https://platform.kimi.ai/docs/pricing/batch)，以及官方 [chat Markdown](https://platform.kimi.ai/docs/pricing/chat.md) 和 [batch Markdown](https://platform.kimi.ai/docs/pricing/batch.md)。

计价单位为 **USD per 1M tokens**。Standard input 0.95、cached input 0.16、output 4.00；Batch input 0.57、output 2.40。官方 Batch 表格明确显示 cached input **0.10**，同页又说明 Batch 为标准价格的 60%，计算为 `0.16 × 0.60 = 0.096`。

HTML 的编译 MDX、官方 Markdown DocTable 和实际浏览器 DOM 都有 authored literal 0.10。相同表格 K2.7 的缓存价显示 0.114，因此没有证据表明这是统一两位小数的浏览器 formatter。仍无法证明 authored 0.10 是独立结算价，或 0.096 的手工展示舍入；没有找到官方精度/舍入/该项折扣例外规则。

进一步读取 models、models-overview、quickstart、contextcache、limits、Batch 使用说明、account-and-payments、modeluse、llms.txt 等公开文档；没有发现解冲突规则。按官方 quickstart host 尝试公开 `https://api.moonshot.ai/v1/models`，TLS UNEXPECTED_EOF，不能声称取得可用的计费 API 元数据。没有使用凭证或付费请求。

实际 DOM 证据由独立无登录 headless Edge/Playwright 获取三个官方页面；CUA 初始化因 sandbox setup refresh kernel 失败，改用此可复核方式。没有启动本地生产服务，没有调用 3017。`kimi-dom.json` 的表格与路径已保存在 `evidence.json`。

canonical Batch cached input 原有 0.096 不被数学推断重新认证，也不被无精度规则的展示 0.10 替换。5 个其他组件吻合不等于整条模型可以刷新。确切剩余事实：官方明确说明 Batch cached input 实际结算金额/精度以及 60% 规则是否适用于该项。

## 4. Supplemental URL Verdict

**WARNING_NONCRITICAL：403 为补充公告反爬拦截观察，不是主来源失效，不导致整个 Freshness Check 失败。**

URL：[GPT-6 Astra announcement](https://openai.com/index/gpt-6-astra/)，对应 `openai/gpt-6-astra`，用于补充发布/产品公告背景。实际 HTTP 403，`Server: cloudflare`、`Cf-Mitigated: challenge`，没有 Location 迁移证据；不能判断为永久失效或历史公告迁移。

关键 model/pricing/changelog 官方来源本次均 200。发布事实已有 canonical release_evidence 指向官方 changelog，9 月 3 日发布可由该主证据支持，不依赖此公告。保留公告 URL 与原 registry verifiedAt `2026-09-04T17:34:11Z`，未伪造页面正文或刷新成功时间。

## 5. Website/HF Parity Verdict

**EXPECTED PRE-PUBLICATION DRIFT；candidate 对公开 Website/HF 的 PARITY 未通过。**

Dataset authoritative 为当前 canonical；本地 V1、V2、SQL、Website projection 与 HF candidate 按现有生成规范重建并校验。Website repository HEAD `855eaa2e8ab39ea4b3f0ca28dbc41413be988d38` 只读，tracked diff 空。公开 HF 的 prices.json、prices.csv、train.csv、meta.json 四文件均逐字节/哈希等于远程 main `4d4f32d...` 发布内容，均不等于本地 unpublished candidate；具体 hash 在 `evidence.json`。

| 分类 | 本次判断 |
|---|---|
| A 真实内容冲突 | 已发布 HF 与 main 四文件没有同版本内容冲突；candidate 与 Website 存在已核验价格/条件差异，不能写成 PASS 或回滚新事实 |
| B 尚未发布 | 已用真实 remote refs 和公开 HF bytes 验证 EXPECTED PRE-PUBLICATION DRIFT |
| C 新生命周期兼容 | 现有 Website consumer 模块接受 candidate retired native OCR；public identity 保留、defaultSafe=false、过期记录拒绝，兼容测试 PASS |
| D 生成/同步错误 | 本地 canonical/generated/SQL/HF 一致性回归 PASS；当前外部差异有版本依据，不归因为生成损坏；正式版本 provenance 与同版本同步门禁仍未满足 |

candidate 对 Website 的价格/计费条件差异准确为：`google-gemini/gemini-3.8-flash`、`mistral-ai/mistral-ocr-4-0`、`xai/grok-4.6`、`xai/grok-imagine-image-quality`。Astra 为证据元数据差异，非金额/计费条件差异。remote main 对 Website 的 GPT-4.1 mini 差异只在 lifecycleStatus，符合其生命周期修复尚未发布到 Dataset main。

版本信息：candidate Dataset version 1.0.0，85 models，generated_at 2026-10-09T08:13:17Z；HF schema 1.8.0、83 public records、generated_at 同上、last_verified_at 2026-10-09T08:08:15Z。公开 HF generated_at 2026-10-08T08:54:59Z、last_verified_at 2026-10-05T02:42:02Z。两者 schema 相同不等于同一次发布。

candidate Website projection schema `website-pricing-projection-v2.phase4a`，generatedAt 2026-10-09T08:21:25Z；Website 同 schema、generatedAt 2026-10-08T08:54:59Z；effectiveAt 都保留 2026-10-05T02:47:26Z。Dataset source_commit_sha 为 build 时的 HEAD `80c2ec4...`，这是生成基线标识，不能声称本轮未提交 OCR 修改已经包含在该不可变提交中；正式发布 provenance 必须在授权的 release 流程重建。

实际 consumer 测试只在隔离 Node 进程把 candidate JSON 注入现有 Website modules，未写 Website、未启动服务。结果：retired、defaultSafe=false、strict reason PRICE_RECORD_EXPIRED、normalize pricingStatus unavailable、默认安全列表无 OCR 4.0、保留 1 条历史展示 component。不是 production HTML 验证。原始结果见 `website-consumer-compatibility.json`。

外部 HF exporter 的 Website parity gate 实际 exit 1：`Website pricing components differ from the canonical Pricing V2 projection`，保留门禁，不虚报 PASS。

## 6. Release Readiness

**NOT READY TO RELEASE。** Kimi 未完成真实计费核验，stale=1；本轮 candidate 未提交/发布，与 Website/HF 尚不满足同一正式发布版本的 parity/provenance 门禁。补充反爬 403 是独立 warning；不能把该 warning 当成主来源 Freshness 失败。没有为了 parity 回滚已核验事实。

## 7. Issue #26 Closure Readiness

**NOT READY TO CLOSE。** 实际 freshness exit 1，不满足 stale=0/exit=0 的验收标准。Issue 只读检查仍 OPEN；本轮没有触发发布 workflow，没有关闭 Issue。

## 8. Changed Files

相对 `80c2ec4`：**仅 OCR 4.0 一条 canonical 改动，其余 84 条完全不变，Kimi 整条不变，所有 V1 金额保持不变。**

- `data/canonical/models.json`：OCR 历史标准 component、dated lifecycle、官方来源与核验时间/说明。
- `scripts/generate_pricing_v2_preview.py`：historical component 保留其自身核验时间。
- `scripts/generate_website_projection_v2.py`：仅 retired native identity 显示非 default-safe 的已有历史价格，来源归类为经核验 canonical history；不把 legacy fallback 混同于此来源。
- V1/API/HF、V2/source registry/SQL/projection/report、当日 snapshot 与 append-only history：现有生成流程必要同步；其他模型的 baseRevision provenance 变更不表示重新核验其事实。
- 两个已有 tests 更新本次 OCR 事实；新增 `tests/test_issue26_final_blockers.py` 5 项范围、历史定价和 lifecycle/source 回归。
- 本报告及证据、测试日志、Freshness 报告。

全部具体路径见 `files-changed.txt`。41 个原有 tracked 文件修改，另加新测试与本报告目录。history 旧前缀逐字保留。没有修改 validator/schema/workflow 或 Website tracked 文件；Website 既有 untracked 文件保留，其时间为 2026-10-08T03:25:08Z，早于本轮。

git diff 已审查，`git diff --check` PASS；HEAD 仍 80c2ec4，staged diff 空。没有 git add、commit、push、PR、部署或关闭 Issue。

## 9. Complete Test Results

| 检查 | 实际结果 |
|---|---|
| 现有 build / V2 / projection / SQL / HF candidate 生成规范 | PASS，build 在 projection 之前运行；candidate HF 按 export 函数生成并校验，未绕过外部 parity FAIL 声称正式发布 |
| `python -m unittest discover -s tests` | PASS，542 tests，167.535s，完整日志 unittest-final.log |
| 10 个相关模块回归 | PASS，114 tests；准确命令及输出见 gates-final.json |
| `python scripts/validate.py` | PASS |
| `python scripts/validate_pricing_v2_preview.py` | PASS，97 identities / 94 models / 257 prices / 778 charges / 173 sources |
| `python scripts/sql_seed.py --check` | PASS |
| 完整 freshness 命令及联网主来源检查 | exit 1：stale 1；85 主来源、41 unique URLs、0 failures |
| canonical 与生成物、history prefix、范围回归 | PASS，仅 OCR canonical 改变，Kimi 不变 |
| Website 现有 consumer 的 candidate 生命周期兼容 | PASS，读数据注入测试；未进行生产 HTML 验证 |
| 外部 Website parity exporter --check | FAIL，exit 1，预期未发布版本差异 |
| live HF vs published main 四文件哈希 | PASS；不等于 candidate parity PASS |
| git diff --check | PASS |

上轮 537/132 不是本轮测试数。本轮完整回归实际为 542，所选相关回归实际为 114，不沿用旧报告结果。曾出现一次历史 source governance 分类回归失败，随后修正 generator 的 source classification，保留既有 governance 测试约束，最终完整 542 和相关 114 均重跑通过。

## 10. Remaining Blockers

1. **Freshness 唯一剩余阻断：** Kimi K2.6 Batch cached input 0.10 vs 0.096。缺的是官方实际计费/精度/折扣例外证据；未得到前不改金额、不刷新日期。
2. **正式发布门禁：** candidate 尚未形成已发布的同一不可变版本；Website/HF 同版本 parity 与 provenance 需后续经授权发布流程满足。本轮按指令停止，不进行提交、推送或发布。
3. **独立 warning/未声明能力：** Astra announcement 反爬 403；OCR 4.0 authenticated API 可用性、独立 cached/Batch 数值未建立。不把这些未声明的内容伪造为已核验，也不冒充本次主来源失败。

已经实际解决可安全处理的 OCR 4.0 阻断；保留 Kimi 的确切证据冲突。全部原始下载、DOM、生成日志与脚本保存在 `D:/ai-api-pricing-data/dist/release-candidate/issue26-final-blockers`（ignored），本报告目录保存稳定摘要和完整最终测试输出。
