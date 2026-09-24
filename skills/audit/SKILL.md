---
name: audit
description: Report where this machine's Claude Code prompt-cache spend goes — model switches, idle expiry, effort changes, compaction, session starts — from the local transcripts, and what the model-switch guard and a keep-alive would have reached. Use when the user asks why usage is high, what cache rebuilds cost, or runs /cachekeeper:audit.
---

Run `cachekeeper audit` with the Bash tool (it is on the PATH while this plugin is enabled). Where there is no Bash tool, only PowerShell (Windows without Git Bash), run `& "${CLAUDE_PLUGIN_ROOT}/bin/cachekeeper.ps1" audit` instead, and the other `cachekeeper` commands below the same way. Pass `--days N` when the user names a period, `--lang ko` or `--lang en` to match the user's language, and `--basis subscription` or `--basis api` only when the user asks for the other yardstick. It reads only `~/.claude/projects/*/*.jsonl` on this machine and prints aggregate shares; nothing leaves the machine.

Then answer in the user's language:

1. The largest cause of rebuilds and its share of all usage.
2. The one change that reaches it: for manual model switches, pick the model at the start of a session or hand the part that needs the other model to a subagent on that model; for idle expiry, the keep-alive is on by default (`auto`): run `cachekeeper keepalive` and give its best policy and the one auto mode uses now (or say it would not have paid off, so auto mode leaves it off), and `/compact` before breaks longer than its cap; for effort changes, set effort at the start of a session.
3. When requests re-send several hundred thousand tokens, also run `cachekeeper compaction` and give the window that holds up in its cautious column, how many compactions a day that means, and that it measures cost only: a compaction loses details, so `/compact` at the end of a piece of work is the first recommendation and the window the safety net.
4. Which yardstick the report used, as its first lines say: subscription usage (how a plan's usage limits count, measured from outside: cache reads next to nothing, cache writes at the input price) or API list prices. Either way the shares are shares of usage, not a bill.

Do not switch models, change effort, run `/compact` or edit settings yourself.
