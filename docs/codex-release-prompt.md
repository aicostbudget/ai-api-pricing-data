# Codex 发布提示词模板

把一次普通的数据发布（新增模型、改价、元数据或生命周期更新）交给 Codex 时，复制下面的模板，替换所有 `<…>` 占位符。模板在 Rehearse 通过后停止；Publish、push 和 IndexNow 由人工批准后另行执行。流程细节见 `docs/daily-pricing-release.md`。

契约类改动（新的计费单位、组件或导出 schema 升级）不要用这个模板：它们需要先合并 Website PR，再合并 Dataset PR（Dataset CI 会对照 Website `main` 检查计费词表），HF 由 `hf-contract-republish.yml` 自动重发。

```text
任务：<一句话说明，例如：新增 mistral-ai/voxtral-mini-tts-3-0，价格 $13 / 1M characters>。按 docs/daily-pricing-release.md 走到 REHEARSE 为止，不要 Publish。

执行环境
- 所有 git、npm、python 命令都在沙箱外运行（沙箱访问不了这两个仓库，也没有网络）。
- Dataset 主检出 D:\ai-api-pricing-data，Website 主检出 D:\ai-cost-control-tool\aicostguard-english。两者都必须在 main 上、工作区干净、与 origin/main 一致；否则停下来报告，不要 stash、reset 或切换分支，也不要动 Website 的 stash。
- 临时文件和日志只放在 D:\ai-api-pricing-data\.release-logs\ 或系统临时目录，不要写到盘符根目录。

第 1 步：建工作目录
- 在 D:\ai-api-pricing-data 中运行：python scripts/release_worktree.py create D:/ai-api-pricing-data-<短名> --branch data/<短名>

第 2 步：修改 canonical（只改 data/canonical/models.json）
- <逐条写明要新增或修改的记录：provider_id、model_id、display_name、model_family、model_category、status/release_stage、released_at、模态、V1 pricing、price_records（component、modality、unit、amount、transport）、billing_note、notes、official_source_url 与 official_source_urls>
- 结构参照同文件中的 <相近的现有模型 ID>。只做局部插入或修改，不要整体重排。
- 价格只用官方来源中当前可复核的数值：<官方 URL 列表>。来源之间有冲突时停下来报告，不要自行选择。
- 改完运行：python scripts/format_canonical.py，并查看 diff，确认只改了预期的记录。
- 不收录、只记录证据的内容：<例如没有标价的型号、工作流计费>，写进 docs/billing-unit-vnext-decision.md，但要等 Prepare 之后再改（Validate/Prepare 要求只有 canonical 一个文件有改动）。

第 3 步：Validate → Prepare
- .\scripts\daily-pricing-release.ps1 -Validate -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"
  报告 CHANGED MODELS、CHANGE TYPE、PRICE CHANGE、SNAPSHOT、WEBSITE BUSINESS CHANGE。
- .\scripts\daily-pricing-release.ps1 -Prepare -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"

第 4 步：审批改动（全部用 git commit --amend 并入生成提交，不得修改任何生成的数据）
- 运行 python scripts/update_release_approvals.py，查看它写入的摘要和 Website 对照行。
- 处理它在 STILL MANUAL 中列出的项目：价格变动的事件审批扩展、针对具体模型的断言（例如 provider onboarding 测试里的型号集合）。
- 第 2 步中推迟的文档改动。

第 5 步：Rehearse（发布关卡）
- .\scripts\daily-pricing-release.ps1 -Rehearse -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"
- 必须得到 "status": "REHEARSAL PASS"。如果是 FAIL，按 suites[].log 里的完整日志修复。修复只能是审批或测试改动（amend 进生成提交）；如果问题出在 Website 测试里写死的值，就停下来报告，不要改 Website 仓库。
- Prepare 之后、Publish 之前，直接在真实检出里跑跨仓库测试必然失败，不能作为结论；以 Rehearse 为准。

禁止：Publish、push、开 PR、IndexNow、修改 schema 或单位枚举、改动 Website 仓库、删除 worktree。

报告：worktree 路径和分支、源提交与生成提交的 SHA、diff 摘要、Validate 要点、update_release_approvals 的输出与人工补充、Rehearse 的 status 及两套测试结果和日志路径、仍需人工确认的事项。
```

## 审阅通过后（人工或 Claude）

```text
.\scripts\daily-pricing-release.ps1 -Publish -Follow -WebsitePath "D:\ai-cost-control-tool\aicostguard-english"
```

`-Follow` 等待 Website 上线、HF 发布及其 parity，并做 IndexNow dry run；输出 `PUBLISHED AND VERIFIED` 后，经批准再执行它打印的 `--send` 命令。最后在 D:\ai-api-pricing-data 中运行 `python scripts/release_worktree.py remove <worktree 路径> --delete-branch` 清理。
