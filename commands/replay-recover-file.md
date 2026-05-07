---
description: Recover a single deleted file by replaying its history from Claude session JSONLs (lifeline mode)
allowed-tools: Bash
argument-hint: "--file /abs/path/to/lost.py [--at-ts ISO] [--list-versions] [--output-dir DIR]"
---

Reconstruct a deleted/lost file from its session history. Use when:

- Claude (or you) accidentally deleted an important code file
- The file was originally created or substantively edited via Claude
- You need to recover its content (or a specific historical version)

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/replay_engine.py" recover-file $ARGUMENTS
```

**Common patterns:**

- See the timeline of all ops on a file (no recovery yet):
  ```
  /replay-recover-file --file /abs/path/foo.py --list-versions
  ```
- Recover the latest version to stdout:
  ```
  /replay-recover-file --file /abs/path/foo.py
  ```
- Recover the version as it was at a specific timestamp:
  ```
  /replay-recover-file --file /abs/path/foo.py --at-ts 2026-05-06T14:00:00Z
  ```
- Recover all files under a path pattern into a directory:
  ```
  /replay-recover-file --path-match 'app/src/.*UserModel.*\.kt' --output-dir /tmp/recovered
  ```

By default the engine searches **all** session dirs under `~/.claude/projects/`, so even if you've moved the project or no longer have the original cwd, recovery works. Pin to one project with `--project-name -home-me-myrepo` (the encoded directory name).

If the first op on the file is `Edit` rather than `Write`, the engine cannot reconstruct without a baseline (the file existed before Claude saw it) and will skip with a warning.
