import { createHash } from "node:crypto";
import { cp, mkdir, mkdtemp, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const packageDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(packageDir, "..", "..");
const pricingDir = join(repoRoot, "packages", "ai-api-pricing");
const outputDir = join(repoRoot, "dist-mcpb");
const npmCli = process.env.npm_execpath;
const mcpbCli = join(repoRoot, "node_modules", "@anthropic-ai", "mcpb", "dist", "cli", "cli.js");

if (!npmCli) throw new Error("npm_execpath is required; run this script through npm run build:mcpb");

function run(command, args, options = {}) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(command, args, {
      cwd: repoRoot,
      stdio: "inherit",
      shell: false,
      ...options,
    });
    child.on("error", reject);
    child.on("exit", (code, signal) => {
      if (code === 0) resolvePromise();
      else reject(new Error(`${command} ${args.join(" ")} failed with ${signal ? `signal ${signal}` : `exit code ${code}`}`));
    });
  });
}

async function sha256(path) {
  const data = await readFile(path);
  return createHash("sha256").update(data).digest("hex");
}

async function removeSourceMaps(path) {
  for (const entry of await readdir(path, { withFileTypes: true })) {
    const child = join(path, entry.name);
    if (entry.isDirectory()) await removeSourceMaps(child);
    else if (entry.isFile() && entry.name.endsWith(".map")) await rm(child);
  }
}

const mcpPackage = JSON.parse(await readFile(join(packageDir, "package.json"), "utf8"));
const pricingPackage = JSON.parse(await readFile(join(pricingDir, "package.json"), "utf8"));
const manifestPath = join(packageDir, "mcpb", "manifest.json");
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));

if (manifest.version !== mcpPackage.version) {
  throw new Error(`MCPB manifest version ${manifest.version} must match package version ${mcpPackage.version}`);
}

const temporaryRoot = await mkdtemp(join(tmpdir(), "ai-api-pricing-mcpb-"));
const stageDir = join(temporaryRoot, "bundle");
const packDir = join(temporaryRoot, "packs");
const bundleName = `ai-api-pricing-mcp-${mcpPackage.version}.mcpb`;
const outputPath = join(outputDir, bundleName);

try {
  await run(process.execPath, [npmCli, "run", "build", "--workspace", "ai-api-pricing"]);
  await run(process.execPath, [npmCli, "run", "build", "--workspace", "ai-api-pricing-mcp"]);

  await mkdir(stageDir, { recursive: true });
  await mkdir(packDir, { recursive: true });
  await mkdir(outputDir, { recursive: true });
  await rm(outputPath, { force: true });

  await cp(manifestPath, join(stageDir, "manifest.json"));
  await cp(join(packageDir, "mcpb", "icon.png"), join(stageDir, "icon.png"));
  await cp(join(packageDir, "dist"), join(stageDir, "server"), { recursive: true });

  await run(process.execPath, [npmCli,
    "pack",
    "--ignore-scripts",
    "--pack-destination",
    packDir,
    "--workspace",
    "ai-api-pricing",
  ]);

  const pricingTarball = join(packDir, `ai-api-pricing-${pricingPackage.version}.tgz`);
  const installPackage = {
    private: true,
    type: "module",
    dependencies: {
      "@modelcontextprotocol/sdk": mcpPackage.dependencies["@modelcontextprotocol/sdk"],
      "ai-api-pricing": `file:${pricingTarball}`,
      zod: mcpPackage.dependencies.zod,
    },
  };
  await writeFile(join(stageDir, "package.json"), `${JSON.stringify(installPackage, null, 2)}\n`);
  await run(process.execPath, [npmCli,
    "install",
    "--prefix",
    stageDir,
    "--omit=dev",
    "--ignore-scripts",
    "--no-package-lock",
    "--no-audit",
    "--no-fund",
  ]);
  await rm(join(stageDir, "node_modules", ".bin"), { recursive: true, force: true });
  await removeSourceMaps(stageDir);

  const bundledPackage = {
    name: "ai-api-pricing-mcp-bundle",
    private: true,
    version: mcpPackage.version,
    type: "module",
    dependencies: {
      "@modelcontextprotocol/sdk": mcpPackage.dependencies["@modelcontextprotocol/sdk"],
      "ai-api-pricing": pricingPackage.version,
      zod: mcpPackage.dependencies.zod,
    },
  };
  await writeFile(join(stageDir, "package.json"), `${JSON.stringify(bundledPackage, null, 2)}\n`);

  await run(process.execPath, [mcpbCli, "validate", join(stageDir, "manifest.json")]);
  await run(process.execPath, [mcpbCli, "pack", stageDir, outputPath]);
  await run(process.execPath, [mcpbCli, "info", outputPath]);

  const { size } = await stat(outputPath);
  console.log(`MCPB bundle: ${outputPath}`);
  console.log(`Size: ${size} bytes`);
  console.log(`SHA-256: ${await sha256(outputPath)}`);
} finally {
  await rm(temporaryRoot, { recursive: true, force: true });
}
