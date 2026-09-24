<p align="center"><img src="assets/icon.png" width="160" alt="cachekeeper icon: a shield around a stack of cache layers with a refresh arrow"></p>

# cachekeeper

**English** · [한국어](README.ko.md)

**Stop throwing away a warm prompt cache by accident.** A Claude Code plugin with three parts:

- a **model-switch guard**: before `/model` or the model picker forfeits a warm cache, it asks — with the size of the loss and the alternative that keeps the cache;
- a **keep-alive**, on by default: while you are away, one short request every 55 minutes keeps a long session's cache warm, for as long as your own history says that is cheaper than the rebuild;
- **`cachekeeper audit`**: shows how much the keep-alive and the guard save, as a share of your usage on your own history, and attributes every cache rebuild to its cause, so you know which habit costs you the most.

## Install

You need Claude Code (2.1.280 has every hook cachekeeper uses) and Python 3.8 or newer ([On Windows](#on-windows)). In a terminal:

```
claude plugin marketplace add grapefruit0205/cachekeeper
claude plugin install cachekeeper@cachekeeper
```

or inside Claude Code: `/plugin marketplace add grapefruit0205/cachekeeper`, then `/plugin install cachekeeper@cachekeeper`.

That is all: there is nothing to set. The desktop app loads the plugin into open sessions at once; restart a terminal session.

- Update: `claude plugin marketplace update cachekeeper`, then `claude plugin update cachekeeper@cachekeeper`.
- Remove: `claude plugin uninstall cachekeeper@cachekeeper`.

### On Windows

On Windows, Claude Code runs a plugin's hooks with Git Bash, and with PowerShell when there is no Git Bash; cachekeeper's hooks run in either (from 0.9.0 on). This holds for the Claude desktop app and for Claude Code in a terminal. What they need is Python:

1. **Install Python 3.8 or newer** from [python.org](https://www.python.org/downloads/windows/). In PowerShell, one of `python3 --version`, `python --version` or `py -3 --version` should print 3.8 or newer. The `python` that comes with Windows only points you to the Microsoft Store; it is not Python.
2. **Quit the desktop app or the terminal completely and open it again** (the desktop app from its tray icon too). A Claude Code that is already running keeps the environment it started with.
3. **Check**: in a new session, run `/cachekeeper:audit`. A report means Python was found, and the hooks find the same one. If it says `Python 3.8 or newer is required`, go back to step 1. Without Python the hooks stay off without an error, so this is the way to tell.

Git for Windows is not needed. If you have it, Claude Code runs the hooks with its Git Bash, which it looks for in `C:\Program Files\Git` and next to the `git` on your PATH; name one installed elsewhere in `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_GIT_BASH_PATH": "C:\\Program Files\\Git\\bin\\bash.exe"
  }
}
```

Without it, they run in PowerShell 7 (`pwsh`) if it is installed, and otherwise in the Windows PowerShell 5.1 that comes with Windows. There `/cachekeeper:audit` runs `bin/cachekeeper.ps1` by its path, since Claude Code puts a plugin's `bin/` only on the Bash tool's PATH.

- **WSL**: Claude Code in WSL, including the desktop app's WSL environment, runs as on Linux: install cachekeeper in the Claude Code inside WSL. WSL's Ubuntu comes with Python.
- The author uses cachekeeper on Ubuntu. On Windows it is tested in CI (GitHub's Windows runners, in Git Bash, PowerShell 7 and Windows PowerShell 5.1), not yet on a Windows machine running Claude Code.

The Windows desktop app installed as an MSIX package has a bug: outside programs such as Git Bash and Python cannot see plugin files the app unpacks into its own folder (`%APPDATA%\Claude`) ([anthropics/claude-code#96087](https://github.com/anthropics/claude-code/issues/96087)). A plugin installed from a marketplace usually goes to `C:\Users\<you>\.claude\plugins` instead, so this should not touch cachekeeper, but that is not verified. If it does, the hooks find no files and end quietly (a hook exits 2 only for a keep-alive ping): no loop, only no guard and no keep-alive.

## How to use

Day to day there is nothing to run. Three things happen by themselves.

**When you switch models.** If `/model` or the model picker would throw away a warm cache whose rewrite counts at least $1, the switch stops and shows the amount. Then either:

- send the request you meant for the other model. You are asked whether a subagent on that model should handle it: yes, and it does just that request, then the conversation goes on with your session's model and its warm cache; no, and your session's model answers as usual;
- or, to switch the session anyway, type the `/model` command the message names within 120 seconds (a terminal session shows a confirmation dialog instead).

**When you step away.** In a long session, 55 minutes after your last message the model gets a short ping and answers `(keep-alive)`, which keeps the cache for another hour. Which sessions, and for how long, cachekeeper works out from your own history and redoes once a day; when your history says it would not have paid off, it stays off. To turn it off yourself, add this to `~/.claude/settings.json`, inside the existing `env` block if there is one:

```json
{
  "env": {
    "CACHEKEEPER_KEEPALIVE": "0"
  }
}
```

**When you want to know what it saves and where your usage goes.** Type `/cachekeeper:audit` in a session, or ask Claude to run one of these (the plugin puts `cachekeeper` on the PATH of Claude Code's shell):

| command | shows |
|---|---|
| `cachekeeper audit` | how much the keep-alive and the guard save on your history, what your usage is made of, and the cause of every cache rebuild |
| `cachekeeper keepalive` | which keep-alive policy pays off on your history, and the one in use |
| `cachekeeper compaction` | what an earlier auto-compaction would have saved and cost |
| `cachekeeper events` | the guard's asks and the keep-alive's pings |

`--days N` sets the period (30 days by default), `--lang ko` or `--lang en` the language, and `--basis subscription` or `--basis api` the [yardstick](#two-yardsticks); `audit --json` prints the numbers as JSON. The commands read only this machine's transcripts and send nothing. Outside Claude Code, run them from a checkout: `git clone https://github.com/grapefruit0205/cachekeeper`, then `cachekeeper/bin/cachekeeper audit`.

In the terminal, the status line can also count down the cache's hour and the next ping: [set it up](#in-the-terminals-status-line).

## What to expect

On a subscription, cache reads count next to nothing, and a rebuild, which writes the whole conversation again, is the costliest thing a turn can do. On the author's 13 days of history (2026-09-11 to 09-24, 178 sessions, counted on subscription usage), rebuilds after model switches were 11.9% of usage and rebuilds after breaks of more than an hour 11.5%. Replaying that history:

| part | on the author's history |
|---|---|
| keep-alive | **+6.6%** of usage with the computer's real up-time (it shuts down or sleeps most nights); +8.4% on a computer that stays on |
| model-switch guard | it would have asked before 29 of 40 manual switches, and the rebuilds behind them were **8.2%** of usage. What you save depends on how often you hand the task to a subagent instead; one costs its own start, about 45k tokens written |
| an earlier auto-compaction | an `autoCompactWindow` of 300k-400k tokens nets **+17%** (+10-12% with cautious assumptions); `cachekeeper compaction` gives your number |

The three overlap, so they do not add up: a break the keep-alive bridges leaves no rebuild for a smaller window to shrink. These are replays of one person's history, not a controlled test; `/cachekeeper:audit` shows yours.

## Strengths

Measured numbers come from the author's machine, replays from the author's history ([What to expect](#what-to-expect)), and comparisons from the other projects' READMEs on 2026-09-24 ([Compared with other keep-alives](#compared-with-other-keep-alives)).

1. **On in every session once installed, the desktop app included.** There is nothing to arm per session. Measured in the desktop app from 2026-09-23 14:50 to 2026-09-24 17:28 KST: 26 keep-alive pings, 7 guard asks and 1 request handed to a subagent. Many other keep-alives are armed per session (cachebeat's `/cachebeat`; cache-tax's `/keepwarm`, unless set to arm at every session start), run only in interactive CLI sessions (plugin monitors such as demouo's), or need the early-access function hooks (Delitefully's claude-keepwarm, cache-tax).
2. **Both big causes of rebuilds, not one.** On the author's 13 days, rebuilds after model switches were 11.9% of usage and rebuilds after breaks of more than an hour 11.5% (replay). A keep-alive alone addresses only the second; the guard covers the first.
3. **A refused switch still gets the other model's answer.** Refuse the switch and send the request: it can go to a subagent on that model, while the main conversation keeps its warm cache. In the desktop app and in `-p` runs, where Claude Code shows no confirmation dialog of its own, the guard is what stops the switch.
4. **A policy from your own breaks, on the yardstick your plan counts.** Which sessions to keep warm, and for how long, is recomputed daily from your history and priced on subscription usage. The others use fixed or hand-set times, and those that price their pings use list prices. On real up-time the edge over a fixed policy is small, though: 3 hours nets +6.2% and 24 hours +6.6% on the author's machine (replay).
5. **It shows what it saves.** `cachekeeper audit` replays your history. On the author's, the keep-alive nets +6.6% of usage with real up-time, and the switches the guard would have asked about carried rebuilds worth 8.2% of usage (replay). It also names the cause of every rebuild.
6. **Its safety is checked in CI.** A hook exits 2, the code that wakes the model, only to ping, so a broken install cannot wake it in a loop ([Keep-alive](#keep-alive)). CI runs the hooks on Linux and macOS, and on Windows in Git Bash, PowerShell 7 and Windows PowerShell 5.1.

Its weak points are under [Limits](#limits).

## Q&A

**Does it ping my old sessions?** No. A session is pinged only after a turn ends in it while cachekeeper is running, so after you restart the app, only the sessions you have used since. Each session also stops at its cap (on the author's history, 24 hours after your last message in it), and at once when the app closes or the computer sleeps past the hour.

**I run several sessions in parallel. Which ones get pinged?** Each runs on its own clock: 55 minutes after that session's last request, up to its cap after your last message there. Typing in one session does not reset another. cachekeeper cannot tell a finished session from one you will come back to, so the cap comes from how often you did come back. On the author's history 70% of the pings went to sessions never returned to and cost 0.6% of usage; the rest prevented rebuilds worth 7.5%.

**What does a ping cost?** About a cent of subscription usage: it writes a few hundred tokens, and the cache read counts next to nothing. At API list prices it also re-reads the whole conversation: about $0.07 for a 300k-token Opus 5.5 conversation, against $2.40 for the rebuild.

**Will I see the pings?** Yes: a `cachekeeper keep-alive ping` notification and the reply `(keep-alive)`. Each adds a few hundred tokens to the conversation.

**Why not ping every 55 minutes forever?** On the author's computer, which shuts down or sleeps at night, no cap gives the same +6.6%. On a computer that never slept it would have cost 0.4% of usage (6.5% for sessions of any size), because pings would go on for days into sessions never returned to. The cap is for computers that stay on.

**Does it work while the computer sleeps or the app is closed?** No. A ping is a request the session itself makes, so the computer has to be awake and the session open. After a sleep that outlasted the hour the cache is gone, and cachekeeper stands down instead of paying for a rebuild.

**Is the one hour Anthropic's rule?** Yes. Per [Claude Code's documentation](https://code.claude.com/docs/en/prompt-caching#cache-lifetime), the main conversation's cache lives one hour on a Claude subscription within its plan usage, and five minutes with an API key, usage credits or a cloud provider; every request that reads it starts the timer again. cachekeeper reads each session's actual cache lifetime from its transcript and stays off on the five-minute cache.

**I use an API key.** Unless you set `promptCacheTtl` to `1h`, your sessions use the five-minute cache: the keep-alive stays off, and the guard and the audit count at list prices. With `1h`, set `CACHEKEEPER_BASIS=api` so that they count at list prices too.

**Does it work on Windows and macOS?** Yes. Both need only Python 3.8 or newer; on Windows, restart the app after installing it ([On Windows](#on-windows)). CI runs the tests on all three systems, on Windows in Git Bash and in both PowerShells; the author uses it on Ubuntu.

**Does it send anything anywhere?** No. It reads this machine's transcripts. Its log (`events.jsonl` in the plugin's data folder) holds model ids, token counts and decisions, no prompt text.

**How do I turn one part off?** The keep-alive: `"CACHEKEEPER_KEEPALIVE": "0"`. The guard: `"CACHEKEEPER_MODE": "off"`, or `"warn"` to show the message without stopping the switch. Both go in the `env` block of `~/.claude/settings.json` ([all settings](#requirements-and-settings)).

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
fable-5-1 — about $4.52 of subscription usage (a cache write counts at the input price). To run just
this task on fable-5-1, send the request as you meant to: you will be asked whether a fable-5-1
subagent should handle it, and this session then continues on opus-5. To switch the session itself,
type `/model claude-fable-5-1` within 120s. If a model picker still shows fable-5-1, this session is
still on opus-5.
```

On the one-hour cache the amount is Claude Code's estimate on subscription usage: the write without its 2× premium. On the five-minute cache, or with `CACHEKEEPER_BASIS=api`, it is Claude Code's list-price estimate (`about $9.04 at list price`). The `$1` threshold is on the same yardstick, so on subscription usage the guard asks from about 250k tokens on Opus 5.5 and 100k on Fable 5.1 (125k and 50k at list price); `CACHEKEEPER_MIN_USD=0.5` asks as often as before 0.6.0.

- In a terminal session Claude Code shows that as its confirmation dialog. Claude Code asks there by itself too before a `/model` switch while the cache is warm ([documentation](https://code.claude.com/docs/en/prompt-caching#switching-models)); a `PreModelSwitch` hook's `ask` is that same dialog, here with the amount and the alternative.
- **In the Claude desktop app** — where the model picker and a typed `/model` both reach Claude Code as an app request — and in headless `-p` sessions there is no dialog: the switch is blocked with that text, and **typing the `/model` command it names within 120 seconds is the confirmation**. Verified in the desktop app on 2026-09-23: `/model opus` was blocked with the message; the same command 21 seconds later switched the session.
- The desktop app's picker is not a reliable way to confirm. A switch blocked between turns can leave the picker showing the new model while the session stays on the old one, and picking it again sends nothing (seen 2026-09-23). A switch blocked mid-turn puts the picker back on the session's model (desktop app 2.2553.13 logs `record restored`), and picking the new model again then reaches Claude Code and confirms the switch: on 2026-09-24 a second pick six seconds after the refusal switched the author's session. If the picker disagrees with the session, pick the session's current model to bring them back in line.
- Switches with a cold cache, small contexts, automatic fallbacks and resume restores pass silently: `PreModelSwitch` only fires for `/model`, the picker and SDK calls.
- A subagent keeps the main cache: its call and result are appended to the conversation, and it builds its own cache on its own model.

### Run just this task on the other model

The refusal also offers the cheaper way to get the other model's work: **send the request you meant for the other
model as your next message, and you are asked whether a subagent on that model should handle it.** Yes, and the
subagent does that one request while the session stays on its model and its cache stays warm; when it returns, the
main model relays or applies the result and the conversation goes on with the session's model. No, and the
session's model answers it. A `UserPromptSubmit` hook puts the question to the main model (it asks with
AskUserQuestion, in your language) together with the handover: the Agent tool with the exact model you asked for,
e.g. `model: "claude-fable-5-1"`, falling back to the alias `fable`, and a self-contained brief — the subagent does
not see the conversation, so the main model writes it what it needs. Later messages run normally. In `claude -p`
runs and Agent SDK apps (an `sdk-` entrypoint), where nobody is there to answer, the request goes to the subagent
without the question. It works in every direction: from Fable, `/model claude-opus-5` offers an Opus 5 subagent.
Typing the `/model` command instead switches the session as before.

The session itself never changes model: the main model asks, writes the brief and carries on afterwards, all on
its own model, so going back to the main model takes no second switch and no second rebuild.

Verified live on 2026-09-23 with Opus 5.5 as the main model: after a refused switch the next request went to a
subagent on the other model (`Agent`, `model: "sonnet"`) and the answer ended with "This session is still on
Opus". With Haiku 4.5 as the main model the instruction reached the model and was ignored three times out of
three, so the offer is as reliable as the main model's instruction-following. The question before the handover is
new and not yet verified live.

Every switch request and every switch that happens is logged to `events.jsonl` in the plugin's data directory — model ids, token counts, the estimate and the decision; no prompt text. `cachekeeper events` summarizes it.

## The audit

The audit's job is to show the saving: how much of your usage cachekeeper saves, replayed on your own history. For the keep-alive that is the net saving, after what its pings cost; for the guard it is the usage riding on its questions, since what it saves depends on your answers. On the author's history (2026-09-11 to 09-24):

```
With the model-switch guard on
  Of 41 manual switches, 30 had a warm cache and a rebuild of at least $1: the guard would have asked; 26 of them did rebuild — 7.9% of all usage rode on those answers.

With a 55-minute keep-alive (one-hour TTL sessions, 8-hour cap)
  1222 pings (with those after the last message of sessions never returned to) would cost 1.1% of usage and prevent 33 idle rebuilds (7.5%): net +6.4%.
  Keep-alive pings actually sent: 27, 0.1% of usage
```

The saving of the policy in use, which `auto` picks, is in `cachekeeper keepalive` (on the author's history: sessions from 100k tokens for up to 24 hours, net +8.0%).

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

## Keep-alive

Coming back to a session after more than an hour re-caches the whole conversation. cachekeeper keeps a long session's cache warm while you are away, for as long as that is cheaper than the rebuild:

- When a turn ends, a `Stop` hook waits in the background (an `asyncRewake` hook: Claude Code wakes the model only if it exits with code 2). 55 minutes after the last request started, it wakes the model, which replies `(keep-alive)`: one request that reads the cache and starts its hour again. For a 300k-token Opus 5.5 conversation a ping costs about $0.07 at list price, nearly all of it the read, against $2.40 for the rebuild. On subscription usage the read counts next to nothing, and a ping counts mostly its own few hundred tokens: about $0.007 against $1.20 (the author's 15 pings each wrote 511 tokens and replied with 123, on average).
- Only for conversations on the one-hour cache above a minimum size, and for at most so many pings in a row. By default both come from your history (below); the fixed settings are 100k tokens and 3 pings, after which the cache lasts one more hour, about 3¾ hours after you left. Your next message starts the count again.
- It stands down when you write, when another turn ends, when the model is switched (the next request re-caches anyway), after `/compact`, and when the machine slept past the hour. `claude -p` runs and Agent SDK apps are left alone.
- Exit 2 is the one failure that loops. Claude Code 2.1.280 wakes the model on exit code 2 and on nothing else (read in its code), so a Stop hook that exits 2 at every turn end wakes it without end ([anthropics/claude-code#96087](https://github.com/anthropics/claude-code/issues/96087) and [#96148](https://github.com/anthropics/claude-code/issues/96148), both a Python that could not open its script). So a cachekeeper hook exits 2 only on request: for a ping the keep-alive ends with its own code, 75, and the Stop hook's command turns that code alone into 2. Whatever else ends a hook (its files gone, no Python, a crash, a shell that cannot open a script, as Ubuntu's `sh` then exits 2 too) ends it with 0, and the model-switch and prompt hooks always end with 0: their answers are JSON.

Which numbers pay off depends on how you take breaks, and on the yardstick. `cachekeeper keepalive` replays your history (the breaks you came back from, and the time after each session's last message, where pings would only have cost) and prints the best policy: the one the default `auto` mode uses. On the author's 12.7 days:

- on subscription usage: sessions of at least 100k tokens kept for up to 24 hours — 1,981 pings (2.5% of usage) would have prevented 40 rebuilds (11.0%), net +8.5%. Up to 3 hours: +7.0%. With reads at 0 the 24-hour cap nets +10.0%; at 0.5% of the input price, the top of the interval, +6.1%, against +6.2% for 3 hours.
- at list prices: sessions of at least 300k tokens for up to 2 hours — 161 pings (1.5%), 20 rebuilds prevented (3.9%), net +2.4%. Up to 24 hours: −6.9%: two thirds of the pings at that cap go to sessions never returned to, and at list price each one re-reads the whole conversation.

The replay assumes the computer stays awake. Pings only run while it is awake and the session is open: on a computer that sleeps at night the pings before it sleeps are spent and the morning rebuild happens anyway. On subscription usage those pings cost under a cent each, so a long cap risks little. On the author's machine, which shuts down or sleeps most nights, the same replay with its real up-time (boots and suspends from the system journal; pings stop at the first shutdown or suspend) gives +6.2% for 3 hours and +6.6% for 24 hours on subscription usage: the long cap loses nothing there, and gains little. With no cap at all it gives +6.6% there, where shutting down or sleeping at night acts as the cap, but −0.4% if the computer never slept (−6.5% for sessions of any size): pings would go on for days into sessions never returned to. The cap is for computers that stay on.

| variable | default | effect |
|---|---|---|
| `CACHEKEEPER_KEEPALIVE` | `auto` | `auto`: on, with the best policy on your history, recomputed daily; `1`: on, with the settings below; `0`: off |
| `CACHEKEEPER_KEEPALIVE_MIN_TOKENS` | `100000` | with `1`: smaller conversations are left to expire |
| `CACHEKEEPER_KEEPALIVE_HOURS` | `3` | with `1`: how long to keep pinging after your last message |
| `CACHEKEEPER_KEEPALIVE_MINUTES` | `55` | idle minutes before each ping |

With `auto`, the default, the Stop hook redoes the `cachekeeper keepalive` replay once a day, in the background, and waits under the best policy it finds (the two settings above are then ignored; near-ties within 1% go to the policy with fewer pings). It prices the replay on subscription usage, since the keep-alive only waits in one-hour-cache sessions, unless `CACHEKEEPER_BASIS=api`; a policy computed on the other yardstick, or by 0.5 at list prices, is redone at the next turn's end. With fewer than 10 idle stretches to go on it uses the defaults; when no policy would have saved anything, or your sessions only use the five-minute cache, it stays off. Pings are left out of the replay — a three-hour break kept warm counts as the three-hour break it was, with the rebuild it avoided — so the policy does not talk itself out of the savings it makes. Claude Code deletes terminal transcripts 30 days after their last activity (desktop sessions are kept), so the idle stretches it has seen are also kept, as numbers only, in the plugin's data folder.

Measured live in the desktop app ([details](docs/measurement-2026-09-23.md#keep-alive-live)): pings 55 and 110 minutes after the last message each read the cache ($0.014 apiece at list price for a 57k-token Opus 5.5 session), and a message 112 minutes after the last one cost $0.015 instead of the $0.46 of writing it again.

`cachekeeper events` lists the pings and why each wait stood down.

### In the terminal's status line

In the terminal, `cachekeeper statusline` fills Claude Code's status line with the cache's time left and the next ping:

```
cache 312k · 36m left · next ping in 31m (1/26)
```

`312k` is what the next request would write again if the cache went cold; `(1/26)` says the next ping is the first of the 26 the current policy allows after your last message. It can also say `ping due`, `ping cap (26/26)`, `no ping (under 100k)`, `keep-alive off`, `(5-min cache)` (the keep-alive only keeps the one-hour cache) and `cache cold · next request rewrites 312k`. It speaks Korean with `CACHEKEEPER_LANG=ko` or a Korean `LANG`.

A plugin cannot set the status line, so add this to `~/.claude/settings.json` yourself. The path is the marketplace's copy of the plugin, which stays in place across versions:

```json
{
  "statusLine": {
    "type": "command",
    "command": "~/.claude/plugins/marketplaces/cachekeeper/bin/cachekeeper statusline",
    "refreshInterval": 30
  }
}
```

- `refreshInterval` re-runs it every 30 seconds, so the minutes count down while you are away; without it Claude Code refreshes the line only after events and when the cache expires.
- On Windows the command above works where Git Bash is installed. Without Git Bash: `"command": "powershell -NoProfile -ExecutionPolicy Bypass -File C:/Users/<you>/.claude/plugins/marketplaces/cachekeeper/bin/cachekeeper.ps1 statusline"`, with forward slashes.
- If you already have a status line, have your script call this one and join the two, for example `echo "$(your part) · $(printf '%s' "$input" | ~/.claude/plugins/marketplaces/cachekeeper/bin/cachekeeper statusline)"`.
- It reads the end of the transcript and the plugin's own files, and writes and sends nothing: about 0.1 s on a 12 MB transcript (measured). It needs Claude Code 2.1.251 or later, which passes the cache's state to status lines.
- The desktop app runs no status line command: none ran in 1 minute 44 seconds with a 5-second `refreshInterval` (measured 2026-09-24, Claude Code 2.1.280), and in Claude Code's code the status line belongs to the terminal interface. So this is for the terminal only.

### Compared with other keep-alives

Other projects keep the cache warm too. cachekeeper first, then the others as their READMEs describe them on 2026-09-24:

| project | how it pings | when | priced at |
|---|---|---|---|
| **cachekeeper** | an `asyncRewake` `Stop` hook that comes with the plugin; measured in the desktop app, tested in CI on Linux, macOS and Windows | 55 minutes after the last request; the minimum size and the cap after your last message come from your history, recomputed daily (fixed settings: 100k tokens, 3 hours) | subscription usage (list prices with `CACHEKEEPER_BASIS=api`) |
| [Delitefully/claude-keepwarm](https://github.com/Delitefully/claude-keepwarm) | a function-hooks module (needs `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`, an early-access feature) or a background monitor; a second plugin blanks the ping rows | after 45 idle minutes, up to 8 times (about 8 hours), from 20k tokens; skips a ping once the cache is cold | list prices |
| [FiredMosquito831/claude-cache-warm](https://github.com/FiredMosquito831/claude-cache-warm) | a plugin monitor, which runs only in interactive CLI sessions; elsewhere, as in the desktop app, it has Claude schedule a `CronCreate` task, which fires on a fixed schedule even while you work. Status line, dashboard, tray app | by default only while a subagent or background command runs; every 50 minutes, for up to 3 hours away, from 20k tokens | list prices |
| [santiquiroz/claude-prompt-cache-keepalive](https://github.com/santiquiroz/claude-prompt-cache-keepalive) | a skill arms a ladder of background timers that hold an OS sleep lock, and a hook arms it when you write "afk" or "I'm going to sleep". Reports that a recurring `CronCreate` job never fired in an idle session and `ScheduleWakeup` works only inside `/loop` | as long as you size the ladder | list prices |
| [Pan1127/cc-cache-keepalive](https://github.com/Pan1127/cc-cache-keepalive) | a systemd timer pings the most recent session from a fork that is not saved; needs Linux, tmux and a `sessions.json` kept by your own session manager | 50 minutes after the last activity | — |
| [cnighswonger/claude-code-coffee](https://github.com/cnighswonger/claude-code-coffee) | `/coffee 30` or `/coffee overnight` before a break schedules `CronCreate` pings | the break you name | list prices |
| [yujiachen-y/claude-code-cache-keepalive](https://github.com/yujiachen-y/claude-code-cache-keepalive) | a `Stop` hook sleeps 4 minutes, then blocks the stop to run one more turn | the five-minute cache: up to 7 times (about 28 minutes) | API key billing; says to turn it off on a subscription |
| [demouo/claude-code-cache-keepalive](https://github.com/demouo/claude-code-cache-keepalive) | a plugin monitor (the Monitor tool) watches the time the `Stop` hook writes; plugin monitors run only in interactive CLI sessions | after 50 idle minutes, until 12 hours of idle | list prices |
| [159753a52/claude-cache-keepalive](https://github.com/159753a52/claude-cache-keepalive) | an `asyncRewake` `Stop` hook in Node.js, added to `settings.json` by hand | 50 minutes after a turn ends, up to 3 times, from 50k tokens, on a claude.ai subscription only | — |
| [ARahim3/cachebeat](https://github.com/ARahim3/cachebeat) | `/cachebeat` starts a background shell task that exits after 50 idle minutes; the exit wakes Claude, which starts the task again | after 50 idle minutes, until 8 hours after you arm it (by default); the one-hour cache only | — |
| [karanb192/cache-tax](https://github.com/karanb192/cache-tax) | a function-hooks module (needs `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1`) sends a tool-less fork of the session. It also stops a message to a cold cache once and shows the rewrite price; status line | after 50 idle minutes, inside a window you arm with `/keepwarm` (6 hours by default, or at every session start); at least 3 hours after a cold rewrite | list prices |
| [bpeers01/tkr-releases](https://github.com/bpeers01/tkr-releases) | an `asyncRewake` watcher hook, part of a token-saving suite shipped as a binary. Since v5.31 it also warns before a model switch that would rebuild a large cache | after an idle time you can set, on the one-hour cache; skips small contexts | — |
| [luoxiaoxin123/cc-keepalive-desktop](https://github.com/luoxiaoxin123/cc-keepalive-desktop) | a local proxy, set per project folder through `HTTPS_PROXY`, repeats the session's request with `max_tokens=1`; Windows only, made for the desktop app | every 50 minutes (58 at most) in the sessions you turn it on for; stops after 58 idle minutes | — |

[xinnyu/claude-cache-warm](https://github.com/xinnyu/claude-cache-warm) (a `/loop` every 270 seconds) and [meetvaghani12/claude-cache-warmer](https://github.com/meetvaghani12/claude-cache-warmer) also keep the five-minute cache. On forks, Delitefully measured that `claude --resume <id> --fork-session -p` against a live session read nothing and wrote 54,300 tokens: the system prompt carries text unique to each session, so a fork warms its own cache, not the session's. cache-tax's fork, which Claude Code makes over the running session's transcript, read 157k tokens from the cache in its one measured return.

[navaro1/warmfold](https://github.com/navaro1/warmfold) and [intenex/claude-idle-compactor](https://github.com/intenex/claude-idle-compactor) take the other road: they compact an idle session before its cache expires, so coming back rewrites a summary instead of the whole conversation. [ruodou233/claude-cache-keepalive](https://github.com/ruodou233/claude-cache-keepalive) is a skill and a spec: the agent measures your setup first, then sets up pings (on a subscription, 55 minutes apart, at most 2 per break).

What cachekeeper does not do: hide the ping rows (keepwarm-quiet does), show a countdown in the desktop app, which runs no status line (FiredMosquito831's claude-cache-warm has a dashboard and a tray app), stop a message that would rewrite a cold cache (cache-tax and warmfold do), compact an idle session before it goes cold (warmfold and claude-idle-compactor do), keep the computer awake (santiquiroz's timers do), or keep the five-minute cache warm (yujiachen-y's, xinnyu's and meetvaghani12's do).

Claude Code itself also helps: the status line receives the cache's expiry time, `/usage` shows the hit ratio and the likely cause of the last miss, and resuming a large session after a long break offers to resume from a summary.

## Requirements and settings

Needs Python 3.8+ (the hook stays silent and lets every switch through without one) and a Claude Code with `PreModelSwitch` hooks (and `asyncRewake` hooks for the keep-alive; 2.1.280 has both). To try a checkout: `claude --plugin-dir /path/to/cachekeeper`.

It runs on Linux, macOS and Windows, there in Git Bash or in PowerShell ([On Windows](#on-windows)), and CI runs the tests on all three ([Tests](#tests)).

| variable | default | effect |
|---|---|---|
| `CACHEKEEPER_MODE` | `ask` | `ask`, `warn` (never blocks; shows the message) or `off` |
| `CACHEKEEPER_BASIS` | follows the cache | `subscription` or `api`: the [yardstick](#two-yardsticks) for every amount |
| `CACHEKEEPER_MIN_USD` | `1.0` | ask only when the estimated rewrite counts at least this much, on that yardstick |
| `CACHEKEEPER_MIN_TOKENS` | `100000` | threshold when the new model's price is unknown |
| `CACHEKEEPER_CONFIRM_SECONDS` | `120` | how long a repeat counts as the confirmation |
| `CACHEKEEPER_OFFER_SECONDS` | `900` | how long after a refusal the next message still brings the subagent question |
| `CACHEKEEPER_LANG` | from `LANG` | `ko` or `en` |

Set them in the `env` block of `~/.claude/settings.json`.

## Limits

- `prompt_cache_warm` describes the current model's cache. Switching back to a model you used within the TTL can hit that model's own entry, so the rebuild is smaller than asked about: in the replay, 25 of the 29 asks were followed by a real rebuild.
- The replays model what the guard and a keep-alive would have done; what they save depends on your answers and your breaks.
- The subscription yardstick is measured from outside and can change without notice. Its read rate is small, but the author's history read 4.2 billion tokens from the cache in 12.7 days: across the 80% interval (0-0.5% of the input price), reads make 0% to 12% of its subscription usage. That one-hour writes count at the input price, not above it, is unmeasured: if they counted at 2× like the list price, rebuilds would weigh more, and the guard and the keep-alive would save more than shown.
- Each keep-alive ping is a short turn you can see in the conversation, and it counts toward your usage like any request.
- The keep-alive works only while the computer is awake and the session is open: a ping is a request the session itself makes. After a sleep that outlasted the hour it stands down instead of paying for a rebuild.
- The guard only sees switches that Claude Code routes through `PreModelSwitch`. Effort changes invalidate the cache on most models too (not on Opus 5.5 and Fable 5.1); Claude Code asks about those itself while the cache is warm.
- The numbers in this README come from one author's history on one Linux machine. Windows is tested in CI only, not yet on a real Windows machine running Claude Code.

## Tests

```
python3 -m unittest discover -s tests
```

`tests/test_runner.py` runs the hooks and the CLI the way Claude Code does: hooks.json's own commands in each shell Claude Code uses (`/bin/sh -c` on macOS and Linux; on Windows Git Bash, or without it PowerShell 7 or Windows PowerShell 5.1), the event on stdin, under the code pages Python uses for pipes on Windows (cp1252, cp949). It checks that the keep-alive exits 2 with its message, which is what makes `asyncRewake` wake the model, that only the keep-alive's own code becomes 2, and that no hook exits 2 when the plugin's files are gone. CI runs every test on Ubuntu, macOS and Windows with Python 3.8 and 3.12 (3.12 only on macOS); on Windows in Git Bash with a Windows path and in both PowerShells.

MIT License.
