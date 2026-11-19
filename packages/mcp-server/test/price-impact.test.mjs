import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createPricingMcpServer } from "../dist/server.js";
import { computePriceImpact, monthlyCost } from "../dist/impact.js";

const fixture = JSON.parse(await readFile(new URL("../../ai-api-pricing/test/fixtures/prices.json", import.meta.url), "utf8"));
const sitemap = `<?xml version="1.0"?><urlset><url><loc>https://aicostbudget.com/en/models/gpt-4-1-pricing</loc></url></urlset>`;

const price = (input, cached_input, output) => ({ input, cached_input, output });
const base = { provider_id: "openai", model_id: "gpt-4.1", verified_at: "2026-10-09", official_source_url: "https://developers.openai.com/api/docs/pricing", announcement_url: null };
const eventA = { ...base, event_id: "a", change_type: "price_update", detected_at: "2026-06-01", effective_from: "2026-06-01", date_basis: "effective_from", old_prices: price(4, 1, 16), new_prices: price(2, 0.5, 8) };
const eventB = { ...base, event_id: "b", change_type: "scheduled_price_change", detected_at: "2026-10-09", effective_from: "2027-01-01", date_basis: "effective_from", old_prices: price(2, 0.5, 8), new_prices: price(3, 0.75, 12) };
const eventC = { ...base, event_id: "c", change_type: "cached_price_added", detected_at: "2026-03-01", date_basis: "first_observed", old_prices: price(4, null, 16), new_prices: price(4, 1, 16) };
const eventOther = { ...base, event_id: "other", model_id: "gpt-4.1-mini", change_type: "price_update", detected_at: "2026-09-01", old_prices: price(1, 0.25, 4), new_prices: price(0.4, 0.1, 1.6) };
const eventLaunch = { ...base, event_id: "launch", change_type: "model_added", detected_at: "2026-02-01", old_prices: null, new_prices: price(4, null, 16) };
const eventTime = { ...base, event_id: "time", change_type: "temporal_price_schedule_update", detected_at: "2026-05-01", old_prices: price(2, 0.5, 8), new_prices: price(2, 0.5, 8) };

// 1000 requests a month of 1000 input and 100 output tokens.
const noCache = { inputTokensPerRequest: 1000, outputTokensPerRequest: 100, requestsPerMonth: 1000, cachedInputRatio: 0 };
const quarterCached = { ...noCache, cachedInputRatio: 0.25 };

test("monthlyCost prices the three components and names a missing rate instead of assuming it", () => {
  // 1,000,000 input tokens at $2, 100,000 output tokens at $8
  assert.deepEqual(monthlyCost(noCache, price(2, 0.5, 8)), { cost: 2.8 });
  // 750,000 uncached at $2, 250,000 cached at $0.5, 100,000 output at $8
  assert.deepEqual(monthlyCost(quarterCached, price(2, 0.5, 8)), { cost: 2.425 });
  assert.deepEqual(monthlyCost(quarterCached, price(2, null, 8)), { missing: "cached_input" });
  assert.deepEqual(monthlyCost(noCache, price(null, 0.5, 8)), { missing: "input" });
  // A cached rate that the workload does not use is not needed.
  assert.deepEqual(monthlyCost(noCache, price(2, null, 8)), { cost: 2.8 });
});

test("a change in effect and an announced change are priced separately and the net covers only the first", () => {
  const result = computePriceImpact([eventA, eventB, eventOther, eventLaunch], "gpt-4.1", quarterCached, { today: "2026-11-17" });
  assert.deepEqual(result.entries.map((entry) => [entry.event_id, entry.status]), [["b", "scheduled"], ["a", "in_effect"]]);
  const a = result.entries[1];
  // before: 750,000 x 4 + 250,000 x 1 + 100,000 x 16 = 3.0 + 0.25 + 1.6 = 4.85
  assert.equal(a.before_monthly_usd, 4.85);
  assert.equal(a.after_monthly_usd, 2.425);
  assert.equal(a.direction, "cheaper");
  assert.equal(Math.round(a.delta_percent), -50);
  const b = result.entries[0];
  assert.equal(b.before_monthly_usd, 2.425);
  assert.equal(b.after_monthly_usd, 3.6375);
  assert.equal(b.direction, "more_expensive");
  assert.equal(Math.round(b.delta_percent), 50);
  assert.equal(result.net.changes, 1);
  assert.equal(result.net.before_monthly_usd, 4.85);
  assert.equal(result.net.after_monthly_usd, 2.425);
  assert.equal(result.net_unavailable_reason, null);
  // Changes of other models and launches are not price changes of this model.
  assert.deepEqual(result.skipped, []);
});

