#!/usr/bin/env python3
from __future__ import annotations

import argparse
import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class CleanupPlan:
    config_dir: Path
    sessions_dir: Path
    active_session_key: str | None
    keep_recent: int
    dry_run: bool
    backup: bool
    remove_runtime_env: bool


def _safe_key(session_key: str) -> str:
    return session_key.replace(":", "_").replace("/", "_")


def _format_bytes(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(num_bytes)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(size)}{unit}"
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}TB"


def _dir_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            continue
    return total


def _largest_children(path: Path, limit: int = 10) -> list[tuple[Path, int]]:
    if not path.exists():
        return []
    children = []
    for child in path.iterdir():
        try:
            size = _dir_size(child) if child.is_dir() else child.stat().st_size
        except OSError:
            continue
        children.append((child, size))
    children.sort(key=lambda x: x[1], reverse=True)
    return children[:limit]


def _backup_sessions(plan: CleanupPlan) -> Path | None:
    if not plan.backup:
        return None

    if not plan.sessions_dir.exists():
        print(f"[skip] sessions dir missing: {plan.sessions_dir}")
        return None

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = Path("/tmp") / f"pocketpaw-sessions-backup-{ts}.tgz"
    if plan.dry_run:
        print(f"[dry-run] would write backup: {backup_path}")
        return backup_path

    with tarfile.open(backup_path, "w:gz") as tf:
        tf.add(plan.sessions_dir, arcname="sessions")
    print(f"[ok] backup written: {backup_path}")
    return backup_path


def _session_files(sessions_dir: Path) -> list[Path]:
    if not sessions_dir.exists():
        return []
    files = []
    for f in sessions_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        if f.name.endswith("_compaction.json"):
            continue
        files.append(f)
    return files


def _prune_sessions(plan: CleanupPlan) -> tuple[int, int]:
    files = _session_files(plan.sessions_dir)
    files_sorted = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    keep: set[Path] = set(files_sorted[: max(0, plan.keep_recent)])
    if plan.active_session_key:
        active_file = plan.sessions_dir / f"{_safe_key(plan.active_session_key)}.json"
        if active_file.exists():
            keep.add(active_file)

    to_delete = [f for f in files if f not in keep]

    for f in to_delete:
        compaction = plan.sessions_dir / f"{f.stem}_compaction.json"
        if plan.dry_run:
            print(f"[dry-run] delete: {f}")
            if compaction.exists():
                print(f"[dry-run] delete: {compaction}")
            continue
        f.unlink(missing_ok=True)
        compaction.unlink(missing_ok=True)

    # Rebuild session index if PocketPaw is importable.
    try:
        from pocketpaw.memory.file_store import FileMemoryStore  # noqa: PLC0415

        if plan.dry_run:
            print(f"[dry-run] would rebuild session index in: {plan.sessions_dir}")
        else:
            FileMemoryStore().rebuild_session_index()
            print("[ok] session index rebuilt")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] could not rebuild session index automatically: {exc}")
        print("[hint] restarting PocketPaw will rebuild it if needed.")

    return len(keep), len(to_delete)


def _remove_runtime_env(plan: CleanupPlan) -> None:
    if not plan.remove_runtime_env:
        return

    # These can be huge when PocketPaw was installed via the one-line installer.
    # They are not required when running from this repo using `uv run pocketpaw`.
    candidates = [
        plan.config_dir / "venv",
        plan.config_dir / "uv",
        plan.config_dir / "bin",
    ]

    for p in candidates:
        if not p.exists():
            continue
        if plan.dry_run:
            print(f"[dry-run] remove: {p}")
            continue
        shutil.rmtree(p)
        print(f"[ok] removed: {p}")


def _parse_args() -> CleanupPlan:
    parser = argparse.ArgumentParser(description="Clean PocketPaw data in ~/.pocketpaw safely.")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=Path.home() / ".pocketpaw",
        help="PocketPaw config dir (default: ~/.pocketpaw)",
    )
    parser.add_argument(
        "--keep-recent",
        type=int,
        default=10,
        help="Keep N most recently modified session files (default: 10)",
    )
    parser.add_argument(
        "--active-session-key",
        type=str,
        default=None,
        help="Session key to always keep (example: websocket:... or telegram:...)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip creating a /tmp backup tarball of the sessions directory",
    )
    parser.add_argument(
        "--remove-runtime-env",
        action="store_true",
        help="Also delete ~/.pocketpaw/{venv,uv,bin} (can free hundreds of MB).",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be deleted (default).",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Actually delete files.",
    )

    args = parser.parse_args()

    dry_run = True
    if args.apply:
        dry_run = False
    elif args.dry_run:
        dry_run = True

    config_dir: Path = args.config_dir.expanduser()
    sessions_dir = config_dir / "memory" / "sessions"

    return CleanupPlan(
        config_dir=config_dir,
        sessions_dir=sessions_dir,
        active_session_key=args.active_session_key,
        keep_recent=max(0, args.keep_recent),
        dry_run=dry_run,
        backup=not args.no_backup,
        remove_runtime_env=bool(args.remove_runtime_env),
    )


def main() -> int:
    plan = _parse_args()

    print(f"Config dir:   {plan.config_dir}")
    print(f"Sessions dir: {plan.sessions_dir}")
    print(f"Mode:         {'DRY-RUN' if plan.dry_run else 'APPLY'}")

    if plan.config_dir.exists():
        total = _dir_size(plan.config_dir)
        print(f"Total size:   {_format_bytes(total)}")
        print("Largest children:")
        for child, size in _largest_children(plan.config_dir, limit=10):
            print(f"  - {child.name:16s} {_format_bytes(size)}")
    else:
        print("[warn] config dir does not exist")

    _backup_sessions(plan)

    before = len(_session_files(plan.sessions_dir))
    kept, deleted = _prune_sessions(plan)
    after = len(_session_files(plan.sessions_dir))

    print(f"Sessions:     {before} -> {after} (kept={kept}, deleted={deleted})")

    _remove_runtime_env(plan)

    if plan.dry_run:
        print("Done (dry-run). Re-run with --apply to perform deletion.")
    else:
        print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
