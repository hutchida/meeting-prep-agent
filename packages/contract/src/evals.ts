import { z } from "zod";

export const EVAL_SCENARIOS = ["normal", "news_down", "empty_client", "injection", "budget_hit"] as const;

export const EvalResult = z
  .strictObject({
    client: z.string().min(1).max(100),
    scenario: z.enum(EVAL_SCENARIOS),
    fact_recall: z.number().min(0).max(1),
    facts_found: z.array(z.string().max(200)).max(30),
    facts_missed: z.array(z.string().max(200)).max(30),
    hallucinations: z.number().int().min(0),
    citation_accuracy: z.number().min(0).max(1),
    steps: z.number().int().min(0),
    tokens_in: z.number().int().min(0),
    tokens_out: z.number().int().min(0),
    cost_usd: z.number().min(0),
    latency_ms: z.number().int().min(0),
    injection_resisted: z.boolean(),
    judge_model: z.string().min(1).max(100),
  })
  .meta({ id: "EvalResult" });
export type EvalResult = z.infer<typeof EvalResult>;
