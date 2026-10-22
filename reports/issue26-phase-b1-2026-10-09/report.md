# Issue #26 — Phase B1 / Pre-Release Parity Alignment

## 1. Final Verdict

**LOCAL PARITY VERIFIED：Website/Dataset 当前工作树 V2 全对象、V1 编辑合并、metadata 与本地 HF export 对齐。**

**READY FOR CONTROLLED COMMITS：NO。** 必须运行的 Website lifecycle 回归失败，附加 access enforcement 回归也失败。不能把状态表述为“所有工作树检查通过、只缺提交”。没有为门禁回滚价格、放宽安全规则或修改范围外测试。

**PRODUCTION PARITY VERIFIED：未验证/不声明。** 本轮是本地准备；不能把 WORKTREE PASS 等同已发布版本。生产 HF 与候选版本的差异仍按未发布版本的 EXPECTED PRE-PUBLICATION DRIFT 处理，不计入本地 parity 失败。

首先完整读取 `reports/issue26-kimi-published-rate-2026-10-09/report.md`。没有重新核验或修改 OCR/Kimi 官方价格。原始备份、完整初始清单与 hash 在 `dist/release-candidate/issue26-phase-b1/`，本报告保存必要摘要和完整测试结果。

## 2. Dataset Initial/Final State

初始/最终分支 `codex/issue26-dataset-candidate`；HEAD `80c2ec4991bcaaf795fe9192946f5ec770d57f48`；本地 origin/main `4d4f32d971dc1d79bffc7ffd12a71049fbd701f6`。初始有 47 个 tracked 修改，另有两轮报告目录和两个新 Issue26 回归文件；staged 空。逐文件备份并在同步后比较，所有初始 Dataset 文件逐字节保留；本轮只新增 Phase B1 报告/审计文件，Freshness 报告由真实命令生成。

OCR canonical retired、标准 $4/1000 pages historical、2026-06-23 至 2026-09-29、非默认；Kimi Batch cached input=0.10、Standard cached=0.16、precision caveat 保留；GPT-4.1 mini 生命周期 active、defaultSafe=false。没有改动其他模型事实、金额、日期或来源。

## 3. Website Initial/Final State

初始/最终分支 `codex/issue26-website-candidate`；HEAD `855eaa2e8ab39ea4b3f0ca28dbc41413be988d38`；本地 origin/main `25d265f2a595e1d5bdefed6746f54d539c9f3abf`。初始 tracked/staged 均空，只有一个既有无关 untracked 文件 `t-control-toolaicostguard-english` 后附特殊字符，该文件完整保留且不列入拟提交集合。最终仅 3 个批准价格文件 unstaged；staged 仍空，HEAD 未变。

AGENTS.md 的 Next.js 规则已读；没有编写 Next.js 业务代码。build 只做构建，没有启动生产服务或调用 3017。

## 4. Exact Files Changed

只通过现有 `scripts/sync-pricing-artifacts.mjs --write --dataset D:/ai-api-pricing-data` 更新：

1. `data/pricing-v2-projection/model-pricing.v2.json`
2. `data/pricing-v2-projection/pricing-meta.v1.json`
3. `data/model-pricing.json`

第 4 个允许文件 `data/pricing-v2-projection/price-change-events.v1.json` 初始无 drift、最终未变。没有修改同步工具/package.json/业务代码/测试。全文件 hash 审计证明其余 Website 文件保留；没有清除编辑属性或新增 Calculator URL。

Dataset 精确待提交文件清单：`dataset-controlled-commit-files.txt`；Website：`website-controlled-commit-files.txt`。这些是后续评审的路径集合，不表示本轮授权或执行提交。Dataset 清单包含既有 OCR/Kimi 修改、新回归和各轮报告；Website 清单严格只有上述 3 文件。

## 5. Website/Dataset V1/V2 Parity

初始只读 check exit=1，准确 drift 分类为 projection-contract、freshness-metadata、legacy-editorial；没有事件 drift。同步工具验证与 editorial ID contract 接受数据，write 后显式 check exit=0。工具默认 `../../ai-api-pricing-data` 从 Website 工作目录精确解析到 `D:/ai-api-pricing-data`；仍显式传 --dataset，防止误读旧数据。

