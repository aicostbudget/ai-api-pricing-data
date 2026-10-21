import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  MissingPriceError,
  compareModels,
  estimateCost,
  getPrice,
  listModels,
  loadPrices,
} from "../dist/esm/index.js";

const fixture = JSON.parse(await readFile(new URL("./fixtures/prices.json", import.meta.url), "utf8"));
const liveFetch = async () => new Response(JSON.stringify(fixture), { status: 200, headers: { "content-type": "application/json" } });

test("normalizes a live fixture with source and provenance", async () => {
  const catalog = await loadPrices({ fetchImpl: liveFetch });
  assert.equal(catalog.source, "live");
  assert.equal(catalog.license, "CC BY 4.0");
  assert.equal(catalog.models.length, 6);
  assert.equal(catalog.models[0].pricing.cachedInput, 0.5);
  assert.match(catalog.models[0].officialSourceUrl, /^https:/);
  assert.equal(catalog.models[0].lastVerifiedAt, "2026-10-09T06:29:38Z");
});

test("falls back to the bundled snapshot when live fetch fails", async () => {
  const catalog = await loadPrices({ fetchImpl: async () => { throw new Error("offline"); } });
  assert.equal(catalog.source, "bundled");
  assert.match(catalog.fallbackReason, /offline/);
  assert.ok(catalog.models.length >= 5);
});

test("getPrice and listModels retain official source and verification date", async () => {
  const model = await getPrice("GPT-4.1", { fetchImpl: liveFetch });
  assert.equal(model.modelId, "gpt-4.1");
  assert.ok(model.officialSourceUrl);
  assert.ok(model.lastVerifiedAt);
  const models = await listModels({ provider: "anthropic", fetchImpl: liveFetch });
  assert.deepEqual(models.map((item) => item.modelId), ["claude-haiku-5-5", "claude-opus-5-5"]);
});

test("estimateCost handles cached tokens and batch prices exactly", async () => {
  const cached = await estimateCost({
    modelId: "gpt-4.1",
    inputTokens: 1_000_000,
    cachedInputTokens: 250_000,
    outputTokens: 100_000,
    fetchImpl: liveFetch,
  });
  assert.equal(cached.breakdown.input, 1.5);
  assert.equal(cached.breakdown.cachedInput, 0.125);
  assert.equal(cached.breakdown.output, 0.8);
  assert.equal(cached.total, 2.425);
  assert.ok(cached.officialSourceUrl);
  assert.ok(cached.lastVerifiedAt);

  const batch = await estimateCost({
    modelId: "gpt-4.1",
    inputTokens: 1_000_000,
    outputTokens: 100_000,
    batch: true,
    fetchImpl: liveFetch,
  });
  assert.equal(batch.total, 1.4);
  assert.equal(batch.pricesUsed.batch, true);
});

test("tier selection uses thresholds and prices the whole request", async () => {
  const short = await estimateCost({ modelId: "tiered-example", inputTokens: 99_999, outputTokens: 100_000, fetchImpl: liveFetch });
  assert.equal(short.pricesUsed.tierId, "short");
  const long = await estimateCost({ modelId: "tiered-example", inputTokens: 100_000, outputTokens: 100_000, fetchImpl: liveFetch });
  assert.equal(long.pricesUsed.tierId, "long");
  assert.ok(Math.abs(long.total - 0.6) < Number.EPSILON);
});

test("refuses a missing required cache or batch price", async () => {
  await assert.rejects(
    estimateCost({ modelId: "aya-expanse-32b", inputTokens: 10, cachedInputTokens: 1, outputTokens: 1, fetchImpl: liveFetch }),
    MissingPriceError,
  );
  await assert.rejects(
    estimateCost({ modelId: "gpt-4.1", inputTokens: 10, cachedInputTokens: 1, outputTokens: 1, batch: true, fetchImpl: liveFetch }),
    MissingPriceError,
  );
});

test("compareModels sorts estimates by ascending total", async () => {
  const compared = await compareModels(["gpt-4.1", "claude-haiku-5-5"], {
    inputTokens: 1_000_000,
    outputTokens: 100_000,
    fetchImpl: liveFetch,
  });
  assert.deepEqual(compared.map((item) => item.modelId), ["claude-haiku-5-5", "gpt-4.1"]);
  assert.ok(compared.every((item) => item.officialSourceUrl && item.lastVerifiedAt));
});
