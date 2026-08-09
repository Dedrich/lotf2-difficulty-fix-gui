"""Discover and describe character save slots."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from .properties import (
    difficulty_label,
    get_difficulty,
    get_player_level,
    get_player_name,
)
from .save_format import parse_save, payload_from_chunks

# Versioned archives like Save03_2_5_550.sav — skip for the character list
_VERSIONED = re.compile(r"^Save\d+_\d+_\d+")
# Rotating auto-backups written by the game
_ROTATING = re.compile(r"^Save(\d+)_b([12])\.sav$", re.I)
_MAIN = re.compile(r"^Save(\d+)\.sav$", re.I)


def default_save_dir() -> Path:
    local = Path.home() / "AppData" / "Local" / "LOTF2" / "Saved" / "SaveGames"
    return local


@dataclass
class CharacterSlot:
    """One character slot (main SaveNN.sav, optionally with b1/b2 companions)."""

    index: int
    main_path: Path
    name: str
    level: Optional[int]
    difficulty: str
    difficulty_raw: Optional[str]
    modified: datetime
    size: int
    rotating: List[Path]
    error: Optional[str] = None

    @property
    def slot_label(self) -> str:
        return f"Save{self.index:02d}"

    @property
    def all_paths(self) -> List[Path]:
        return [self.main_path, *self.rotating]


def _is_listable_save(path: Path) -> bool:
    name = path.name
    if not name.lower().endswith(".sav"):
        return False
    if _VERSIONED.match(name):
        return False
    if name.lower().startswith("general") or name.lower().startswith("photo"):
        return False
    return bool(_MAIN.match(name) or _ROTATING.match(name))


def _load_payload(path: Path) -> bytes:
    _h, chunks, _t = parse_save(path.read_bytes())
    return payload_from_chunks(chunks)


def list_character_slots(save_dir: Path) -> List[CharacterSlot]:
    """List main character slots under a SaveGames folder."""
    save_dir = Path(save_dir)
    if not save_dir.is_dir():
        raise FileNotFoundError(f"Save folder not found: {save_dir}")

    mains: dict[int, Path] = {}
    rotating: dict[int, List[Path]] = {}

    for path in sorted(save_dir.iterdir()):
        if not path.is_file() or not _is_listable_save(path):
            continue
        m = _MAIN.match(path.name)
        if m:
            mains[int(m.group(1))] = path
            continue
        r = _ROTATING.match(path.name)
        if r:
            idx = int(r.group(1))
            rotating.setdefault(idx, []).append(path)

    slots: List[CharacterSlot] = []
    all_indices = sorted(set(mains) | set(rotating))
    for idx in all_indices:
        rots = sorted(rotating.get(idx, []), key=lambda p: p.name)
        # Prefer main SaveNN.sav; fall back to newest rotating copy
        if idx in mains:
            path = mains[idx]
            companion = rots
        else:
            path = max(rots, key=lambda p: p.stat().st_mtime)
            companion = [p for p in rots if p != path]
        try:
            payload = _load_payload(path)
            slots.append(
                CharacterSlot(
                    index=idx,
                    main_path=path,
                    name=get_player_name(payload),
                    level=get_player_level(payload),
                    difficulty=difficulty_label(payload),
                    difficulty_raw=get_difficulty(payload),
                    modified=datetime.fromtimestamp(path.stat().st_mtime),
                    size=path.stat().st_size,
                    rotating=companion,
                    error=None,
                )
            )
        except Exception as exc:  # noqa: BLE001 - show per-slot errors to user
            slots.append(
                CharacterSlot(
                    index=idx,
                    main_path=path,
                    name="(unreadable)",
                    level=None,
                    difficulty="?",
                    difficulty_raw=None,
                    modified=datetime.fromtimestamp(path.stat().st_mtime),
                    size=path.stat().st_size,
                    rotating=companion,
                    error=str(exc),
                )
            )
    return slots


def format_slot_table(slots: Iterable[CharacterSlot]) -> str:
    rows = [
        f"{'#':>3}  {'Slot':<8}  {'Name':<18}  {'Lvl':>4}  {'Difficulty':<28}  Modified"
    ]
    rows.append("-" * len(rows[0]) + "-" * 12)
    for n, s in enumerate(slots, start=1):
        lvl = "—" if s.level is None else str(s.level)
        name = (s.name[:16] + "…") if len(s.name) > 17 else s.name
        diff = s.difficulty
        if s.error:
            diff = f"ERROR: {s.error[:40]}"
        rows.append(
            f"{n:>3}  {s.slot_label:<8}  {name:<18}  {lvl:>4}  {diff:<28}  "
            f"{s.modified.strftime('%Y-%m-%d %H:%M')}"
        )
    return "\n".join(rows)
