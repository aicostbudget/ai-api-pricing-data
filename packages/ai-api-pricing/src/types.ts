export type DataSource = "live" | "bundled";

export type FetchLike = (
  input: string | URL | Request,
  init?: RequestInit,
) => Promise<Response>;

export interface Pricing {
  currency: "USD";
  unit: "1M tokens" | null;
  input: number | null;
  output: number | null;
  cachedInput: number | null;
  cacheWrite: number | null;
  cacheWrite1h: number | null;
  batchInput: number | null;
  batchCachedInput: number | null;
  batchOutput: number | null;
}

export interface PricingTier {
  id: string;
  processingMode: string;
  pricingStatus: string;
  calculationDefault: boolean;
  promptTokenThreshold: number;
  thresholdComparison: "less_than" | "less_than_or_equal" | "greater_than" | "greater_than_or_equal";
  thresholdTokenBasis: string;
  cachedPromptTokensIncluded: boolean;
  wholeRequestPricing: boolean;
  currency: "USD";
  unit: "1M tokens";
  input: number;
  cachedInput: number;
  output: number;
}

export interface PricingComponent {
  id?: string;
  component?: string;
  amount?: number | string;
  unit?: string;
  currency?: string;
  processingMode?: string;
  pricingStatus?: string;
  calculationDefault?: boolean;
  [key: string]: unknown;
}

export interface ModelPrice {
  modelId: string;
  providerId: string;
  displayName: string;
  status: string;
  pricing: Pricing;
  pricingTiers: PricingTier[];
  pricingComponents: PricingComponent[];
  officialSourceUrl: string;
  lastVerifiedAt: string;
  releasedAt: string | null;
  effectiveFrom: string | null;
  notes: string;
  source: DataSource;
}

export interface PriceCatalog {
  generatedAt: string;
  lastVerifiedAt: string;
  license: string;
  models: ModelPrice[];
  source: DataSource;
  fallbackReason?: string;
}

export interface LoadPricesOptions {
  source?: DataSource;
  fetchImpl?: FetchLike;
}

export interface ListModelsOptions extends LoadPricesOptions {
  provider?: string;
  status?: string;
}

export interface EstimateCostInput extends LoadPricesOptions {
  modelId: string;
  inputTokens: number;
  outputTokens: number;
  cachedInputTokens?: number;
  batch?: boolean;
}

export interface Workload extends LoadPricesOptions {
  inputTokens: number;
  outputTokens: number;
  cachedInputTokens?: number;
  batch?: boolean;
}

export interface CostBreakdown {
  input: number;
  cachedInput: number;
  output: number;
}

export interface PricesUsed {
  currency: "USD";
  unit: "1M tokens";
  input: number | null;
  cachedInput: number | null;
  output: number | null;
  batch: boolean;
  tierId: string | null;
}

export interface CostEstimate {
  modelId: string;
  total: number;
  breakdown: CostBreakdown;
  pricesUsed: PricesUsed;
  assumptions: string[];
  officialSourceUrl: string;
  lastVerifiedAt: string;
  source: DataSource;
}

export interface ModelComparison extends CostEstimate {
  displayName: string;
  providerId: string;
}
