import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import * as z from "zod/v4";
import {
  compareModels,
  estimateCost,
  loadPrices,
  type DataSource,
  type FetchLike,
  type ModelPrice,
  type PriceCatalog,
} from "ai-api-pricing";
import { bundledPriceChangeEvents } from "./generated/bundled-events.js";
import { bundledModelPageUrls } from "./generated/bundled-pages.js";

const SITEMAP_URL = "https://aicostbudget.com/sitemap.xml";
const PRICE_CHANGES_URL = "https://raw.githubusercontent.com/aicostbudget/ai-api-pricing-data/main/data/price-change-events/events.jsonl";
const MODELS_INDEX_URL = "https://aicostbudget.com/en/models";
const PRICE_MONITOR_URL = "https://aicostbudget.com/en/model-price-monitor";
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;
const FETCH_TIMEOUT_MS = 10_000;

const outputSchema = {
  data: z.record(z.string(), z.unknown()),
  source: z.enum(["live", "bundled"]),
  bundled_fallback: z.boolean(),
  official_source_urls: z.array(z.string().url()),
  verified_at: z.string(),
  aicostbudget_url: z.string().url(),
};

type RawRecord = Record<string, unknown>;

interface ToolEnvelope extends Record<string, unknown> {
  data: RawRecord;
  source: DataSource;
  bundled_fallback: boolean;
  official_source_urls: string[];
  verified_at: string;
  aicostbudget_url: string;
}

export interface PricingMcpServerOptions {
  fetchImpl?: FetchLike;
  pricingSource?: DataSource;
}

interface PriceChangeResult {
  events: RawRecord[];
  source: DataSource;
  fallbackReason?: string;
}

function asRecord(value: unknown): RawRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Expected an object");
  }
  return value as RawRecord;
}

// $2.43 for normal amounts; keep significant digits for sub-cent totals ($0.0042).
function formatUsd(value: number): string {
  const fractionDigits = value !== 0 && Math.abs(value) < 0.01 ? 6 : 2;
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: fractionDigits }).format(value);
}

function dateOnly(value: string): string {
  return value.slice(0, 10);
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function textResult(summary: string, envelope: ToolEnvelope, fallbackReason?: string) {
  const fallback = envelope.bundled_fallback
    ? `\nData source: bundled fallback${fallbackReason ? ` (${fallbackReason})` : ""}.`
    : "";
  const footer = [
    `Official source URL(s): ${envelope.official_source_urls.join(", ") || "none"}`,
    `Verified ${dateOnly(envelope.verified_at)}`,
    `AICostBudget: ${envelope.aicostbudget_url}`,
  ].join("\n");
  return {
    content: [{ type: "text" as const, text: `${summary}${fallback}\n${footer}` }],
    structuredContent: envelope,
  };
}

function errorResult(message: string, footer: { sources?: string[]; verifiedAt?: string; pageUrl?: string } = {}) {
  const suffix = [
    `Official source URL(s): ${(footer.sources ?? []).join(", ") || "none"}`,
    `Verified ${dateOnly(footer.verifiedAt ?? new Date(0).toISOString())}`,
    `AICostBudget: ${footer.pageUrl ?? MODELS_INDEX_URL}`,
  ].join("\n");
  return { isError: true, content: [{ type: "text" as const, text: `${message}\n${suffix}` }] };
}

function slugForModel(modelId: string): string {
  return `${modelId.toLowerCase().replaceAll(".", "-").replace(/[^a-z0-9-]/g, "")}-pricing`;
}

function parseSitemap(xml: string): Set<string> {
  return new Set(
    [...xml.matchAll(/<loc>\s*(https:\/\/aicostbudget\.com\/en\/models\/[^<]+)\s*<\/loc>/g)]
      .map((match) => match[1].trim()),
  );
}

function normalizeSearch(value: string): string {
  return value.toLowerCase().replace(/[^a-z0-9]/g, "");
}

function levenshtein(left: string, right: string): number {
  const row = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let i = 1; i <= left.length; i += 1) {
    let previous = row[0];
    row[0] = i;
    for (let j = 1; j <= right.length; j += 1) {
      const current = row[j];
      row[j] = Math.min(row[j] + 1, row[j - 1] + 1, previous + (left[i - 1] === right[j - 1] ? 0 : 1));
      previous = current;
    }
  }
  return row[right.length];
}

