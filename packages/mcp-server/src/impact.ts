// get_price_impact: what each recorded price change of one model does to a monthly workload.
// Pure functions over price-change events (old_prices / new_prices per 1M tokens). A price the workload needs and an event
// does not list is never filled in: that event is skipped with the reason, and a net total is only given when every change
// in effect could be priced and the changes connect.

export interface EventPriceTriple {
  input: number | null;
  output: number | null;
  cached_input: number | null;
}

export interface ImpactWorkload {
  inputTokensPerRequest: number;
  outputTokensPerRequest: number;
  requestsPerMonth: number;
  /** Share of the input tokens read from cache, 0 to 1. */
  cachedInputRatio: number;
}

export type ImpactDirection = "cheaper" | "more_expensive" | "no_change_for_workload";
export type ImpactStatus = "in_effect" | "scheduled";

export interface ChangedPrice {
  component: "input" | "cached_input" | "output";
  before: number | null;
  after: number | null;
  /** True when the workload uses this component, so the change moves its cost. */
  used_by_workload: boolean;
}

export interface PriceImpactEntry {
  event_id: string;
  change_type: string;
  /** effective_from when the provider gave a date, else the day the monitor first saw the change. */
  date: string;
  date_basis: string;
  status: ImpactStatus;
  before_monthly_usd: number;
  after_monthly_usd: number;
  delta_monthly_usd: number;
  /** Null when the monthly cost before the change is zero. */
  delta_percent: number | null;
  direction: ImpactDirection;
  changed_prices: ChangedPrice[];
  official_source_url: string | null;
  announcement_url: string | null;
}

export interface PriceImpactSkip {
  event_id: string;
  change_type: string;
  date: string;
  date_basis: string;
  status: ImpactStatus;
  reason: string;
}

export interface PriceImpactNet {
  from_date: string;
  to_date: string;
  before_monthly_usd: number;
  after_monthly_usd: number;
  delta_monthly_usd: number;
  delta_percent: number | null;
  changes: number;
}

export interface PriceImpactResult {
  entries: PriceImpactEntry[];
  skipped: PriceImpactSkip[];
  /** Across the in-effect changes, oldest to newest; null with `net_unavailable_reason` when it cannot be stated. */
  net: PriceImpactNet | null;
  net_unavailable_reason: string | null;
}

type RawRecord = Record<string, unknown>;

/** Same-model price changes the tool prices. Launches, successors and lifecycle notices are not price changes. */
const PRICED_TYPES = new Set(["price_update", "component_price_update", "cached_price_added", "cached_price_removed", "scheduled_price_change", "temporal_price_schedule_update"]);
const COMPONENTS = ["input", "cached_input", "output"] as const;
const COMPONENT_LABELS: Record<(typeof COMPONENTS)[number], string> = { input: "input", cached_input: "cached input", output: "output" };

const dateOnly = (value: unknown) => typeof value === "string" ? value.slice(0, 10) : "";
const numberOrNull = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value : null;

function triple(value: unknown): EventPriceTriple {
  const record = (value && typeof value === "object" && !Array.isArray(value) ? value : {}) as RawRecord;
  return { input: numberOrNull(record.input), output: numberOrNull(record.output), cached_input: numberOrNull(record.cached_input) };
}

export function eventDate(event: RawRecord): string {
  return dateOnly(event.effective_from) || dateOnly(event.detected_at) || dateOnly(event.verified_at);
}

/** Monthly cost of the workload at the given rates (USD per 1M tokens), or the name of the first rate it needs and lacks. */
export function monthlyCost(workload: ImpactWorkload, rates: EventPriceTriple): { cost: number } | { missing: "input" | "cached_input" | "output" } {
  const totalInput = workload.inputTokensPerRequest * workload.requestsPerMonth;
  const cached = Math.round(totalInput * workload.cachedInputRatio);
  const uncached = totalInput - cached;
  const output = workload.outputTokensPerRequest * workload.requestsPerMonth;
  if (uncached > 0 && rates.input === null) return { missing: "input" };
  if (cached > 0 && rates.cached_input === null) return { missing: "cached_input" };
  if (output > 0 && rates.output === null) return { missing: "output" };
  return { cost: (uncached * (rates.input ?? 0) + cached * (rates.cached_input ?? 0) + output * (rates.output ?? 0)) / 1_000_000 };
}

function usedComponents(workload: ImpactWorkload) {
  const totalInput = workload.inputTokensPerRequest * workload.requestsPerMonth;
  const cached = Math.round(totalInput * workload.cachedInputRatio);
  return { input: totalInput - cached > 0, cached_input: cached > 0, output: workload.outputTokensPerRequest * workload.requestsPerMonth > 0 };
}

const sameRates = (left: EventPriceTriple, right: EventPriceTriple) => COMPONENTS.every((component) => left[component] === right[component]);

