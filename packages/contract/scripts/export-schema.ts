import { mkdirSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { buildJsonSchemas, serializeJsonSchema } from "../src/json-schema";

const dir = join(dirname(fileURLToPath(import.meta.url)), "..", "schema");
mkdirSync(dir, { recursive: true });
for (const f of readdirSync(dir)) if (f.endsWith(".json")) rmSync(join(dir, f));
for (const [name, schema] of Object.entries(buildJsonSchemas())) {
  writeFileSync(join(dir, `${name}.json`), serializeJsonSchema(schema));
}
