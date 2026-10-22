# Issue #26 — Phase B3 Final npm Test Contract Reconciliation

## 1. Final Verdict

**PASS。READY FOR CONTROLLED COMMITS = YES。** 原五个失败入口全部解决；完整 `npm.cmd test` exit0；本轮54个去重脚本入口54PASS、0FAIL。Lifecycle、Access Enforcement、Saved Workload、TypeScript/build、本地parity与实时Freshness均PASS；未修改生产消费者、数据、安全事实或flag。

这是受控提交准备结果，不是已经提交/发布。**LOCAL FRESHNESS VERIFIED / LOCAL PARITY VERIFIED**；PRODUCTION PARITY本轮未验证，不虚报正式bundlePASS或发布成功。

## 2. Dataset / Website Git Baseline

首先执行Set-Location到Website，完整读取B2、B1报告及相关源码。两仓库status/branch/HEAD/origin/main/unstaged/staged已重新核查；完整文件备份与hash在ignored `dist/release-candidate/issue26-phase-b3/before`。本报告initial/final-state JSON保留精确Git输出。

Dataset：分支codex/issue26-dataset-candidate，HEAD `80c2ec4991bcaaf795fe9192946f5ec770d57f48`，origin/main `4d4f32d971dc1d79bffc7ffd12a71049fbd701f6`；初始47tracked修改及此前报告/两个测试untracked，staged空。

Website：分支codex/issue26-website-candidate，HEAD `855eaa2e8ab39ea4b3f0ca28dbc41413be988d38`，origin/main `25d265f2a595e1d5bdefed6746f54d539c9f3abf`；初始B1三个数据文件、B2两个测试修改，B2helper和既有特殊字符文件untracked，staged空。最终HEAD与staged未变。

Dataset所有初始文件、B1三个同步数据文件、B2修复逐字节保留；既有untracked不删除、不纳入无关提交集合。

## 3. Five-Failure Reproduction Matrix

五项均在编辑前实际重跑并失败。精确assertion/Expected/Actual/stack/consumer/生命周期关联见failure-matrix.json；完整原始stdout/stack保存在ignored审计目录before-*.log。父Phase4H与同一子测试重复失败合并根因，不重复计数。

| Script / 原始File:line | Expected | Actual | 生产消费者 / 根因 |
|---|---|---|---|
| Phase4F:236 decimal price parity | 0.039809250000000004 | 0.010955250000000001 | API；deprecated gpt54nano仍被当作exact-parity fixture；新安全ID解析转向原默认 |
| Phase4G:361，caller82 | gpt54nano在V2-safe active source，true | false | Budget；同一旧safe场景假设，需另查真实消费者 |
| Phase4H:176 | child exit0 | child exit1 | 降级resolver；包装legacy范围失败 |
| legacy-fallback:56 | removedUnsafe仅GPT4.1family | false | legacy/degraded；旧单次修复HEAD被用作全量永久基线 |
| mini-consumer:47 | 复原mini lifecycle后整份projection等于HEAD | false/full diff | mini/Saved；旧单字段scope与B1已批准全量candidate混用 |

未将全部统一判作“旧测试”。Phase4F/G还发现独立预期算法漏掉已存在的defaultSafe/review veto及selected文本input/output证据，必须对照真实运行时；预算消费者另行核查，见第6/8节。

## 4. Four Contract Root Causes

1. API算术fixture/选项集合：deprecated不是Current Target；review/defaultSafe和文本modality证据门禁未被旧测试完整表达。
2. Budget场景fixture/预期集合：旧gpt54nano safe假设与当前事实冲突，且测试未验证真实getBudgetPlannerModels及URL/preset/降级路径。
3. family专项scope：本次批准的多模型事实/metadata更新不能套用“只改GPT4.1family”的旧HEAD范围；该范围保护仍必须在独立fixture里保留。
4. mini单字段scope：全量当前candidate不是旧一次mini变更的after对象；构造同一当前事实上的deprecated→active one-field fixture再验证价格/历史/IDs不变。

这四类修复都没有改价格来迁就测试；未发现当前获批准候选数据的实际运行时安全错误需要产品变更。

## 5. Phase4F Resolution

数字价格fixture换为当前合格gpt-5.6-luna，保留decimal/high-volume/零input/output等全部算术断言。gpt54nano转为明确“历史事实保留、不可Current Target”的验证，而不是复活资格。

独立expected resolver补齐Active CURRENT_TARGET、explicit veto、selected text-token input/output证据要求，并与真实getApiCostCalculatorModels在unset/OFF/ON逐ID及顺序相等。旧预期差异完整输出consumer-audit.json：

