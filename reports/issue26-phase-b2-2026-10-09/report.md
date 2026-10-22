# Issue #26 — Phase B2 Website Lifecycle & Access Regression Repair

## 1. Final Verdict

**原始两项回归修复 PASS；总体 BLOCKED。READY FOR CONTROLLED COMMITS = NO。**

生命周期与 access enforcement 指定回归、activation blockers、access policy、Model Switch、Saved Workload、同步/组件 parity、TypeScript 和 build 均通过。本轮实际 `npm test` 失败，继续独立执行被中断的后续全部顶层脚本并检查嵌套子测试，另定位 4 个旧断言契约阻断（5 个失败脚本入口，Phase4H 是包装器）。没有通过 skip/todo/删测试/弱化真实安全事实制造全套 PASS。

**LOCAL FRESHNESS VERIFIED / LOCAL PARITY VERIFIED 保持。PRODUCTION PARITY 未验证或声明。** 新阻断来自全量旧契约测试，不是 Freshness 或本地 HF parity 失败。

## 2. Repository Baseline

按附件先切换 Website，完整读取 Phase B1 报告及两条完整 stack trace。两仓库初始 status/branch/HEAD/origin/main/unstaged/staged 已重新记录并备份全部 tracked/non-ignored untracked 文件，见 initial-state JSON；完整 hash manifest 在 ignored `dist/release-candidate/issue26-phase-b2/initial-state.json`。

Website：`codex/issue26-website-candidate`；HEAD `855eaa2e8ab39ea4b3f0ca28dbc41413be988d38`，origin/main `25d265f2a595e1d5bdefed6746f54d539c9f3abf`；初始三项 B1 数据修改、staged 空，既有特殊字符 untracked 文件保留。

Dataset：`codex/issue26-dataset-candidate`；HEAD `80c2ec4991bcaaf795fe9192946f5ec770d57f48`，origin/main `4d4f32d971dc1d79bffc7ffd12a71049fbd701f6`；初始47项 tracked修改及此前报告/测试 untracked，staged 空。最终两个 HEAD 和 staged 状态不变。

本轮没有重查/更改官方事实。Dataset 所有初始文件逐字节保留；OCR retired/history、Kimi published0.10/caveat、GPT4.1 mini 历史提交与 B1 同步数据完整保留。

## 3. Lifecycle Root Cause

重新复现原测试 `scripts/test-model-lifecycle-policy.mjs:55`：AssertionError `migration source billing catalog retains deprecated records`，Actual=false、Expected=true；Node v24.16.0 / Windows PowerShell。

该断言要求生产 Catalog 至少存在一个 deprecated/safe，混淆“策略允许合格 deprecated 作为 existing source”与“当前生产样本一定有合格价格”。HEAD 数据唯一该组合是 gpt-5.3-codex；WORKTREE 当前 deprecated catalog：gpt-4.1-nano mode_unsupported，gpt-5.3-codex 和 gpt-5.4-nano billing_semantics_unresolved；无 deprecated/safe。

修复保留原42项任意ID fixture与mutation断言，新增明确 public/approved 的 active/deprecated/retired fixture，以及独立 access/binding matrix：Active可Current Target；Deprecated仅Existing Source；Retired不可实时Source/Target；FACT_HISTORICAL均允许。Access Enforcement ON 仍同时要求 public或existing_users_only适用范围及approved binding。

真实事实保留检查覆盖全部 deprecated/retired authoritative row，未修改原始记录；publicExposure=public 的身份在实际 public adapter保留；隐含alias/hidden事实保留于完整投影，非token/无可比scalar不强制进入token价格表。实际API列表无deprecated/retired，catalog中的retired不可safe。未发现需修改生产策略的运行时错误。

## 4. Access Enforcement Root Cause

重新复现原 `scripts/test-access-policy-enforcement.mjs:55:81`：Actual58、Expected59。固定身份数量是过时的数据样本假设。

改为实际 union.identityCount，三个surface逐身份比较 `policy.accessPolicyDecision` 与 `shadow.evaluateAccessShadow` 的eligible/reason，并核对surface及allowsAccessSelector。当前 **58 identities ×3=174 decisions，0 mismatches**，遍历计数也独立断言为identityCount×3。

保留不可变旧基线 `855eaa2...`：历史union仍断言59；在隔离只读子进程用git show注入旧JSON与WORKTREE真实JSON，比较精确IDs。没有把59机械改成58。集合中identity未从projection删除，没有access/binding变化，没有同步遗漏。

通过第一阻断后发现同一脚本的后续“Google从target/Retry完全消失、provider=5”假设也过时：现有 verified Gemini3.8 Flash已具结构化价格并合格。修复仍阻断existing_users_only Gemini2.5 Pro目标/Retry；独立合格Gemini3.8允许，集合及provider数由真实shadow决策验证，安全规则不降级。

