import { z } from "zod";
import { SCHEMAS, type SchemaName } from "./schemas";

/** Draft 2020-12 JSON Schema for every exported schema, keyed by schema name. */
export function buildJsonSchemas(): Record<SchemaName, Record<string, unknown>> {
  const out = {} as Record<SchemaName, Record<string, unknown>>;
  for (const name of Object.keys(SCHEMAS).sort() as SchemaName[]) {
    out[name] = z.toJSONSchema(SCHEMAS[name], { target: "draft-2020-12" }) as Record<string, unknown>;
  }
  return out;
}

export function serializeJsonSchema(schema: unknown): string {
  return `${JSON.stringify(schema, null, 2)}\n`;
}
