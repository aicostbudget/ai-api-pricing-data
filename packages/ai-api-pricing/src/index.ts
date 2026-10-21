import { bundledPriceDocument } from "./generated/bundled.js";
import type {
  CostEstimate,
  DataSource,
  EstimateCostInput,
  FetchLike,
  ListModelsOptions,
  LoadPricesOptions,
  ModelComparison,
  ModelPrice,
  PriceCatalog,
  Pricing,
  PricingComponent,
  PricingTier,
  PricesUsed,
  Workload,
} from "./types.js";

export type * from "./types.js";

export const LIVE_PRICES_URL = "https://aicostbudget.github.io/ai-api-pricing-data/api/v1/prices.json";
const FETCH_TIMEOUT_MS = 10_000;

export class PricingDataError extends Error {
  constructor(message: string, readonly code: string) {
    super(message);
    this.name = new.target.name;
  }
}

export class ModelNotFoundError extends PricingDataError {
  constructor(modelId: string) {
    super(`Unknown model: ${modelId}`, "MODEL_NOT_FOUND");
  }
}

export class MissingPriceError extends PricingDataError {
  constructor(modelId: string, component: string) {
    super(`Cannot estimate ${modelId}: required ${component} price is missing.`, "MISSING_PRICE");
  }
}

export class InvalidWorkloadError extends PricingDataError {
  constructor(message: string) {
    super(message, "INVALID_WORKLOAD");
  }
}

export class UnsupportedPricingError extends PricingDataError {
  constructor(message: string) {
    super(message, "UNSUPPORTED_PRICING");
  }
}

interface RawDocument {
  generated_at?: unknown;
  last_verified_at?: unknown;
  licenses?: { data?: unknown };
  models?: unknown;
}

type RawRecord = Record<string, unknown>;

function asRecord(value: unknown): RawRecord {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new PricingDataError("Pricing document contains a non-object record.", "INVALID_DATA");
  }
  return value as RawRecord;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new PricingDataError(`Pricing document is missing ${field}.`, "INVALID_DATA");
  }
  return value;
}

function nullableString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function nullableNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function normalizePricing(value: unknown): Pricing {
  const raw = asRecord(value);
  if (raw.currency !== "USD") {
    throw new PricingDataError("Only USD pricing is supported by this package.", "UNSUPPORTED_CURRENCY");
  }
  const unit = raw.unit === "1M tokens" ? "1M tokens" : null;
  return {
    currency: "USD",
    unit,
    input: nullableNumber(raw.input),
    output: nullableNumber(raw.output),
    cachedInput: nullableNumber(raw.cached_input),
    cacheWrite: nullableNumber(raw.cache_write),
    cacheWrite1h: nullableNumber(raw.cache_write_1h),
    batchInput: nullableNumber(raw.batch_input),
    batchCachedInput: nullableNumber(raw.batch_cached_input),
    batchOutput: nullableNumber(raw.batch_output),
  };
}

function normalizeTier(value: unknown): PricingTier {
  const raw = asRecord(value);
  const comparison = requiredString(raw.threshold_comparison, "pricing_tiers[].threshold_comparison");
  if (!["less_than", "less_than_or_equal", "greater_than", "greater_than_or_equal"].includes(comparison)) {
    throw new PricingDataError(`Unsupported tier comparison: ${comparison}`, "INVALID_DATA");
  }
  if (raw.currency !== "USD" || raw.unit !== "1M tokens") {
    throw new PricingDataError("Tier pricing must be USD per 1M tokens.", "INVALID_DATA");
  }
  const input = nullableNumber(raw.input);
  const cachedInput = nullableNumber(raw.cached_input);
  const output = nullableNumber(raw.output);
  const threshold = nullableNumber(raw.prompt_token_threshold);
  if (input === null || cachedInput === null || output === null || threshold === null) {
    throw new PricingDataError("Tier pricing contains a missing numeric field.", "INVALID_DATA");
  }
  return {
    id: requiredString(raw.id, "pricing_tiers[].id"),
    processingMode: requiredString(raw.processing_mode, "pricing_tiers[].processing_mode"),
    pricingStatus: requiredString(raw.pricing_status, "pricing_tiers[].pricing_status"),
    calculationDefault: raw.calculation_default === true,
    promptTokenThreshold: threshold,
    thresholdComparison: comparison as PricingTier["thresholdComparison"],
    thresholdTokenBasis: requiredString(raw.threshold_token_basis, "pricing_tiers[].threshold_token_basis"),
    cachedPromptTokensIncluded: raw.cached_prompt_tokens_included === true,
    wholeRequestPricing: raw.whole_request_pricing === true,
    currency: "USD",
    unit: "1M tokens",
    input,
    cachedInput,
    output,
  };
}

