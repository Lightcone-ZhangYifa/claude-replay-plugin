---
description: Interactive end-to-end replay — show status, propose plan, await approval, build chain, verify, await final approval, apply
allowed-tools: Bash, AskUserQuestion
---

Drive the full claude-replay workflow.

1. **Status**: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/replay_engine.py" status --repo .`. If 0 ops, stop and tell the user there's nothing to replay.

2. **Plan**: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/replay_engine.py" plan --repo .` with the default `doc-files` strategy. Show the commit list. If no boundaries (i.e. fell back to one-shot), suggest the user choose a different `--strategy` and `--boundary-glob` (e.g. `--strategy time-gap --gap-minutes 30`).

3. **Confirm strategy**: ask the user (use AskUserQuestion if available) whether to proceed with this plan or adjust the strategy. Only proceed when they explicitly approve.

4. **Execute**: run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/replay_engine.py" execute --repo .` (no `--apply` yet). Report:
   - Sandbox path
   - Commit count
   - Bytewise verification result
   - Any divergent files

5. **Confirm apply**: if verification is clean (0 divergent files), ask the user whether to apply. If divergent, recommend they inspect the sandbox first.

6. **Apply**: only with explicit user approval, run with `--apply --yes`. Show the new HEAD and the backup tag.

Be conservative: never `--apply` without an explicit approval message in the current turn. The previous HEAD is always backed up via tag, but rolling back is not the user's intended path.
