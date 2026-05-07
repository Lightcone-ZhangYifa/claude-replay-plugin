---
description: Show what Claude Code session work is currently uncommitted in this repo
allowed-tools: Bash
---

Show the user a summary of session work that is sitting in `~/.claude/projects/` for the current repo but is not yet captured in git history.

Run:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/replay_engine.py" status --repo .
```

Then briefly interpret the result for the user — how many ops are in scope, whether they suggest a commit chain is recoverable, and recommend the next command (`/replay-plan` or `/replay-execute`).