## 5. Exact Missing/Removed Identity

固定历史HEAD → Phase B1 WORKTREE（Access OFF，明确记录生产集合与ON策略区别）：

| 集合 | Before | After | Removed IDs | Added IDs |
| api | 58 | 58 | None | None |
| homepage | 56 | 55 | gemini-3.8-flash | None |
| source | 30 | 31 | gpt-5.3-codex | gemini-3.8-flash, grok-4.6 |
| target | 29 | 31 | None | gemini-3.8-flash, grok-4.6 |
| shadow | 59 | 58 | gpt-5.3-codex | None |

移出union的是 **gpt-5.3-codex**。模型仍在完整Dataset/Website投影：lifecycleStatus=deprecated、status=legacy、verificationStatus=verified、accessStatus=public、bindingStatus=approved、identityType=canonical_model，以上字段及priceRecords/pricingComponents均与旧基线相等。

变化是 defaultSafe true→false、input/cached/output scalar→null、selectedPriceRecordId原standard→null；catalog safe→billing_semantics_unresolved，实际strict record返回 NOT_V2_PRICING（public adapter将无当前scalar的existing legacy行保留为legacy_fallback）。因此它仅退出计算候选，不从事实数据删除；访问和绑定不变。属于合法候选/计费安全阻断（B/C），不是A/E/F。

Gemini3.8/Grok4.6因当前候选明确tier/region structured contract进入Switch safe source/target；它们此前已在API/union，因此不扩大union。测试检查strictStandardRecords非空。Gemini3.8退出简化Homepage候选，与不能假装复杂价格是单一scalar的原有规则一致；不会用它替代移出的gpt53身份。

## 6. Files Changed

本轮仅修改 Website：

- scripts/test-model-lifecycle-policy.mjs
- scripts/test-access-policy-enforcement.mjs
- 新增最小只读测试辅助 scripts/test-access-candidate-baseline.mjs

未修改生产业务、同步工具、package.json、flag、Dataset canonical/pricing、官方来源、Website三项同步数据、事件、access/binding、SEO或Calculator URL。B1数据和全部无关/untracked初始文件hash保留，git diff --check PASS。新增本Dataset报告目录/ignored审计文件仅用于证据。

## 7. Regression Test Results

四项先执行独立脚本均PASS；后续所有本轮指定专项 npm入口均PASS。重复direct/npm/subprocess不重复计数。

按顶层npm pretest/test及专项入口、已独立执行嵌套失败去重：**54个独立脚本入口，49PASS、5FAIL**；这是入口数量，不冒充assertion/test case总数。其中npm pretest+test有48个唯一入口，后续被首次失败中断的顶层脚本全部补跑。5失败入口对应4断言契约：Phase4H本身因legacy fallback子测试失败，不能双算成不同根因。详见test-inventory.json、npm-tail-tests.json及nested-failures.json。

Original修复后的enforcement为20 contracts/58identity/174decision；lifecycle保留42旧fixture assertions并新增99个lifecycle/access fixture assertions及真实事实检查；access policy36mutation assertions，activation blocker21contracts。以上不可相加为全套独立test数量。

## 8. Access OFF/ON Safety Results

OFF missing/empty/false/0/off/invalid解析和explicit false语义一致，实际adapter/homepage与HEAD生产实现语义一致。ON完整矩阵保留public/existing_users_only/restricted/invite_only/unknown、approved/unresolved、active/deprecated/retired/unknown，实际selector集合与shadow逐ID一致；Target与Existing Source分别检查。OFF→ON→OFF精确恢复原集合与defaults，public JSON/CSV不因flag变化。测试仅修改隔离进程模块配置并finally恢复；没有修改生产 ACCESS_POLICY flag或env文件。

## 9. Saved Workload Safety

既有Saved脚本PASS：原始ID、历史snapshot、invalid/unknown/legacy原记录保留；Open/Reopen不写入；无自动替代；retired/unavailable历史摘要保留。current/alternative分别进行权限检查；invalid primary及unused historical fallback也被Retry拒绝；显式合格替代且Save才写一次。activation blockers真实组件路径与webpack OFF/ON/OFF证明通过；未启动服务/真实生产HTML验证。

## 10. Dataset Freshness Results

本轮实际 `python scripts/validate.py` PASS；完整 `python scripts/validate.py --freshness-report --max-age-days 30 --check-urls` **exit0、stale0、85/85主来源通过、0URLfailures**。阈值30天未改，全部85逐条检查（41个唯一URL）；freshness-report.md两项None。未伪造核验时间/移除URL，初始Dataset文件与最终hash一致。

