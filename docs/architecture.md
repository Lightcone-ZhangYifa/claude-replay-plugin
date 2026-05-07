# Architecture

How `claude-replay` reads Claude Code's raw session records and reconstructs them into git history without losing intermediate state.

## 1. The data source

Claude Code persists a complete record of every assistant turn — including every tool call's exact input — to JSONL files on disk:

```
~/.claude/projects/-{encoded-cwd}/
  ├── <session-uuid-1>.jsonl         ← main session
  ├── <session-uuid-2>.jsonl         ← another main session
  ├── <session-uuid-1>/
  │   └── subagents/
  │       ├── agent-<id>.jsonl       ← Task-spawned sub-agent
  │       └── agent-<id>.meta.json   ← sub-agent metadata
  └── ...
```

The encoded-cwd is your project root with `/` replaced by `-` and a leading `-`. So `/home/me/myrepo` becomes `-home-me-myrepo`.

Each line of a JSONL is a JSON object representing one message:

```json
{
  "timestamp": "2026-05-06T15:11:11.123Z",
  "message": {
    "role": "assistant",
    "content": [
      {
        "type": "tool_use",
        "id": "toolu_01abc...",
        "name": "Edit",
        "input": {
          "file_path": "/home/me/repo/foo.py",
          "old_string": "def f(): return 1",
          "new_string": "def f(): return 2"
        }
      }
    ]
  }
}
```

And the matching tool result, in a later message:

```json
{
  "timestamp": "2026-05-06T15:11:11.456Z",
  "message": {
    "role": "user",
    "content": [
      {"type": "tool_result", "tool_use_id": "toolu_01abc...", "content": "...", "is_error": false}
    ]
  }
}
```

Three tool families are file-modifying:

| Tool        | Reconstruction                                     |
|-------------|----------------------------------------------------|
| `Write`     | Replace entire file content with `input.content`   |
| `Edit`      | `content.replace(input.old_string, input.new_string, 1 or all)` |
| `MultiEdit` | Sequence of Edits applied in order                 |
| `Bash`      | Re-execute `input.command` (file mods only)        |

Plus user messages (extracted for the `user-approve` boundary strategy and for analyze stats).

## 2. Why replay is byte-exact

This is the core insight. Each Edit/Write was originally applied to a deterministic input state — whatever the file looked like at that moment. That state is the result of all previous ops on that file, starting from the baseline commit.

So if we:

1. Start from the same baseline commit
2. Apply every op in original timestamp order
3. Use the same algorithm Claude Code uses internally (Python `str.replace` with first-occurrence or replace_all)

…then the byte sequence at any moment in our replay == the byte sequence at the corresponding moment in history. There is no inference, no heuristic, no "guess what the agent meant". It's mechanical re-execution.

The verification step (`diff -r --brief sandbox repo`) confirms this empirically. If the cumulative replay produces 0 divergent files, the replay is provably faithful.

## 3. Bash is the wrinkle

`Bash` calls can also modify files, via `sed -i`, `cat > file`, `rm`, `mv`, `awk`, for-loops, etc. We can't statically parse arbitrary bash, so we **re-execute** the captured `command` in the sandbox:

```python
fixed = original_cmd.replace(real_repo_path, sandbox_path)
fixed = re.sub(r"cd\s+" + re.escape(real_repo_path), f"cd {sandbox}", fixed)
subprocess.run(["bash", "-c", fixed], cwd=sandbox)
```

This is intentionally pragmatic: complex bash patterns work because bash itself interprets them. The trade-off: the sandbox needs to provide the same environment as the original (PATH, file system layout). For most modifications this is fine; for very environment-dependent commands it isn't, but those are rare.

## 4. Commit boundary detection

Replay alone gives you "the final state, byte-equal." But you usually want **multiple commits**, semantically grouped. We support five strategies:

### `doc-files` (default)

Each new file matching `--boundary-glob` (default `docs/*.md`) marks the **start** of a feature window. The next match marks the end. Why this works: a common Claude Code workflow is "write design doc → user approves → execute → next feature." The doc creation timestamps cleanly partition the timeline.

### `time-gap`

A gap of `--gap-minutes` between consecutive ops marks a boundary. Useful when the user worked in batches separated by lunch / overnight / context-compaction.

### `user-approve`

User messages matching `--approve-regex` mark a boundary. This is the most explicit strategy — relies on the user's actual approval signals.

### `one-shot`

Everything in a single commit. Bare-minimum recovery; useful when no other signal is available.

### `manual`

Read a JSON file with explicit `(name, until_ts, subject, body)` records. Full control.

## 5. The sandbox

Replay never touches the real repo until the final `--apply` step. The sandbox is a clone of the real repo, checked out at the chosen baseline:

```bash
git clone --quiet $REAL_REPO $SANDBOX
git -C $SANDBOX checkout --quiet $BASELINE
git -C $SANDBOX checkout -b claude-replay
git -C $SANDBOX config core.hooksPath /dev/null   # don't run user's pre-commit hooks
```

After every commit boundary's ops are applied, we `git add -A && git commit --allow-empty -m '...'` in the sandbox. Empty commits are allowed for pure-doc windows.

## 6. Verification

After all boundaries are committed, we run:

```bash
diff -r --brief \
  -x .git -x build -x .gradle -x node_modules -x ... \
  $SANDBOX $REAL_REPO
```

If this returns 0 entries, the cumulative replay is byte-equal to the working tree. This is the **byte-equality assertion** that gives the user confidence.

If it returns >0 entries, we report them and offer two paths:

1. Add a final `chore: align with working tree` commit that copies the divergent files from the real repo into the sandbox, then re-commits.
2. Pass `--allow-drift` to apply anyway and patch up later.

Common reasons for divergence:

- A `sed -i` pattern with quoting that bash interpreted differently in the sandbox (rare).
- The user manually edited a file outside Claude (the JSONL has no record).
- A file deletion was done outside Claude (e.g., user typed `rm` in a separate terminal).

## 7. Apply

When the user approves `--apply`:

```bash
git -C $REAL_REPO tag claude-replay-backup-$(date +%s)
git -C $REAL_REPO reset --hard $BASELINE
git -C $REAL_REPO fetch $SANDBOX claude-replay:claude-replay-fetched
git -C $REAL_REPO reset --hard claude-replay-fetched
```

The previous HEAD becomes a tag, recoverable via `git reset --hard claude-replay-backup-<ts>`.

## 8. Sub-agents

When Claude spawns a sub-agent via the `Task` / `Agent` tool, the sub-agent runs its own conversation with its own tool calls. These are persisted to `subagents/agent-<id>.jsonl`. claude-replay walks the entire `~/.claude/projects/-{cwd}/` tree (including `subagents/`) and merges all tool calls into one chronological timeline. The `is_subagent` field on each event makes it easy to separate them downstream.

## 9. Limits

- **Statically deleted files**: a `bash -c "rm foo.py"` records the command, which we re-execute. But if the user deleted a file via their editor's UI, no record exists. Such files become divergences caught by the verification diff.
- **Concurrency**: sessions are sequential per project. If you ran two parallel `claude` instances on the same project, both wrote to the same JSONL directory; the timeline merges them by timestamp, which is usually fine but may interleave unexpectedly.
- **Forensic feedback loop**: if you run claude-replay itself in a session that you later replay, claude-replay's own bash commands become part of the timeline. Use `--before <ts>` to cap the replay before your own forensic work began.
