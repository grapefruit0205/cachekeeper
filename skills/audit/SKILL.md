---
name: audit
description: Report where this machine's Claude Code prompt-cache spend goes — model switches, idle expiry, effort changes, compaction, session starts — from the local transcripts, and what the model-switch guard and a keep-alive would have reached. Use when the user asks why usage is high, what cache rebuilds cost, or runs /cachekeeper:audit.
---

Run `cachekeeper audit` with the Bash tool (it is on the PATH while this plugin is enabled). Pass `--days N` when the user names a period and `--lang ko` or `--lang en` to match the user's language. It reads only `~/.claude/projects/*/*.jsonl` on this machine and prints aggregate shares; nothing leaves the machine.

Then answer in the user's language:

1. The largest cause of rebuilds and its share of all usage.
2. The one change that reaches it: for manual model switches, pick the model at the start of a session or hand the part that needs the other model to a subagent on that model; for idle expiry, run `cachekeeper keepalive` and give its best policy with the settings line it prints (or say it would not have paid off), and `/compact` before breaks longer than that; for effort changes, set effort at the start of a session.
3. That the shares are weighted at API list prices and are not a subscription bill.

Do not switch models, change effort, run `/compact` or edit settings yourself.
