# Package and MCP registry submission drafts

Drafted 2026-10-21. These are human-reviewed submission materials only. Nothing in this file publishes a package, registry entry, pull request, or listing.

## punkpeye/awesome-mcp-servers

Current rule audit: the list accepts servers with a public GitHub repository that users install and run themselves. Entries must be one line, categorized, alphabetized, factual, and use the README language/scope legend. `Finance & Fintech` is the closest current category. This TypeScript server calls public remote data endpoints, so the legend is `📇 ☁️`.

Exact README entry:

```markdown
- [aicostbudget/ai-api-pricing-data](https://github.com/aicostbudget/ai-api-pricing-data) 📇 ☁️ - Read-only AI API pricing tools with official provider source URLs and verification dates, including model lookup, filtering, monthly cost estimates, comparisons and price-change events.
```

PR title:

```text
Add AICostBudget AI API Pricing MCP server
```

PR body:

```text
Adds the AICostBudget AI API Pricing MCP server to Finance & Fintech. The server is installed from its public GitHub/npm project, runs over stdio, and reads public source-linked pricing data. It exposes read-only model lookup, filtering, cost-estimation, comparison, and price-change tools.

Disclosure: I maintain the linked project.
```

The repository's automated-agent title suffix is optional for a human submission and is not included above.

## Official MCP Registry

The package must be public on npm before Registry publication. `packages/mcp-server/package.json#mcpName` and `packages/mcp-server/server.json#name` are both `io.github.aicostbudget/ai-api-pricing-mcp`. The publisher must authenticate as a GitHub user who is an Owner of the `aicostbudget` organization; ordinary membership is insufficient for the organization namespace.

After npm publication, from `packages/mcp-server`:

```powershell
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "D:\ai-cost-control-tool\ai-api-pricing-data\packages\mcp-server"
mcp-publisher validate
if ($LASTEXITCODE -ne 0) { throw "mcp-publisher validate failed with exit code $LASTEXITCODE" }
mcp-publisher login github
if ($LASTEXITCODE -ne 0) { throw "mcp-publisher login failed with exit code $LASTEXITCODE" }
mcp-publisher publish
if ($LASTEXITCODE -ne 0) { throw "mcp-publisher publish failed with exit code $LASTEXITCODE" }
```

The official Registry is currently preview software. Confirm the live schema and publisher release immediately before publication.

## MCPB bundle (GitHub Releases, Claude Desktop)

Build and test the self-contained MCPB bundle from the repository root:

```powershell
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath "D:\ai-api-pricing-data"
npm.cmd ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed with exit code $LASTEXITCODE" }
npm.cmd run build:mcpb
if ($LASTEXITCODE -ne 0) { throw "npm run build:mcpb failed with exit code $LASTEXITCODE" }
npm.cmd run test:mcpb
if ($LASTEXITCODE -ne 0) { throw "npm run test:mcpb failed with exit code $LASTEXITCODE" }
```

Manual GitHub Release checklist:

1. Confirm the source commit and that `npm test`, `npm run build`, `npm run build:mcpb`, and `npm run test:mcpb` pass.
2. Create the maintainer-approved GitHub Release `vX` for that exact commit.
3. Attach `dist-mcpb/ai-api-pricing-mcp-X.mcpb` and record the build output's size and SHA-256.
4. Verify the uploaded asset hash matches the local bundle. Never commit the `.mcpb` file.

## Smithery (dropped 2026-10-22)

Not pursued. Smithery announced that on 2026-10-31 it shuts down its connection management services: server URLs on run.tools and server.smithery.ai, the Smithery API, Connect and Toolbox, Smithery accounts and API keys, and the CLI and SDKs (deprecated). smithery.ai remains only as a public, non-proxied directory that shows vendors' own MCP URLs ([notice](https://smithery.ai/future), checked 2026-10-22).

This server is a local stdio package with no hosted MCP URL, so a directory-only listing adds little. A publish attempt on 2026-10-22 was also rejected with HTTP 403 ("Updating servers has been removed"). The `.smithery.mcpb` variant built by `build:mcpb` is no longer needed for distribution; the standard `.mcpb` above remains the bundle for GitHub Releases and Claude Desktop.

## Glama

On Glama's Servers page, choose **Add MCP Server** and provide:

- GitHub repository: `https://github.com/aicostbudget/ai-api-pricing-data`
- Display name: `AICostBudget AI API Pricing`
- Description: `Read-only source-linked AI API prices, comparisons, monthly cost estimates and price-change events.`

Glama performs license, security, and health checks during indexing. Because the repository is organization-owned, claiming the listing also requires a root `glama.json` naming authorized GitHub maintainer usernames, followed by the Claim ownership flow. That file is intentionally not drafted with a guessed username.

## ankitvirdi4/awesome-llm-cost

Target category: `Pricing Data`.

Exact future entry:

```markdown
- [AICostBudget AI API Pricing Dataset](https://github.com/aicostbudget/ai-api-pricing-data) — Source-linked AI API pricing data with an npm library and read-only MCP server for model lookup, comparisons, cost estimates, and price-change events.
```

PR title:

```text
Add AICostBudget AI API Pricing Dataset
```

PR body:

```text
Adds one entry to Pricing Data for a maintained public dataset and its npm/MCP consumers. Records carry official provider source URLs and verification dates; descriptions and estimates do not replace provider billing records.

Disclosure: I maintain the linked project.
```

Eligibility blocker: the list requires at least six months of public history plus a real-world-use signal. GitHub reports this repository was created 2026-07-05, so it is not yet six months old on 2026-10-21. Do not submit this PR until the time threshold and a qualifying use signal are both verifiable. The list also rejects mass cross-posting; submit independently, not as part of a bulk awesome-list sweep.

## jmfontaine/awesome-finops

Target category: `Tools` → `Open Source Tools`. Keep the category alphabetized.

Exact entry:

```markdown
- [AICostBudget AI API Pricing Dataset](https://github.com/aicostbudget/ai-api-pricing-data) - Provides source-linked AI API pricing data, an npm library and a read-only MCP server for cost estimates and price changes.
```

PR title:

```text
Add AICostBudget AI API Pricing Dataset
```

PR body:

```text
Adds one open source FinOps data/tooling entry. The dataset records official provider source URLs and verification dates, and its npm and MCP consumers provide read-only pricing lookup and cost estimation.

Disclosure: I maintain the linked project.
```

## Hugging Face dataset card

The prepared local mirror diff adds this paragraph below `## Explore and download` in `huggingface/README.md`:

```markdown
For JavaScript or TypeScript, the proposed `ai-api-pricing` npm package provides source-linked lookups and cost estimates. AI assistants can use the proposed read-only `ai-api-pricing-mcp` server for model prices, comparisons, monthly estimates, and price-change events. Both packages are developed in the [source repository](https://github.com/aicostbudget/ai-api-pricing-data/tree/main/packages); package and registry publication remain separate maintainer steps.
```

The repository's existing Hugging Face publisher allowlist contains only `prices.json`, `prices.csv`, `train.csv`, and `meta.json`; this README change is a versioned manual mirror and is not automatically published to Hugging Face.