- Legacy unset/OFF旧44→实际39，差异gpt54nano、gpt53codex、gpt4.1、gpt4.1mini、gpt4.1nano；分别读取生命周期/defaultSafe/access/binding/review/selection。active的base/mini因独立review/defaultSafe阻断，不误称全是deprecated。
- V2旧60→实际58，差异Gemini3.5 Transcribe/Live；它们active，但选中组件是audio输入而非普通text-token input/output，故旧测试按scalar简单筛选错误，不是生命周期改变。

新增明确Active/Deprecated/Retired fixture：合格Active可Current Target，其他不可；历史状态可FACT_HISTORICAL；Access ON额外public/approved，existing_users_only/restricted/invite_only/unknown/unresolved不得绕过。真实API三个pricing flag状态及access ON也验证符合策略。

## 6. Phase4G Resolution

读清getBudgetPlannerModels与API实现差异：Budget沿用共享resolver，不新增API式外层生命周期/Access rollout。当前候选authoritative defaultSafe/review/selection已正确阻断全部deprecated/retired计算选项；测试实际核验unset/OFF=39、ON=58、degraded=39，均无inactive actual option。属于当前设计兼容行为加测试旧预期（A/B），本轮没有观察到C中的deprecated实际进入新的Budget计算。

scenario只将已deprecated的gpt54nano替换为真实合格decimal model gpt56luna，不改preset生产配置、模型默认或价格。读取真实budget-planner.ts并调用真实sanitizePlannerState：恢复旧gpt54nano/gpt53codex/grok3 URL状态时遵循既有确定性default gpt54mini，非model状态保留；没有新增implicit fallback。Presets、scenario、默认存在、全部实际可计算IDs与独立expected set逐项校验。降级source也无inactive option，且带正确degraded provenance。

未给Budget描述不存在的独立access rollout；Access ON fixture策略和已有受控表面（API/Switch/Retry/Saved）的门禁由第11节核验。没有因设计路径不同擅自扩大生产改动或改OFF兼容。

## 7. Phase4H Child-Test Resolution

Phase4H自身安全降级断言未删除/修改；两个子测试恢复后父测试PASS。

**专项fixture：**在内存克隆批准candidate，构造GPT4.1family安全资格before/after；其价格和historical identity在两个版本一致，允许变更只有显式安全/lifecycle/selected字段。原 `removedUnsafe.every(id=>family.includes(id))` 继续在此隔离fixture运行；新增负向测试修改其他模型outputPrice、family inputPrice都被scope断言拒绝。defaultSafe=false/review、binding unresolved、降级fail-closed和Saved兼容原断言保留。

mini fixture以当前批准事实构造only-lifecycle before，复原后整份projection完全相等；额外跨model价格修改必须被拒绝。所有原selector/degraded/public事实/Saved/Retry/存储/默认行为检查继续执行，不用skip/todo/删断言。

**当前集成：**新增approved-projection测试manifest固定批准候选的精确canonicalized SHA256、完整IDs、历史SHA855e与逐row before/after digest、准确字段变更清单。没有把allowlist扩为所有模型：任何不匹配的identity/价格/资格/metadata修改都使精确digest失败。完整变更ID/字段/批准原因见approved-candidate-change-ids.json及Website fixture manifest；现有候选来自已授权PhaseA/OCR/Kimi/B1，不重查价格、不生成新来源。

该manifest是明确冻结测试基线，**不是未来release commit SHA**；日后有新的合法候选必须另行审查基线，不能拿它长期自动接受数据变化。旧HEAD只用于解释已批准差异，不当成当前全量候选scope。

mini原同步幂等验证仍在SYSTEM TEMP副本运行check/write，不重同步真实Website；三个工作树数据文件hash证明零修改。

## 8. Production Safety Assessment

生产pricing-adapter.ts、model-lifecycle-policy.ts、budget-planner.ts、components全部未改。当前实际API/Budget候选与旧测试算法差异已分类成合法生命周期/独立review-veto/文本modality门禁，不是模型删除、访问升级或sync遗漏。

保留OFF兼容、原默认、URL恢复行为；不修改Dataset事实、价格、access/binding、Saved原记录、Price Events或生产Flag。没有新产品路径/安全缺口由本轮引入。由于没有生产消费者改动，本轮不需要为产品变更启动Browser验收；未启动生产服务/使用3017，也不冒称production HTML验证。

## 9. Files Changed

B3新增修改4个既有Website相关测试：Phase4F、Phase4G、legacy-fallback-eligibility、gpt41-mini-lifecycle-consumer。mini是原第五项失败的直接子测试修复，属于同scope。Phase4H自身无需变更，两个B2修复及B2helper逐字节保护。

新增2个最小测试辅助文件：scripts/issue26-contract-fixtures.mjs、scripts/fixtures/issue26-approved-projection.json。前者提供只读isolated runtime、专项范围negative fixture；后者是精确批准candidate范围证据。package.json未改，失败脚本仍在npm链中。

