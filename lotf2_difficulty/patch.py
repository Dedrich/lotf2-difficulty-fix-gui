"""Backup + apply difficulty patches to character saves."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Sequence

from .properties import get_difficulty, get_player_level, get_player_name, patch_payload_difficulty
from .save_format import parse_save, payload_from_chunks, surgical_rebuild, verify_save_bytes
from .slots import CharacterSlot


@dataclass
class PatchResult:
    path: Path
    action: str
    before: Optional[str]
    after: Optional[str]
    backup: Optional[Path]
    character: str
    level: Optional[int]
    error: Optional[str] = None


def make_backup(path: Path, backup_dir: Path) -> Path:
    """Copy ``path`` into ``backup_dir`` with a timestamp suffix. Always called before writes."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"{path.name}.bak_{stamp}"
    # Avoid clobber if two writes in the same second
    n = 1
    while dest.exists():
        dest = backup_dir / f"{path.name}.bak_{stamp}_{n}"
        n += 1
    shutil.copy2(path, dest)
    return dest


def patch_save_file(
    path: Path,
    mode: str,
    backup_dir: Path,
    *,
    dry_run: bool = False,
) -> PatchResult:
    """Backup (unless dry-run) and set difficulty on a single .sav file."""
    path = Path(path)
    try:
        data = path.read_bytes()
        header, chunks, _trailer = parse_save(data)
        payload = payload_from_chunks(chunks)
        before = get_difficulty(payload)
        character = get_player_name(payload)
        level = get_player_level(payload)

        new_payload, action = patch_payload_difficulty(payload, mode)
        after = get_difficulty(new_payload)

        if action == "already_set":
            return PatchResult(
                path=path,
                action=action,
                before=before,
                after=after,
                backup=None,
                character=character,
                level=level,
            )

        if dry_run:
            return PatchResult(
                path=path,
                action=f"dry_run_{action}",
                before=before,
                after=after,
                backup=None,
                character=character,
                level=level,
            )

        backup = make_backup(path, backup_dir)
        new_data = surgical_rebuild(header, chunks, new_payload)
        verify = verify_save_bytes(new_data)
        got = get_difficulty(verify)
        if got != f"EDifficultyMode::{mode}":
            raise RuntimeError(f"Post-write verify failed: got {got!r}")

        path.write_bytes(new_data)
        return PatchResult(
            path=path,
            action=action,
            before=before,
            after=after,
            backup=backup,
            character=character,
            level=level,
        )
    except Exception as exc:  # noqa: BLE001
        return PatchResult(
            path=path,
            action="error",
            before=None,
            after=None,
            backup=None,
            character="?",
            level=None,
            error=str(exc),
        )


def patch_slot(
    slot: CharacterSlot,
    mode: str,
    backup_dir: Path,
    *,
    include_rotating: bool = True,
    dry_run: bool = False,
) -> List[PatchResult]:
    """Patch main save and optionally game-written SaveNN_b1 / _b2 companions."""
    paths: Sequence[Path] = slot.all_paths if include_rotating else [slot.main_path]
    results: List[PatchResult] = []
    for path in paths:
        if not path.exists():
            continue
        results.append(patch_save_file(path, mode, backup_dir, dry_run=dry_run))
    return results


def default_backup_dir(save_dir: Path) -> Path:
    return Path(save_dir) / "_difficulty_fix_backups"