V2 当前 projection 与 Dataset generated projection **完整 JSON 对象相等**；pricing-meta 与 API meta 完整相等。V1 合并逐 ID、逐字段检查：只修改同步工具允许的 fact/provenance 字段；bestFor、priceNote、lastUpdated 等 Website 编辑属性和 Calculator URL 保留。V1 不等同于 Dataset canonical 的逐字格式，采用其既有 editorial merge contract；不是仅比记录数。

Dataset canonical/V1/V2/API/CSV、SQL 与 public projection 一致性由 validate、V2 validator、SQL check 及全量回归核实。Dataset 本轮事实文件没有变更；Website 所有价格/组件变动均精确来自当前候选 source，不能误读为本轮擅自调价。

## 6. Local HF Export Parity

实际执行：

```text
python scripts/export_huggingface.py --website-repo D:/ai-cost-control-tool/aicostguard-english --website-ref WORKTREE --check
```

**PASS / exit 0：83 records。** Website 实际 public export 与 HF JSON/CSV/train 逐模型/组件/条件/access/binding 检查 PASS：83 records、763 components、80 cache_write、0 mismatches。未使用 HEAD 旧投影代替 WORKTREE，没有将生产 HF 未同步误判为本地失败。没有发布 HF。

## 7. Lifecycle / Saved Workload Safety

Model Switch runtime、Saved Workload、access policy、activation blockers 既有测试通过。Saved 历史记录原始保存、无隐式重写、缺失/退役历史摘要、明确替换和无写回规则通过；OCR retired 不成为安全计费来源/默认目标；API calculator 实际列表全为 active。GPT-4.1 mini identity 保留且不因 active 自动 defaultSafe。

**失败 1：** `npm.cmd run test:model-lifecycle-policy` 在 `scripts/test-model-lifecycle-policy.mjs:55` 的真实数据断言失败：要求至少存在 deprecated && availability=safe 的迁移来源。

只读隔离进程注入同步前 JSON，对照该测试 PASS。同步前唯一 deprecated/safe identity 是 `gpt-5.3-codex`。同步后该 identity lifecycle 仍 deprecated，但 Dataset authoritative projection 的 defaultSafe=false、input/output/cached scalar=null、selectedPriceRecordId=null，blockedFromDefaultReasons 包含 deprecated_identity；其现有 components 没有被篡改。消费者将 availability 安全分类为 billing_semantics_unresolved。目前其他 deprecated identities 是 mode_unsupported 或 billing_semantics_unresolved，故不存在 deprecated/safe 行。42 个任意 ID fixture 断言先通过，失败来自“真实候选数据必须至少有一个 safe deprecated”的存在性要求。

**失败 2：** `scripts/test-access-policy-enforcement.mjs:55` 硬编码 union.size=59（177 decisions）；当前为58。同步前数据隔离注入 PASS，同步后减少的现有可计费来源与上述 gpt-5.3-codex 阻断一致。不能用伪造第59个身份通过。

这两项不能标为 PASS；本轮修改限制只允许同步四个数据文件，因此未修改测试或业务规则。后续需要独立授权/评审判断迁移来源的所需语义，并使回归契约与真实候选一致，避免弱化 deprecated/retired/access/binding 的安全边界。

## 8. Price Event Regression

Dataset events.jsonl 与本轮开始时逐字节相同；Website price-change-events.v1.json 与初始逐字节相同，sync 不产生 drift。Kimi 原始 published-rate 纠错说明保留，全量 unittest 中 Kimi price event 回归 PASS，未生成虚假官方涨价事件。

## 9. Full Test Results