## 11. Website/Dataset/HF Local Parity

实际sync check（显式Dataset路径）PASS；test:pricing-sync PASS；组件逐身份/条件/access/binding与HF JSON/CSV/train对齐 **83records、763components、80cache_write、0mismatches**。

`python scripts/export_huggingface.py --website-repo D:/ai-cost-control-tool/aicostguard-english --website-ref WORKTREE --check` PASS，83records。本轮Website三个已同步价格文件逐字节保持B1结果，本地parity未损坏。外部生产HF本轮未发布/验证，仍区分 EXPECTED PRE-PUBLICATION DRIFT。

## 12. Build / TypeScript / npm test Results

| 命令类别 | 结果 |
|---|---|
| lifecycle/access enforcement/activation/access四独立脚本 | PASS |
| npm test:model-lifecycle-policy / test:access-enforcement / test:access-policy | PASS |
| npm test:model-switch / test:pricing-sync / test:dataset-pricing-components | PASS |
| npm pricing:sync:check（显式路径） | PASS |
| Saved Workload独立脚本 | PASS |
| npx tsc --noEmit | PASS |
| npm build | PASS，静态构建，无生产server/3017 |
| npm test | **FAIL**，首次Phase4F；后续独立脚本检查见下面 |
| Dataset validate/freshness/local HF WORKTREE | PASS |
| 两仓库git diff --check | PASS |

新增完整套件阻断：

1. **Phase4F scripts/test-pricing-phase4f.mjs:236**：decimal fixture固定gpt-5.4-nano为exact_parity，V1单请求0.010955250000000001，V2安全ID解析转向默认模型结果0.039809250000000004。B1候选中的gpt54nano已deprecated/defaultSafefalse/scalarsnull；不能强行作safefixture。
2. **Phase4G scripts/test-pricing-phase4g.mjs:361 / scenario82**：要求gpt54nano在V2-safe active source，实际不存在，Actualfalse/Expectedtrue；同一旧deprecatedfixture假设。
3. **Phase4H包装器:176 → scripts/test-legacy-fallback-eligibility.mjs:56**：冻结baseline并限定只有GPT4.1家族可退出unsafe集合，当前gpt53/gpt54等deprecated候选变化超出该旧专项场景，失败 `getPromptCostOptimizerModels: unrelated unsafe-model scope expansion`。
4. **Phase4H后续另独立执行 scripts/test-gpt41-mini-lifecycle-consumer.mjs:47**：断言整份candidate相对其冻结baseline只能改变mini lifecycle，不能接受B1同步的其他已授权事实/metadata变化；失败 `only mini lifecycle can change; all prices, IDs, metadata, other records and order preserved`。

四个具体失败脚本及Phase4H包装器与B2初始备份逐字节相同，数据输入也逐字节相同；这些不由本轮两项测试修改引入，但本轮完整门禁确实FAIL，不能用“旧失败”声称PASS。完整原始mini diff输出较大，保存在ignored `dist/release-candidate/issue26-phase-b2/test-gpt41-mini-lifecycle-consumer.mjs.log`，其他完整输出在本报告目录及审计目录。

依附件“禁止不相关测试与组件”的范围，本轮不修改这些旧专项测试或为了它们改真实数据。后续应为这些冻结场景建立隔离fixture/当前安全选择契约，需新范围授权；未通过注释/skip降级。

## 13. Release Bundle Preconditions

本轮没有构建/虚报正式bundlePASS。必须两个仓库已授权的最终40字节GitSHA、准确snapshot `data/snapshots/2026-10-09/`、不可变数据/metadata provenance与同版本parity。当前Dataset HEAD80c2与Website HEAD855e都不能代表dirty修复已在提交中。正式bundle参数必须使用最终真实SHA，不能旧HEAD/WORKTREE；正式publish与生产parity是后续门禁。

## 14. Remaining Blockers

原两项回归已修复；剩余全量npm旧专项契约4个失败（5脚本入口）。总体不能达到“没有其他测试失败”。两个仓库最终immutable提交/provenance与正式bundle仍待后续；生产Website/Pages/HF未发布。Kimi账单精度未知caveat不被伪装成已确认，也不扩大为本地Freshness失败。

保留可审查修复，没有reset/clean/restore/checkout覆盖、git add/commit/push、PR/tag/部署/HF Publish/关闭Issue。完成本轮允许范围后停止。

## 15. READY FOR CONTROLLED COMMITS = NO

**BLOCKED**。本地Freshness/parity及本轮安全修复PASS，但npm test仍有上述完整失败。只有这些门禁另行修复并全部通过后，才可转为YES。
