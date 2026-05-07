---
description: Reconstruct an entire deleted project from Claude session JSONLs (back-from-the-dead mode)
allowed-tools: Bash
argument-hint: "--output-dir /path/to/recovered [--project-name -home-me-old] [--git-init]"
---

Bring a deleted project back from the dead. Use when:

- You accidentally `rm -rf`'d (or otherwise lost) a project directory
- The project was built primarily through Claude Code
- The session JSONLs are still present at `~/.claude/projects/-{encoded-cwd}/`

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/replay_engine.py" recover-project $ARGUMENTS
```

**Quick recovery (auto-infer original project root):**

```
/replay-recover-project --output-dir ~/recovered-myapp --project-name -home-me-myapp --git-init
```

This:
1. Loads every session JSONL under `~/.claude/projects/-home-me-myapp/`
2. Finds every Write/Edit/MultiEdit op on files under the original project root
3. Reconstructs each file's final content (skips files whose first op wasn't a Write — those existed before Claude saw them)
4. Materializes the file tree into `~/recovered-myapp/`
5. With `--git-init`: creates a git repo + one snapshot commit

After recovery, you can run the standard replay pipeline against the new repo to reconstruct the **commit history** as well:

```
cd ~/recovered-myapp
git -C . tag pre-replay-baseline
/replay-execute --apply
```

The result is a fully-recovered project with semantic commit history derived from the same sessions. Total information loss: only files Claude never touched (typically initial scaffolding, vendored dependencies, generated build outputs).

**Listing available projects to recover:**

```
ls ~/.claude/projects/
```

Each subdirectory is a project Claude has worked on; the name encodes the original cwd as `-` + path with `/` replaced by `-`.