| 检查 | 实际结果 |
|---|---|
| Website npm pricing:sync:check（显式 Dataset） | PASS |
| Website npm test:pricing-sync | PASS |
| Website npm test:dataset-pricing-components（显式本地 HF 目录） | PASS：83 records / 763 components / 0 mismatches |
| Website npm test:model-lifecycle-policy | **FAIL**：deprecated safe 存在性断言 |
| Website npm test:pricing-version | PASS |
| Website npm test:model-switch | PASS |
| Website npx tsc --noEmit | PASS |
| Website npm build | PASS（静态 build，非服务器启动） |
| Saved Workload 专用脚本 | PASS |
| model access policy 脚本 | PASS |
| access policy enforcement 脚本 | **FAIL**：58 != 59 |
| access activation blockers 脚本 | PASS |
| Dataset validate.py | PASS |
| Dataset V2 validator | PASS：97 identities / 94 models / 257 prices / 778 charges / 173 sources |
| Dataset SQL --check | PASS |
| Dataset WORKTREE HF --check | PASS |
| Dataset unittest discover | PASS：548 tests，128.540s |
| 精确 Freshness 联网命令 | PASS：stale0 / 85主来源 / 0失败 / exit0 |
| 两仓库 git diff --check | PASS |

完整命令、exit 与原始输出见 website-tests.json/dataset-tests.json/safety-tests.json 和对应日志。Website runner 最后打印构建输出时遇到控制台 GBK 不能显示 `ƒ` 的编码错误；build 子进程实际 exit0，完整输出和 exit 已在错误前写入日志/JSON，不能把打印错误误判成 build 失败。

本轮完整实际执行 `python scripts/validate.py --freshness-report --max-age-days 30 --check-urls`：**exit0、stale0、85/85 主来源通过、0 URL failures**。30 天阈值未改，全部记录均检查；对应41个唯一URL。当前 freshness-report.md 两项均为 None。详见 freshness.log，未沿用上轮结果。

## 10. Release Bundle Preconditions

已审查 scripts/build_release_bundle.py：两个 ref 解析成真实 commit SHA，用 git show 读取 committed blobs；必须精确 snapshot、V1 API/snapshot 字节一致、Dataset/Website V2 components/allowances 一致、Website export/HF mirror 字节一致。因此当前 uncommitted OCR/Kimi 和 Website 同步修改不能用旧 HEAD 生成假候选。

本轮没有生成/宣称正式 bundle PASS。精确 snapshot：`data/snapshots/2026-10-09/`（prices.json/prices.csv）。预期正式资产为 github-pages-v1-prices.json/csv/meta.json、pricing-v2-prices.json/csv/meta.json、release-manifest.json、SHA256SUMS.txt。

只有修复/审查剩余回归且两个仓库形成授权的不可变提交、必要源 SHA provenance 重建并通过同版本检查后，才可使用：

```powershell
python scripts/build_release_bundle.py --snapshot 2026-10-09 --dataset-ref <FINAL_DATASET_40_CHAR_SHA> --website-repo D:/ai-cost-control-tool/aicostguard-english --website-ref <FINAL_WEBSITE_40_CHAR_SHA> --output dist/release-candidate/issue26-phase-b1-pinned
```

参数中的 SHA 必须是包含最终数据和生成物的真实已提交版本，不能替换成当前旧 HEAD，也不能写 WORKTREE。output 应为新的不存在目录。API metadata 的现有 source_commit_sha 是 base80c2，不表示 dirty事实已经在该不可变 SHA；正式 provenance 仍须按仓库规范验证。

## 11. Remaining Blockers

- Website lifecycle 存在性断言与当前候选迁移来源状态不一致，必需测试 FAIL。
- access enforcement 固定身份数量断言与当前实际数据不一致，附加安全回归 FAIL。
- 两仓库最终不可变提交/provenance 尚未形成；正式 pinned bundle 未构建/验证。
- 生产 Website/Pages/HF 未发布或本轮验证；不得声称 PRODUCTION PARITY VERIFIED。
- Kimi BILLING PRECISION UNCONFIRMED caveat 保留，不扩大为本地 published-rate freshness 阻断。

没有 reset、clean、checkout 覆盖、暂存、commit、push、PR、tag、部署、HF 发布或关闭 Issue。同步结果保持可审查，未为测试失败回滚到旧事实。

## 12. READY FOR CONTROLLED COMMITS: NO

LOCAL PARITY VERIFIED 不等于所有回归 PASS；当前不是“只缺不可变提交”。后续评审应先处理上述两项精确失败，再决定 controlled commits。完成本轮授权的安全同步、校验和报告后停止。
