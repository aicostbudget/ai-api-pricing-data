# Daily Pricing Release V1

日常模型新增、价格变更和生命周期更新使用同一个入口。价格事实仍由现有 Canonical、生成器、Release Gate、Pages 与 Hugging Face workflow 管理；本工具只负责编排和安全恢复。

## Prepare

Codex 完成 Canonical 修改后运行：

```powershell
Set-Location "D:\ai-api-pricing-data"
$ErrorActionPreference = "Stop"
.\scripts\daily-pricing-release.ps1 -Prepare
if ($LASTEXITCODE -ne 0) { throw "Prepare failed" }
```

Prepare 生成所有本地候选、检查 Website/HF parity，并在被 Git 忽略的 `.daily-pricing-release/` 中保存发布计划和状态。输出包含 release ID、plan digest、模型变更、V1/V2 记录数及 `READY FOR APPROVAL`。同日 Snapshot 已存在但字节不同会安全失败，不会覆盖。

非默认工作树可显式传入路径：

```powershell
Set-Location "C:\work\dataset"
$ErrorActionPreference = "Stop"
.\scripts\daily-pricing-release.ps1 -Prepare -DatasetPath "C:\work\dataset" -WebsitePath "C:\work\website"
if ($LASTEXITCODE -ne 0) { throw "Prepare failed" }
```

## Publish

审核 release ID、plan digest、模型和价格差异后，用户只需执行：

```powershell
Set-Location "D:\ai-api-pricing-data"
$ErrorActionPreference = "Stop"
.\scripts\daily-pricing-release.ps1 -Publish
if ($LASTEXITCODE -ne 0) { throw "Publish failed" }
```

Publish 的固定顺序为：Prepare → 人工审核 Plan → S1 → S2 → W1 → pre-tag gate → 唯一 Annotated Tag → Validate → Pages Release Gate → Pages → Website 生产 parity → HF Dry Run → HF Publish → HF 生产 parity。GitHub 环境中的 maintainer 授权仍是强制门禁。

## Pre-tag hard gate

Tag 创建前必须同时满足以下条件，否则立即停止，且不得把 Validate 成功当作 Pages Release Gate 成功：

- S1、S2、W1 都是精确的 40 位 Commit SHA；S1 与 S2 不同，且 S1 是 S2 的真实祖先。
- `release-plans/<release-id>.json` 以完全相同的字节存在于 S1 与 S2，SHA-256 等于人工审核的 plan digest。仅在 S2 之后回填计划不能授权正式 Tag。
- S1 与 S2 的 `data/canonical/models.json` 字节一致；S2 的公开 metadata 必须把 `source_commit_sha` 指回 S1，并把 artifact identity 指向 S2。
- Dataset `main` 已精确指向 S2，Website `main` 已精确指向 W1；真实 Website serializer 对 Pricing V2/HF 投影的 parity 通过。
- 候选 Tag 在本地与远端均不存在。任何同名 Tag（即使恰好指向 S2）都按冲突处理，绝不移动、覆盖或复用。

Tag 名称由快照日期、单模型的可读 model ID（多模型使用 `pricing`）和 Canonical SHA-256 前 8 位确定，例如 `dataset-2026-10-15-grok-voice-3-0-1a2b3c4d`。旧 Tag 永远保持不变。

普通 `aicostbudget-daily-pricing-release-plan-v1` 只能授权其 Plan 已在 S1 中提交的正常发布链，不能事后修复缺少审核来源的旧链。若未来确需恢复发布，必须另行设计、审核并实现独立的 recovery plan schema；当前流程明确不支持。

每个成功阶段都会写入本地状态，并分别记录 `validate_verified`、`pages_release_preflight_verified`、`pages_production_deployed`、`pages_production_verified`、`website_production_verified`、`hf_dry_run_verified`、`hf_publish_verified` 与 `hf_production_verified`，避免把测试、门禁、真实部署和生产 parity 混为一谈。Pages 的三个生产阶段只能由同一个人工 `workflow_dispatch` Run 中的 preflight、`actions/deploy-pages` 和公网 parity 步骤独立成功证据写入；普通 push 只能记为 build-only，不是 production deploy。失败后再次执行相同 Publish 命令会从失败阶段继续；不会重复提交、移动 Tag、重复部署 Pages、重复发布 HF 或重新生成已完成事件。若计划、Canonical、远端 main 或 Tag 可用性已变化，必须停止并人工核验真实远端状态。

本地测试通过只代表 LOCAL VERIFIED；Validate workflow 成功只代表 CI VERIFIED；只有 Pages/Website/HF 各自的正式门禁和生产 parity 都成功后，才能报告对应的 PRODUCTION VERIFIED。Tag 存在本身不表示 Pages 或 HF 已发布。

本地状态不进入 Git；审核计划会在 Publish 的 S1 中写入 `release-plans/<release-id>.json`，CI 使用 plan ID 和 SHA-256 digest 精确验证 Canonical、V1、V2 以及批准的模型集合和每行内容。
