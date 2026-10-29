---
title: AI Cost Budget
emoji: 💸
colorFrom: indigo
colorTo: green
sdk: static
pinned: false
short_description: Open LLM API pricing data and cost calculators
---

# AI Cost Budget

Open, source-linked LLM API pricing data and cost tools. Every price is verified against the provider's official pricing page and carries its verification date.

## Datasets

- [AI API Pricing Dataset](https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing): current prices per 1M tokens for about 100 models from OpenAI, Anthropic, Google, xAI, DeepSeek, Mistral, Cohere, Moonshot AI, Alibaba Qwen, Meta and more, including cache, batch, tiered and non-token pricing.
- [LLM API Price History](https://huggingface.co/datasets/aicostbudget-ai/llm-api-price-history): dated price snapshots since 2026-07-05 and a log of verified price changes, new models, deprecations and retirements.

## Space

- [LLM API Pricing Calculator](https://huggingface.co/spaces/aicostbudget-ai/llm-api-pricing-calculator): price table, monthly cost estimate and recent price changes, loaded live from the datasets.

All three are grouped in the [LLM API Pricing & Cost collection](https://huggingface.co/collections/aicostbudget-ai/llm-api-pricing-and-cost-6ae3690fbe696553bf43f16a).

## Tools on aicostbudget.com

- [AI API cost calculator](https://aicostbudget.com/en/ai-api-cost-calculator?utm_source=huggingface&utm_medium=referral&utm_campaign=hf_org_card)
- [Model switch cost calculator](https://aicostbudget.com/en/model-switch-cost-calculator?utm_source=huggingface&utm_medium=referral&utm_campaign=hf_org_card): cost per successful task when changing models
- [Cheapest LLM APIs](https://aicostbudget.com/en/cheapest-llm-api?utm_source=huggingface&utm_medium=referral&utm_campaign=hf_org_card)
- [Model pricing comparison](https://aicostbudget.com/en/model-pricing-comparison?utm_source=huggingface&utm_medium=referral&utm_campaign=hf_org_card)
- [Prompt caching savings calculator](https://aicostbudget.com/en/prompt-caching-savings-calculator?utm_source=huggingface&utm_medium=referral&utm_campaign=hf_org_card)
- [Model price monitor](https://aicostbudget.com/en/model-price-monitor?utm_source=huggingface&utm_medium=referral&utm_campaign=hf_org_card)

## Use from code

- `npm install ai-api-pricing`: look up prices and estimate workload costs in JavaScript / TypeScript.
- `npx -y ai-api-pricing-mcp`: read-only MCP server for AI assistants.
- Source, methodology and history: [github.com/aicostbudget/ai-api-pricing-data](https://github.com/aicostbudget/ai-api-pricing-data)

Pricing data may change over time. Always verify final production costs with the official provider pricing pages. AICostBudget is independent and not affiliated with the listed providers.
