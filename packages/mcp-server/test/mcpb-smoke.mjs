import assert from "node:assert/strict";
import { lstat, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import test from "node:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const packageDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(packageDir, "..", "..");
const mcpPackage = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
const bundlePath = join(repoRoot, "dist-mcpb", `ai-api-pricing-mcp-${mcpPackage.version}.mcpb`);
const mcpbCli = join(repoRoot, "node_modules", "@anthropic-ai", "mcpb", "dist", "cli", "cli.js");
const expectedToolNames = [
  "get_model_price",
  "list_models",
  "estimate_monthly_cost",
  "compare_models",
  "price_changes",
];

function runNode(args, options = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(process.execPath, args, { cwd: repoRoot, stdio: "inherit", shell: false, ...options });
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (code === 0) resolvePromise();
      else reject(new Error(`node ${args.join(" ")} failed with ${signal ? `signal ${signal}` : `exit code ${code}`}`));
    });
  });
}

async function walk(root) {
  const entries = [];
  async function visit(path) {
    const metadata = await lstat(path);
    entries.push({ path, metadata });
    if (metadata.isDirectory()) {
      for (const child of await readdir(path)) await visit(join(path, child));
    }
  }
  await visit(root);
  return entries;
}

async function connect(entryPoint, wrapperPath) {
  const args = wrapperPath ? [wrapperPath, entryPoint] : [entryPoint];
  const transport = new StdioClientTransport({ command: process.execPath, args });
  const client = new Client({ name: "mcpb-smoke-test", version: "1.0.0" });
  await client.connect(transport);
  return { client, transport };
}

function resultText(result) {
  return result.content.map((item) => item.type === "text" ? item.text : "").join("\n");
}

test("packed MCPB is self-contained and serves all five tools over stdio", async (t) => {
  const bundleStats = await stat(bundlePath);
  assert.ok(bundleStats.size < 10 * 1024 * 1024, `bundle is ${bundleStats.size} bytes, expected less than 10 MB`);

  const unpackRoot = await mkdtemp(join(tmpdir(), "ai-api-pricing-mcpb-smoke-"));
  t.after(async () => { await rm(unpackRoot, { recursive: true, force: true }); });
  await runNode([mcpbCli, "unpack", bundlePath, unpackRoot]);

  const manifest = JSON.parse(await readFile(join(unpackRoot, "manifest.json"), "utf8"));
  assert.equal(manifest.version, mcpPackage.version);
  assert.equal(manifest.tools_generated, false);
  assert.deepEqual(manifest.prompts, []);
  assert.deepEqual(manifest.tools.map((tool) => tool.name), expectedToolNames);

  const entries = await walk(unpackRoot);
  assert.equal(entries.some(({ metadata }) => metadata.isSymbolicLink()), false, "bundle contains a symbolic link");
  assert.equal(entries.some(({ path }) => path.endsWith(".map")), false, "bundle contains a source map");
  assert.equal(entries.some(({ path }) => path.includes(join("node_modules", "typescript"))), false, "bundle contains typescript");
  assert.equal(entries.some(({ path }) => path.includes(join("node_modules", "@anthropic-ai", "mcpb"))), false, "bundle contains @anthropic-ai/mcpb");
  for (const dependency of ["@modelcontextprotocol/sdk", "ai-api-pricing", "zod"]) {
    assert.ok(entries.some(({ path }) => path === join(unpackRoot, "node_modules", ...dependency.split("/"))), `bundle is missing ${dependency}`);
  }

  const entryPoint = join(unpackRoot, manifest.server.entry_point);
  const live = await connect(entryPoint);
  t.after(async () => { await live.client.close(); });
  const listed = await live.client.listTools();
  assert.deepEqual(listed.tools.map((tool) => tool.name), expectedToolNames);
  assert.deepEqual(
    listed.tools.map(({ name, description }) => ({ name, description })),
    manifest.tools,
    "manifest tool names/descriptions drifted from the running server",
  );
  const price = await live.client.callTool({ name: "get_model_price", arguments: { model: "gpt-6.1-sol" } });
  const priceText = resultText(price);
  assert.match(priceText, /Official source URL\(s\): https:\/\//);
  assert.match(priceText, /Verified \d{4}-\d{2}-\d{2}/);

  const offlineWrapper = join(unpackRoot, "offline-wrapper.mjs");
  await writeFile(offlineWrapper, [
    "globalThis.fetch = async () => { throw new Error('offline smoke test'); };",
    "const { pathToFileURL } = await import('node:url');",
    "await import(pathToFileURL(process.argv[2]).href);",
    "",
  ].join("\n"));
  const offline = await connect(entryPoint, offlineWrapper);
  t.after(async () => { await offline.client.close(); });
  const fallback = await offline.client.callTool({ name: "get_model_price", arguments: { model: "gpt-6.1-sol" } });
  const fallbackText = resultText(fallback);
  assert.equal(fallback.structuredContent.bundled_fallback, true);
  assert.match(fallbackText, /Data source: bundled fallback \(offline smoke test\)/);

  console.log(`MCPB smoke tools: ${listed.tools.map((tool) => tool.name).join(", ")}`);
  console.log(`MCPB smoke get_model_price result:\n${priceText}`);
  console.log(`MCPB offline fallback: ${fallbackText.match(/Data source: bundled fallback[^.]*\./)?.[0]}`);
});