function suggestions(models: ModelPrice[], query: string): ModelPrice[] {
  const needle = normalizeSearch(query);
  return [...models].sort((left, right) => {
    const leftScore = Math.min(levenshtein(needle, normalizeSearch(left.modelId)), levenshtein(needle, normalizeSearch(left.displayName)));
    const rightScore = Math.min(levenshtein(needle, normalizeSearch(right.modelId)), levenshtein(needle, normalizeSearch(right.displayName)));
    return leftScore - rightScore || left.modelId.localeCompare(right.modelId);
  }).slice(0, 5);
}

function resolveModel(catalog: PriceCatalog, query: string): { model?: ModelPrice; candidates: ModelPrice[] } {
  const needle = normalizeSearch(query);
  const exact = catalog.models.filter((model) =>
    normalizeSearch(model.modelId) === needle || normalizeSearch(model.displayName) === needle);
  if (exact.length === 1) return { model: exact[0], candidates: exact };
  if (exact.length > 1) return { candidates: exact };
  const partial = catalog.models.filter((model) => {
    const id = normalizeSearch(model.modelId);
    const name = normalizeSearch(model.displayName);
    return id.includes(needle) || name.includes(needle) || needle.includes(id);
  });
  if (partial.length === 1) return { model: partial[0], candidates: partial };
  return { candidates: partial.length > 0 ? partial.slice(0, 10) : suggestions(catalog.models, query) };
}

async function fetchText(fetchImpl: FetchLike, url: string): Promise<string> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(url, { signal: controller.signal });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return await response.text();
  } finally {
    clearTimeout(timeout);
  }
}

function parseEvents(jsonl: string): RawRecord[] {
  return jsonl.split(/\r?\n/).filter(Boolean).map((line) => asRecord(JSON.parse(line)));
}

