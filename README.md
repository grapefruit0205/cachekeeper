# cachekeeper

**Stop throwing away a warm prompt cache by accident.** A Claude Code plugin with three parts:

- a **model-switch guard**: before `/model` or the model picker forfeits a warm cache, it asks — with the size of the loss and the alternative that keeps the cache;
- **`cachekeeper audit`**: reads your own transcripts and attributes every cache rebuild to its cause, so you know which habit costs you the most — and `cachekeeper keepalive` finds how long a keep-alive would have paid off for you;
- an opt-in **keep-alive**: while you are away, one short request every 55 minutes keeps a long session's cache warm, for as long as that is cheaper than the rebuild.

[한국어](README.ko.md)

## Why

Claude Code re-sends the whole conversation on every turn; the prompt cache makes that cheap (a cache read bills at 0.1× the input price or less). A rebuild writes the whole context again: 2× the input price with the one-hour TTL a subscription gets. On the author's history — 12 days, 2026-09-11 to 09-23, 131 main sessions, 8,664 requests — weighted at list prices:

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

### Run just this task on the other model

The refusal also offers the cheaper way to get the other model's work: **send the request you meant for the other
model as your next message, and a subagent on that model handles it** while the session stays on its model and
its cache stays warm. A `UserPromptSubmit` hook tells the main model to delegate that one message (Agent tool,
`model: "fable"`, a self-contained brief — the subagent does not see the conversation, so the main model writes it
what it needs); later messages run normally. Typing the `/model` command instead switches the session as before.

Verified live on 2026-09-23 with Opus 5.5 as the main model: after a refused switch the next request went to a
subagent on the other model (`Agent`, `model: "sonnet"`) and the answer ended with "This session is still on
Opus". With Haiku 4.5 as the main model the instruction reached the model and was ignored three times out of
three, so the offer is as reliable as the main model's instruction-following.

Every switch request and every switch that happens is logged to `events.jsonl` in the plugin's data directory — model ids, token counts, the estimate and the decision; no prompt text. `cachekeeper events` summarizes it.

## The audit

```
cachekeeper audit            # the last 30 days (or as much history as there is), in your locale's language (ko/en)
cachekeeper audit --days 7 --json
```

or `/cachekeeper:audit` inside a session. `cachekeeper keepalive` shows how your idle stretches are distributed and
which keep-alive policy (how long to keep a session warm, and from what context size) would have paid off. It reads `~/.claude/projects/*/*.jsonl` (main sessions; subagents are left out), counts each API response once even when a resumed session copied it into another file, and reports:

- what your usage is made of (cache read, cache write, output, input);
- every rebuild, attributed to the first cause that explains it: session start, manual or automatic model switch, effort change, compaction, idle expiry, other;
- a replay of the guard: how many of your switches it would have asked about and how much usage rode on the answers;
- a replay of a 55-minute keep-alive: what the pings would have cost against the idle rebuilds they would have prevented.

Shares are weighted at API list prices. How a subscription counts usage is not published, so treat them as "which part of my usage is this", not as a bill.

## Keep-alive (opt-in)

Coming back to a session after more than an hour re-caches the whole conversation. With `CACHEKEEPER_KEEPALIVE=1`, cachekeeper keeps a long session's cache warm while you are away, for as long as that is cheaper than the rebuild:

- When a turn ends, a `Stop` hook waits in the background (an `asyncRewake` hook: Claude Code wakes the model only if it exits with code 2). 55 minutes after the last request started, it wakes the model, which replies `(keep-alive)`: one request that reads the cache at about 0.1× the input price and starts its hour again. For a 300k-token Opus 5.5 conversation that is about $0.06 per ping against $2.40 for the rebuild, at list price.
- Only for conversations of at least 100k tokens on the one-hour cache, and at most 3 pings in a row; the cache then lasts one more hour, about 3¾ hours after you left. Your next message starts the count again.
- It stands down when you write, when another turn ends, when the model is switched (the next request re-caches anyway), after `/compact`, and when the machine slept past the hour. `claude -p` runs are left alone.

