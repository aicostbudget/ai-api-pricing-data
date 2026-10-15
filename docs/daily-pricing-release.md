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

Publish 保留 S1/S2/W1、Annotated Tag、精确 SHA CI、Pages、Hostinger parity、HF dry run、HF 正式发布及生产 parity。GitHub 环境中的 maintainer 授权仍是强制门禁。

每个成功阶段都会写入本地状态。失败后再次执行相同 Publish 命令会从失败阶段继续；不会重复提交、移动 Tag、重复部署 Pages、重复发布 HF 或重新生成已完成事件。若计划、Canonical 或远端 main 已变化，必须重新 Prepare 和审核。

本地状态不进入 Git；审核计划会在 Publish 的 S1 中写入 `release-plans/<release-id>.json`，CI 使用 plan ID 和 SHA-256 digest 精确验证 Canonical、V1、V2 以及批准的模型集合和每行内容。
