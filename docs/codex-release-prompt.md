# Codex 发布提示词模板

把一次普通的数据发布（新增模型、改价、元数据或生命周期更新）交给 Codex 时，复制下面的模板，替换所有 `<…>` 占位符。模板在 Rehearse 通过后停止；Publish 和 push 只在明确授权后执行（见文末"正式发布"）。流程细节见 `docs/daily-pricing-release.md`。

契约类改动（新的计费单位、组件或导出 schema 升级）不要用这个模板：它们需要先合并 Website PR，再合并 Dataset PR（Dataset CI 会对照 Website `main` 检查计费词表），HF 由 `hf-contract-republish.yml` 自动重发。

```text
任务：<一句话说明，例如：新增 mistral-ai/voxtral-mini-tts-3-0，价格 $13 / 1M characters>。按 docs/daily-pricing-release.md 走到 REHEARSE 为止，不要 Publish。

执行环境
- 所有 git、npm、python 命令都在沙箱外运行（沙箱访问不了这两个仓库，也没有网络）。
- Dataset 主检出 D:\ai-api-pricing-data，Website 主检出 D:\ai-cost-control-tool\aicostguard-english。只读取它们的状态（分支、HEAD、origin/main、工作区），不要 stash、reset、切换分支，也不要动 Website 的 stash。Website 主检出经常有别的工作在进行，发布一律用第 1 步新建的 Website worktree。
- 临时文件和日志只放在 D:\ai-api-pricing-data\.release-logs\ 或系统临时目录，不要写到盘符根目录。
- 授权范围：worktree 内的本地 commit（Prepare 生成的提交、git commit --amend）无需另行授权；push、开 PR、Publish 需要明确授权。

第 1 步：建工作目录（只用 release_worktree.py）
- 在 D:\ai-api-pricing-data 中运行：
  python scripts/release_worktree.py create D:/ai-api-pricing-data-<短名> --branch data/<短名>
  python scripts/release_worktree.py create D:/aicostguard-website-<短名> --repo D:/ai-cost-control-tool/aicostguard-english --branch release/<短名> --link-node-modules D:/ai-cost-control-tool/aicostguard-english/node_modules
- Website worktree 必须停在 origin/main、没有任何未跟踪文件（Rehearse/Publish 遇到未跟踪文件会拒绝）。下文 <WEBSITE_WT> 指这个路径。
- 不要用 rm -rf、Remove-Item 或 shutil.rmtree 删除含 node_modules junction 的目录；清理只用 release_worktree.py remove。

第 2 步：修改 canonical（只改 data/canonical/models.json）
- <逐条写明要新增或修改的记录：provider_id、model_id、display_name、model_family、model_category、status/release_stage、released_at、模态、V1 pricing、price_records（component、modality、unit、amount、transport）、billing_note、notes、official_source_url 与 official_source_urls>
- 结构参照同文件中的 <相近的现有模型 ID>。只做局部插入或修改，不要整体重排。不要用 JS 的 JSON.stringify 重写文件（会把 10.0 变成 10）；需要脚本时用 Python json 局部修改，再格式化。
- 价格只用官方来源中当前可复核的数值：<官方 URL 列表>。改 canonical 之前，先对每个模型运行：
  python scripts/capture_price_evidence.py --model <provider>/<model> --url <官方 URL> --expect '<价格文字>'
  它必须成功（页面含该价格、HTTP 200）；它列出的"与上次相比的变化"要写进报告。
- 来源冲突或证据缺失：新增模型或改价时停下来报告，不要自行选择。批量重新核实（只更新时间戳）时，把证据不符的模型剔出本次发布并在报告中列出，其余模型继续；只有完整价格记录与页面一致的模型才更新 accessed_at、last_verified_at 和 checked_at/verified_at。
- 改完运行：python scripts/format_canonical.py，并查看 diff，确认只改了预期的记录。
- 不收录、只记录证据的内容：<例如没有标价的型号、工作流计费>，写进 docs/billing-unit-vnext-decision.md，但要等 Prepare 之后再改（Validate/Prepare 要求只有 canonical 一个文件有改动）。

第 3 步：Validate → Prepare
- .\scripts\daily-pricing-release.ps1 -Validate -WebsitePath "<WEBSITE_WT>"
  报告 CHANGED MODELS、CHANGE TYPE、PRICE CHANGE、SNAPSHOT、WEBSITE BUSINESS CHANGE。
- .\scripts\daily-pricing-release.ps1 -Prepare -WebsitePath "<WEBSITE_WT>"
- 元数据或时间戳更新不要伪造价格变动事件；纯时间戳或 provenance 变化不应产生 Website 业务变化。

第 4 步：审批改动（全部用 git commit --amend 并入生成提交，不得修改任何生成的数据）
- 运行 python scripts/update_release_approvals.py，查看它写入的摘要和 Website 对照行。
- 处理它在 STILL MANUAL 中列出的项目：价格变动的事件审批扩展、针对具体模型的断言（例如 provider onboarding 测试里的型号集合）。
  已知误报：纯重新核实时它仍会列出 "add price-change event approval"。确认 data/price-change-events 未变即可，不要补事件。
  已知漏报：重定向派生的投影行（例如 xai/grok-3 → grok-4.3）需要手工补摘要。
- 第 2 步中推迟的文档改动。
- 第 2 步生成的 reports/price-evidence/ 存档。

第 5 步：Rehearse（发布关卡）
- .\scripts\daily-pricing-release.ps1 -Rehearse -WebsitePath "<WEBSITE_WT>"
- 必须得到 "status": "REHEARSAL PASS"。如果是 FAIL，按 suites[].log 里的完整日志修复。修复只能是审批或测试改动（amend 进生成提交）；如果问题出在 Website 测试里写死的值，就停下来报告，不要改 Website 仓库。
- REHEARSAL PASS 只对当时的 Dataset 与 Website SHA 有效。之后任何 amend、审批改动或 Website 变动都必须重跑 Rehearse；没有变动时不要重复运行。
- Prepare 之后、Publish 之前，直接在真实检出里跑跨仓库测试必然失败，不能作为结论；以 Rehearse 为准。

禁止：Publish、push、开 PR、IndexNow、修改 schema 或单位枚举、改动 Website 仓库、删除 worktree。

报告：两个 worktree 的路径和分支、源提交与生成提交的 SHA（Rehearse 所用的最终 SHA）、diff 摘要、Validate 要点、update_release_approvals 的输出与人工补充、剔出的模型及原因、Rehearse 的 status 及两套测试结果和日志路径、仍需人工确认的事项。
```

