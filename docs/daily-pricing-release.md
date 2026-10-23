# Daily Pricing Release

普通模型新增、价格更新、metadata 更新和生命周期更新统一使用以下流程：

```text
EDIT canonical
→ VALIDATE（可选的完整演练，不改任何仓库）
→ PREPARE（本地生成两个提交：源数据+快照，然后生成数据）
→ HUMAN APPROVAL（审阅、补充审批测试）
→ REHEARSE（临时克隆中打桩发布，并对同步后的两仓库跑完整测试）
→ PUBLISH ONCE
→ PRODUCTION VERIFY ONCE
→ INDEXNOW（Website 有业务变化时；先 dry run，确认后 --send）
→ STOP
```

Canonical（`data/canonical/models.json`）仍是唯一 Source of Truth。普通流程不创建 Release Plan，不保存 checkpoint，不支持 resume。

## 工作目录

发布在独立 worktree 中进行，用 `scripts/release_worktree.py` 创建和删除：

```powershell
python scripts/release_worktree.py create D:/ai-api-pricing-data-<名称> --branch data/<名称>
python scripts/release_worktree.py remove D:/ai-api-pricing-data-<名称> --delete-branch
```

需要 Website worktree 时加 `--repo D:/ai-cost-control-tool/aicostguard-english --link-node-modules D:/ai-cost-control-tool/aicostguard-english/node_modules`，依赖以目录链接共享。`remove` 会拒绝含未提交改动的 worktree（`--force` 才丢弃），先逐个拆除其中所有目录链接（不进入链接内部；Python 3.11 的 `rmtree`/`os.walk` 会沿 Windows junction 删除真实依赖），再删除 worktree，git 因路径过长失败时改用长路径删除。不要用 `rm -rf`、`Remove-Item -Recurse` 或 `rmtree` 直接删除含 `node_modules` 链接的目录。

## 快照编号

快照目录按 UTC 日期命名：当天第一次发布用 `data/snapshots/YYYY-MM-DD/`；同一 UTC 日再次发布时依次使用 `YYYY-MM-DD-2`、`YYYY-MM-DD-3`……已有快照永不改写。快照按“日期、序号”排序，price-change event 的 `detected_at` 取日期部分。

同一模型在同一 UTC 日只能有一条同类型 price-change event（validate 按 provider、model、change_type、detected_at 去重）。同一天两次修改同一模型的价格时，应把两次修改合并到一次发布。

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

Prepare 之后先运行 `python scripts/update_release_approvals.py`：它为本次源提交改动的每个模型写入 `tests/fixtures/official-pricing-repair-scope.json` 的 canonical 与 projection 摘要，并为新增模型在 `tests/fixtures/website-model-pricing.json` 追加网站对照行（`tests/test_website_projection_v2.py` 的网站模型数由该文件推出，不再手改）。它不会代写价格变动事件的审批扩展或针对具体模型的断言，这些会在输出的 STILL MANUAL 中列出。审阅 diff、补齐人工部分、跑测试后 `git commit --amend` 到生成提交。

canonical 编辑后须保持统一格式（两空格缩进、UTF-8、原 key 顺序）：编辑完运行 `python scripts/format_canonical.py`。Validate/Prepare 遇到未格式化的 canonical 会直接拒绝。

## Rehearse（发布演练）

```powershell
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "D:\ai-api-pricing-data"
.\scripts\daily-pricing-release.ps1 -Rehearse -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"
if ($LASTEXITCODE -ne 0) { throw "Rehearsal failed" }
```

Prepare（含审批测试的 amend）之后、Publish 之前运行。要求两个仓库工作区干净，前提与 Publish 相同。它把两个仓库克隆到临时目录，在克隆里执行完整的 Publish（推送与 HF 触发全部替换为记录，不触碰远端），核对推送顺序（Website → Dataset → HF），然后在已同步的两份克隆上跑完整测试：Website `npm run test:all`（`DATASET_ROOT` 指向 Dataset 克隆）和 Dataset `python -m unittest discover -s tests`（`WEBSITE_SOURCE_ROOT` 指向 Website 克隆）。Website 依赖通过目录链接共享，结束时先拆链接再删除克隆，真实 `node_modules` 不受影响。

