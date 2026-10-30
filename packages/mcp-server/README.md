# ai-api-pricing-mcp

Read-only MCP server for the source-linked [AICostBudget AI API Pricing Dataset](https://aicostbudget.com/en/datasets/ai-api-pricing). It exposes model prices, filtered model lists, monthly cost estimates, comparisons, and price-change events. Every successful result includes official provider source URL(s), a verification date, and an AICostBudget page link.

Data, history and issue tracker: [aicostbudget/ai-api-pricing-data on GitHub](https://github.com/aicostbudget/ai-api-pricing-data). Spot a wrong price? [Open an issue](https://github.com/aicostbudget/ai-api-pricing-data/issues) with the official source link.

The server writes no files, collects no telemetry, and uses only these public endpoints at runtime:

- `https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json`
- `https://raw.githubusercontent.com/aicostbudget/ai-api-pricing-data/main/data/price-change-events/events.jsonl`
- `https://aicostbudget.com/sitemap.xml`

If live pricing or price-change loading fails, the response explicitly reports that the bundled fallback was used. Model-page links are emitted only when present in the sitemap; otherwise the server links to `https://aicostbudget.com/en/models`.

## Run

Node.js 18 or newer is required.

```bash
npx -y ai-api-pricing-mcp
```

## Claude Desktop

Add this entry under `mcpServers` in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ai-api-pricing": {
      "command": "npx",
      "args": ["-y", "ai-api-pricing-mcp"]
    }
  }
}
```

Restart Claude Desktop after saving the file.

## Install in Claude Desktop (MCPB)

The maintainer creates the GitHub Release and attaches `ai-api-pricing-mcp-<version>.mcpb`. Download the bundle from [GitHub Releases](https://github.com/aicostbudget/ai-api-pricing-data/releases), then double-click it or drag it into **Claude Desktop → Settings → Extensions** to install it.

## Claude Code

```bash
claude mcp add ai-api-pricing -- npx -y ai-api-pricing-mcp
```

## Cursor

Create `.cursor/mcp.json` in a project, or `~/.cursor/mcp.json` for global use:

```json
{
  "mcpServers": {
    "ai-api-pricing": {
      "command": "npx",
      "args": ["-y", "ai-api-pricing-mcp"]
    }
  }
}
```

## VS Code

Create `.vscode/mcp.json`:

```json
{
  "servers": {
    "ai-api-pricing": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "ai-api-pricing-mcp"]
    }
  }
}
```

## Tools

- `get_model_price({ model })`
- `list_models({ provider?, max_input_price?, max_output_price? })`
- `estimate_monthly_cost({ model, input_tokens_per_request, output_tokens_per_request, requests_per_month, cached_input_ratio?, use_batch? })`
- `compare_models({ models, input_tokens_per_request, output_tokens_per_request, requests_per_month })`
- `price_changes({ since?, provider? })`

Model matching accepts exact IDs and display names. A fuzzy query that matches multiple models returns an explicit “Did you mean” list instead of silently choosing one. Cost estimates refuse missing required prices; they never substitute a standard, cache, or batch rate.

## Demo transcript

```text
User: Get the price of gpt-4.1.
Assistant → get_model_price: GPT-4.1; input 2, cached input 0.5, output 8 USD per 1M tokens; official source and verified date included.

User: List OpenAI models with input price at most $2 per million tokens.
Assistant → list_models: Matching model IDs and source-linked rates.

User: Estimate 1,000 monthly requests with 1,000 input and 100 output tokens on gpt-4.1.
Assistant → estimate_monthly_cost: $2.80 before taxes, contracts, credits, or provider rounding.

User: Compare gpt-4.1 and claude-haiku-5-5 for that workload.
Assistant → compare_models: Results sorted from lowest to highest estimated total.

User: Show OpenAI price changes since 2026-01-01.
Assistant → price_changes: Up to 20 newest matching events with source URLs and the price monitor link.
```

## Troubleshooting

- **Client cannot start `npx`:** install Node.js 18+ and ensure `node` and `npx` are on the client application's PATH.
- **First launch is slow:** `npx` may need to download the package once. Corporate proxies must allow the npm registry and the three documented runtime URLs.
- **Bundled fallback appears:** the live URL timed out, returned a non-2xx response, or failed validation. The response remains usable but may be older; inspect its verification date.
- **Missing-price error:** the requested cache, batch, input, or output rate is not present. Change the workload only if that matches the real provider billing mode; the server will not guess.
- **A model links to `/en/models`:** the model-specific URL was absent from the current sitemap and the index link is intentional.
