# Daily Pricing Release

普通模型新增、价格更新、metadata 更新和生命周期更新统一使用极简流程：

```text
EDIT
→ VALIDATE ONCE
→ HUMAN APPROVAL
→ PUBLISH ONCE
→ PRODUCTION VERIFY ONCE
→ STOP
```

Canonical 仍是唯一 Source of Truth。普通流程不创建 Release Plan，不保存 checkpoint，不支持 resume，也不使用多提交身份。

## Validate

```powershell
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "D:\ai-api-pricing-data"
.\scripts\daily-pricing-release.ps1 -Validate -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"
if ($LASTEXITCODE -ne 0) { throw "Validate failed" }
```

Validate 读取当前 HEAD 与工作区 Canonical 差异，分类 `added`、`pricing`、`metadata`、`lifecycle`，并只运行一次必要生成与验证路径。报告明确给出价格是否变化、生成文件及 Website 是否存在真实业务变化。Validate 不执行远端写入。

仅 `pricing` 变化可进入 price-change event 生成；metadata-only 更新不得伪造价格事件。Website 仅 timestamp、provenance 或换行变化时报告 `WEBSITE BUSINESS CHANGE: NO`。

## Publish

人工审核 Validate 输出，并将审核后的单一 revision 提交后，执行：

```powershell
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "D:\ai-api-pricing-data"
.\scripts\daily-pricing-release.ps1 -Publish -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"
if ($LASTEXITCODE -ne 0) { throw "Publish failed" }
```

Publish 要求工作区干净，只将当前审核 revision 推送到 `main` 一次。main push 分别触发 Pages 与 Hugging Face 的单次渠道 workflow；各渠道只执行自己的最小构建、安全检查、发布和一次生产 parity。

失败即停止。普通流程不自动进入事故 Recovery。

## Forward Recovery

Forward Recovery 只用于真实发布事故，入口为 `python -m scripts.forward_recovery`。它独立于普通 Daily，可保留 Recovery Plan、严格双 revision 身份、状态和 resume。详见 [Forward-Only Recovery](forward-only-recovery.md)。

`p04-release-dependency-gates.md` 与 `p06-release-gates.md` 是历史实现证据，不是当前 ordinary daily procedure。