## 正式发布（获得明确授权后，人工、Claude 或 Codex）

```text
.\scripts\daily-pricing-release.ps1 -Publish -Follow -WebsitePath "<WEBSITE_WT>"
```

- 只通过脚本发布。它按 Website → Dataset → HF 的顺序执行；不要手工 push main、手工触发 HF 发布，也不要添加 Tag、GitHub Release 或额外步骤。
- `-Follow` 用 `npm run verify:live -- --commit <sha>` 确认 Website 已上线（Hostinger 不向 GitHub 报告状态，不要轮询 commit status），等待 HF 发布及其 `BUSINESS_PARITY: PASS`，再做 IndexNow dry run。输出 `PUBLISHED AND VERIFIED` 后，检查 dry run 的 URL 列表无误即执行它打印的 `--send` 命令，无需再次批准。
- 中途失败时，先确认哪些远端动作已经成功，只处理失败的步骤；不要重跑整条链，不要强推或改写历史。
- Website 有业务变化并上线时，在报告中注明需要补一个记录 deployDate 的 ledger PR。
- 最后在 D:\ai-api-pricing-data 中运行 `python scripts/release_worktree.py remove <worktree 路径> --delete-branch` 清理两个 worktree（Website 的加 `--repo D:/ai-cost-control-tool/aicostguard-english`）。