function normalizeModel(value: unknown, source: DataSource): ModelPrice {
  const raw = asRecord(value);
  return {
    modelId: requiredString(raw.model_id, "models[].model_id"),
    providerId: requiredString(raw.provider_id, "models[].provider_id"),
    displayName: requiredString(raw.display_name, "models[].display_name"),
    status: requiredString(raw.status, "models[].status"),
    pricing: normalizePricing(raw.pricing),
    pricingTiers: Array.isArray(raw.pricing_tiers) ? raw.pricing_tiers.map(normalizeTier) : [],
    pricingComponents: Array.isArray(raw.pricing_components)
      ? raw.pricing_components.map((component) => ({ ...asRecord(component) } as PricingComponent))
      : [],
    officialSourceUrl: requiredString(raw.official_source_url, "models[].official_source_url"),
    lastVerifiedAt: requiredString(raw.last_verified_at, "models[].last_verified_at"),
    releasedAt: nullableString(raw.released_at),
    effectiveFrom: nullableString(raw.effective_from),
    notes: typeof raw.notes === "string" ? raw.notes : "",
    source,
  };
}

function normalizeDocument(value: unknown, source: DataSource, fallbackReason?: string): PriceCatalog {
  const raw = asRecord(value) as RawDocument;
  if (!Array.isArray(raw.models)) {
    throw new PricingDataError("Pricing document is missing models[].", "INVALID_DATA");
  }
  return {
    generatedAt: requiredString(raw.generated_at, "generated_at"),
    lastVerifiedAt: requiredString(raw.last_verified_at, "last_verified_at"),
    license: requiredString(raw.licenses?.data, "licenses.data"),
    models: raw.models.map((model) => normalizeModel(model, source)),
    source,
    ...(fallbackReason ? { fallbackReason } : {}),
  };
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function fetchLive(fetchImpl: FetchLike): Promise<unknown> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  try {
    const response = await fetchImpl(LIVE_PRICES_URL, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timeout);
  }
}

export async function loadPrices(options: LoadPricesOptions = {}): Promise<PriceCatalog> {
  if ((options.source ?? "live") === "bundled") {
    return normalizeDocument(bundledPriceDocument, "bundled");
  }
  try {
    const fetchImpl = options.fetchImpl ?? globalThis.fetch;
    if (!fetchImpl) {
      throw new Error("global fetch is unavailable");
    }
    return normalizeDocument(await fetchLive(fetchImpl), "live");
  } catch (error) {
    return normalizeDocument(bundledPriceDocument, "bundled", errorMessage(error));
  }
}

function findModel(catalog: PriceCatalog, modelId: string): ModelPrice {
  const normalized = modelId.trim().toLowerCase();
  const model = catalog.models.find((candidate) => candidate.modelId.toLowerCase() === normalized);
  if (!model) {
    throw new ModelNotFoundError(modelId);
  }
  return model;
}

export async function getPrice(modelId: string, options: LoadPricesOptions = {}): Promise<ModelPrice> {
  return findModel(await loadPrices(options), modelId);
}

export async function listModels(options: ListModelsOptions = {}): Promise<ModelPrice[]> {
  const catalog = await loadPrices(options);
  const provider = options.provider?.trim().toLowerCase();
  const status = options.status?.trim().toLowerCase();
  return catalog.models.filter((model) =>
    (!provider || model.providerId.toLowerCase() === provider) &&
    (!status || model.status.toLowerCase() === status));
}

function assertTokenCount(name: string, value: number): void {
  if (!Number.isFinite(value) || value < 0 || !Number.isInteger(value)) {
    throw new InvalidWorkloadError(`${name} must be a non-negative integer.`);
  }
}

function thresholdMatches(tier: PricingTier, promptTokens: number): boolean {
  switch (tier.thresholdComparison) {
    case "less_than": return promptTokens < tier.promptTokenThreshold;
    case "less_than_or_equal": return promptTokens <= tier.promptTokenThreshold;
    case "greater_than": return promptTokens > tier.promptTokenThreshold;
    case "greater_than_or_equal": return promptTokens >= tier.promptTokenThreshold;
  }
}