test("the announced change turns into one in effect once its date passes, and the net joins the two", () => {
  const result = computePriceImpact([eventA, eventB], "gpt-4.1", quarterCached, { today: "2027-01-01" });
  assert.deepEqual(result.entries.map((entry) => entry.status), ["in_effect", "in_effect"]);
  assert.equal(result.net.changes, 2);
  assert.equal(result.net.before_monthly_usd, 4.85);
  assert.equal(result.net.after_monthly_usd, 3.6375);
});

test("include_scheduled false leaves announced changes out", () => {
  const result = computePriceImpact([eventA, eventB], "gpt-4.1", quarterCached, { today: "2026-11-17", includeScheduled: false });
  assert.deepEqual(result.entries.map((entry) => entry.event_id), ["a"]);
});

test("since drops changes dated before it", () => {
  const result = computePriceImpact([eventA, eventB], "gpt-4.1", quarterCached, { today: "2026-11-17", since: "2026-07-01" });
  assert.deepEqual(result.entries.map((entry) => entry.event_id), ["b"]);
});

test("an event missing a price the workload needs is skipped with the reason and blocks the net", () => {
  // Without cached input the added cached price is irrelevant: the change is priced and moves nothing.
  const free = computePriceImpact([eventC], "gpt-4.1", noCache, { today: "2026-11-17" });
  assert.equal(free.entries.length, 1);
  assert.equal(free.entries[0].direction, "no_change_for_workload");
  assert.equal(free.entries[0].delta_monthly_usd, 0);
  assert.equal(free.entries[0].delta_percent, 0);
  assert.equal(free.entries[0].changed_prices.length, 1);
  assert.equal(free.entries[0].changed_prices[0].component, "cached_input");
  assert.equal(free.entries[0].changed_prices[0].used_by_workload, false);

  // With cached input the workload needs a price the event did not have before the change.
  const needed = computePriceImpact([eventC], "gpt-4.1", quarterCached, { today: "2026-11-17" });
  assert.equal(needed.entries.length, 0);
  assert.equal(needed.skipped.length, 1);
  assert.match(needed.skipped[0].reason, /cached input price before this change is not listed/);
  assert.match(needed.skipped[0].reason, /no price is assumed/);
  assert.equal(needed.net, null);
  assert.ok(needed.net_unavailable_reason);

  // A skipped change in effect keeps a net total from leaving it out.
  const mixed = computePriceImpact([eventC, eventA], "gpt-4.1", quarterCached, { today: "2026-11-17" });
  assert.equal(mixed.entries.length, 1);
  assert.equal(mixed.skipped.length, 1);
  assert.equal(mixed.net, null);
  assert.match(mixed.net_unavailable_reason, /could not be priced/);
});

test("changes that do not start where the previous one ended are not netted", () => {
  const gap = { ...eventB, event_id: "gap", effective_from: "2026-08-01", old_prices: price(9, 9, 9), new_prices: price(3, 0.75, 12) };
  const result = computePriceImpact([eventA, gap], "gpt-4.1", quarterCached, { today: "2026-11-17" });
  assert.equal(result.entries.length, 2);
  assert.equal(result.net, null);
  assert.match(result.net_unavailable_reason, /do not connect/);
});

test("a time-of-day schedule is skipped, never priced", () => {
  const result = computePriceImpact([eventTime], "gpt-4.1", noCache, { today: "2026-11-17" });
  assert.equal(result.entries.length, 0);
  assert.equal(result.skipped.length, 1);
  assert.match(result.skipped[0].reason, /time of day/);
});

