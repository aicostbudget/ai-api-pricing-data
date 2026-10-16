# Forward-Only Recovery V1

Forward Recovery 用一个新的、经过人工审核的发布身份重新发布已经真实存在于 Dataset `main` 的 Canonical 事实。它不是历史修正、Tag 修复或 Plan 回填，也不能追认旧 S1/S2。旧提交、旧 Plan 缺失状态和旧 Tag 必须保持原样。

## 与 Daily Release 的隔离

- Daily Release 使用 `aicostbudget-daily-pricing-release-plan-v1`，用于新的 Canonical 变化。
- Forward Recovery 使用 `aicostbudget-forward-recovery-plan-v1`，只允许恢复经审核且在 C0 已存在的 Canonical 字节。
- 两个 loader、状态 schema、阶段名和 Backend 相互独立；任一 schema 进入另一条路径都会 fail closed。
- Recovery 不会因为 Website reuse 失败而自动切换为新 W1，也不会把普通 Daily 流程降级为无 Canonical 变化的发布。

## 身份链

正式 Recovery 必须在 Recovery 代码 commit 已经 push、CI 通过并成为不可变 C0 后，才生成正式 Plan：

```text
C0 (reviewed recovery code)
  -> S1 (exactly release-plans/<recovery-id>.json)
  -> S2 (allowlisted generated/public artifacts only)
```

以下条件必须同时成立：

- `parent(S1) == C0`，`parent(S2) == S1`。
- `Canonical(C0) == Canonical(S1) == Canonical(S2)`，且 SHA-256 等于 Plan 的 `canonical_sha256`。
- S1 与 S2 中的 Plan 字节完全相同，SHA-256 等于人工批准的 digest。
- S2 的 `api/v1/meta.json.source_commit_sha == S1`。
- `snapshot_generated_at` 保存被恢复数据的事实时间；`recovery_created_at` 单独保存恢复审核时间。生成器不得用恢复执行时间覆盖事实时间。
- 历史 SHA 与旧 Tag 只属于 `historical_context`，不能成为新的 S1/S2 或新 Tag。

## Recovery Plan 审核合同

正式 Plan 必须由 C0 之后的独立步骤生成并人工审核，不得在 C0 实现阶段提前提交。至少审核：

- `recovery_id`、C0 `dataset_base_sha`、Canonical SHA-256、两个时间字段及非空的 `recovery_reason`。
- 历史 source/artifact/tag object/tag target，以及旧 identity/plan 均为 `FAIL_CLOSED` 的事实。
- Pages V1 和 Pricing V2/HF 两套独立 projection contract：record/model count、provider count、完整 provider/model identity set、逐行 digest、JSON digest、CSV digest。两套 projection 的数量不要求相等。
- Website contract 的明确模式。`reuse` 必须固定 W1、W1 parent、schema version、生产 JSON/CSV digest、pricing fingerprint 与 pricing-version manifest digest；任一远端或生产证据漂移都停止并重新人工审核。

## Tag 与发布门禁

Recovery Tag 使用 `dataset-recovery-<snapshot-date>-<recovery-id>-<collision-digest>` 形式，必须与历史 Tag 明确区分。创建前，本地和远端同名 Tag 都必须不存在；存在即停止，绝不移动或覆盖。历史 Tag 的 annotated object SHA 与 target commit SHA 必须继续与 Plan 审核值完全一致。

Pages 与 Hugging Face 继续使用现有 workflow、环境审批和精确输入：S1、S2、W1、新 Tag、Recovery Plan ID 与 digest。Recovery 不增加旁路 workflow。Pages、Website、HF 的生产写入和生产 parity 是分别授权、分别取证的阶段；CI success 不能替代生产成功。

## 状态与恢复

Recovery 使用 `aicostbudget-forward-recovery-state-v1`，并记录独立的 `recovery_*` 阶段。旧 Daily state、未知阶段或不同 Plan digest 一律 fail closed。已完成阶段在 resume 时不会再次创建 commit/Tag、再次部署或再次发布。

当前 C0 本地实现不会创建真实 Recovery Plan、S1、S2、W1 或 Tag。下一步只能在 C0 单独 commit/push 且 CI 通过后，生成并人工审核绑定精确 C0 SHA 的正式 Plan。

代码只提供需要显式 `--plan` 与 `--plan-digest` 的 `publish-recovery` 入口，不提供 `prepare-recovery` 或历史 Plan 回填入口。该入口在获得后续分阶段授权前不得执行；本地 C0 验收不会调用它。
