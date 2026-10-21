import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { createPricingMcpServer } from "../dist/server.js";

const fixture = JSON.parse(await readFile(new URL("../../ai-api-pricing/test/fixtures/prices.json", import.meta.url), "utf8"));
const sitemap = `<?xml version="1.0"?><urlset><url><loc>https://aicostbudget.com/en/models/gpt-4-1-pricing</loc></url><url><loc>https://aicostbudget.com/en/models/claude-haiku-5-5-pricing</loc></url></urlset>`;
const event = {
  event_id: "openai:gpt-4.1:price_update:test",
  provider_id: "openai",
  model_id: "gpt-4.1",
  change_type: "price_update",
  detected_at: "2026-10-09",
  verified_at: "2026-10-09",
  official_source_url: "https://developers.openai.com/api/docs/pricing",
  announcement_url: null,
};

function fetchFixture(input) {
  const url = String(input);
  if (url.endsWith("/api/v1/prices.json")) return Promise.resolve(new Response(JSON.stringify(fixture), { status: 200 }));
  if (url.endsWith("/sitemap.xml")) return Promise.resolve(new Response(sitemap, { status: 200 }));
  if (url.includes("events.jsonl")) return Promise.resolve(new Response(`${JSON.stringify(event)}\n`, { status: 200 }));
  return Promise.resolve(new Response("not found", { status: 404 }));
}

async function connectedClient(options = {}) {
  const server = createPricingMcpServer({ fetchImpl: fetchFixture, ...options });
  const client = new Client({ name: "test-client", version: "1.0.0" });
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await Promise.all([server.connect(serverTransport), client.connect(clientTransport)]);
  return { client, server };
}

function text(result) {
  return result.content.map((item) => item.type === "text" ? item.text : "").join("\n");
}

function assertFooter(result) {
  assert.match(text(result), /Official source URL\(s\): https:\/\//);
  assert.match(text(result), /Verified \d{4}-\d{2}-\d{2}/);
  assert.match(text(result), /AICostBudget: https:\/\/aicostbudget\.com\/en\//);
  assert.ok(result.structuredContent);
}

test("all five tools run through the SDK in-memory transport", async (t) => {
  const { client, server } = await connectedClient();
  t.after(async () => { await client.close(); await server.close(); });

  const price = await client.callTool({ name: "get_model_price", arguments: { model: "GPT-4.1" } });
  assertFooter(price);
  assert.equal(price.structuredContent.data.model.modelId, "gpt-4.1");
  assert.match(text(price), /gpt-4-1-pricing/);

  const listed = await client.callTool({ name: "list_models", arguments: { provider: "openai", max_input_price: 2 } });
  assertFooter(listed);
  assert.equal(listed.structuredContent.data.models.length, 1);

  const estimate = await client.callTool({
    name: "estimate_monthly_cost",
    arguments: { model: "gpt-4.1", input_tokens_per_request: 1000, output_tokens_per_request: 100, requests_per_month: 1000, cached_input_ratio: 0.25 },
  });
  assertFooter(estimate);
  assert.equal(estimate.structuredContent.data.estimate.total, 2.425);

  const compared = await client.callTool({
    name: "compare_models",
    arguments: { models: ["gpt-4.1", "claude-haiku-5-5"], input_tokens_per_request: 1000, output_tokens_per_request: 100, requests_per_month: 1000 },
  });
  assertFooter(compared);
  assert.deepEqual(compared.structuredContent.data.comparisons.map((item) => item.modelId), ["claude-haiku-5-5", "gpt-4.1"]);

  const changes = await client.callTool({ name: "price_changes", arguments: { since: "2026-01-01", provider: "openai" } });
  assertFooter(changes);
  assert.equal(changes.structuredContent.data.events.length, 1);
  assert.match(text(changes), /model-price-monitor/);
});

test("ambiguous fuzzy matching returns an explicit did-you-mean list", async (t) => {
  const { client, server } = await connectedClient();
  t.after(async () => { await client.close(); await server.close(); });
  const result = await client.callTool({ name: "get_model_price", arguments: { model: "claude" } });
  assert.equal(result.isError, true);
  assert.match(text(result), /Did you mean: claude-haiku-5-5, claude-opus-5-5/);
  assert.match(text(result), /Official source URL\(s\):/);
  assert.match(text(result), /Verified \d{4}-\d{2}-\d{2}/);
});

test("fetch failure is disclosed as bundled fallback", async (t) => {
  const { client, server } = await connectedClient({ fetchImpl: async () => { throw new Error("offline"); } });
  t.after(async () => { await client.close(); await server.close(); });
  const result = await client.callTool({ name: "get_model_price", arguments: { model: "gpt-4.1" } });
  assert.equal(result.structuredContent.source, "bundled");
  assert.equal(result.structuredContent.bundled_fallback, true);
  assert.match(text(result), /Data source: bundled fallback \(offline\)/);
  assertFooter(result);
});
