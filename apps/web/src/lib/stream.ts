import { AgentEvent, type BriefingRequest } from "@mpa/contract";
import { readSse } from "./sse";
import type { RunAction } from "./run";

export interface StreamOptions {
  apiUrl: string;
  message: string;
  failSource?: "news";
  signal: AbortSignal;
  dispatch: (action: RunAction) => void;
  fetchImpl?: typeof fetch;
}

const isAbort = (err: unknown) => err instanceof DOMException && err.name === "AbortError";

/** POST /briefings and feed validated events into `dispatch`. Never throws. */
export async function streamBriefing(opts: StreamOptions): Promise<void> {
  const { apiUrl, message, failSource, signal, dispatch } = opts;
  const doFetch = opts.fetchImpl ?? fetch;
  const body: BriefingRequest = failSource ? { message, fail_source: failSource } : { message };
  let response: Response;
  try {
    response = await doFetch(`${apiUrl}/briefings`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (err) {
    if (isAbort(err) || signal.aborted) dispatch({ type: "stopped" });
    else dispatch({ type: "failed", kind: "unreachable", detail: "Could not reach the API." });
    return;
  }
  if (!response.ok || !response.body) {
    dispatch({
      type: "failed",
      kind: response.ok ? "stream" : "http",
      detail: response.ok ? "The API sent no stream." : `The API answered with status ${response.status}.`,
    });
    return;
  }
  try {
    for await (const frame of readSse(response.body)) {
      let event: AgentEvent | undefined;
      try {
        const parsed = AgentEvent.safeParse(JSON.parse(frame.data));
        if (parsed.success) event = parsed.data;
      } catch {
        event = undefined;
      }
      dispatch(event ? { type: "event", event } : { type: "skipped" });
    }
  } catch (err) {
    if (isAbort(err) || signal.aborted) {
      dispatch({ type: "stopped" });
      return;
    }
  }
  if (signal.aborted) dispatch({ type: "stopped" });
  else dispatch({ type: "stream_end" });
}
