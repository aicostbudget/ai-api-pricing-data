# ai-api-pricing

Zero-runtime-dependency TypeScript/JavaScript access to the source-linked [AICostBudget AI API Pricing Dataset](https://aicostbudget.com/en/datasets/ai-api-pricing).

```bash
npm install ai-api-pricing
```

```js
import { estimateCost } from "ai-api-pricing";
const estimate = await estimateCost({
  modelId: "gpt-4.1", inputTokens: 1_000_000, outputTokens: 100_000,
});
console.log(estimate.total, estimate.officialSourceUrl, estimate.lastVerifiedAt);
```

The package exports `loadPrices`, `getPrice`, `listModels`, `estimateCost`, and `compareModels`. Live loading uses the GitHub Pages JSON with a 10-second timeout and falls back to the bundled snapshot on any fetch or validation error. Check the returned `source` field to distinguish `live` from `bundled` data. Missing required prices raise a typed `MissingPriceError`; the package never substitutes another rate.

## From price per token to cost per result

A price estimate is the cost of one call. To measure what one *correct* result costs on your models, including retries and reasoning tokens, use the open [LLM cost-per-task benchmark](https://github.com/aicostbudget/llm-cost-per-task-benchmark): 16 tasks with code-only validators, run with your own API keys, priced from this dataset.

## Refresh the bundled snapshot

From the repository root, run:

```bash
npm run refresh-bundle --workspace ai-api-pricing
```

The generator reads the checked-in `api/v1/prices.json`, embeds its `generated_at` value, and rewrites `src/generated/bundled.ts`. Review and commit that generated file with the package change.

## Data license and citation

Code is MIT-licensed. Pricing data is licensed under [CC BY 4.0](../../LICENSE-DATA). Attribution: **AICostBudget AI API Pricing Dataset**, https://aicostbudget.com/en/datasets/ai-api-pricing, DOI [10.5281/zenodo.23087250](https://doi.org/10.5281/zenodo.23087250).

Prices are verified against official provider pages; always confirm before billing decisions.
