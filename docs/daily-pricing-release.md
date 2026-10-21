# Daily Pricing Release

普通模型新增、价格更新、metadata 更新和生命周期更新统一使用以下流程：

```text
EDIT canonical
→ VALIDATE（可选的完整演练，不改任何仓库）
→ PREPARE（本地生成两个提交：源数据+快照，然后生成数据）
→ HUMAN APPROVAL（审阅、跑测试、补充审批测试）
→ PUBLISH ONCE
→ PRODUCTION VERIFY ONCE
→ STOP
```

Canonical（`data/canonical/models.json`）仍是唯一 Source of Truth。普通流程不创建 Release Plan，不保存 checkpoint，不支持 resume。

## 快照编号

快照目录按 UTC 日期命名：当天第一次发布用 `data/snapshots/YYYY-MM-DD/`；同一 UTC 日再次发布时依次使用 `YYYY-MM-DD-2`、`YYYY-MM-DD-3`……已有快照永不改写。快照按“日期、序号”排序，price-change event 的 `detected_at` 取日期部分。

## Validate（演练）

```powershell
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "D:\ai-api-pricing-data"
.\scripts\daily-pricing-release.ps1 -Validate -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"
if ($LASTEXITCODE -ne 0) { throw "Validate failed" }
```

工作区只允许修改 canonical。Validate 在临时克隆中完整执行 Prepare 的全部步骤（分配快照编号、提交源数据、生成、全部校验），报告变更分类、是否有价格变化、快照编号、生成文件及 Website 是否有真实业务变化。Dataset 与 Website 仓库都不改变，不执行远端写入。

仅 `pricing` 变化可进入 price-change event 生成；metadata-only 更新不得伪造价格事件。Website 仅 timestamp、provenance 或换行变化时报告 `WEBSITE BUSINESS CHANGE: NO`。

## Prepare（两个本地提交）

```powershell
.\scripts\daily-pricing-release.ps1 -Prepare -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"
```

1. 源提交 `data: prepare pricing source <快照编号>`：只含 canonical 与本次快照，提交时间等于 `generated_at`。价格事件生成要求快照已被 Git 跟踪，因此快照必须先进入这个提交。
2. 生成提交 `data: publish pricing artifacts <快照编号>`：从源提交生成的全部数据（API、HF 导出、v2 projection、price-change events 等），`source_commit_sha` 指向源提交。

Prepare 不推送、不修改 Website 仓库。随后人工审阅、运行完整测试；需要新增审批记录（如 `tests/fixtures/official-pricing-repair-scope.json`）时，可以修改测试文件并 `git commit --amend` 到生成提交，但不得改动生成数据。

## Publish

```powershell
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "D:\ai-api-pricing-data"
.\scripts\daily-pricing-release.ps1 -Publish -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"
if ($LASTEXITCODE -ne 0) { throw "Publish failed" }
```

Publish 要求两个仓库工作区干净，HEAD 为生成提交、HEAD^ 为源提交。它在临时克隆中从源提交重新生成全部数据，并要求与生成提交逐文件一致；不一致即停止。通过后依次：

1. Website 有真实业务变化时，同步四个允许文件、提交一次并推送 Website `main`（Hostinger 部署）；
2. 推送 Dataset `main`（触发 Pages）；
3. 最后触发 Hugging Face 发布（HF 导出会与已发布的 Website 比对，所以必须在 Website 之后）。

失败即停止。普通流程不自动进入事故 Recovery。

## Forward Recovery

Forward Recovery 只用于真实发布事故，入口为 `python -m scripts.forward_recovery`。它独立于普通 Daily，可保留 Recovery Plan、严格双 revision 身份、状态和 resume。详见 [Forward-Only Recovery](forward-only-recovery.md)。Forward Recovery 尚未支持同日序号快照，同一 UTC 日已有快照时仍按原规则拒绝。

`p04-release-dependency-gates.md` 与 `p06-release-gates.md` 是历史实现证据，不是当前 ordinary daily procedure。
