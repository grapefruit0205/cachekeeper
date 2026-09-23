# cachekeeper

**Stop throwing away a warm prompt cache by accident.** A Claude Code plugin with two parts:

- a **model-switch guard**: before `/model` or the model picker forfeits a warm cache, it asks — with the size of the loss and the alternative that keeps the cache;
- **`cachekeeper audit`**: reads your own transcripts and attributes every cache rebuild to its cause, so you know which habit costs you the most.

[한국어](README.ko.md)

## Why

Claude Code re-sends the whole conversation on every turn; the prompt cache makes that cheap (a cache read bills at about 0.1× the input price). A rebuild writes the whole context again: 2× the input price with the one-hour TTL a subscription gets. On the author's last 30 days (131 main sessions, 8,664 requests), weighted at list prices:

| | share of all usage |
|---|---|
| cache reads | 55.2% |
| cache writes | 31.7% |
| output | 13.1% |

and the rebuilds behind those writes came from:

| cause | rebuilds | median size | share of all usage |
|---|---|---|---|
| **model switch (`/model`)** | 35 | 545k tokens | **8.1%** |
| **idle past the one-hour TTL** | 39 | 470k tokens | **7.3%** |
| other (tool definitions, upgrades, images) | 16 | 635k tokens | 3.1% |
| session start / resume | 18 | 147k tokens | 2.7% |
| automatic switch, effort change, compaction | 13 | | 1.5% |

One switch between Opus 5 and Fable 5.1 in a 450k-token session re-caches the whole conversation on the new model (about $9 at list price for Fable 5.1). The full record is in [docs/measurement-2026-09-23.md](docs/measurement-2026-09-23.md).

## The model-switch guard

Claude Code already knows what a switch costs: its `PreModelSwitch` hook input carries `prompt_cache_warm`, `context_tokens`, `cache_ttl` and `estimated_cache_write_usd` (verified on Claude Code 2.1.280). When the cache is warm and the rewrite would cost at least `$1`, cachekeeper answers `ask` with:

```
cachekeeper: switching opus-5 → fable-5-1 forfeits the warm 1h cache and re-caches 452k tokens on
fable-5-1 — about $9.04 at list price. If only this task needs fable-5-1, ask for a fable subagent
instead and the main session's cache stays warm. To switch anyway, type `/model claude-fable-5-1`
within 120s (picking the same model again in a model picker may not reach Claude Code).
```

- In a terminal session Claude Code shows that as its confirmation dialog.
- **In the Claude desktop app** — where the model picker and a typed `/model` both reach Claude Code as an app request — and in headless `-p` sessions there is no dialog: the switch is blocked with that text, and **typing the `/model` command it names within 120 seconds is the confirmation**. Verified in the desktop app on 2026-09-23: `/model opus` was blocked with the message; the same command 21 seconds later switched the session.
- Don't confirm by picking the same model again in the desktop app's picker. After a blocked switch the picker can keep showing the new model while the session stays on the old one, and picking it again sends nothing. If the picker disagrees with the session, pick the session's current model to bring them back in line.
- Switches with a cold cache, small contexts, automatic fallbacks and resume restores pass silently: `PreModelSwitch` only fires for `/model`, the picker and SDK calls.
- A subagent keeps the main cache: its call and result are appended to the conversation, and it builds its own cache on its own model.

Every switch request and every switch that happens is logged to `events.jsonl` in the plugin's data directory — model ids, token counts, the estimate and the decision; no prompt text. `cachekeeper events` summarizes it.

## The audit

```
cachekeeper audit            # last 30 days, in your locale's language (ko/en)
cachekeeper audit --days 7 --json
```

or `/cachekeeper:audit` inside a session. It reads `~/.claude/projects/*/*.jsonl` (main sessions; subagents are left out), counts each API response once even when a resumed session copied it into another file, and reports:

- what your usage is made of (cache read, cache write, output, input);
- every rebuild, attributed to the first cause that explains it: session start, manual or automatic model switch, effort change, compaction, idle expiry, other;
- a replay of the guard: how many of your switches it would have asked about and how much usage rode on the answers;
- a replay of a 55-minute keep-alive: what the pings would have cost against the idle rebuilds they would have prevented.

Shares are weighted at API list prices. How a subscription counts usage is not published, so treat them as "which part of my usage is this", not as a bill.

## Keep-alive is not included — on purpose

Several projects already keep an idle session's cache warm, each with a different mechanism. Pick one after running the audit: its keep-alive line tells you whether pings would have paid for themselves on your history (on the author's: pings 2.2% of usage, prevented rebuilds 4.5%, net +2.3%).

| project | mechanism |
|---|---|
| [Delitefully/claude-keepwarm](https://github.com/Delitefully/claude-keepwarm) | after 45 idle minutes submits one line asking for a single period, and hides the rows it leaves |
| [FiredMosquito831/claude-cache-warm](https://github.com/FiredMosquito831/claude-cache-warm) | plugin with status line, dashboard and per-session settings |
| [santiquiroz/claude-prompt-cache-keepalive](https://github.com/santiquiroz/claude-prompt-cache-keepalive) | a ladder of background timers that wake the session; documents that a recurring `CronCreate` job never fired in an idle session and `ScheduleWakeup` only works inside `/loop` |
| [Pan1127/cc-cache-keepalive](https://github.com/Pan1127/cc-cache-keepalive) | pings from a non-persistent fork so the original session gets no extra messages |
| [cnighswonger/claude-code-coffee](https://github.com/cnighswonger/claude-code-coffee) | `/coffee 30` before a break |

Claude Code itself also helps: the status line receives the cache's expiry time, `/usage` shows the hit ratio and the likely cause of the last miss, and resuming a large session after a long break offers to resume from a summary.

## Install

```
claude plugin marketplace add grapefruit0205/cachekeeper
claude plugin install cachekeeper@cachekeeper
```

Needs Python 3.8+ (the hook stays silent and lets every switch through without one) and a Claude Code with `PreModelSwitch` hooks. To try a checkout: `claude --plugin-dir /path/to/cachekeeper`.

| variable | default | effect |
|---|---|---|
| `CACHEKEEPER_MODE` | `ask` | `ask`, `warn` (never blocks; shows the message) or `off` |
| `CACHEKEEPER_MIN_USD` | `1.0` | ask only when the estimated rewrite costs at least this much |
| `CACHEKEEPER_MIN_TOKENS` | `100000` | threshold when the new model's price is unknown |
| `CACHEKEEPER_CONFIRM_SECONDS` | `120` | how long a repeat counts as the confirmation |
| `CACHEKEEPER_LANG` | from `LANG` | `ko` or `en` |

Set them in the `env` block of `~/.claude/settings.json`.

## Limits

- `prompt_cache_warm` describes the current model's cache. Switching back to a model you used within the TTL can hit that model's own entry, so the rebuild is smaller than asked about: in the replay, 25 of the 29 asks were followed by a real rebuild.
- The replays model what the guard and a keep-alive would have done; what they save depends on your answers and your breaks.
- The guard only sees switches that Claude Code routes through `PreModelSwitch`. Effort changes invalidate the cache on most models too (not on Opus 5.5 and Fable 5.1); Claude Code asks about those itself while the cache is warm.

## Tests

```
python3 -m unittest discover -s tests
```

MIT License.
