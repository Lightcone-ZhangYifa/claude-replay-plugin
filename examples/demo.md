# Demo: 165 uncommitted files → 21 clean commits

This is the real story claude-replay was built to solve.

## Setup

A user's working tree after a week of Claude Code sessions:

```
$ git status -s | wc -l
165

$ git log --oneline -1
70e2cd2 fix: SessionVM auto-refresh observer also tracks SshConnection identity
       (last commit was 4 weeks ago)
```

165 uncommitted entries spanning:

- `Modified`: 80+ existing files
- `Untracked`: 50+ new files (new modules, components, tests)
- `Deleted`: 12 files (refactored away)

Across 6 Claude Code session JSONLs (~135 MB total) and 19 sub-agent invocations.

## Step 1 — status

```
$ /replay-status
Project: /home/user/myproject
Session JSONLs: 103 (6 main + 97 subagent)
File ops in scope: 1274 (Write: 312, Edit: 731, MultiEdit: 9, Bash: 222)
User messages: 8822
```

## Step 2 — plan

The user's workflow is "design-doc-driven": each feature begins with a `docs/<name>-<date>.md` file.

```
$ /replay-plan --strategy doc-files --boundary-glob "docs/*.md"
Strategy: doc-files
Boundaries: 20

  1. [  94 ops,  33 files]  chore(replay): ssh-architecture-audit-2026-05-04
  2. [  18 ops,   7 files]  chore(replay): volume-keys-configurable-2026-05-05
  3. [  30 ops,  10 files]  chore(replay): sessions-tab-ux-fix-2026-05-05
  ...
 20. [  37 ops,   7 files]  chore(replay): fab-bubble-fix-2026-05-06
```

## Step 3 — execute (sandbox)

```
$ /replay-execute
Baseline: 70e2cd2
Boundaries: 20  Total ops: 1274
Sandbox: /tmp/claude-replay-abc123

Commits created: 20
Edit/MultiEdit fall-throughs: 0
Bash non-zero exits: 29   (gradle/adb commands that returned 1 — harmless)
Diff vs working tree (entries): 4
  Files .../ServerDetailScreen.kt and .../ServerDetailScreen.kt differ
  Files .../YamlEditorScreen.kt and .../YamlEditorScreen.kt differ
  Files .../LibraryDetailScreen.kt and .../LibraryDetailScreen.kt differ
  Only in sandbox: docs/scattered-controls-audit-2026-05-06.md
```

The 4 divergences are all minor (a few stray blank lines from `sed` migrations + one doc that was deleted manually outside Claude). Add a `chore: align with working tree` commit:

```
$ cd /tmp/claude-replay-abc123
$ rm docs/scattered-controls-audit-2026-05-06.md
$ cp ~/myproject/app/src/.../ServerDetailScreen.kt app/src/.../ServerDetailScreen.kt
$ # ... etc
$ git add -A && git commit -m "chore: align with working tree"
```

## Step 4 — apply

```
$ /replay-execute --apply --yes
Real repo HEAD now: 1205576a8d12
Backup tag: claude-replay-backup-1730912345
```

## Result

```
$ git log --oneline 70e2cd2..HEAD
1205576 chore: align with current working tree (post-replay cleanup)
0c15efe fix(editor): FAB bubble VSCode-style Find + dynamic content sizing
15f4d26 fix: SessionResizeBus v2 — visibility-driven yield
3e4defa fix: AppSwipeActions v2 — clip + height-aware
55f5fe7 refactor: SessionResizeBus v1
71ae775 refactor: AppFab/AppFabBubble + EditorFabCluster
079c3ef refactor: extract AppCard/AppCrashRecoveryDialog/AppMultiSelect*
7a5d67c docs: scattered-controls audit
ac01f76 refactor: AppSwipeActions v1 — shared swipe→action panel
31b9073 refactor: unified RetryCountdown component
278c770 fix: AppScaffold canonical content padding
28d62ff docs: debugging playbook + AppLogger polish
b649d34 feat: AppLogger framework + DebugLogScreen + DebugBundle
d8b1f8e feat: design-rules grep gates wired into gradle
a0fb007 docs: design-system spec
38be5b5 feat: design tokens + App component library
2b317c4 refactor: declarative settings registry
52877bb refactor: extract ConnectionTrigger sealed type
5d5b092 fix: sessions-tab UX rework
75a47b6 feat: configurable volume-key behavior
271bd57 refactor(ssh): cleanup + server YAML migration per audit

$ git diff HEAD --stat
(empty)
```

21 commits, byte-equal to the working tree, semantic subjects, full provenance via design docs. Now you can:

- `git revert 3e4defa` — undo just the v2 fix, keeping v1 (`ac01f76`) intact
- `git bisect` to find which commit broke the test you noticed yesterday
- Push to a feature branch and open one PR per commit, or one PR for the whole stack

Total time: ~30 seconds of compute. Forensic accuracy: byte-perfect.
