# Release Process

## Normal Daily Release

```text
EDIT
→ VALIDATE ONCE
→ HUMAN APPROVAL
→ PUBLISH ONCE
→ PRODUCTION VERIFY ONCE
→ STOP
```

普通发布以一个经过审核的 Dataset revision 为身份：

1. 修改 Canonical Source of Truth。
2. `daily-pricing-release.ps1 -Validate` 执行一次本地生成与验证并报告真实变更。
3. 人工审核报告和 diff。
4. 审核 revision 提交后，`-Publish` 只推送一次。
5. main push 触发 Pages 和 Hugging Face 各自的一次 workflow。
6. Pages 验证公网 revision、JSON/CSV parity；HF 验证远端生产 parity；随后停止。

普通流程没有 Release Plan、plan digest、checkpoint、resume、pre-tag 或多阶段状态文件。失败后不得自动进入第二条发布链。

Pages 只发布 allowlisted `api/**`，不得包含仓库内部文件。构建时 `SOURCE_COMMIT_SHA` 等于审核 revision，公网 metadata 必须精确匹配该 revision。

Hugging Face 仍只允许 `prices.json`、`prices.csv`、`train.csv`、`meta.json`；发布器继续要求干净 fresh clone、remote HEAD 未移动、fast-forward-only 且禁止 force push。

Website projection 只有业务字节变化才需要后续同步；纯时间戳、provenance 或换行变化不得制造 Website commit。

## Forward Recovery

真实发布事故使用独立 `scripts.forward_recovery`。Recovery 可以保留更严格的 Recovery Plan、双 revision identity、Tag、状态和 resume，但这些概念不得进入 Normal Daily Release。

`p04-release-dependency-gates.md` 与 `p06-release-gates.md` 记录旧实现阶段，仅作为 historical implementation evidence，不定义当前 ordinary flow。
