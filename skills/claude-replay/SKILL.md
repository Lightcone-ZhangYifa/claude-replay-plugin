---
name: claude-replay
description: Recover lost work from Claude Code session JSONLs by byte-replaying every Edit/Write/Bash tool call. Use for FOUR scenarios — (1) RESCUE: user forgot to commit and has hundreds of uncommitted files across many Claude sessions; reconstruct a clean commit chain. (2) LIFELINE: user wants to recover a specific deleted/lost file that was originally created or edited via Claude. (3) BACK-FROM-DEAD: user accidentally rm -rf'd an entire project that was built through Claude; resurrect the file tree from JSONLs alone. (4) RESEARCH: user studies AI-agent behavior (tool retry patterns, sub-agent delegation, error recovery) and needs structured event-log export. Trigger on phrases like "forgot to commit", "uncommitted work", "lost commits", "rebuild git history", "deleted file", "rm -rf", "lost project", "resurrect project", "agent behavior analysis", "Claude tool-call log", "byte-level replay", "session JSONL".
---

# claude-replay

Recover semantic git history from Claude Code session JSONLs.

## When to invoke

- User has many uncommitted files (`git status` shows hundreds of changes) accumulated across sessions
- User asks to "split", "reconstruct", "recover", or "replay" their work into commits
- User mentions byte-level / forensic / chronological reconstruction of their session
- User says "I forgot to commit" or "I want to undo X but keep Y" where X and Y are intermixed in the working tree

## When NOT to invoke

- User just wants to make ONE commit of current state → use `/commit` or plain `git commit`
- User wants to write a feature plan → use `/feature-dev` or write the design doc directly
- The repo has no `~/.claude/projects/-{cwd}/` session JSONLs → there's nothing to replay

## Mechanism (essential to understand before running)

Claude Code persists every assistant turn — including every tool call's input — to JSONL files at `~/.claude/projects/-{encoded-cwd}/*.jsonl` (and `subagents/*.jsonl` for Task-spawned sub-agents). Each `Edit`/`Write`/`MultiEdit` tool call is fully recoverable: Write contains the absolute file content; Edit contains `old_string`+`new_string`. Bash commands that mutate files (`sed -i`, `rm`, `mv`, `cat > file`) are also captured.

Replay = clone the repo into a sandbox, checkout a baseline commit, and replay every op in chronological timestamp order. Because each op is deterministic against the state it was originally applied to, replaying them in the same order against the same baseline reproduces the exact same byte sequence.

## Slash commands by scenario

| Scenario | Command | Purpose |
|---|---|---|
| Rescue (forgot to commit) | `/replay` | Guided end-to-end |
| Rescue inspection | `/replay-status` | Read-only — what's in the JSONLs |
| Rescue planning | `/replay-plan` | Preview the proposed commit chain |
| Rescue execution | `/replay-execute [--apply]` | Build sandbox; optionally rewrite HEAD |
| Lifeline (deleted file) | `/replay-recover-file` | Reconstruct one file from history |
| Back-from-dead (lost project) | `/replay-recover-project` | Resurrect a whole project tree |
| Research (event log export) | `/replay-analyze` | JSONL/CSV/stats over every tool call |

## Boundary strategies

The default `doc-files` strategy assumes the user follows a "design-doc-driven" workflow: each new file matching `docs/*.md` marks the start of a feature, and the next match ends it. This produces semantic commits like `chore(replay): swipe-actions-unification-2026-05-06`.

Other strategies:
- `time-gap` — idle gap of N minutes ⇒ boundary. Good for sessions without doc files.
- `user-approve` — user message matches `批准|approve|lgtm|ship it` ⇒ boundary. Good when user explicitly gates each phase.
- `one-shot` — everything in one commit. Bare-minimum recovery.
- `manual` — JSON file lists `(name, until_ts, subject, body)`. For full control.

## Safety

The replay always runs in a temp sandbox first (`/tmp/claude-replay-*`). The real repo is only touched when `--apply` is passed AND the sandbox diverges 0 files from the working tree (or `--allow-drift` is set). The previous HEAD is always tagged `claude-replay-backup-<unix-ts>` before any history rewrite.

## Limitations & known gotchas

- **Sub-agent ops**: extracted from `subagents/*.jsonl` automatically (since v0.1).
- **Bash sed pattern complexity**: simple `s/foo/bar/g` and for-loops over file lists work; exotic escapes occasionally don't. The verification diff catches any divergence.
- **Untracked manual edits**: any file the user modified in their editor (outside Claude) won't appear in JSONL, so it'll show up as a divergence. Pin those into a final `chore: align with working tree` commit.
- **Forensic ops**: when `claude-replay` itself is replayed, its own ops are part of the timeline. Use `--before <ts>` to cap the replay before your own forensic work began.

## Example interaction

```
User: I have 165 uncommitted files from a week of Claude work. Help me split into clean commits.
You: I'll first show you what's in your session history.
   → /replay-status
   "Found 6 sessions, 1274 ops, 165 files touched."
You: The default strategy splits commits by docs/*.md files. Here's the proposed chain:
   → /replay-plan
   "20 commits proposed: ssh-architecture-audit, volume-keys-configurable, ..."
User: Looks good. Build it.
You:
   → /replay-execute
   "Sandbox at /tmp/claude-replay-abc123, 21 commits, 0 divergent files."
User: Apply.
You:
   → /replay-execute --apply --yes
   "Real repo HEAD now: 1205576. Backup tag: claude-replay-backup-1730912345."
```
