# Changelog

## 0.4.2 — 2026-09-23

- The subagent offered after a refused switch runs on the exact model asked for: `claude-opus-5`, not the alias
  `opus`, which resolves to Opus 5.5 by default (Claude Code 2.1.280 accepts full model ids for subagents; the
  alias stays as the fallback). The question and the notice name that model too.

## 0.4.1 — 2026-09-23

- The policy pick no longer turns on noise: among the combinations within 1% of the best net saving, the one
  with the fewest pings wins, then the larger minimum context. On the author's history the exact best had
  become "every session" because the 57k-token live-test session added $0.20; it is "sessions of at least 100k
  tokens, 3 hours" again.

## 0.4.0 — 2026-09-23

- `CACHEKEEPER_KEEPALIVE=auto`: the keep-alive's minimum context and cap are recomputed once a day from the local
  history, in the background Stop hook, as the best policy of the `cachekeeper keepalive` replay. With fewer than
  10 idle stretches it uses the defaults (100k tokens, 3 hours); when no policy would have saved anything, or only
  the five-minute cache is in use, it stays off. The idle stretches seen are also kept, as numbers only, in
  `keepalive/gaps.jsonl`, because Claude Code deletes terminal transcripts 30 days after their last activity.
- Keep-alive pings are left out of the replays: a break the pings kept warm counts as the whole break, with the
  rebuild they prevented, so a policy does not argue itself off on the history its own pings shaped. `cachekeeper
  audit` reports the pings actually sent.
- `cachekeeper audit` and `cachekeeper keepalive` say how much history they actually read: on the author's
  machine 12 days, not the 30 the earlier docs said; the docs are corrected.
- Waits that stand down at once (small or five-minute-cache sessions) are no longer logged.
- 0.3.0's keep-alive measured live in the desktop app: pings 55 and 110 minutes after the last message each
  read the cache, and a message 112 minutes after the last one cost $0.015 instead of $0.46 (Opus 5.5, 57k
  tokens). `asyncRewake` wakes an idle desktop session, the cap holds, a message from another session counts as
  the user, and settings edits apply to the next wait without a restart.

## 0.3.0 — 2026-09-23

- Keep-alive, opt-in with `CACHEKEEPER_KEEPALIVE=1`: a `Stop` hook with `asyncRewake` waits in the background after
  each turn and, 55 minutes after the last request started, wakes the model for a one-word reply that reads the
  cache and starts its hour again. Only for conversations of at least 100k tokens on the one-hour cache, and at
  most 3 pings after the user's last message (`CACHEKEEPER_KEEPALIVE_MIN_TOKENS`, `_HOURS`, `_MINUTES`). It stands
  down when the user writes, another turn ends, the model is switched, after `/compact`, when the machine slept
  past the hour, and in `claude -p` runs, where Claude Code would run the hook in the foreground.
- `cachekeeper keepalive` ends with the settings for the best policy on your history, or says to leave it off.
- `cachekeeper events` lists keep-alive pings and why each wait stood down.

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
