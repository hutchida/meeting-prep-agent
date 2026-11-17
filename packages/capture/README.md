# @mpa/capture

The one shared screen-capture helper. Features supply steps; nobody writes a private browser harness.
It drives Chromium (Playwright), takes a frame after every step, writes named PNGs and an animated GIF
(pure JS: `gifenc` + `pngjs`, no ffmpeg) into `docs/media/`.

## Setup

```sh
pnpm install
pnpm --filter @mpa/capture run install-browsers   # playwright install chromium (once)
```

Without Chromium, `pnpm check` still passes: the browser tests are skipped with a warning
(set `RUN_BROWSER_TESTS=1` to force them).

## Run a script

```sh
pnpm --filter @mpa/capture run capture -- demo                       # packages/capture/scripts/demo.ts
pnpm --filter @mpa/capture run capture -- demo --base http://localhost:3000 --out docs/media
pnpm --filter @mpa/capture run capture -- demo --live                # briefing limit 90 s instead of 10 s
pnpm --filter @mpa/capture run capture -- demo --fixture --out /tmp/x  # built-in fake page, no app needed
pnpm --filter @mpa/capture run capture -- ./my-script.ts --no-gif --headed
```

Options: `--base`, `--out` (default `docs/media`, relative to the repo root unless given explicitly),
`--no-gif`, `--headed`, `--live`, `--max-briefing-ms <n>`, `--fixture`. Prints a step table
(step, ms, status) and exits 0/1.

Outputs (deterministic, overwritten on every run): `<name>-<NN>-<label>.png` for each `screenshot` step,
`<name>.gif` (<= 960 px wide, < 4 MB: colours, size and frames are reduced until it fits) and, on failure,
`<name>-failed-<NN>.png`.

## Writing a script

`scripts/<name>.ts` default-exports `{ name, steps, baseUrl?, totalTimeoutMs? }` or a function
`(ctx: { live, maxBriefingMs? }) => that`.

```ts
import { click, goto, screenshot, waitForTestId } from "../src/steps";

export default { name: "tour", steps: [goto("/"), click({ testId: "chat-send" }), waitForTestId("briefing"), screenshot("done")] };
```

Steps (`src/steps.ts`): `goto`, `click`, `fill`, `press`, `toggle`, `waitForText`, `waitForTestId`, `waitFor`,
`waitForNoTestId`, `wait`, `screenshot`, `expectVisible`, `expectText`, `expectCount`, `expectDistinctAttr`,
`mark`, `expectMarkWithin`, `note`. Targets: `{testId}`, `{text}`, `{role, name}` or `{css}`, each with an
optional `nth` (`-1` = last); prefer `data-testid`. Every step takes `{ name?, timeoutMs? }`.
`mark` times exclude the time spent taking frames. Failures name the step, the target and the failed-state
screenshot; env values and secret-shaped strings are redacted.

## Programmatic use

```ts
import { runCapture } from "@mpa/capture";
const result = await runCapture({ name: "x", baseUrl: "http://localhost:3000", steps });
// { ok, screenshots, gif, marks, durationMs, failedStep, steps, warnings, notes }
```

## Test-id interface used by `scripts/demo.ts`

`chat-input`, `chat-send`, `starter-halden|brightmoor|kettle`, `step-timeline`, `timeline-event`
(`data-type`, `data-agent`), `briefing`, `section-<id>` (7 sections), `citation` (`data-cite`),
`source-panel`, `source-panel-close`, `toggle-news-outage`, `run-stats`.