全部原有Dataset文件/B1同步数据/事件/无关工作hash保留。两仓库git diff --check PASS、staged空、HEAD不变，未经允许修改数量0。精确本轮新增清单和最终受控提交文件清单见scope-check.json与两份controlled-commit-files.txt。

## 10. Full npm test Results

**完整 npm.cmd test：exit0。** pretest+test链48个唯一顶层入口，Phase4H另执行2个独立子入口；本轮强制专项/Saved一起去重54入口，**54PASS、0FAIL**。重复父子/direct/npm执行不重复计数；fixture/helper不计成独立测试。此数是脚本入口，不是assertion数量。原五项全部独立重跑exit0，npm完整串行链也全部通过；未排除任何脚本。

完整原始输出在npm-test.log、direct-contract-tests.json、website-tests.json；test-inventory.json保存实际入口清单。Node MODULE_TYPELESS_PACKAGE_JSON只是已有warning，退出0；未为消除warning擅改package.json。

## 11. Access OFF/ON & Saved Workload

B2 Lifecycle PASS；Access Enforcement20contracts/58identity/174decision零mismatch、精确59→58基线差异保留；activation21contracts、access policy36mutation assertions PASS。OFF/unset语义、ON权限矩阵、CURRENT_TARGET与EXISTING_WORKLOAD_SOURCE、FACT_HISTORICAL、OFF→ON→OFF、public JSON/CSV不变全部通过。

Saved Workload独立脚本PASS；原ID和snapshot不改、Reopen不写入/不替代、unknown/retired unavailable、current/alternative独立权限检查、Retry/Fallback拒绝、明确合格替代及Save恢复规则继续PASS。没有改真实Flag或持久化存储。

## 12. TypeScript / Build

npx.cmd tsc --noEmit exit0；npm.cmd run build exit0。真实静态Next build完成，未启动生产server或3017。没有生产消费者代码修改，未虚报额外Browser结果。

## 13. Dataset Freshness

本轮实际python scripts/validate.py PASS；python -m unittest discover -s tests **548PASS**；完整 `python scripts/validate.py --freshness-report --max-age-days 30 --check-urls` **exit0、stale0、85/85主来源PASS、0 URL failures**（41uniqueURL）。30天阈值不变，全部记录均检查，不修改dates/sources/skip规则。freshness-report.md两项None；完整日志见full-unittest.log/freshness.log。

## 14. Website/Dataset/HF Local Parity

sync check显式Dataset源PASS，无write重同步。组件逐模型/amount/unit/条件/证据/access/binding与HF JSON/CSV/train一致，83records/763components/80cache_write/0mismatches。

Dataset `export_huggingface.py --website-repo D:/ai-cost-control-tool/aicostguard-english --website-ref WORKTREE --check` PASS，83records。初始数据hash保留，无其他价格漂移，无Kimi虚假Price Event。LOCAL PARITY VERIFIED不能代表PRODUCTION PARITY VERIFIED；生产镜像仍属未发布候选差异，本轮不发布或验证生产。

## 15. Remaining Blockers

本轮要求的本地回归/安全/Freshness/parity门禁均通过，原5项失败已消除；没有本地剩余阻断。Kimi BILLING PRECISION UNCONFIRMED caveat仍保留，不能把它写成invoice验证。

正式release仍需授权形成两个最终不可变提交、核验精确source provenance、snapshot/API和tag来源及正式bundle。当前Dataset80c2/Website855e不包含dirty修复，不能用旧HEAD构建假candidate。没有构建/虚报正式bundlePASS，也没有声称整体已经发布。

## 16. READY FOR CONTROLLED COMMITS = YES

需要进入最终评审提交的精确文件分别列在dataset-controlled-commit-files.txt、website-controlled-commit-files.txt；保留前轮OCR/Kimi、B1/B2及本轮相关测试/证据，排除Website无关特殊字符untracked文件。清单不表示本轮执行Git写操作。

后续Release Bundle必须使用 **尚未产生的最终Dataset40字符SHA、最终Website40字符SHA**，不虚构未来值。准确snapshot是 `data/snapshots/2026-10-09/`。

```powershell
python scripts/build_release_bundle.py --snapshot 2026-10-09 --dataset-ref <FINAL_DATASET_SHA> --website-repo D:/ai-cost-control-tool/aicostguard-english --website-ref <FINAL_WEBSITE_SHA> --output dist/release-candidate/issue26-final-pinned
```

output使用新目录；在授权提交后的精确blobs上重新验bundle/provenance与同版本parity，不能用WORKTREE冒充正式SHA。API source_commit_sha80c2是现有build base，不表示dirty事实已提交；生成规范和后续发布门禁仍需满足。

已停止：无git add/commit/push、PR/tag、部署Website/Dataset、HF Publish或关闭Issue。所有修复停留于可审查工作树。
