# Measurement, 2026-09-23

What the plugin is built on, measured on the author's own machine before it was built. The corpus is
`~/.claude/projects/*/*.jsonl` for the last 30 days: main sessions only, each API response counted once. It is
one person's usage: mostly Opus 5 (72% of usage) and Fable 5.1 (25%) in the Claude desktop app, with long sessions
(median prompt 406k tokens per request) on a subscription, so the main conversation used the one-hour cache TTL.
Shares are weighted at API list prices; a subscription is not billed these amounts.

## The audit

```
cachekeeper audit — last 30 days, 131 main sessions, 8,664 requests

What the usage is made of (share, at list prices)
  cache read          55.2%
  cache write         31.7%
  output              13.1%
  uncached input       0.0%

Why the cache was rebuilt (share of all usage)
  cause                    count   median size   share
  session start/resume        18       147,167    2.7%
  model switch (manual)       35       545,191    8.1%
  model switch (automatic)     2       637,881    0.7%
  effort change                7       220,845    0.7%
  compaction                   4        65,224    0.1%
  idle past the TTL           39       470,328    7.3%
  other                       16       634,662    3.1%

With the model-switch guard on
  Of 40 manual switches, 29 had a warm cache and a rebuild of at least $1: the guard would have asked; 25 of them
  did rebuild — 5.6% of all usage rode on those answers.
  Out of scope: 11 switches after the cache had already expired, 4 automatic switches.

With a 55-minute keep-alive (one-hour TTL sessions, 8-hour cap)
  265 pings would cost 2.2% of usage and prevent 23 idle rebuilds (4.5%): net +2.3%.
```

Reading it:

- **Usage is the context, not the answers.** Reading and writing the cached conversation is 87% of usage;
  output (thinking and answers) is 13%. Requests whose prompt exceeded 300k tokens carried 83% of all usage.
- **Two habits make most of the rebuilds, about equally:** switching models mid-session (8.1% of usage, almost
  all between Opus 5 and Fable 5.1) and coming back after more than an hour (7.3%).
- **The guard's reach:** 29 questions in 30 days, about one a day, with 5.6% of usage behind them. What it
  saves is the part of that where the answer would have been "use a subagent" or "not now".
- **A keep-alive pays for itself here, modestly:** +2.3% net at an 8-hour cap. That is why the plugin points to
  the existing keep-alive projects instead of adding another one.

## A correction this tool made

An earlier one-off analysis of the same corpus counted cache rebuilds per transcript file and found model
switches behind 54% of rebuild events. Resumed sessions copy earlier history into a new file, so those rebuilds
were counted more than once. Counting each API response once — what the audit does — puts manual switches at 35
of 121 rebuilds and idle expiry at 39, about equal in usage share.

## The guard, live

Claude Code 2.1.280, the plugin loaded with `--plugin-dir`, a headless session warmed with one Haiku 4.5 turn
(23k tokens re-sent per request), `CACHEKEEPER_MIN_USD=0` so the small test session qualifies:

1. `/model sonnet` → `PreModelSwitch` (`source: command`, `prompt_cache_warm: true`,
   `estimated_cache_write_usd: 0.0915` — 22,868 tokens at Sonnet 5's one-hour write rate, $4/MTok) → the guard
   answered `ask`; a headless session cannot show a dialog, so Claude Code blocked the switch with the guard's text:
   `Model switch to Sonnet 5 was blocked by a PreModelSwitch hook: cachekeeper: … pick the same model again within 120s.`
2. The same `/model sonnet` again 20 seconds later → the guard answered `allow` →
   `Set model to Sonnet 5 for this session only`, and `PostModelSwitch` (`source: command`) logged the switch.

The first live run found a bug the unit tests had not: resuming the session fires
`PostModelSwitch (source: resume)` as Claude Code restores the session's model, and the guard treated that as
"the switch happened" and dropped the pending question, so the repeat was asked again. A pending question is now
cleared only by the switch it asked about (`tests/test_guard.py`,
`test_a_resume_restoring_the_model_keeps_the_pending_ask`).

## The guard in the Claude desktop app

The installed plugin (0.1.0 from the marketplace) in the desktop app, with the default `$1` threshold; the app's own
log (`~/.config/Claude/logs/main.log`) shows each `LocalSessions.setModel` it sends to Claude Code.

| time | action | app log | guard | result |
|---|---|---|---|---|
| 14:50:24 | switch a test session (141k tokens) Opus 5.5 → Fable 5.1 through the app | `setModel` | `ask` ($2.83) | blocked with the message; no dialog |
| 14:50:38 | the same switch again | `setModel` | `allow` | switched |
| 14:59:03 | model picker in a 829k-token session: Opus 5.5 → Fable 5.1 | `setModel` | `ask` ($16.59) | blocked with the message |
| (after) | picked Fable 5.1 again in the picker | **nothing sent** | — | the picker showed Fable 5.1; the session stayed on Opus 5.5 and kept reading its cache |
| 15:04:04 | typed `/model opus` in the test session (now on Fable 5.1) | `setModel` | `ask` ($1.13) | blocked with the message |
| 15:04:25 | typed `/model opus` again | `setModel` | `allow` | `Set model to opus (claude-opus-5-5)` |

Every app-routed switch arrives as `source: sdk`, the picker's and a typed `/model`'s alike, and the app shows no
dialog for `ask`. Confirming by a repeat works when the repeat is actually sent; picking the model the picker
already displays is not. 0.1.1 therefore names a typed `/model <resolved id>` as the confirmation.

## Limits of these numbers

- One person's 30 days, on one machine, weighted at list prices.
- The replays model what the guard and a keep-alive would have done; they cannot say how the user would have
  answered or when they would have come back.
- `prompt_cache_warm` covers the current model's cache only: switching back to a model used within the TTL can
  hit that model's own entry. 4 of the 29 asks were not followed by a full rebuild.
- "Other" rebuilds (3.1%) have no cause the transcript shows: tool-definition changes, Claude Code upgrades, images.
- After a blocked switch the desktop app's picker can keep showing the model that was refused. That display is the
  app's; the guard cannot correct it, only tell the user to confirm with a typed `/model`.
