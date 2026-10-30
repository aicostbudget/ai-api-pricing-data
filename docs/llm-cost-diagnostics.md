# Retry and fallback cost diagnostics

Run the repository's dependency-free Python example to estimate the cost of anonymized LLM task attempts while keeping first attempts, retries, and model fallbacks separate:

```bash
python examples/llm_cost_diagnostics.py examples/sample_llm_attempts.json
```

Expected output for the checked-in synthetic input and current checked-in Pricing V2 catalog:

```text
LLM cost diagnostics
Input provenance: synthetic_example_not_production_measurement
Pricing catalog: data/pricing-v2-preview/generated/model-pricing.v2.json
Tasks: 3
Successful tasks: 2
Attempts: 5
Billed attempts: 5
Not-billed attempts: 0
First-attempt estimated cost (USD): 0.287500
Retry estimated cost (USD): 0.150000
Fallback estimated cost (USD): 0.300000
Total estimated cost (USD): 0.737500
Cost per successful task (USD): 0.368750
```

The example input is synthetic and is not a production measurement, provider invoice, or claimed success-rate benchmark. Replace it with anonymized attempt records from your own system. Each record must identify its task and attempt, classify the attempt as `first_attempt`, `retry`, or `fallback`, state whether the task attempt succeeded, and provide normalized usage by pricing component. `usage.input` must contain only uncached input tokens; cached input belongs in `usage.cached_input` so the two counts do not overlap.

The utility deliberately has a narrow billing scope:

- It reads the checked-in Pricing V2 catalog and accepts only its verified, default-safe selected billing record.
- It supports standard, short-context, global text pricing in USD per one million tokens for `input`, `cached_input`, and `output` components.
- `billing_status` must be `billed`, `not_billed`, or `unknown`. An explicit `not_billed` attempt contributes zero; `unknown` stops the run instead of silently contributing zero.
- Missing models or rates, conditional tiers, alternative processing modes, non-token units, unsupported usage components, and ambiguous billing conditions stop the run with an error.
- Results are catalog-rate estimates for diagnostic comparison, not invoice reconciliation. Provider-specific taxes, contracts, credits, rounding, and unrecorded charges are outside this example's scope.

Use the interactive tools for scenario exploration:

- [Analyze retry cost](https://aicostbudget.com/en/llm-retry-cost-calculator?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_retry_cost_calculator)
- [Compare model-switch cost](https://aicostbudget.com/en/model-switch-cost-calculator?utm_source=github&utm_medium=referral&utm_campaign=pricing_dataset&utm_content=readme_model_switch_cost_calculator)

To measure real success rates instead of assuming them, the open [LLM cost-per-task benchmark](https://github.com/aicostbudget/llm-cost-per-task-benchmark) runs 16 tasks with code-only validators against your own API keys and prices every attempt from this dataset. Its first published run found a flagship model matching a cheap one on accuracy at 5–9× the cost per successful task.