function selectTier(model: ModelPrice, promptTokens: number, batch: boolean): PricingTier | null {
  const mode = batch ? "batch" : "standard";
  const tiers = model.pricingTiers.filter((tier) => tier.pricingStatus === "current" && tier.processingMode === mode);
  if (tiers.length === 0) return null;
  for (const tier of tiers) {
    if (tier.thresholdTokenBasis !== "total_prompt_tokens" || !tier.wholeRequestPricing) {
      throw new UnsupportedPricingError(`Cannot safely apply tier ${tier.id} for ${model.modelId}.`);
    }
  }
  const matches = tiers.filter((tier) => !tier.calculationDefault && thresholdMatches(tier, promptTokens));
  if (matches.length > 1) {
    throw new UnsupportedPricingError(`Multiple pricing tiers match ${model.modelId}.`);
  }
  if (matches.length === 1) return matches[0];
  const defaults = tiers.filter((tier) => tier.calculationDefault);
  if (defaults.length !== 1) {
    throw new UnsupportedPricingError(`No unambiguous pricing tier matches ${model.modelId}.`);
  }
  return defaults[0];
}

function requiredRate(model: ModelPrice, component: string, value: number | null, tokens: number): number | null {
  if (tokens === 0) return value;
  if (value === null) throw new MissingPriceError(model.modelId, component);
  return value;
}

function estimateFromModel(model: ModelPrice, workload: Workload): CostEstimate {
  const cached = workload.cachedInputTokens ?? 0;
  const batch = workload.batch ?? false;
  assertTokenCount("inputTokens", workload.inputTokens);
  assertTokenCount("outputTokens", workload.outputTokens);
  assertTokenCount("cachedInputTokens", cached);
  if (cached > workload.inputTokens) {
    throw new InvalidWorkloadError("cachedInputTokens cannot exceed inputTokens.");
  }
  const uncached = workload.inputTokens - cached;
  const tier = selectTier(model, workload.inputTokens, batch);
  if (!tier && model.pricing.unit !== "1M tokens") {
    throw new UnsupportedPricingError(`${model.modelId} is not priced per 1M tokens.`);
  }

  const rawInputRate = tier?.input ?? (batch ? model.pricing.batchInput : model.pricing.input);
  const rawCachedRate = tier?.cachedInput ?? (batch ? model.pricing.batchCachedInput : model.pricing.cachedInput);
  const rawOutputRate = tier?.output ?? (batch ? model.pricing.batchOutput : model.pricing.output);
  const inputRate = requiredRate(model, batch ? "batch input" : "input", rawInputRate, uncached);
  const cachedRate = requiredRate(model, batch ? "batch cached input" : "cached input", rawCachedRate, cached);
  const outputRate = requiredRate(model, batch ? "batch output" : "output", rawOutputRate, workload.outputTokens);
  const inputCost = uncached * (inputRate ?? 0) / 1_000_000;
  const cachedCost = cached * (cachedRate ?? 0) / 1_000_000;
  const outputCost = workload.outputTokens * (outputRate ?? 0) / 1_000_000;
  const pricesUsed: PricesUsed = {
    currency: "USD",
    unit: "1M tokens",
    input: inputRate,
    cachedInput: cachedRate,
    output: outputRate,
    batch,
    tierId: tier?.id ?? null,
  };
  const assumptions = [
    "inputTokens includes cachedInputTokens; only the remainder is billed at the uncached input rate.",
    "Catalog rates exclude taxes, negotiated discounts, credits, and provider-specific rounding.",
    tier ? `Tier ${tier.id} prices the whole request using total prompt tokens.` : "The dataset compatibility/default token rates are used.",
  ];
  return {
    modelId: model.modelId,
    total: inputCost + cachedCost + outputCost,
    breakdown: { input: inputCost, cachedInput: cachedCost, output: outputCost },
    pricesUsed,
    assumptions,
    officialSourceUrl: model.officialSourceUrl,
    lastVerifiedAt: model.lastVerifiedAt,
    source: model.source,
  };
}

export async function estimateCost(input: EstimateCostInput): Promise<CostEstimate> {
  const catalog = await loadPrices({ source: input.source, fetchImpl: input.fetchImpl });
  return estimateFromModel(findModel(catalog, input.modelId), input);
}

export async function compareModels(modelIds: string[], workload: Workload): Promise<ModelComparison[]> {
  if (!Array.isArray(modelIds) || modelIds.length === 0) {
    throw new InvalidWorkloadError("modelIds must contain at least one model.");
  }
  const catalog = await loadPrices({ source: workload.source, fetchImpl: workload.fetchImpl });
  return modelIds.map((modelId) => {
    const model = findModel(catalog, modelId);
    return {
      ...estimateFromModel(model, workload),
      displayName: model.displayName,
      providerId: model.providerId,
    };
  }).sort((left, right) => left.total - right.total || left.modelId.localeCompare(right.modelId));
}