/** `today` is a YYYY-MM-DD day: a change dated after it is scheduled, not in effect. */
export function computePriceImpact(events: readonly RawRecord[], modelId: string, workload: ImpactWorkload, options: { since?: string; includeScheduled?: boolean; today: string; limit?: number }): PriceImpactResult {
  const used = usedComponents(workload);
  const wanted = events
    .filter((event) => PRICED_TYPES.has(String(event.change_type)) && String(event.model_id).toLowerCase() === modelId.toLowerCase())
    .map((event) => ({ event, date: eventDate(event) }))
    .filter(({ date }) => date !== "" && (!options.since || date >= options.since))
    .map((item) => ({ ...item, status: (item.date > options.today ? "scheduled" : "in_effect") as ImpactStatus }))
    .filter((item) => options.includeScheduled !== false || item.status === "in_effect")
    .sort((left, right) => left.date.localeCompare(right.date) || String(left.event.event_id).localeCompare(String(right.event.event_id)));

  const entries: Array<PriceImpactEntry & { before_rates: EventPriceTriple; after_rates: EventPriceTriple }> = [];
  const skipped: PriceImpactSkip[] = [];
  for (const { event, date, status } of wanted) {
    const eventId = String(event.event_id);
    const changeType = String(event.change_type);
    const before = triple(event.old_prices), after = triple(event.new_prices);
    const skip = (reason: string) => skipped.push({ event_id: eventId, change_type: changeType, date, date_basis: String(event.date_basis ?? "unknown"), status, reason });
    if (changeType === "temporal_price_schedule_update") { skip("The model is billed by time of day, so its monthly cost depends on when the requests run. This tool does not price that."); continue; }
    const priceBefore = monthlyCost(workload, before);
    if ("missing" in priceBefore) { skip(`The ${COMPONENT_LABELS[priceBefore.missing]} price before this change is not listed, and this workload needs it, so no price is assumed.`); continue; }
    const priceAfter = monthlyCost(workload, after);
    if ("missing" in priceAfter) { skip(`The ${COMPONENT_LABELS[priceAfter.missing]} price after this change is not listed, and this workload needs it, so no price is assumed.`); continue; }
    const delta = priceAfter.cost - priceBefore.cost;
    const epsilon = 1e-12 * Math.max(1, Math.abs(priceBefore.cost));
    const direction: ImpactDirection = Math.abs(delta) <= epsilon ? "no_change_for_workload" : delta < 0 ? "cheaper" : "more_expensive";
    entries.push({
      event_id: eventId, change_type: changeType, date, date_basis: String(event.date_basis ?? "unknown"), status,
      before_monthly_usd: priceBefore.cost, after_monthly_usd: priceAfter.cost, delta_monthly_usd: Math.abs(delta) <= epsilon ? 0 : delta,
      delta_percent: priceBefore.cost === 0 ? null : (Math.abs(delta) <= epsilon ? 0 : delta / priceBefore.cost * 100), direction,
      changed_prices: COMPONENTS.filter((component) => before[component] !== after[component])
        .map((component) => ({ component, before: before[component], after: after[component], used_by_workload: used[component] })),
      official_source_url: typeof event.official_source_url === "string" ? event.official_source_url : null,
      announcement_url: typeof event.announcement_url === "string" ? event.announcement_url : null,
      before_rates: before, after_rates: after,
    });
  }

  // Net across the changes already in effect: only when none of them was skipped and each one starts where the previous ended.
  const inEffect = entries.filter((entry) => entry.status === "in_effect");
  const skippedInEffect = skipped.filter((item) => item.status === "in_effect");
  let net: PriceImpactNet | null = null;
  let netReason: string | null = null;
  if (inEffect.length === 0) netReason = "No change in effect is priced for this workload.";
  else if (skippedInEffect.length > 0) netReason = "A change in effect could not be priced, so a net total would leave it out.";
  else if (inEffect.some((entry, index) => index > 0 && !sameRates(inEffect[index - 1].after_rates, entry.before_rates))) netReason = "The recorded changes do not connect: a later change does not start from the price the previous one set.";
  else {
    const first = inEffect[0], last = inEffect[inEffect.length - 1];
    const delta = last.after_monthly_usd - first.before_monthly_usd;
    net = {
      from_date: first.date, to_date: last.date, before_monthly_usd: first.before_monthly_usd, after_monthly_usd: last.after_monthly_usd, delta_monthly_usd: delta,
      delta_percent: first.before_monthly_usd === 0 ? null : delta / first.before_monthly_usd * 100, changes: inEffect.length,
    };
  }

  // Newest first, like price_changes. A net total always describes all the in-effect changes, not only the ones shown.
  const limit = options.limit ?? 20;
  const shown = [...entries].reverse().slice(0, limit).map(({ before_rates: _before, after_rates: _after, ...entry }) => entry);
  return { entries: shown, skipped: [...skipped].reverse(), net, net_unavailable_reason: netReason };
}
