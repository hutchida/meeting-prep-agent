import { readFileSync } from "node:fs";
import { assemblePack, checkEventOrder, type AgentEvent } from "../src/index";

// Used by the pytest parity test. stdin: {"mode": "assemble" | "order", "inputs": AgentEvent[][]}.
// stdout: one result per input: {pack} / {error} for assemble, string[] for order.
const { mode, inputs } = JSON.parse(readFileSync(0, "utf8")) as { mode: string; inputs: AgentEvent[][] };
const out = inputs.map((events) => {
  if (mode === "order") return checkEventOrder(events);
  try {
    return { pack: assemblePack(events) };
  } catch (err) {
    return { error: err instanceof Error ? `${err.name}: ${err.message}` : String(err) };
  }
});
process.stdout.write(JSON.stringify(out));
