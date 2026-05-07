#!/usr/bin/env python3
"""
claude-replay — reconstruct git commits from Claude Code session history.

Reads ~/.claude/projects/-{cwd}/*.jsonl (main + subagents), extracts every
Edit/Write/MultiEdit tool call plus Bash file-modification commands (sed/awk/
mv/rm/cat>), replays them in chronological order against a git baseline, and
materializes the result as a chain of commits.

Three modes:
  --plan        Print the commit plan (boundaries + file counts) and exit
  --execute     Build the chain in a sandbox clone, verify byte-equality
                against the working tree, but don't touch the real repo
  --apply       Same as --execute, then move HEAD of the real repo to the
                rebuilt chain (DESTRUCTIVE: requires --yes or interactive
                confirm)

Boundary strategies (--strategy):
  doc-files     New file matching --boundary-glob (default docs/*.md) marks
                the START of a feature; the next match ends it. Best for
                "design-doc-driven" workflows.
  time-gap      Idle gap of --gap-minutes between ops marks a boundary.
  user-approve  User messages matching --approve-regex mark a boundary
                (default: 批准|approve|lgtm|ship it).
  one-shot      Everything in a single commit.
  manual        Read --boundaries-file (JSON list of timestamps).

Language/project agnostic: works for any git repo with any file types.
No external dependencies — Python 3.10+ standard library only.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional


# --------------------------------------------------------------------------- #
# Session discovery
# --------------------------------------------------------------------------- #

def project_session_dir(cwd: Path | str | None = None) -> Path:
    """Resolve ~/.claude/projects/-{encoded-cwd}/ for the given project root."""
    cwd = Path(cwd or os.getcwd()).resolve()
    encoded = "-" + str(cwd).lstrip("/").replace("/", "-")
    return Path.home() / ".claude" / "projects" / encoded


def find_session_jsonls(session_dir: Path) -> list[Path]:
    """All JSONLs under session_dir (main + subagents/*.jsonl)."""
    if not session_dir.exists():
        return []
    return sorted(session_dir.rglob("*.jsonl"))


# --------------------------------------------------------------------------- #
# Timeline extraction
# --------------------------------------------------------------------------- #

@dataclass
class Op:
    ts: str           # ISO 8601
    sid: str          # session id
    name: str         # Edit / Write / MultiEdit / Bash
    payload: dict     # original tool input (or {'cmd': ...} for Bash)
    success: bool = True

    @property
    def file_path(self) -> Optional[str]:
        if self.name in ("Edit", "Write", "MultiEdit"):
            return self.payload.get("file_path")
        return None


@dataclass
class UserMessage:
    ts: str
    sid: str
    text: str


def extract_timeline(jsonls: Iterable[Path], repo_root: Path,
                      after_ts: Optional[str] = None,
                      before_ts: Optional[str] = None) -> tuple[list[Op], list[UserMessage]]:
    """Parse all JSONLs and return (file_ops, user_messages) sorted by ts."""
    repo_str = str(repo_root.resolve())
    tool_uses: dict[str, dict] = {}
    tool_results: dict[str, dict] = {}
    user_msgs: list[UserMessage] = []

    for path in jsonls:
        sid = path.stem
        try:
            with path.open(encoding="utf-8") as fp:
                for line_no, line in enumerate(fp):
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("timestamp", "")
                    if after_ts and ts < after_ts:
                        continue
                    if before_ts and ts >= before_ts:
                        continue
                    msg = rec.get("message") or {}
                    role = msg.get("role")
                    content = msg.get("content", [])
                    if isinstance(content, str):
                        content = [{"type": "text", "text": content}]
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "tool_use" and role == "assistant":
                            tu_id = block.get("id") or f"{sid}-{line_no}"
                            tool_uses.setdefault(tu_id, {
                                "ts": ts, "sid": sid,
                                "name": block.get("name"),
                                "input": block.get("input") or {},
                            })
                        elif btype == "tool_result" and role == "user":
                            tu_id = block.get("tool_use_id")
                            if not tu_id:
                                continue
                            rc = block.get("content", "")
                            if isinstance(rc, list):
                                rc = "".join(
                                    x.get("text", "") for x in rc
                                    if isinstance(x, dict) and x.get("type") == "text"
                                )
                            tool_results.setdefault(tu_id, {
                                "is_error": block.get("is_error", False),
                                "text": str(rc)[:5000],
                            })
                        elif btype == "text" and role == "user":
                            txt = block.get("text", "") or ""
                            if txt and not txt.startswith("<local-command-caveat>") and not txt.startswith("<command-"):
                                user_msgs.append(UserMessage(ts=ts, sid=sid, text=txt[:1000]))
        except OSError:
            continue

    ops: list[Op] = []
    for tu_id, tu in tool_uses.items():
        name = tu.get("name")
        res = tool_results.get(tu_id, {})
        success = not res.get("is_error", False)
        if name in ("Edit", "Write", "MultiEdit"):
            inp = tu["input"]
            fp = inp.get("file_path")
            if not fp or not fp.startswith(repo_str + "/"):
                continue
            ops.append(Op(ts=tu["ts"], sid=tu["sid"], name=name, payload=inp, success=success))
        elif name == "Bash":
            cmd = tu["input"].get("command", "")
            if not _bash_touches_repo(cmd, repo_str):
                continue
            ops.append(Op(ts=tu["ts"], sid=tu["sid"], name="Bash",
                          payload={"cmd": cmd}, success=success))

    ops.sort(key=lambda o: o.ts)
    user_msgs.sort(key=lambda u: u.ts)
    return ops, user_msgs


_BASH_FILE_OP_RE = re.compile(
    r"(?:\bsed\s+-i|\b(?:rm|mv|cp)\s+(?:-[a-zA-Z]+\s+)?[^\s]|"
    r"\bgit\s+rm\b|>\s*[^\s|&]|<<\s*['\"]?EOF|\bawk\b)"
)


def _bash_touches_repo(cmd: str, repo_str: str) -> bool:
    """Heuristic: does this Bash command modify files inside repo_str?

    A pragmatic test — fast and high-recall (better to include irrelevant
    bash than miss a real file modification). The replay sandbox is
    isolated so false positives only waste compute, not safety.
    """
    if not _BASH_FILE_OP_RE.search(cmd):
        return False
    return repo_str in cmd or _looks_like_relative_repo_op(cmd)


def _looks_like_relative_repo_op(cmd: str) -> bool:
    return any(s in cmd for s in ("sed -i", " mv ", " rm ", "git rm", "cat <<"))


# --------------------------------------------------------------------------- #
# Replay (forward, in a sandbox)
# --------------------------------------------------------------------------- #

@dataclass
class ReplayResult:
    sandbox: Path
    branch: str
    commits: list[tuple[str, str, str]]   # [(sha, subject, body)]
    op_count: int
    edit_failures: int
    bash_nonzero: int
    final_diff_entries: int
    final_diff_text: str


def make_sandbox(real_repo: Path, baseline: str, branch_name: str,
                 sandbox_dir: Optional[Path] = None) -> Path:
    """Clone real_repo into a sandbox, checkout baseline, create branch."""
    if sandbox_dir is None:
        sandbox_dir = Path(tempfile.mkdtemp(prefix="claude-replay-"))
    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir)
    subprocess.run(["git", "clone", "--quiet", str(real_repo), str(sandbox_dir)], check=True)
    subprocess.run(["git", "-C", str(sandbox_dir), "checkout", "--quiet", baseline], check=True)
    for key in ("user.name", "user.email"):
        try:
            v = subprocess.check_output(
                ["git", "-C", str(real_repo), "config", "--get", key],
                stderr=subprocess.DEVNULL).decode().strip()
            if v:
                subprocess.run(["git", "-C", str(sandbox_dir), "config", key, v], check=True)
        except subprocess.CalledProcessError:
            pass
    subprocess.run(["git", "-C", str(sandbox_dir), "checkout", "-b", branch_name], check=True)
    subprocess.run(["git", "-C", str(sandbox_dir), "config", "core.hooksPath", "/dev/null"], check=True)
    return sandbox_dir


def _apply_edit(file_path: Path, old: str, new: str, replace_all: bool) -> bool:
    if not file_path.exists():
        return False
    content = file_path.read_text()
    if replace_all:
        new_content = content.replace(old, new)
        if new_content == content and old != new:
            return False
    else:
        idx = content.find(old)
        if idx < 0:
            return False
        new_content = content[:idx] + new + content[idx + len(old):]
    file_path.write_text(new_content)
    return True


def _apply_write(file_path: Path, content: str) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content)


def _apply_multiedit(file_path: Path, edits: list[dict]) -> bool:
    if not file_path.exists():
        return False
    content = file_path.read_text()
    for e in edits:
        old = e.get("old_string", "")
        new = e.get("new_string", "")
        ra = e.get("replace_all", False)
        if ra:
            content = content.replace(old, new)
        else:
            idx = content.find(old)
            if idx < 0:
                return False
            content = content[:idx] + new + content[idx + len(old):]
    file_path.write_text(content)
    return True


def _run_bash(cmd: str, sandbox: Path, real_repo: Path, timeout: int = 30) -> int:
    """Re-run the original Bash command but pinned to the sandbox.

    Path-rewrite real_repo → sandbox so absolute paths land in the sandbox.
    Run with cwd=sandbox so `cd <repo>` and relative paths also work.
    """
    fixed = cmd.replace(str(real_repo), str(sandbox))
    fixed = re.sub(r"cd\s+" + re.escape(str(real_repo)), f"cd {sandbox}", fixed)
    env = {**os.environ, "PATH": "/usr/bin:/bin:/usr/local/bin"}
    try:
        r = subprocess.run(
            ["bash", "-c", fixed], cwd=str(sandbox),
            capture_output=True, timeout=timeout, env=env,
        )
        return r.returncode
    except subprocess.TimeoutExpired:
        return 124
    except Exception:
        return -1


def replay(ops: list[Op], commits_plan: list["CommitSpec"],
            real_repo: Path, sandbox: Path, verbose: bool = False) -> ReplayResult:
    op_idx = 0
    edit_failures = 0
    bash_nonzero = 0
    committed: list[tuple[str, str, str]] = []
    repo_str = str(real_repo.resolve())
    sandbox_str = str(sandbox.resolve())
    total_commits = len(commits_plan)

    for ci, spec in enumerate(commits_plan, 1):
        if verbose:
            print(f"  [{ci:2d}/{total_commits}] {spec.subject}", file=sys.stderr)
        while op_idx < len(ops) and (spec.until_ts == "9999" or ops[op_idx].ts < spec.until_ts):
            op = ops[op_idx]
            try:
                if op.name == "Write":
                    target = Path(op.payload["file_path"].replace(repo_str, sandbox_str))
                    _apply_write(target, op.payload.get("content", ""))
                elif op.name == "Edit":
                    target = Path(op.payload["file_path"].replace(repo_str, sandbox_str))
                    if not _apply_edit(target, op.payload.get("old_string", ""),
                                         op.payload.get("new_string", ""),
                                         op.payload.get("replace_all", False)):
                        edit_failures += 1
                elif op.name == "MultiEdit":
                    target = Path(op.payload["file_path"].replace(repo_str, sandbox_str))
                    if not _apply_multiedit(target, op.payload.get("edits", [])):
                        edit_failures += 1
                elif op.name == "Bash":
                    if _run_bash(op.payload["cmd"], sandbox, real_repo) != 0:
                        bash_nonzero += 1
            except Exception:
                pass
            op_idx += 1

        subprocess.run(["git", "-C", str(sandbox), "add", "-A"], check=True)
        msg = spec.commit_message()
        r = subprocess.run(
            ["git", "-C", str(sandbox), "commit", "--allow-empty", "-m", msg],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            raise RuntimeError(f"commit failed for {spec.name}: {r.stderr}")
        sha = subprocess.check_output(
            ["git", "-C", str(sandbox), "rev-parse", "HEAD"]
        ).decode().strip()
        committed.append((sha, spec.subject, spec.body))

    diff = subprocess.run(
        ["diff", "-r", "--brief"] + [arg for x in DEFAULT_DIFF_EXCLUDES for arg in ("-x", x)] +
        [str(sandbox), str(real_repo)],
        capture_output=True, text=True,
    )
    diff_lines = [l for l in diff.stdout.split("\n") if l.strip()]
    return ReplayResult(
        sandbox=sandbox, branch="claude-replay",
        commits=committed, op_count=op_idx,
        edit_failures=edit_failures, bash_nonzero=bash_nonzero,
        final_diff_entries=len(diff_lines),
        final_diff_text="\n".join(diff_lines[:200]),
    )


DEFAULT_DIFF_EXCLUDES = [
    ".git", "build", ".gradle", ".idea", "local.properties",
    "node_modules", "target", "dist", ".next", ".kotlin", "__pycache__",
    ".venv", "venv", ".pytest_cache", ".mypy_cache", ".tox", ".tsbuildinfo",
]


# --------------------------------------------------------------------------- #
# Boundary strategies — yield CommitSpec objects in chronological order
# --------------------------------------------------------------------------- #

@dataclass
class CommitSpec:
    name: str
    until_ts: str        # boundary end (exclusive), or "9999" for last
    subject: str
    body: str = ""

    def commit_message(self) -> str:
        co = "Co-Authored-By: claude-replay <noreply@anthropic.com>"
        return f"{self.subject}\n\n{self.body}\n\n{co}".strip()


def boundaries_doc_files(ops: list[Op], glob_pat: str) -> list[CommitSpec]:
    """Each new file matching glob_pat starts a new commit window."""
    pat = _glob_to_regex(glob_pat)
    doc_writes: list[tuple[str, str]] = []
    seen: set[str] = set()
    for op in ops:
        fp = op.file_path or ""
        if op.name == "Write" and pat.search(fp) and fp not in seen:
            doc_writes.append((op.ts, fp))
            seen.add(fp)
    if not doc_writes:
        return []
    specs: list[CommitSpec] = []
    for i, (ts, path) in enumerate(doc_writes):
        end = doc_writes[i + 1][0] if i + 1 < len(doc_writes) else "9999"
        name = Path(path).stem
        specs.append(CommitSpec(name=name, until_ts=end,
                                  subject=f"chore(replay): {name}"))
    return specs


def boundaries_time_gap(ops: list[Op], gap_minutes: int) -> list[CommitSpec]:
    if not ops:
        return []
    specs: list[CommitSpec] = []
    cur_start = ops[0].ts
    for i in range(1, len(ops)):
        prev = _parse_ts(ops[i - 1].ts)
        cur = _parse_ts(ops[i].ts)
        if (cur - prev).total_seconds() >= gap_minutes * 60:
            specs.append(CommitSpec(
                name=f"batch-{cur_start[:19]}",
                until_ts=ops[i].ts,
                subject=f"chore(replay): batch starting {cur_start[:16]}",
            ))
            cur_start = ops[i].ts
    specs.append(CommitSpec(
        name=f"batch-{cur_start[:19]}", until_ts="9999",
        subject=f"chore(replay): batch starting {cur_start[:16]}",
    ))
    return specs


def boundaries_user_approve(ops: list[Op], user_msgs: list[UserMessage],
                              regex: str) -> list[CommitSpec]:
    pat = re.compile(regex, re.IGNORECASE)
    approve_ts = sorted(u.ts for u in user_msgs if pat.search(u.text))
    if not approve_ts:
        return []
    specs: list[CommitSpec] = []
    for i, ts in enumerate(approve_ts):
        end = approve_ts[i + 1] if i + 1 < len(approve_ts) else "9999"
        specs.append(CommitSpec(
            name=f"approval-{ts[:19]}", until_ts=end,
            subject=f"chore(replay): batch ending at approval {ts[:16]}",
        ))
    return specs


def boundaries_one_shot(ops: list[Op]) -> list[CommitSpec]:
    return [CommitSpec(name="all", until_ts="9999",
                        subject="chore(replay): bundle all session work")]


def boundaries_manual(path: Path) -> list[CommitSpec]:
    data = json.loads(Path(path).read_text())
    return [CommitSpec(**entry) for entry in data]


def _glob_to_regex(pat: str) -> re.Pattern:
    s = re.escape(pat).replace(r"\*\*", ".*").replace(r"\*", "[^/]*").replace(r"\?", ".")
    return re.compile(s + "$")


def _parse_ts(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return datetime.min


# --------------------------------------------------------------------------- #
# Apply chain to real repo
# --------------------------------------------------------------------------- #

def apply_chain_to_real_repo(real_repo: Path, sandbox: Path, branch: str,
                              baseline: str, backup_tag: bool = True) -> str:
    if backup_tag:
        ts = int(datetime.utcnow().timestamp())
        subprocess.run(["git", "-C", str(real_repo), "tag", f"claude-replay-backup-{ts}"], check=True)
    subprocess.run(["git", "-C", str(real_repo), "reset", "--hard", baseline], check=True)
    subprocess.run(
        ["git", "-C", str(real_repo), "fetch", str(sandbox), f"{branch}:claude-replay-fetched"],
        check=True,
    )
    subprocess.run(["git", "-C", str(real_repo), "reset", "--hard", "claude-replay-fetched"], check=True)
    return subprocess.check_output(
        ["git", "-C", str(real_repo), "rev-parse", "HEAD"]
    ).decode().strip()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def cmd_recover_file(args: argparse.Namespace) -> int:
    """Reconstruct a single file's content from its session history.

    Use case: Claude (or you) deleted an important file. As long as you
    originally created/edited it through Claude, every byte is recoverable
    from the session JSONLs.

    Strategy: find all Write/Edit/MultiEdit ops on the target path across
    every session JSONL (including subagents), apply them in chronological
    order starting from empty. The result is the file's final content
    (or its content at --at-ts).
    """
    target = Path(args.file).resolve() if args.file else None
    if not target and not args.path_match:
        print("ERROR: --file or --path-match required", file=sys.stderr)
        return 2

    # Find session dir(s)
    session_dirs: list[Path] = []
    if args.session_dir:
        session_dirs.append(Path(args.session_dir))
    elif args.project_name:
        session_dirs.append(Path.home() / ".claude" / "projects" / args.project_name)
    else:
        # Auto-discover: scan all project dirs and pick those that touch this file
        root = Path.home() / ".claude" / "projects"
        if not root.exists():
            print(f"ERROR: {root} does not exist", file=sys.stderr)
            return 2
        for d in root.iterdir():
            if d.is_dir():
                session_dirs.append(d)

    # Collect file ops on target across all sessions
    matching_path_re = re.compile(args.path_match) if args.path_match else None

    ops_per_file: dict[str, list[Op]] = defaultdict(list)
    found_paths: set[str] = set()

    for sd in session_dirs:
        jsonls = find_session_jsonls(sd)
        for path in jsonls:
            sid = path.stem
            try:
                with path.open(encoding="utf-8") as fp:
                    for line in fp:
                        try:
                            rec = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        ts = rec.get("timestamp", "")
                        if args.at_ts and ts > args.at_ts:
                            continue
                        msg = rec.get("message") or {}
                        if msg.get("role") != "assistant":
                            continue
                        content = msg.get("content", [])
                        if not isinstance(content, list):
                            continue
                        for block in content:
                            if not isinstance(block, dict) or block.get("type") != "tool_use":
                                continue
                            name = block.get("name")
                            if name not in ("Write", "Edit", "MultiEdit"):
                                continue
                            inp = block.get("input") or {}
                            fp_ = inp.get("file_path", "")
                            # Match by exact path or path-match regex
                            matches = False
                            if target and fp_ == str(target):
                                matches = True
                            elif matching_path_re and matching_path_re.search(fp_):
                                matches = True
                            if not matches:
                                continue
                            found_paths.add(fp_)
                            ops_per_file[fp_].append(
                                Op(ts=ts, sid=sid, name=name, payload=inp)
                            )
            except OSError:
                continue

    if not found_paths:
        suffix = ""
        if target:
            suffix = f"\nLooked for: {target}"
        elif args.path_match:
            suffix = f"\nPattern: {args.path_match}"
        print(f"No file ops found.{suffix}", file=sys.stderr)
        print(f"Searched {len(session_dirs)} session dir(s).", file=sys.stderr)
        return 2

    # If --list-versions, just show the timeline
    if args.list_versions:
        print(f"# Found {len(found_paths)} file(s) with ops:", file=sys.stderr)
        for path in sorted(found_paths):
            ops = sorted(ops_per_file[path], key=lambda o: o.ts)
            print(f"\n=== {path} ({len(ops)} ops) ===")
            for o in ops:
                detail = ""
                if o.name == "Write":
                    detail = f"(content: {len(o.payload.get('content', ''))} bytes)"
                elif o.name == "Edit":
                    old_len = len(o.payload.get("old_string", ""))
                    detail = f"(replace {old_len} chars)"
                elif o.name == "MultiEdit":
                    detail = f"({len(o.payload.get('edits', []))} edits)"
                print(f"  {o.ts[:19]}  {o.name:10s}  {detail}")
        return 0

    # Reconstruct each file
    out_root = Path(args.output_dir) if args.output_dir else None
    if out_root:
        out_root.mkdir(parents=True, exist_ok=True)

    recovered = 0
    skipped = 0
    for path in sorted(found_paths):
        ops = sorted(ops_per_file[path], key=lambda o: o.ts)
        # Need a baseline. If first op is Write, baseline is "" (Write supplies it).
        # If first op is Edit, we have no baseline — skip with warning.
        if ops[0].name != "Write":
            print(f"SKIP {path}: no leading Write — cannot reconstruct without baseline "
                  f"(first op was {ops[0].name})", file=sys.stderr)
            skipped += 1
            continue
        content = ""
        for o in ops:
            try:
                if o.name == "Write":
                    content = o.payload.get("content", "")
                elif o.name == "Edit":
                    old = o.payload.get("old_string", "")
                    new = o.payload.get("new_string", "")
                    if o.payload.get("replace_all", False):
                        content = content.replace(old, new)
                    else:
                        idx = content.find(old)
                        if idx < 0:
                            print(f"WARN {path} @ {o.ts[:19]}: Edit old_string not found, skipping",
                                  file=sys.stderr)
                            continue
                        content = content[:idx] + new + content[idx + len(old):]
                elif o.name == "MultiEdit":
                    for e in o.payload.get("edits", []):
                        old = e.get("old_string", "")
                        new = e.get("new_string", "")
                        if e.get("replace_all", False):
                            content = content.replace(old, new)
                        else:
                            idx = content.find(old)
                            if idx < 0:
                                continue
                            content = content[:idx] + new + content[idx + len(old):]
            except Exception as ex:
                print(f"WARN {path} @ {o.ts[:19]}: {ex}", file=sys.stderr)

        if out_root:
            # Preserve the original directory structure under out_root
            rel = Path(path).name if not args.preserve_paths else Path(path).relative_to("/")
            dest = out_root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
            print(f"RECOVERED {dest}  ({len(content)} bytes from {len(ops)} ops)")
        else:
            # stdout
            if len(found_paths) > 1:
                print(f"\n# === {path} ({len(content)} bytes from {len(ops)} ops) ===")
            sys.stdout.write(content)
        recovered += 1

    print(f"\n# Recovered {recovered} file(s), skipped {skipped}", file=sys.stderr)
    return 0


def cmd_recover_project(args: argparse.Namespace) -> int:
    """Reconstruct an entire project from Claude session JSONLs.

    Use case: you accidentally rm -rf'd your project. As long as it was
    built primarily through Claude, every file with a leading Write op
    can be reconstructed.

    Output is a new directory with all recovered files placed at their
    original absolute paths (rebased under --output-dir). If --git-init
    is set, also produces a commit chain via the standard execute pipeline.
    """
    out = Path(args.output_dir).resolve()
    if out.exists() and not args.force:
        print(f"ERROR: {out} already exists; pass --force to overwrite", file=sys.stderr)
        return 2

    # Discover sessions for the original project
    if args.project_name:
        session_dir = Path.home() / ".claude" / "projects" / args.project_name
    elif args.session_dir:
        session_dir = Path(args.session_dir)
    else:
        # Try auto: derive from out's name (assume user names the recovery dir
        # similarly to the original project, common pattern)
        candidates = [
            Path.home() / ".claude" / "projects" / f"-{out.name}",
        ]
        for d in (Path.home() / ".claude" / "projects").iterdir() if (Path.home() / ".claude" / "projects").exists() else []:
            if d.is_dir() and out.name in d.name:
                candidates.append(d)
        session_dir = next((c for c in candidates if c.exists()), None)
        if not session_dir:
            print(f"ERROR: cannot auto-discover session dir; pass --project-name or --session-dir",
                  file=sys.stderr)
            print(f"Available projects:", file=sys.stderr)
            root = Path.home() / ".claude" / "projects"
            if root.exists():
                for d in sorted(root.iterdir()):
                    print(f"  {d.name}", file=sys.stderr)
            return 2

    print(f"Session dir: {session_dir}")
    jsonls = find_session_jsonls(session_dir)
    if not jsonls:
        print(f"ERROR: no JSONLs in {session_dir}", file=sys.stderr)
        return 2

    # Determine the original project root from the first file_path we see
    original_root = args.original_root
    if not original_root:
        original_root = _infer_original_root(jsonls)
        if not original_root:
            print("ERROR: cannot infer original project root; pass --original-root /home/.../proj",
                  file=sys.stderr)
            return 2
    original_root = original_root.rstrip("/")
    print(f"Original project root (inferred): {original_root}")

    # Gather all ops on files under original_root
    ops_per_file: dict[str, list[Op]] = defaultdict(list)
    for jpath in jsonls:
        sid = jpath.stem
        try:
            with jpath.open(encoding="utf-8") as fp:
                for line in fp:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("timestamp", "")
                    if args.at_ts and ts > args.at_ts:
                        continue
                    msg = rec.get("message") or {}
                    if msg.get("role") != "assistant":
                        continue
                    content = msg.get("content", [])
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "tool_use":
                            continue
                        name = block.get("name")
                        if name not in ("Write", "Edit", "MultiEdit"):
                            continue
                        inp = block.get("input") or {}
                        fp_ = inp.get("file_path", "")
                        if not fp_.startswith(original_root + "/"):
                            continue
                        ops_per_file[fp_].append(Op(ts=ts, sid=sid, name=name, payload=inp))
        except OSError:
            continue

    print(f"Files with recoverable ops: {len(ops_per_file)}")
    if not ops_per_file:
        print("Nothing to recover.", file=sys.stderr)
        return 2

    # Materialize each file into out
    if out.exists() and args.force:
        shutil.rmtree(out)
    out.mkdir(parents=True)

    recovered = 0
    skipped = 0
    for orig_path, ops in sorted(ops_per_file.items()):
        ops_sorted = sorted(ops, key=lambda o: o.ts)
        if ops_sorted[0].name != "Write":
            print(f"SKIP {orig_path}: no leading Write", file=sys.stderr)
            skipped += 1
            continue
        content = ""
        for o in ops_sorted:
            try:
                if o.name == "Write":
                    content = o.payload.get("content", "")
                elif o.name == "Edit":
                    old = o.payload.get("old_string", "")
                    new = o.payload.get("new_string", "")
                    if o.payload.get("replace_all", False):
                        content = content.replace(old, new)
                    else:
                        idx = content.find(old)
                        if idx < 0:
                            continue
                        content = content[:idx] + new + content[idx + len(old):]
                elif o.name == "MultiEdit":
                    for e in o.payload.get("edits", []):
                        old = e.get("old_string", "")
                        new = e.get("new_string", "")
                        if e.get("replace_all", False):
                            content = content.replace(old, new)
                        else:
                            idx = content.find(old)
                            if idx < 0:
                                continue
                            content = content[:idx] + new + content[idx + len(old):]
            except Exception:
                pass
        rel = Path(orig_path).relative_to(original_root)
        dest = out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content)
        recovered += 1

    print(f"\nRecovered {recovered} files into {out}")
    print(f"Skipped (no Write op): {skipped}")

    if args.git_init:
        subprocess.run(["git", "-C", str(out), "init", "-q", "-b", "main"], check=True)
        for key, fallback in (("user.name", "claude-replay"),
                                 ("user.email", "claude-replay@local")):
            try:
                v = subprocess.check_output(["git", "config", "--global", "--get", key],
                                              stderr=subprocess.DEVNULL).decode().strip()
            except subprocess.CalledProcessError:
                v = fallback
            subprocess.run(["git", "-C", str(out), "config", key, v or fallback], check=True)
        subprocess.run(["git", "-C", str(out), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(out), "commit", "-q", "-m",
             f"chore(replay): project recovered from {session_dir.name} JSONLs\n\n"
             f"Files: {recovered}  Skipped: {skipped}"],
            check=True,
        )
        print(f"Initialized git repo at {out} with one snapshot commit.")
        print(f"For per-feature commits, run: claude-replay execute --repo {out} ...")

    return 0


def _infer_original_root(jsonls: list[Path]) -> Optional[str]:
    """Find the longest common prefix of file_paths across the sessions."""
    paths: list[str] = []
    for jp in jsonls[:5]:  # sample
        try:
            with jp.open(encoding="utf-8") as fp:
                for line in fp:
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    msg = rec.get("message") or {}
                    if msg.get("role") != "assistant":
                        continue
                    content = msg.get("content", [])
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict) or block.get("type") != "tool_use":
                            continue
                        if block.get("name") not in ("Write", "Edit", "MultiEdit"):
                            continue
                        fp_ = (block.get("input") or {}).get("file_path", "")
                        if fp_.startswith("/"):
                            paths.append(fp_)
                            if len(paths) > 100:
                                break
                    if len(paths) > 100:
                        break
        except OSError:
            continue
        if len(paths) > 100:
            break
    if not paths:
        return None
    common = os.path.commonpath(paths)
    return common if common.count("/") >= 2 else None


def cmd_analyze(args: argparse.Namespace) -> int:
    """Emit a structured event log of every tool use Claude made.

    For AI-agent behavior researchers — a ready-to-pipe stream of normalized
    records suitable for jq/pandas/duckdb downstream analysis.
    """
    repo = Path(args.repo).resolve()
    session_dir = project_session_dir(repo)
    jsonls = find_session_jsonls(session_dir)
    if not jsonls:
        print("No session JSONLs found.", file=sys.stderr)
        return 2

    # Re-parse to capture ALL tool uses (not just file-modifying ones).
    # Send metadata to stderr so stdout stays clean for piping.
    print(f"# session_dir: {session_dir}", file=sys.stderr)
    print(f"# jsonls: {len(jsonls)}", file=sys.stderr)
    print(f"# format: {args.format}", file=sys.stderr)

    records: list[dict] = []
    tool_uses: dict[str, dict] = {}
    tool_results: dict[str, dict] = {}
    parent_msg: dict[str, str] = {}

    for path in jsonls:
        sid = path.stem
        is_subagent = "subagents" in str(path)
        try:
            with path.open(encoding="utf-8") as fp:
                for line_no, line in enumerate(fp):
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = rec.get("timestamp", "")
                    if args.after and ts < args.after:
                        continue
                    if args.before and ts >= args.before:
                        continue
                    msg = rec.get("message") or {}
                    role = msg.get("role")
                    content = msg.get("content", [])
                    if isinstance(content, str):
                        content = [{"type": "text", "text": content}]
                    if not isinstance(content, list):
                        continue
                    for block in content:
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "tool_use" and role == "assistant":
                            tu_id = block.get("id") or f"{sid}-{line_no}"
                            tool_uses.setdefault(tu_id, {
                                "ts": ts, "session_id": sid, "is_subagent": is_subagent,
                                "tool": block.get("name"),
                                "input": block.get("input") or {},
                            })
                        elif btype == "tool_result" and role == "user":
                            tu_id = block.get("tool_use_id")
                            if not tu_id:
                                continue
                            rc = block.get("content", "")
                            if isinstance(rc, list):
                                rc = "".join(
                                    x.get("text", "") for x in rc
                                    if isinstance(x, dict) and x.get("type") == "text"
                                )
                            tool_results.setdefault(tu_id, {
                                "is_error": block.get("is_error", False),
                                "result_preview": str(rc)[:300],
                            })
        except OSError:
            continue

    # Optional include-tool filter
    include_tools = set(args.include_tool) if args.include_tool else None

    for tu_id, tu in sorted(tool_uses.items(), key=lambda kv: kv[1]["ts"]):
        if include_tools and tu["tool"] not in include_tools:
            continue
        res = tool_results.get(tu_id, {})
        rec = {
            "ts": tu["ts"],
            "session_id": tu["session_id"],
            "is_subagent": tu["is_subagent"],
            "tool": tu["tool"],
            "tool_use_id": tu_id,
            "file_path": tu["input"].get("file_path"),
            "input": tu["input"] if args.full_input else _truncate_input(tu["input"]),
            "success": not res.get("is_error", False),
            "result_preview": res.get("result_preview"),
        }
        records.append(rec)

    print(f"# records: {len(records)}", file=sys.stderr)

    if args.format == "json":
        # JSONL: one record per line — most pipe-friendly
        for r in records:
            print(json.dumps(r, ensure_ascii=False))
    elif args.format == "csv":
        import csv
        cols = ["ts", "session_id", "is_subagent", "tool", "tool_use_id",
                "file_path", "success", "input_summary", "result_preview"]
        w = csv.writer(sys.stdout)
        w.writerow(cols)
        for r in records:
            w.writerow([
                r["ts"], r["session_id"], r["is_subagent"], r["tool"], r["tool_use_id"],
                r.get("file_path") or "",
                r["success"],
                _input_summary(r["input"]),
                (r.get("result_preview") or "").replace("\n", " ")[:200],
            ])
    elif args.format == "stats":
        _print_stats(records)
    else:
        raise ValueError(f"unknown format: {args.format}")

    return 0


def _truncate_input(inp: dict, max_len: int = 200) -> dict:
    """Return a shallow copy with long string fields truncated for compact JSON output."""
    out = {}
    for k, v in inp.items():
        if isinstance(v, str) and len(v) > max_len:
            out[k] = v[:max_len] + f"...[truncated {len(v)-max_len} chars]"
        else:
            out[k] = v
    return out


def _input_summary(inp: dict) -> str:
    if not inp:
        return ""
    parts = []
    for k in ("file_path", "command", "description"):
        if k in inp and isinstance(inp[k], str):
            parts.append(f"{k}={inp[k][:80]}")
    return " ".join(parts)[:200]


def _print_stats(records: list[dict]) -> None:
    """Human-readable statistics summary on stdout."""
    by_tool: defaultdict[str, int] = defaultdict(int)
    by_tool_success: defaultdict[str, int] = defaultdict(int)
    by_session: defaultdict[str, int] = defaultdict(int)
    by_subagent: defaultdict[str, int] = defaultdict(int)
    file_touches: defaultdict[str, int] = defaultdict(int)
    for r in records:
        by_tool[r["tool"]] += 1
        if r["success"]:
            by_tool_success[r["tool"]] += 1
        by_session[r["session_id"]] += 1
        by_subagent["subagent" if r["is_subagent"] else "main"] += 1
        if r.get("file_path"):
            file_touches[r["file_path"]] += 1

    print(f"Total events: {len(records)}")
    print(f"\nBy session ({len(by_session)} sessions):")
    for sid, n in sorted(by_session.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {n:6d}  {sid[:40]}")
    print(f"\nBy origin: main={by_subagent['main']}  subagent={by_subagent['subagent']}")
    print(f"\nBy tool:")
    for tool, n in sorted(by_tool.items(), key=lambda kv: -kv[1]):
        ok = by_tool_success[tool]
        print(f"  {n:6d}  {tool:18s}  success={ok} ({100*ok/n:5.1f}%)")
    print(f"\nTop 10 hottest files:")
    for fp, n in sorted(file_touches.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {n:4d}  {fp}")


def cmd_status(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    session_dir = project_session_dir(repo)
    jsonls = find_session_jsonls(session_dir)
    print(f"Project: {repo}")
    print(f"Session dir: {session_dir}")
    print(f"Session JSONLs: {len(jsonls)}")
    if not jsonls:
        print("(no sessions found — has Claude Code been run in this repo?)")
        return 0
    ops, msgs = extract_timeline(jsonls, repo, after_ts=args.after, before_ts=args.before)
    counts = defaultdict(int)
    for o in ops:
        counts[o.name] += 1
    print(f"File ops in scope: {len(ops)}  "
          f"(Write: {counts['Write']}, Edit: {counts['Edit']}, "
          f"MultiEdit: {counts['MultiEdit']}, Bash: {counts['Bash']})")
    print(f"User messages: {len(msgs)}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    jsonls = find_session_jsonls(project_session_dir(repo))
    if not jsonls:
        print("No session JSONLs found.", file=sys.stderr)
        return 2
    ops, msgs = extract_timeline(jsonls, repo, after_ts=args.after, before_ts=args.before)
    specs = _build_boundaries(args, ops, msgs)
    print(f"Strategy: {args.strategy}")
    print(f"Boundaries: {len(specs)}")
    print()
    op_idx = 0
    for i, spec in enumerate(specs):
        n = 0
        files: set[str] = set()
        while op_idx + n < len(ops) and (spec.until_ts == "9999" or ops[op_idx + n].ts < spec.until_ts):
            o = ops[op_idx + n]
            if o.file_path:
                files.add(o.file_path)
            n += 1
        op_idx += n
        print(f"  {i+1:3d}. [{n:4d} ops, {len(files):3d} files]  {spec.subject}")
    return 0


def cmd_execute(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    jsonls = find_session_jsonls(project_session_dir(repo))
    if not jsonls:
        print("No session JSONLs found.", file=sys.stderr)
        return 2
    ops, msgs = extract_timeline(jsonls, repo, after_ts=args.after, before_ts=args.before)
    specs = _build_boundaries(args, ops, msgs)
    if not specs:
        print("No commit boundaries derived; nothing to do.", file=sys.stderr)
        return 2

    baseline = args.baseline or _resolve_baseline(repo, ops)
    print(f"Baseline: {baseline}")
    print(f"Boundaries: {len(specs)}  Total ops: {len(ops)}")

    sandbox_dir = Path(args.sandbox) if args.sandbox else None
    sandbox = make_sandbox(repo, baseline, "claude-replay", sandbox_dir)
    print(f"Sandbox: {sandbox}")

    result = replay(ops, specs, repo, sandbox, verbose=args.verbose)
    print(f"\nCommits created: {len(result.commits)}")
    print(f"Edit/MultiEdit fall-throughs: {result.edit_failures}")
    print(f"Bash non-zero exits: {result.bash_nonzero}")
    print(f"Diff vs working tree (entries): {result.final_diff_entries}")
    if result.final_diff_entries:
        print("\n--- divergent entries (first 50) ---")
        for line in result.final_diff_text.split("\n")[:50]:
            print(f"  {line}")

    if args.apply:
        if result.final_diff_entries and not args.allow_drift:
            print("\nERROR: sandbox diverges from working tree; refusing to --apply "
                  "without --allow-drift", file=sys.stderr)
            return 3
        if not args.yes and sys.stdin.isatty():
            confirm = input(f"\nApply {len(result.commits)} commits to {repo}? "
                            f"This is DESTRUCTIVE. [y/N] ")
            if confirm.lower() != "y":
                print("Aborted.")
                return 1
        new_head = apply_chain_to_real_repo(repo, sandbox, "claude-replay", baseline)
        print(f"\nReal repo HEAD now: {new_head[:12]}")
        print(f"Backup tag: claude-replay-backup-<ts>")

    return 0


def _build_boundaries(args, ops, msgs) -> list[CommitSpec]:
    if args.strategy == "doc-files":
        specs = boundaries_doc_files(ops, args.boundary_glob)
        if not specs:
            print(f"WARNING: doc-files strategy found no matches for {args.boundary_glob}; "
                  f"falling back to one-shot.", file=sys.stderr)
            specs = boundaries_one_shot(ops)
        return specs
    if args.strategy == "time-gap":
        return boundaries_time_gap(ops, args.gap_minutes)
    if args.strategy == "user-approve":
        return boundaries_user_approve(ops, msgs, args.approve_regex)
    if args.strategy == "one-shot":
        return boundaries_one_shot(ops)
    if args.strategy == "manual":
        return boundaries_manual(Path(args.boundaries_file))
    raise ValueError(f"unknown strategy {args.strategy}")


def _resolve_baseline(repo: Path, ops: list[Op]) -> str:
    if not ops:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"]
        ).decode().strip()
    first_ts = ops[0].ts
    out = subprocess.check_output(
        ["git", "-C", str(repo), "log", "--all", "--format=%H %cI",
         f"--before={first_ts}", "-n", "1"],
    ).decode().strip()
    if not out:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"]
        ).decode().strip()
    return out.split()[0]


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(
        prog="claude-replay",
        description="Reconstruct git commits from Claude Code session history.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=".", help="repo root (default: cwd)")
    common.add_argument("--after", default=None, help="only ops with ts >= this ISO timestamp")
    common.add_argument("--before", default=None, help="only ops with ts < this ISO timestamp")

    p_status = sub.add_parser("status", parents=[common], help="show session JSONL stats")

    boundary_args = argparse.ArgumentParser(add_help=False)
    boundary_args.add_argument("--strategy", default="doc-files",
                                choices=["doc-files", "time-gap", "user-approve", "one-shot", "manual"])
    boundary_args.add_argument("--boundary-glob", default="docs/*.md",
                                help="for doc-files strategy")
    boundary_args.add_argument("--gap-minutes", type=int, default=30,
                                help="for time-gap strategy")
    boundary_args.add_argument("--approve-regex", default=r"批准|approve|lgtm|ship.?it",
                                help="for user-approve strategy")
    boundary_args.add_argument("--boundaries-file", default=None,
                                help="for manual strategy (JSON list)")

    p_plan = sub.add_parser("plan", parents=[common, boundary_args],
                              help="print commit boundaries without building")

    p_exec = sub.add_parser("execute", parents=[common, boundary_args],
                              help="build the chain in a sandbox; verify byte-equality")
    p_exec.add_argument("--baseline", default=None,
                         help="baseline commit (default: HEAD before first op)")
    p_exec.add_argument("--sandbox", default=None,
                         help="sandbox path (default: temp dir)")
    p_exec.add_argument("--apply", action="store_true",
                         help="after build, move real repo HEAD to the chain (DESTRUCTIVE)")
    p_exec.add_argument("--allow-drift", action="store_true",
                         help="allow --apply even when sandbox diverges from working tree")
    p_exec.add_argument("--yes", "-y", action="store_true",
                         help="skip interactive confirmation for --apply")
    p_exec.add_argument("--verbose", "-v", action="store_true",
                         help="print per-commit progress to stderr")

    p_recover_file = sub.add_parser("recover-file",
                                       help="reconstruct a single file from its session-history (lifeline mode)")
    p_recover_file.add_argument("--file", default=None,
                                  help="absolute path of the file to recover")
    p_recover_file.add_argument("--path-match", default=None,
                                  help="regex matching one or more file paths (alt to --file)")
    p_recover_file.add_argument("--session-dir", default=None,
                                  help="explicit session dir (default: auto-discover all)")
    p_recover_file.add_argument("--project-name", default=None,
                                  help="encoded project name under ~/.claude/projects/ (e.g. -home-me-myrepo)")
    p_recover_file.add_argument("--at-ts", default=None,
                                  help="recover state as of this timestamp (default: latest)")
    p_recover_file.add_argument("--list-versions", action="store_true",
                                  help="just list the timeline of ops on the file, don't reconstruct")
    p_recover_file.add_argument("--output-dir", default=None,
                                  help="write recovered files here (default: stdout)")
    p_recover_file.add_argument("--preserve-paths", action="store_true",
                                  help="under --output-dir, preserve full original paths (default: basename only)")

    p_recover_proj = sub.add_parser("recover-project",
                                      help="reconstruct an entire project from session JSONLs (back-from-the-dead mode)")
    p_recover_proj.add_argument("--output-dir", required=True,
                                  help="where to materialize the recovered project (must be empty or use --force)")
    p_recover_proj.add_argument("--session-dir", default=None,
                                  help="explicit session dir (default: auto from output-dir name or --project-name)")
    p_recover_proj.add_argument("--project-name", default=None,
                                  help="encoded project name under ~/.claude/projects/ (e.g. -home-me-myrepo)")
    p_recover_proj.add_argument("--original-root", default=None,
                                  help="original project absolute path (default: auto-infer from session JSONLs)")
    p_recover_proj.add_argument("--at-ts", default=None,
                                  help="recover state as of this timestamp")
    p_recover_proj.add_argument("--git-init", action="store_true",
                                  help="git init the recovered project + one snapshot commit")
    p_recover_proj.add_argument("--force", action="store_true",
                                  help="overwrite output-dir if it exists")

    p_analyze = sub.add_parser("analyze", parents=[common],
                                 help="emit structured event log of every tool use")
    p_analyze.add_argument("--format", default="json",
                            choices=["json", "csv", "stats"],
                            help="output format (default: json = JSONL on stdout)")
    p_analyze.add_argument("--include-tool", action="append", default=None,
                            help="restrict to these tools (e.g. --include-tool Edit "
                                 "--include-tool Bash). Default: all tools.")
    p_analyze.add_argument("--full-input", action="store_true",
                            help="emit complete tool inputs (default: truncate strings >200 chars)")

    p_status.set_defaults(func=cmd_status)
    p_plan.set_defaults(func=cmd_plan)
    p_exec.set_defaults(func=cmd_execute)
    p_analyze.set_defaults(func=cmd_analyze)
    p_recover_file.set_defaults(func=cmd_recover_file)
    p_recover_proj.set_defaults(func=cmd_recover_project)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