export function createPricingMcpServer(options: PricingMcpServerOptions = {}): McpServer {
  const server = new McpServer({ name: "ai-api-pricing-mcp", version: "0.1.1" });
  const fetchImpl = options.fetchImpl ?? globalThis.fetch;
  let sitemapCache: { expiresAt: number; urls: Set<string> } | undefined;

  async function catalog(): Promise<PriceCatalog> {
    return loadPrices({ source: options.pricingSource, fetchImpl });
  }

  async function modelPage(modelId: string): Promise<string> {
    if (!sitemapCache || sitemapCache.expiresAt <= Date.now()) {
      try {
        if (!fetchImpl) throw new Error("global fetch is unavailable");
        const urls = parseSitemap(await fetchText(fetchImpl, SITEMAP_URL));
        if (urls.size === 0) throw new Error("sitemap has no English model pages");
        sitemapCache = { expiresAt: Date.now() + CACHE_TTL_MS, urls };
      } catch {
        sitemapCache = { expiresAt: Date.now() + CACHE_TTL_MS, urls: new Set(bundledModelPageUrls) };
      }
    }
    const candidate = `${MODELS_INDEX_URL}/${slugForModel(modelId)}`;
    return sitemapCache.urls.has(candidate) ? candidate : MODELS_INDEX_URL;
  }

  async function priceChanges(): Promise<PriceChangeResult> {
    try {
      if (!fetchImpl) throw new Error("global fetch is unavailable");
      return { events: parseEvents(await fetchText(fetchImpl, PRICE_CHANGES_URL)), source: "live" };
    } catch (error) {
      return {
        events: bundledPriceChangeEvents.map(asRecord),
        source: "bundled",
        fallbackReason: error instanceof Error ? error.message : String(error),
      };
    }
  }

  const annotations = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: true };

  server.registerTool("get_model_price", {
    title: "Get model price",
    description: "Find a model by ID or display name and return source-linked prices.",
    inputSchema: { model: z.string().min(1) },
    outputSchema,
    annotations,
  }, async ({ model }) => {
    const prices = await catalog();
    const resolved = resolveModel(prices, model);
    if (!resolved.model) {
      const names = resolved.candidates.map((candidate) => candidate.modelId);
      const newest = resolved.candidates.map((candidate) => candidate.lastVerifiedAt).sort().at(-1) ?? prices.lastVerifiedAt;
      return errorResult(`Ambiguous or unknown model '${model}'. Did you mean: ${names.join(", ") || "no close match"}?`, {
        sources: unique(resolved.candidates.map((candidate) => candidate.officialSourceUrl)),
        verifiedAt: newest,
      });
    }
    const page = await modelPage(resolved.model.modelId);
    const envelope: ToolEnvelope = {
      data: { model: resolved.model },
      source: prices.source,
      bundled_fallback: prices.source === "bundled",
      official_source_urls: [resolved.model.officialSourceUrl],
      verified_at: resolved.model.lastVerifiedAt,
      aicostbudget_url: page,
    };
    return textResult(`${resolved.model.displayName} (${resolved.model.modelId})\n${JSON.stringify(resolved.model.pricing, null, 2)}`, envelope, prices.fallbackReason);
  });

  server.registerTool("list_models", {
    title: "List models",
    description: "List source-linked models, optionally filtering by provider and maximum token prices.",
    inputSchema: {
      provider: z.string().min(1).optional(),
      max_input_price: z.number().nonnegative().optional(),
      max_output_price: z.number().nonnegative().optional(),
    },
    outputSchema,
    annotations,
  }, async ({ provider, max_input_price, max_output_price }) => {
    const prices = await catalog();
    const models = prices.models.filter((model) =>
      (!provider || model.providerId.toLowerCase() === provider.toLowerCase()) &&
      (max_input_price === undefined || (model.pricing.input !== null && model.pricing.input <= max_input_price)) &&
      (max_output_price === undefined || (model.pricing.output !== null && model.pricing.output <= max_output_price)));
    const envelope: ToolEnvelope = {
      data: { models },
      source: prices.source,
      bundled_fallback: prices.source === "bundled",
      official_source_urls: unique(models.map((model) => model.officialSourceUrl)),
      verified_at: models.map((model) => model.lastVerifiedAt).sort().at(-1) ?? prices.lastVerifiedAt,
      aicostbudget_url: MODELS_INDEX_URL,
    };
    return textResult(`${models.length} model(s) matched.\n${models.map((model) => `${model.modelId}: input ${model.pricing.input}, output ${model.pricing.output}`).join("\n")}`, envelope, prices.fallbackReason);
  });

  server.registerTool("estimate_monthly_cost", {
    title: "Estimate monthly cost",
    description: "Estimate monthly token cost from request volume, with optional cached-input and batch pricing.",
    inputSchema: {
      model: z.string().min(1),
      input_tokens_per_request: z.number().int().nonnegative(),
      output_tokens_per_request: z.number().int().nonnegative(),
      requests_per_month: z.number().int().nonnegative(),
      cached_input_ratio: z.number().min(0).max(1).optional(),
      use_batch: z.boolean().optional(),
    },
    outputSchema,
    annotations,
  }, async (args) => {
    const prices = await catalog();
    const resolved = resolveModel(prices, args.model);
    if (!resolved.model) {
      return errorResult(`Ambiguous or unknown model '${args.model}'. Did you mean: ${resolved.candidates.map((model) => model.modelId).join(", ")}?`, {
        sources: unique(resolved.candidates.map((model) => model.officialSourceUrl)),
        verifiedAt: resolved.candidates.map((model) => model.lastVerifiedAt).sort().at(-1) ?? prices.lastVerifiedAt,
      });
    }
    try {
      const totalInput = args.input_tokens_per_request * args.requests_per_month;
      const estimate = await estimateCost({
        modelId: resolved.model.modelId,
        inputTokens: totalInput,
        cachedInputTokens: Math.round(totalInput * (args.cached_input_ratio ?? 0)),
        outputTokens: args.output_tokens_per_request * args.requests_per_month,
        batch: args.use_batch,
        source: prices.source,
        fetchImpl,
      });
      const envelope: ToolEnvelope = {
        data: { estimate, requests_per_month: args.requests_per_month },
        source: estimate.source,
        bundled_fallback: estimate.source === "bundled",
        official_source_urls: [estimate.officialSourceUrl],
        verified_at: estimate.lastVerifiedAt,
        aicostbudget_url: await modelPage(estimate.modelId),
      };
      return textResult(
        `Estimated monthly cost: ${formatUsd(estimate.total)}\n${JSON.stringify(estimate.breakdown, null, 2)}`,
        envelope,
        estimate.source === "bundled" ? prices.fallbackReason : undefined,
      );
    } catch (error) {
      return errorResult(error instanceof Error ? error.message : String(error), {
        sources: [resolved.model.officialSourceUrl],
        verifiedAt: resolved.model.lastVerifiedAt,
        pageUrl: await modelPage(resolved.model.modelId),
      });
    }
  });

  server.registerTool("compare_models", {
    title: "Compare models",
    description: "Compare monthly costs for multiple models and sort them from lowest to highest total.",
    inputSchema: {
      models: z.array(z.string().min(1)).min(1),
      input_tokens_per_request: z.number().int().nonnegative(),
      output_tokens_per_request: z.number().int().nonnegative(),
      requests_per_month: z.number().int().nonnegative(),
    },
    outputSchema,
    annotations,
  }, async (args) => {
    const prices = await catalog();
    const resolved = args.models.map((query) => ({ query, result: resolveModel(prices, query) }));
    const ambiguous = resolved.find((item) => !item.result.model);
    if (ambiguous) {
      return errorResult(`Ambiguous or unknown model '${ambiguous.query}'. Did you mean: ${ambiguous.result.candidates.map((model) => model.modelId).join(", ")}?`, {
        sources: unique(ambiguous.result.candidates.map((model) => model.officialSourceUrl)),
        verifiedAt: ambiguous.result.candidates.map((model) => model.lastVerifiedAt).sort().at(-1) ?? prices.lastVerifiedAt,
      });
    }
    const modelIds = resolved.map((item) => item.result.model!.modelId);
    try {
      const comparisons = await compareModels(modelIds, {
        inputTokens: args.input_tokens_per_request * args.requests_per_month,
        outputTokens: args.output_tokens_per_request * args.requests_per_month,
        source: prices.source,
        fetchImpl,
      });
      const envelope: ToolEnvelope = {
        data: { comparisons, requests_per_month: args.requests_per_month },
        source: comparisons[0]?.source ?? prices.source,
        bundled_fallback: comparisons[0]?.source === "bundled",
        official_source_urls: unique(comparisons.map((comparison) => comparison.officialSourceUrl)),
        verified_at: comparisons.map((comparison) => comparison.lastVerifiedAt).sort().at(-1) ?? prices.lastVerifiedAt,
        aicostbudget_url: MODELS_INDEX_URL,
      };
      return textResult(
        comparisons.map((comparison) => `${comparison.modelId}: ${formatUsd(comparison.total)}`).join("\n"),
        envelope,
        comparisons[0]?.source === "bundled" ? prices.fallbackReason : undefined,
      );
    } catch (error) {
      return errorResult(error instanceof Error ? error.message : String(error), {
        sources: unique(resolved.map((item) => item.result.model!.officialSourceUrl)),
        verifiedAt: resolved.map((item) => item.result.model!.lastVerifiedAt).sort().at(-1) ?? prices.lastVerifiedAt,
      });
    }
  });

  server.registerTool("price_changes", {
    title: "Price changes",
    description: "List up to 20 newest source-linked price-change events.",
    inputSchema: {
      since: z.string().date().optional(),
      provider: z.string().min(1).optional(),
    },
    outputSchema,
    annotations,
  }, async ({ since, provider }) => {
    const result = await priceChanges();
    const events = result.events.filter((event) =>
      (!provider || String(event.provider_id).toLowerCase() === provider.toLowerCase()) &&
      (!since || String(event.detected_at ?? event.verified_at ?? event.effective_from) >= since))
      .sort((left, right) => String(right.detected_at ?? right.verified_at).localeCompare(String(left.detected_at ?? left.verified_at)))
      .slice(0, 20);
    const sources = unique(events.flatMap((event) => [
      typeof event.official_source_url === "string" ? event.official_source_url : "",
      typeof event.announcement_url === "string" ? event.announcement_url : "",
    ]));
    const verifiedAt = events.map((event) => String(event.verified_at ?? "")).sort().at(-1) || "1970-01-01";
    const envelope: ToolEnvelope = {
      data: { events },
      source: result.source,
      bundled_fallback: result.source === "bundled",
      official_source_urls: sources,
      verified_at: verifiedAt,
      aicostbudget_url: PRICE_MONITOR_URL,
    };
    return textResult(`${events.length} price change(s).\n${events.map((event) => `${event.detected_at}: ${event.provider_id}/${event.model_id} ${event.change_type}`).join("\n")}`, envelope, result.fallbackReason);
  });

  return server;
}
