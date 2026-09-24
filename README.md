# cachekeeper

**Stop throwing away a warm prompt cache by accident.** A Claude Code plugin with three parts:

- a **model-switch guard**: before `/model` or the model picker forfeits a warm cache, it asks — with the size of the loss and the alternative that keeps the cache;
- **`cachekeeper audit`**: reads your own transcripts and attributes every cache rebuild to its cause, so you know which habit costs you the most — `cachekeeper keepalive` finds how long a keep-alive would have paid off for you, and `cachekeeper compaction` what compacting earlier would have saved;
- an opt-in **keep-alive**: while you are away, one short request every 55 minutes keeps a long session's cache warm, for as long as that is cheaper than the rebuild.

[한국어](README.ko.md)

## How to use

**1. Install.** It needs Python 3.8 or newer ([requirements](#requirements-and-settings)).

```
claude plugin marketplace add grapefruit0205/cachekeeper
claude plugin install cachekeeper@cachekeeper
```

To update: `claude plugin marketplace update cachekeeper`, then `claude plugin update cachekeeper@cachekeeper`, and restart Claude Code. To remove: `claude plugin uninstall cachekeeper@cachekeeper`.

**2. The model-switch guard needs no setup.** When `/model` or the model picker would throw away a warm cache and the rewrite counts at least $1, the switch stops and shows the amount. Then either:

- to run just this task on the other model, send the request as you meant to: a subagent on that model handles it, and the session keeps its model and its cache;
- to switch the session anyway, type the `/model` command the message names within 120 seconds (a terminal session shows a confirmation dialog instead).

**3. Turn on the keep-alive (optional).** Add this to `~/.claude/settings.json`, inside the existing `env` block if there is one:

```json
{
  "env": {
    "CACHEKEEPER_KEEPALIVE": "auto"
  }
}
```

After each turn in a long session, cachekeeper then keeps the cache warm while you are away. Which sessions, and for how long, it works out from your own history and redoes once a day. It runs only while the computer is awake and the session is open. `1` instead of `auto` uses fixed settings ([keep-alive](#keep-alive-opt-in)).

**4. See where your usage goes.** In a session, type `/cachekeeper:audit`, or ask Claude to run one of these (the plugin puts `cachekeeper` on the PATH of Claude Code's shell):

| command | shows |
|---|---|
| `cachekeeper audit` | what your usage is made of, and the cause of every cache rebuild |
| `cachekeeper keepalive` | which keep-alive policy pays off on your history, and the one `auto` uses now |
| `cachekeeper compaction` | what an earlier auto-compaction would have saved and cost |
| `cachekeeper events` | the guard's asks and the keep-alive's pings |

`--days N` sets the period (30 days by default), `--lang ko` or `--lang en` the language, and `--basis subscription` or `--basis api` the [yardstick](#two-yardsticks); `audit --json` prints the numbers as JSON. The commands read only this machine's transcripts and send nothing. Outside Claude Code, run them from a checkout: `git clone https://github.com/grapefruit0205/cachekeeper`, then `cachekeeper/bin/cachekeeper audit`.

## Why

Claude Code re-sends the whole conversation on every turn; the prompt cache makes that cheap. A rebuild writes the whole context again. What each costs depends on who counts:

- **at API list prices** a cache read bills at 0.1× the input price or less, and a write on the one-hour cache at 2×;
- **on a subscription's usage limits**, as measured from outside, a cache read counts next to nothing (0.18% of the input price) and a write counts at the input price ([two yardsticks](#two-yardsticks)).

On the author's history — 12.7 days, 2026-09-11 to 09-24, 152 main sessions, 9,658 requests, 94% of them on the one-hour cache:

| | subscription usage | list price |
|---|---|---|
| cache reads | 4.6% | 54.8% |
| cache writes | 51.0% | 31.5% |
| output | 44.4% | 13.7% |

and the rebuilds behind those writes came from:

| cause | rebuilds | median size | subscription usage | list price |
|---|---|---|---|---|
| **model switch (`/model`)** | 35 | 545k tokens | **12.5%** | 7.7% |
| **idle past the one-hour TTL** | 42 | 456k tokens | **11.8%** | 7.3% |
| other (tool definitions, upgrades, images) | 17 | 634k tokens | 4.8% | 3.0% |
| session start / resume | 18 | 147k tokens | 4.1% | 2.6% |
| automatic switch, effort change, compaction | 13 | | 2.3% | 1.4% |

On a subscription, where reads cost next to nothing, a rebuild is the costliest thing a turn can do: the two habits the guard and the keep-alive address carry a quarter of the author's usage. One switch between Opus 5 and Fable 5.1 in a 450k-token session re-caches the whole conversation on the new model (about $4.50 of subscription usage for Fable 5.1, $9 at list price). The first measurement, at list prices, is recorded in [docs/measurement-2026-09-23.md](docs/measurement-2026-09-23.md).

## Two yardsticks

Every amount cachekeeper shows — the guard's estimate, the audit's shares, the keep-alive and compaction replays — is on one of two yardsticks:

| yardstick | cache read | cache write (5 min / 1 h) | uncached input | output |
|---|---|---|---|---|
| `subscription` | 0.0018× input | 1× / 1× input | 1× input | output price |
| `api` | 0.1× input or less | 1.25× / 2× input | 1× input | output price |

`subscription` is how a Claude subscription's usage limits count, measured from outside, since the formula is not published: [she-llac.com](https://she-llac.com/claude-limits) recovered it from unrounded usage values in January 2026 (cache reads fit at 0.18% of the input price, 80% interval 0-0.5%: cachekeeper uses the fit), and the alldonesites usage tracker (four Max 20x accounts, to 2026-09-21) finds Fable 5.1 counting 2.11× Opus 5, near its list-price ratio. That one-hour writes count at 1× and that Opus 5.5 follows its list price are assumptions. An amount on this yardstick is list-price dollars of the tokens the limits count: read it as a share of plan usage, not as a bill.

By default the yardstick follows the cache. Claude Code 2.1.280 gives the main conversation the one-hour cache only on a subscription within its plan usage, and five minutes with an API key or in extra usage (billed at API rates), so one-hour sessions count on `subscription` and five-minute ones on `api`. `CACHEKEEPER_BASIS=api` or `subscription` fixes it, for instance when an API key forces the one-hour cache with `ENABLE_PROMPT_CACHING_1H`; the commands also take `--basis`.

## The model-switch guard

Claude Code already knows what a switch costs: its `PreModelSwitch` hook input carries `prompt_cache_warm`, `context_tokens`, `cache_ttl` and `estimated_cache_write_usd` (verified on Claude Code 2.1.280). When the cache is warm and the rewrite would count at least `$1`, cachekeeper answers `ask` with:

```
cachekeeper: switching opus-5 → fable-5-1 forfeits the warm 1h cache and re-caches 452k tokens on
fable-5-1 — about $4.52 of subscription usage (a cache write counts at the input price). Run just this
task on fable-5-1 instead? Send the request as you meant to and a fable-5-1 subagent handles it; this
session then continues on opus-5. To switch the session itself, type `/model claude-fable-5-1` within
120s (picking the same model again in a model picker may not reach Claude Code).
```

On the one-hour cache the amount is Claude Code's estimate on subscription usage: the write without its 2× premium. On the five-minute cache, or with `CACHEKEEPER_BASIS=api`, it is Claude Code's list-price estimate (`about $9.04 at list price`). The `$1` threshold is on the same yardstick, so on subscription usage the guard asks from about 250k tokens on Opus 5.5 and 100k on Fable 5.1 (125k and 50k at list price); `CACHEKEEPER_MIN_USD=0.5` asks as often as before 0.6.0.

- In a terminal session Claude Code shows that as its confirmation dialog.
- **In the Claude desktop app** — where the model picker and a typed `/model` both reach Claude Code as an app request — and in headless `-p` sessions there is no dialog: the switch is blocked with that text, and **typing the `/model` command it names within 120 seconds is the confirmation**. Verified in the desktop app on 2026-09-23: `/model opus` was blocked with the message; the same command 21 seconds later switched the session.
- Don't confirm by picking the same model again in the desktop app's picker. After a blocked switch the picker can keep showing the new model while the session stays on the old one, and picking it again sends nothing. If the picker disagrees with the session, pick the session's current model to bring them back in line.
- Switches with a cold cache, small contexts, automatic fallbacks and resume restores pass silently: `PreModelSwitch` only fires for `/model`, the picker and SDK calls.
- A subagent keeps the main cache: its call and result are appended to the conversation, and it builds its own cache on its own model.

### Run just this task on the other model

The refusal also offers the cheaper way to get the other model's work: **send the request you meant for the other
model as your next message, and a subagent on that model handles it** while the session stays on its model and
its cache stays warm. A `UserPromptSubmit` hook tells the main model to delegate that one message (Agent tool
with the exact model you asked for, e.g. `model: "claude-fable-5-1"`, falling back to the alias `fable`; a
self-contained brief — the subagent does not see the conversation, so the main model writes it what it needs);
later messages run normally. It works in every direction: from Fable, `/model claude-opus-5` offers an Opus 5
subagent. Typing the `/model` command instead switches the session as before.

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
- a replay of a 55-minute keep-alive: what the pings would have cost against the idle rebuilds they would have prevented. Pings after a session's last message count too, whether or not you came back, and `claude -p` runs are left out, as the keep-alive leaves them alone.

Shares are on the yardstick your sessions use ([two yardsticks](#two-yardsticks)); `--basis subscription` or `--basis api` picks one.

## How long to let a session grow

Every request re-reads the whole conversation, so at list prices a long session pays for its length on every turn: on the author's history, requests re-sent 400k tokens at the median, and the part of the context beyond 300k tokens cost 24% of all usage in re-reads alone. On subscription usage re-reads count next to nothing; there a long context costs when it is rewritten, after a break or a switch. Claude Code compacts automatically only near the model's whole window (1M for the current models; the author's sessions compacted at about 970k). The `autoCompactWindow` setting (or `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, 100k-1M tokens) makes it compact earlier.

```
cachekeeper compaction       # what an earlier compaction would have saved and cost, on your history
```

It replays every session with a smaller window: the context grows by what the real one grew by; past the window, a compaction reads it, writes a summary, and the conversation goes on from the size real compactions left behind. Measured on the author's 15 real compactions: the conversation went on from 70k tokens, of which the first request wrote 35k (the system prompt and tools stay cached); the summary took 5.3k tokens of output; and the model read 14k tokens of files again that it had read before. The cautious column assumes 45k read again (all the extra context growth after a compaction, an upper bound) and a 15k summary. On the author's 12.7 days, net (cautious):

| window | compactions a day | subscription usage | list price |
|---|---|---|---|
| 200k | 16 | +16% (−3%) | +46% (+36%) |
| 300k | 9 | +17% (+10%) | +43% (+38%) |
| 400k | 5 | +17% (+12%) | +38% (+34%) |
| 600k | 4 | +15% (+11%) | +29% (+27%) |
| 800k | 2 | +5% (+3%) | +15% (+13%) |

At list prices most of that is re-reads saved. On subscription usage nearly all of it is smaller rewrites after breaks and switches, less the compactions' own cost, and it overlaps with the keep-alive's saving: a break the keep-alive bridges has no rewrite left to shrink.

That is cost only. A compaction loses what its summary leaves out, a smaller window loses it more often, and whether that costs more than a long context is a question about the work, not the bill. Compacting yourself with `/compact` when a piece of work is done — with a note of what to keep — keeps more than a compaction wherever the window happens to fall; the window is the safety net for when you don't. Claude Code's own `/config` text recommends the automatic window "for the best cost and performance"; this replay is the history-specific number to weigh against it.

## Keep-alive (opt-in)

Coming back to a session after more than an hour re-caches the whole conversation. With `CACHEKEEPER_KEEPALIVE=1`, cachekeeper keeps a long session's cache warm while you are away, for as long as that is cheaper than the rebuild:

- When a turn ends, a `Stop` hook waits in the background (an `asyncRewake` hook: Claude Code wakes the model only if it exits with code 2). 55 minutes after the last request started, it wakes the model, which replies `(keep-alive)`: one request that reads the cache and starts its hour again. For a 300k-token Opus 5.5 conversation a ping costs about $0.07 at list price, nearly all of it the read, against $2.40 for the rebuild. On subscription usage the read counts next to nothing, and a ping counts mostly its own few hundred tokens: about $0.007 against $1.20 (the author's 15 pings each wrote 511 tokens and replied with 123, on average).
- Only for conversations of at least 100k tokens on the one-hour cache, and at most 3 pings in a row; the cache then lasts one more hour, about 3¾ hours after you left. Your next message starts the count again.
- It stands down when you write, when another turn ends, when the model is switched (the next request re-caches anyway), after `/compact`, and when the machine slept past the hour. `claude -p` runs are left alone.

Which numbers pay off depends on how you take breaks, and on the yardstick. `cachekeeper keepalive` replays your history (the breaks you came back from, and the time after each session's last message, where pings would only have cost) and prints the best policy with the settings to paste. On the author's 12.7 days:

- on subscription usage: sessions of at least 100k tokens kept for up to 24 hours — 1,981 pings (2.5% of usage) would have prevented 40 rebuilds (11.0%), net +8.5%. Up to 3 hours: +7.0%. With reads at 0 the 24-hour cap nets +10.0%; at 0.5% of the input price, the top of the interval, +6.1%, against +6.2% for 3 hours.
- at list prices: sessions of at least 300k tokens for up to 2 hours — 161 pings (1.5%), 20 rebuilds prevented (3.9%), net +2.4%. Up to 24 hours: −6.9%: two thirds of the pings at that cap go to sessions never returned to, and at list price each one re-reads the whole conversation.

The replay assumes the computer stays awake. Pings only run while it is awake and the session is open: on a computer that sleeps at night the pings before it sleeps are spent and the morning rebuild happens anyway. On subscription usage those pings cost under a cent each, so a long cap risks little.

| variable | default | effect |
|---|---|---|
| `CACHEKEEPER_KEEPALIVE` | off | `1`: on, with the settings below; `auto`: on, with the best policy on your history, recomputed daily |
| `CACHEKEEPER_KEEPALIVE_MIN_TOKENS` | `100000` | smaller conversations are left to expire |
| `CACHEKEEPER_KEEPALIVE_HOURS` | `3` | how long to keep pinging after your last message |
| `CACHEKEEPER_KEEPALIVE_MINUTES` | `55` | idle minutes before each ping |

With `auto`, the Stop hook redoes the `cachekeeper keepalive` replay once a day, in the background, and waits under the best policy it finds (the two settings above are then ignored; near-ties within 1% go to the policy with fewer pings). It prices the replay on subscription usage, since the keep-alive only waits in one-hour-cache sessions, unless `CACHEKEEPER_BASIS=api`; a policy computed on the other yardstick, or by 0.5 at list prices, is redone at the next turn's end. With fewer than 10 idle stretches to go on it uses the defaults; when no policy would have saved anything, or your sessions only use the five-minute cache, it stays off. Pings are left out of the replay — a three-hour break kept warm counts as the three-hour break it was, with the rebuild it avoided — so the policy does not talk itself out of the savings it makes. Claude Code deletes terminal transcripts 30 days after their last activity (desktop sessions are kept), so the idle stretches it has seen are also kept, as numbers only, in the plugin's data folder.

Measured live in the desktop app ([details](docs/measurement-2026-09-23.md#keep-alive-live)): pings 55 and 110 minutes after the last message each read the cache ($0.014 apiece at list price for a 57k-token Opus 5.5 session), and a message 112 minutes after the last one cost $0.015 instead of the $0.46 of writing it again.

`cachekeeper events` lists the pings and why each wait stood down. Other projects keep sessions warm with other mechanisms:

| project | mechanism |
|---|---|
| [Delitefully/claude-keepwarm](https://github.com/Delitefully/claude-keepwarm) | after 45 idle minutes submits one line asking for a single period, and hides the rows it leaves |
| [FiredMosquito831/claude-cache-warm](https://github.com/FiredMosquito831/claude-cache-warm) | plugin with status line, dashboard and per-session settings |
| [santiquiroz/claude-prompt-cache-keepalive](https://github.com/santiquiroz/claude-prompt-cache-keepalive) | a ladder of background timers that wake the session; documents that a recurring `CronCreate` job never fired in an idle session and `ScheduleWakeup` only works inside `/loop` |
| [Pan1127/cc-cache-keepalive](https://github.com/Pan1127/cc-cache-keepalive) | pings from a non-persistent fork so the original session gets no extra messages |
| [cnighswonger/claude-code-coffee](https://github.com/cnighswonger/claude-code-coffee) | `/coffee 30` before a break |

Claude Code itself also helps: the status line receives the cache's expiry time, `/usage` shows the hit ratio and the likely cause of the last miss, and resuming a large session after a long break offers to resume from a summary.

## Requirements and settings

Needs Python 3.8+ (the hook stays silent and lets every switch through without one) and a Claude Code with `PreModelSwitch` hooks (and `asyncRewake` hooks for the keep-alive; 2.1.280 has both). To try a checkout: `claude --plugin-dir /path/to/cachekeeper`.

| variable | default | effect |
|---|---|---|
| `CACHEKEEPER_MODE` | `ask` | `ask`, `warn` (never blocks; shows the message) or `off` |
| `CACHEKEEPER_BASIS` | follows the cache | `subscription` or `api`: the [yardstick](#two-yardsticks) for every amount |
| `CACHEKEEPER_MIN_USD` | `1.0` | ask only when the estimated rewrite counts at least this much, on that yardstick |
| `CACHEKEEPER_MIN_TOKENS` | `100000` | threshold when the new model's price is unknown |
| `CACHEKEEPER_CONFIRM_SECONDS` | `120` | how long a repeat counts as the confirmation |
| `CACHEKEEPER_OFFER_SECONDS` | `900` | how long the next message is handed to a subagent after a refusal |
| `CACHEKEEPER_LANG` | from `LANG` | `ko` or `en` |

Set them in the `env` block of `~/.claude/settings.json`.

## Limits

- `prompt_cache_warm` describes the current model's cache. Switching back to a model you used within the TTL can hit that model's own entry, so the rebuild is smaller than asked about: in the replay, 25 of the 29 asks were followed by a real rebuild.
- The replays model what the guard and a keep-alive would have done; what they save depends on your answers and your breaks.
- The subscription yardstick is measured from outside and can change without notice. Its read rate is small, but the author's history read 4.2 billion tokens from the cache in 12.7 days: across the 80% interval (0-0.5% of the input price), reads make 0% to 12% of its subscription usage. That one-hour writes count at the input price, not above it, is unmeasured: if they counted at 2× like the list price, rebuilds would weigh more, and the guard and the keep-alive would save more than shown.
- Each keep-alive ping is a short turn you can see in the conversation, and it counts toward your usage like any request.
- The keep-alive works only while the computer is awake and the session is open: a ping is a request the session itself makes. After a sleep that outlasted the hour it stands down instead of paying for a rebuild.
- The guard only sees switches that Claude Code routes through `PreModelSwitch`. Effort changes invalidate the cache on most models too (not on Opus 5.5 and Fable 5.1); Claude Code asks about those itself while the cache is warm.

## Tests

```
python3 -m unittest discover -s tests
```

MIT License.