Which numbers pay off depends on how you take breaks. `cachekeeper keepalive` replays your history and prints the best policy with the settings to paste. On the author's: sessions of at least 100k tokens kept for up to 3 hours — 126 pings (1.1% of usage) would have prevented 20 rebuilds (4.1%), net +3.0%. Keeping every session warm for 24 hours nets less (+1.9%): pinging through the night costs about what the morning rebuild does.

| variable | default | effect |
|---|---|---|
| `CACHEKEEPER_KEEPALIVE` | off | `1`: on, with the settings below; `auto`: on, with the best policy on your history, recomputed daily |
| `CACHEKEEPER_KEEPALIVE_MIN_TOKENS` | `100000` | smaller conversations are left to expire |
| `CACHEKEEPER_KEEPALIVE_HOURS` | `3` | how long to keep pinging after your last message |
| `CACHEKEEPER_KEEPALIVE_MINUTES` | `55` | idle minutes before each ping |

With `auto`, the Stop hook redoes the `cachekeeper keepalive` replay once a day, in the background, and waits under the best policy it finds (the two settings above are then ignored; near-ties within 1% go to the policy with fewer pings). With fewer than 10 idle stretches to go on it uses the defaults; when no policy would have saved anything, or your sessions only use the five-minute cache, it stays off. Pings are left out of the replay — a three-hour break kept warm counts as the three-hour break it was, with the rebuild it avoided — so the policy does not talk itself out of the savings it makes. Claude Code deletes terminal transcripts 30 days after their last activity (desktop sessions are kept), so the idle stretches it has seen are also kept, as numbers only, in the plugin's data folder.

Measured live in the desktop app ([details](docs/measurement-2026-09-23.md#keep-alive-live)): pings 55 and 110 minutes after the last message each read the cache ($0.014 apiece for a 57k-token Opus 5.5 session), and a message 112 minutes after the last one cost $0.015 instead of the $0.46 of writing it again.

`cachekeeper events` lists the pings and why each wait stood down. Other projects keep sessions warm with other mechanisms:

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

Needs Python 3.8+ (the hook stays silent and lets every switch through without one) and a Claude Code with `PreModelSwitch` hooks (and `asyncRewake` hooks for the keep-alive; 2.1.280 has both). To try a checkout: `claude --plugin-dir /path/to/cachekeeper`.

| variable | default | effect |
|---|---|---|
| `CACHEKEEPER_MODE` | `ask` | `ask`, `warn` (never blocks; shows the message) or `off` |
| `CACHEKEEPER_MIN_USD` | `1.0` | ask only when the estimated rewrite costs at least this much |
| `CACHEKEEPER_MIN_TOKENS` | `100000` | threshold when the new model's price is unknown |
| `CACHEKEEPER_CONFIRM_SECONDS` | `120` | how long a repeat counts as the confirmation |
| `CACHEKEEPER_OFFER_SECONDS` | `900` | how long the next message is handed to a subagent after a refusal |
| `CACHEKEEPER_LANG` | from `LANG` | `ko` or `en` |

Set them in the `env` block of `~/.claude/settings.json`.

## Limits

- `prompt_cache_warm` describes the current model's cache. Switching back to a model you used within the TTL can hit that model's own entry, so the rebuild is smaller than asked about: in the replay, 25 of the 29 asks were followed by a real rebuild.
- The replays model what the guard and a keep-alive would have done; what they save depends on your answers and your breaks.
- Each keep-alive ping is a short turn you can see in the conversation, and it counts toward your usage like any request.
- The keep-alive works only while the computer is awake and the session is open: a ping is a request the session itself makes. After a sleep that outlasted the hour it stands down instead of paying for a rebuild.
- The guard only sees switches that Claude Code routes through `PreModelSwitch`. Effort changes invalidate the cache on most models too (not on Opus 5.5 and Fable 5.1); Claude Code asks about those itself while the cache is warm.

## Tests

```
python3 -m unittest discover -s tests
```

MIT License.
