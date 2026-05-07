---
description: Preview the commit chain claude-replay would build — boundaries, file counts, subjects — without touching anything
allowed-tools: Bash
argument-hint: "[--strategy doc-files|time-gap|user-approve|one-shot] [--boundary-glob 'docs/*.md'] [--gap-minutes 30]"
---

Show the user the proposed commit chain.

Pass any user-supplied arguments through verbatim. Default strategy is `doc-files` (one commit per new doc file in `docs/*.md`); fall back to `time-gap` (30 min idle) if no doc files exist.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/replay_engine.py" plan --repo . $ARGUMENTS
```

After running, briefly summarize: total commits, any commits that look suspicious (very large, very small, empty), and ask the user whether to proceed with `/replay-execute` (sandbox build, byte-equality check) or `/replay-execute --apply` (also rewrites real repo HEAD).
