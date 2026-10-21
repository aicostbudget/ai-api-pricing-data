import { mkdir, writeFile } from "node:fs/promises";

const directory = new URL("../dist/cjs/", import.meta.url);
await mkdir(directory, { recursive: true });
await writeFile(new URL("package.json", directory), '{"type":"commonjs"}\n', "utf8");
