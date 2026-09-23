# Changelog

## 0.1.0 — 2026-09-23

- Model-switch guard: a `PreModelSwitch` hook that answers `ask` when the current model's cache is warm and
  re-caching the conversation on the new model would cost at least `CACHEKEEPER_MIN_USD` (default $1), using the
  estimate Claude Code computes; the same switch asked for again within 120 seconds is the confirmation, so it
  also works where no dialog can be shown. A `PostModelSwitch` hook logs every switch to `events.jsonl`.
- `cachekeeper audit`: attributes every cache rebuild in the local transcripts to its cause and replays the
  guard and a 55-minute keep-alive; `/cachekeeper:audit` runs it inside a session.
- `cachekeeper events`: what the guard saw and answered.
