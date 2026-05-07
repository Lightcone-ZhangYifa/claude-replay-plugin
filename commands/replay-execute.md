---
description: Build the commit chain in a sandbox; with --apply, also move the real repo HEAD to it (DESTRUCTIVE)
allowed-tools: Bash
argument-hint: "[--strategy ...] [--baseline <sha>] [--apply] [--yes] [--allow-drift]"
---

Build the commit chain.

**Without `--apply`** (default): clones the repo into a temp sandbox, replays every Edit/Write/MultiEdit and Bash file-modification op from the session JSONLs in chronological order, and creates one git commit per boundary. Then runs `diff -r --brief sandbox repo` to verify the cumulative state is byte-equal to the current working tree. Reports the sandbox path so the user can `git -C <sandbox> log` to inspect.

**With `--apply`**: same as above, then `git fetch <sandbox> claude-replay && git reset --hard FETCH_HEAD` on the real repo. Tags the previous HEAD as `claude-replay-backup-<unix-ts>` for rollback.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/replay_engine.py" execute --repo . $ARGUMENTS
```

If the user did not pass `--apply`, end by suggesting they:
1. Inspect the sandbox path printed in the output: `git -C <sandbox> log --oneline`
2. If the chain looks correct, re-run with `--apply --yes` to rewrite the real repo HEAD

If the diff vs working tree shows divergent files (Bash `sed -i` patterns the engine couldn't perfectly replay), suggest a follow-up `chore: align with working tree` commit, or use `--allow-drift` to apply anyway and patch up later.
