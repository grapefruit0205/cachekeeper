# Changelog

## 0.2.0 — 2026-09-23

- A refused switch now offers to run just the next request on the other model: a `UserPromptSubmit` hook tells
  the main model to hand that one message to a subagent on the requested model (`fable`, `opus`, `sonnet` or
  `haiku`) with a self-contained brief, so the session keeps its model and its warm cache. A typed `/model`
  still switches the session; confirming the switch or 15 minutes without a message withdraw the offer.
  Verified live: Opus 5.5 delegated; Haiku 4.5 received the instruction and ignored it three times out of three.
  The subagent tool is `Agent` in the desktop app and `Task` in the headless CLI; the instruction names both.
- `cachekeeper keepalive`: the distribution of idle stretches in one-hour-TTL sessions and the net effect of a
  55-minute keep-alive by cap (1-24 h) and minimum context size, with the best policy on your history.

## 0.1.1 — 2026-09-23

- The confirmation the guard asks for is now a typed `/model <resolved model id>`. Verified in the Claude desktop
  app: its model picker and a typed `/model` both reach Claude Code as an app request (`source: sdk`), an `ask`
  shows no dialog there and blocks the switch with the message, and a typed repeat confirms it; picking the
  same model again in the picker sends nothing, and after a blocked switch the picker can keep showing the new
  model while the session stays on the old one. The resolved id avoids an alias resolving to another version.

## 0.1.0 — 2026-09-23

- Model-switch guard: a `PreModelSwitch` hook that answers `ask` when the current model's cache is warm and
  re-caching the conversation on the new model would cost at least `CACHEKEEPER_MIN_USD` (default $1), using the
  estimate Claude Code computes; the same switch asked for again within 120 seconds is the confirmation, so it
  also works where no dialog can be shown. A `PostModelSwitch` hook logs every switch to `events.jsonl`.
- `cachekeeper audit`: attributes every cache rebuild in the local transcripts to its cause and replays the
  guard and a 55-minute keep-alive; `/cachekeeper:audit` runs it inside a session.
- `cachekeeper events`: what the guard saw and answered.