Prepare 之后、Publish 之前，直接在两个仓库里跑跨仓库测试必然失败（Dataset 已含新数据而 Website 尚未同步），这类失败不能作为放行依据；以 Rehearse 的结果为准。输出 `"status": "REHEARSAL PASS"` 才进入 Publish；`REHEARSAL FAIL` 时 `suites[].output_tail` 给出失败摘要。只想核对发布步骤时可加 `-SkipTests`。

## Publish

```powershell
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "D:\ai-api-pricing-data"
.\scripts\daily-pricing-release.ps1 -Publish -Follow -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"
if ($LASTEXITCODE -ne 0) { throw "Publish failed" }
```

Publish 要求两个仓库工作区干净，HEAD 为生成提交、HEAD^ 为源提交。它在临时克隆中从源提交重新生成全部数据，并要求与生成提交逐文件一致；不一致即停止。通过后依次：

1. Website 有真实业务变化时，同步四个允许文件、提交一次并推送 Website `main`（Hostinger 部署）；
2. 推送 Dataset `main`（触发 Pages）；
3. 最后触发 Hugging Face 发布（HF 导出会与已发布的 Website 比对，所以必须在 Website 之后）。

失败即停止。普通流程不自动进入事故 Recovery。

`-Follow`（建议始终使用）在推送后继续完成发布后检查，最后输出 `"status": "PUBLISHED AND VERIFIED"`，否则为 `PUBLISHED, FOLLOW-UP NEEDS ATTENTION` 并以非零退出：

1. Website 有业务变化时，在 Website 仓库运行 `npm run verify:live -- --commit <website_sha> --wait 900`：Hostinger 不向 GitHub 报告部署状态，脚本读取线上 JS 中 Sentry 注入的 `SENTRY_RELEASE` 提交号，直到它等于（或包含）本次 Website 提交；
2. 等待本次 Dataset 提交触发的 Hugging Face 发布运行结束，并要求其日志含 `BUSINESS_PARITY: PASS`（发布工作流最后一步即生产 parity 检查），报告 HF 提交；
3. Website 已上线时执行 IndexNow dry run（带 `--wait-live`），列出将提交的 URL，并给出 `--send` 命令。IndexNow 提交仍需人工确认。

Follow 失败不会回滚已推送的提交；按报告中失败的步骤单独处理。

契约类改动（新计费单位、导出 schema 升级）不经过本流程，而是先合并 Website PR、再合并 Dataset PR。Dataset `main` 上 `huggingface/` 变化且不是发布生成提交时，`hf-contract-republish.yml` 会运行生产 parity 检查，仅在 `DATA_DRIFT` 时自动触发 `publish-huggingface.yml`，无需手动重发。

## IndexNow（Website 部署后）

Publish 的 JSON 输出含 `website_sha` 与 `next_step`。Website 有业务变化时，等 Hostinger 部署完成后，在 Website 仓库（HEAD 为该提交）执行：

```powershell
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "D:\ai-cost-control-tool\aicostguard-english"
npm.cmd run indexnow:pricing -- --commit <website_sha> --wait-live 600
if ($LASTEXITCODE -ne 0) { throw "IndexNow pricing dry run failed" }
```

脚本对比该提交与父提交的 v2 projection 与 price-change events（仅核验时间变化不算），用网站自身模块映射出受影响的模型页、服务商页、对比页、引用这些模型的博客文章及索引页；先确认线上数据集页已显示本次 `last_verified_at`，并跳过非 200 的 URL，然后打印 payload。审阅并获得确认后加 `--send` 重跑。IndexNow 向外部服务提交，每次都需要人工确认，因此不放进 Publish 自动执行。`next_step` 为 `NONE` 时无需提交。详见 Website 仓库 `docs/seo/geo-technical-checklist.md`。

## Forward Recovery

Forward Recovery 只用于真实发布事故，入口为 `python -m scripts.forward_recovery`。它独立于普通 Daily，可保留 Recovery Plan、严格双 revision 身份、状态和 resume。详见 [Forward-Only Recovery](forward-only-recovery.md)。Forward Recovery 尚未支持同日序号快照，同一 UTC 日已有快照时仍按原规则拒绝。

`p04-release-dependency-gates.md` 与 `p06-release-gates.md` 是历史实现证据，不是当前 ordinary daily procedure。