test("a zero-cost workload has no percentage", () => {
  const empty = { ...noCache, requestsPerMonth: 0 };
  const result = computePriceImpact([eventA], "gpt-4.1", empty, { today: "2026-11-17" });
  assert.equal(result.entries[0].before_monthly_usd, 0);
  assert.equal(result.entries[0].delta_percent, null);
  assert.equal(result.entries[0].direction, "no_change_for_workload");
});

const eventFeed = [eventA, eventB, eventC, eventOther, eventLaunch];

function fetchWith(events) {
  return (input) => {
    const url = String(input);
    if (url.endsWith("/api/v1/prices.json")) return Promise.resolve(new Response(JSON.stringify(fixture), { status: 200 }));
    if (url.endsWith("/sitemap.xml")) return Promise.resolve(new Response(sitemap, { status: 200 }));
    if (url.includes("events.jsonl")) return Promise.resolve(new Response(events.map((event) => JSON.stringify(event)).join("\n") + "\n", { status: 200 }));
    return Promise.resolve(new Response("not found", { status: 404 }));
  };
}

async function connectedClient(options = {}) {
  const server = createPricingMcpServer({ fetchImpl: fetchWith(eventFeed), now: () => new Date("2026-11-17T12:00:00Z"), ...options });
  const client = new Client({ name: "test-client", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

const text = (result) => result.content.map((item) => item.type === "text" ? item.text : "").join("\n");

test("get_price_impact is listed with the other tools and marked read-only", async (t) => {
  const { client, server } = await connectedClient();
  t.after(async () => { await client.close(); await server.close(); });
  const { tools } = await client.listTools();
  const tool = tools.find((item) => item.name === "get_price_impact");
  assert.ok(tool);
  assert.equal(tool.annotations.readOnlyHint, true);
  assert.deepEqual(tool.inputSchema.required.sort(), ["input_tokens_per_request", "model", "output_tokens_per_request", "requests_per_month"]);
});

test("get_price_impact runs through the SDK and states what it could not price", async (t) => {
  const { client, server } = await connectedClient();
  t.after(async () => { await client.close(); await server.close(); });
  const result = await client.callTool({
    name: "get_price_impact",
    arguments: { model: "gpt-4.1", input_tokens_per_request: 1000, output_tokens_per_request: 100, requests_per_month: 1000, cached_input_ratio: 0.25 },
  });
  assert.notEqual(result.isError, true);
  const data = result.structuredContent.data;
  assert.equal(data.model.model_id, "gpt-4.1");
  assert.deepEqual(data.entries.map((entry) => entry.event_id), ["b", "a"]);
  assert.deepEqual(data.skipped.map((entry) => entry.event_id), ["c"]);
  assert.equal(data.net, null);
  assert.equal(data.current_monthly_usd, 2.425);
  assert.equal(data.event_feed.earliest_event_date, "2026-02-01");
  assert.equal(data.event_feed.events_checked, 5);
  const body = text(result);
  assert.ok(body.includes("2027-01-01 (announced, not yet in effect): $2.43 to $3.64 a month, +$1.21 (+50.0%): more expensive"));
  assert.ok(body.includes("2026-06-01: $4.85 to $2.43 a month, −$2.43 (−50.0%): cheaper"));
  assert.ok(body.includes("2026-03-01 (first seen by the monitor): not priced."));
  assert.ok(body.includes("No net total:"));
  assert.ok(body.includes("The event feed starts on 2026-02-01; earlier changes are not in it."));
  assert.ok(body.includes("Official source URL(s): https://"));
  assert.equal(result.structuredContent.official_source_urls.includes("https://developers.openai.com/api/docs/pricing"), true);
});

test("get_price_impact gives a net total when every change in effect can be priced", async (t) => {
  const { client, server } = await connectedClient({ fetchImpl: fetchWith([eventA, eventB]) });
  t.after(async () => { await client.close(); await server.close(); });
  const result = await client.callTool({
    name: "get_price_impact",
    arguments: { model: "gpt-4.1", input_tokens_per_request: 1000, output_tokens_per_request: 100, requests_per_month: 1000, cached_input_ratio: 0.25, include_scheduled: false },
  });
  const data = result.structuredContent.data;
  assert.equal(data.net.changes, 1);
  assert.equal(data.net.after_monthly_usd, 2.425);
  assert.ok(text(result).includes("Net across 1 change(s) in effect, 2026-06-01 to 2026-06-01: $4.85 to $2.43 a month, −$2.43 (−50.0%)."));
  // The catalog price and the newest change in effect agree, so no mismatch note.
  assert.equal(data.notes.some((note) => note.includes("a later change is not in the event feed")), false);
});

test("get_price_impact flags a catalog price that the event feed does not explain", async (t) => {
  const stale = { ...eventA, new_prices: price(3, 0.75, 12) };
  const { client, server } = await connectedClient({ fetchImpl: fetchWith([stale]) });
  t.after(async () => { await client.close(); await server.close(); });
  const result = await client.callTool({
    name: "get_price_impact",
    arguments: { model: "gpt-4.1", input_tokens_per_request: 1000, output_tokens_per_request: 100, requests_per_month: 1000, cached_input_ratio: 0.25 },
  });
  assert.ok(result.structuredContent.data.notes.some((note) => note.includes("a later change is not in the event feed")));
});

test("get_price_impact refuses a workload that the catalog prices from a different tier", async (t) => {
  const { client, server } = await connectedClient();
  t.after(async () => { await client.close(); await server.close(); });
  // 150,000 input tokens a request fall in the long-context tier (2 / 4), not the standard rates (1 / 2) that events carry.
  const refused = await client.callTool({
    name: "get_price_impact",
    arguments: { model: "tiered-example", input_tokens_per_request: 150000, output_tokens_per_request: 100, requests_per_month: 10 },
  });
  assert.equal(refused.isError, true);
  assert.ok(text(refused).includes("long tier"));
  assert.ok(text(refused).includes("standard"));
  // A short request is priced at the standard rates, so the model is allowed (no events here: an empty result, not an error).
  const allowed = await client.callTool({
    name: "get_price_impact",
    arguments: { model: "tiered-example", input_tokens_per_request: 1000, output_tokens_per_request: 100, requests_per_month: 10 },
  });
  assert.notEqual(allowed.isError, true);
  assert.deepEqual(allowed.structuredContent.data.entries, []);
  assert.ok(text(allowed).includes("No net total:"));
});

test("get_price_impact answers an ambiguous model with a did-you-mean list and rejects bad input", async (t) => {
  const { client, server } = await connectedClient();
  t.after(async () => { await client.close(); await server.close(); });
  const ambiguous = await client.callTool({
    name: "get_price_impact",
    arguments: { model: "claude", input_tokens_per_request: 1000, output_tokens_per_request: 100, requests_per_month: 1000 },
  });
  assert.equal(ambiguous.isError, true);
  assert.ok(text(ambiguous).includes("Did you mean: claude-haiku-5-5, claude-opus-5-5"));
  const bad = await client.callTool({
    name: "get_price_impact",
    arguments: { model: "gpt-4.1", input_tokens_per_request: 1000, output_tokens_per_request: 100, requests_per_month: 1000, cached_input_ratio: 1.5 },
  }).catch((error) => ({ isError: true, content: [{ type: "text", text: String(error.message) }] }));
  assert.equal(bad.isError, true);
});

test("get_price_impact with the bundled fallback says so", async (t) => {
  const { client, server } = await connectedClient({ fetchImpl: async () => { throw new Error("offline"); } });
  t.after(async () => { await client.close(); await server.close(); });
  const result = await client.callTool({
    name: "get_price_impact",
    arguments: { model: "gpt-4.1", input_tokens_per_request: 1000, output_tokens_per_request: 100, requests_per_month: 1000 },
  });
  assert.equal(result.structuredContent.source, "bundled");
  assert.equal(result.structuredContent.bundled_fallback, true);
  assert.ok(text(result).includes("Data source: bundled fallback (offline)"));
});
