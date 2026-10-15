---
name: keepalive-off
description: Turn cachekeeper's keep-alive off for this session only, until the user writes in it again or resumes it. Other sessions and the settings are unchanged. Runs when the user types /cachekeeper:keepalive-off.
disable-model-invocation: true
---

cachekeeper's `UserPromptExpansion` hook has normally turned the keep-alive off for this session already and added a note that says so: then reply with exactly the line the note gives, and nothing else (no tools). Only without that note (a Claude Code without the event), run `CLAUDE_PLUGIN_DATA="${CLAUDE_PLUGIN_DATA}" cachekeeper keepalive off --session ${CLAUDE_SESSION_ID}` with the Bash tool; where there is no Bash tool, only PowerShell, run `$env:CLAUDE_PLUGIN_DATA = "${CLAUDE_PLUGIN_DATA}"; & "${CLAUDE_PLUGIN_ROOT}/bin/cachekeeper.ps1" keepalive off --session ${CLAUDE_SESSION_ID}` instead, and reply with the line it prints, in the user's language. Do nothing else.
