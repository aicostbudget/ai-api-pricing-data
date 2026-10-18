# Forward-Only Recovery

Forward Recovery 只用于已经发生的真实发布事故，不是普通模型或价格更新的默认路径。

普通流程固定为：

```text
EDIT → VALIDATE ONCE → HUMAN APPROVAL → PUBLISH ONCE → PRODUCTION VERIFY ONCE → STOP
```

Recovery 与普通 Daily 完全独立：

- runtime、state store、backend 和 CLI 均位于 `scripts/forward_recovery.py`；
- ordinary daily 不 import 或调用 Recovery；
- Recovery 不 import ordinary daily；
- 只能通过人工明确提供 Recovery Plan 路径和 SHA-256 digest 启动。

Recovery 保留事故处理需要的严格合同：

- Recovery Plan 和 digest 必须字节精确；
- Recovery source/artifact revision 必须不同且具有真实祖先关系；
- Canonical 在 Recovery 链中不得改变；
- source commit 只能引入审核计划，artifact commit 只能包含 allowlisted 生成产物；
- Website reuse identity 与生产 JSON、CSV、fingerprint 必须一致；
- Tag 不得复用、移动或 force 更新；
- Dataset、Pages、HF 任一远端状态不明确时 fail closed；
- 状态仅供同一事故 Recovery resume，不能被 ordinary daily 使用。

入口示例：

```powershell
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "D:\ai-api-pricing-data"
python -m scripts.forward_recovery `
  --dataset-root "D:\ai-api-pricing-data" `
  --website-root "D:\ai-cost-control-tool\aicostguard-english" `
  --plan "D:\approved\recovery-plan.json" `
  --plan-digest "<exact-sha256>"
if ($LASTEXITCODE -ne 0) { throw "Forward Recovery failed" }
```

旧 P04/P06 文档是 historical implementation evidence，不是当前 ordinary daily procedure。
