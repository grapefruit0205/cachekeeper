# Changelog

## 0.6.0 — 2026-09-24

- Two yardsticks. Every amount cachekeeper shows (the guard's estimate, the audit's shares, the keep-alive and
  compaction replays) is counted either on subscription usage or at API list prices. Subscription usage is how a
  plan's usage limits count, measured from outside: cache reads at 0.18% of the input price, cache writes of
  either TTL and uncached input at the input price, output at the output price (she-llac.com/claude-limits,
  January 2026; the alldonesites usage tracker, four Max 20x accounts, to 2026-09-21). That one-hour writes count
  at the input price and that Opus 5.5 follows its list price are assumptions. By default the cache picks the
  yardstick: the one-hour cache, which Claude Code 2.1.280 gives only to a subscription within its plan usage,
  counts on subscription usage and the five-minute cache at list prices. `CACHEKEEPER_BASIS=subscription` or
  `api` fixes it, and `audit`, `keepalive` and `compaction` take `--basis`.
- The guard: on the one-hour cache the estimate is Claude Code's without the write premium ("약 $4.52 (구독 사용량
  기준: 캐시 쓰기를 입력 단가로 셈)" where 0.5 said "약 $9.04 (API 정가 기준)"), and `CACHEKEEPER_MIN_USD` counts on
  the same yardstick, so on subscription usage it asks from about 250k tokens on Opus 5.5 and 100k on Fable 5.1
  (125k and 50k before). `CACHEKEEPER_MIN_USD=0.5` asks as often as 0.5 did. Each logged event records its
  yardstick, and `cachekeeper events` sums the two apart.
- `CACHEKEEPER_KEEPALIVE=auto` picks its policy on subscription usage (the keep-alive only waits on the one-hour
  cache), or at list prices with `CACHEKEEPER_BASIS=api`. A policy computed on the other yardstick, as every
  policy from 0.5 was, is recomputed when the next turn ends.
- The keep-alive replay counts the time after a session's last message: pings sent then cost and prevent nothing.
  0.5 replayed only the breaks the user came back from, which made long caps look free; at list prices two thirds
  of the pings at a 24-hour cap on the author's history go to sessions never returned to. That time is stored in
  `keepalive/gaps.jsonl` once no cap reaches past it (25 hours), and `claude -p` runs, where the keep-alive
  stands down, are left out. `gaps.jsonl` now keeps the tokens a rebuild wrote and the model, so either yardstick
  can price them; lines written by 0.4-0.5 are still read. The report says the replay assumes the computer stays
  awake.
- Pings are recognized by their exact text ("keep-alive ping N of M, not an error"). 0.5 took any message with
  "keep-alive ping" in it for one: the audit counted compaction summaries and messages about the pings as pings,
  and a user who wrote about them was not seen arriving. A ping never counts as the user arriving, whatever
  origin Claude Code gives it.
- The compaction replay uses constants measured on the author's 15 real compactions: the first request after one
  writes 35k of its 70k tokens (the system prompt and tools stay cached), the summary is 5.3k output tokens, and
  14k tokens of files are read again. The cautious column assumes 45k read again (all the extra context growth
  after a compaction, an upper bound) and a 15k summary. 0.5 assumed 20k and 60k read again, an 8k summary, and
  the whole 70k written anew.
- On the author's 12.7 days (152 sessions, 94% of requests on the one-hour cache), on subscription usage: cache
  writes are 51% of usage, output 44%, reads 5%; model switches cost 12.5% and idle expiry 11.8%. The best
  keep-alive is sessions of at least 100k tokens for up to 24 hours: 1,981 pings (2.5%) would have prevented 40
  rebuilds (11.0%), net +8.5% (at list prices: 300k tokens for 2 hours, +2.4%). An auto-compact window of 300k
  nets +17% (+10% cautious), 400k +17% (+12%).
- Both READMEs open with how to use it: install and update, answering the guard, turning on the keep-alive, and
  the four commands.

## 0.5.0 — 2026-09-23

- `cachekeeper compaction`: replays the local history with a smaller auto-compact window (200k-800k tokens):
  the context grows as it really did, each compaction reads it, writes a summary and continues from the size
  real compactions left behind plus what the model reads again, and later requests and rebuilds carry the
  smaller context. It prints compactions a day, reads and rebuilds saved, the compactions' cost, and the net
  under a normal and a cautious reread assumption. On the author's 13 days: +40% at 300k, +37% at 400k (+35% and
  +32% when every compaction costs 60k of rereading), cost only.

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
