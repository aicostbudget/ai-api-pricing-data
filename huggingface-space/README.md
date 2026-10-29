---
title: LLM API Pricing Calculator
emoji: 💸
colorFrom: indigo
colorTo: green
sdk: static
app_file: index.html
pinned: true
license: cc-by-4.0
short_description: Compare LLM API prices and estimate monthly cost
tags:
  - llm
  - pricing
  - llm-pricing
  - api-pricing
  - cost-calculator
  - token-cost
  - openai
  - anthropic
  - gemini
  - deepseek
  - qwen
datasets:
  - aicostbudget-ai/ai-api-pricing
  - aicostbudget-ai/llm-api-price-history
---

# LLM API Pricing Calculator

Compare API prices per 1M tokens and estimate your monthly bill across OpenAI, Anthropic, Google, xAI, DeepSeek, Mistral, Alibaba Qwen, Moonshot AI, Cohere, Meta and more.

- **Price table:** input, cached-input and output prices with the date each price was verified and a link to the official provider page.
- **Monthly cost estimate:** enter tokens per request, cached share and monthly requests; models are ranked from cheapest.
- **Price changes:** verified provider price changes, new models, deprecations and retirements.

Prices load live from the [AI API Pricing Dataset](https://huggingface.co/datasets/aicostbudget-ai/ai-api-pricing) and the [LLM API Price History](https://huggingface.co/datasets/aicostbudget-ai/llm-api-price-history) on every visit, so the Space is current after each dataset release.

For cost per successful task when switching models, use the [Model Switch Cost Calculator](https://aicostbudget.com/en/model-switch-cost-calculator?utm_source=huggingface&utm_medium=referral&utm_campaign=hf_space&utm_content=readme).

Prices change often. Verify against the provider's pricing page before production billing decisions. AICostBudget is independent and not affiliated with the listed providers.
