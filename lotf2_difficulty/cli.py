"""Command-line and interactive UI."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from . import __version__
from .patch import default_backup_dir, patch_save_file, patch_slot
from .slots import CharacterSlot, default_save_dir, format_slot_table, list_character_slots

KNOWN_MODES = ("Veteran", "Legacy")


def _print_banner() -> None:
    print(f"LOTF2 Difficulty Fix  v{__version__}")
    print("Lords of the Fallen (2023) — set Veteran / Legacy on existing characters")
    print()


def _print_results(results) -> None:
    for r in results:
        if r.error:
            print(f"  ERROR  {r.path.name}: {r.error}")
            continue
        if r.action == "already_set":
            print(f"  OK     {r.path.name}: already {r.after}")
            continue
        if r.action.startswith("dry_run_"):
            print(
                f"  DRY    {r.path.name}: would {r.action[8:]} "
                f"({r.before} -> {r.after})"
            )
            continue
        bak = r.backup.name if r.backup else "(none)"
        print(
            f"  FIXED  {r.path.name}: {r.action}  "
            f"[{r.character} Lv{r.level}]  {r.before} -> {r.after}"
        )
        print(f"         backup: {bak}")


def cmd_list(save_dir: Path) -> int:
    slots = list_character_slots(save_dir)
    if not slots:
        print(f"No character saves found in:\n  {save_dir}")
        return 1
    print(f"Save folder: {save_dir}\n")
    print(format_slot_table(slots))
    print()
    print("Tip: missing difficulty flag = Legacy/Normal in-game.")
    print("     Red Veteran icon in the load menu means EDifficultyMode::Veteran.")
    return 0


def _resolve_selection(
    slots: Sequence[CharacterSlot],
    selection: str,
) -> List[CharacterSlot]:
    """Parse user selection: numbers, slot names, 'all', or character name substrings."""
    selection = selection.strip()
    if not selection:
        return []
    if selection.lower() in {"all", "*"}:
        return list(slots)

    chosen: List[CharacterSlot] = []
    seen = set()
    for part in selection.replace(";", ",").split(","):
        token = part.strip()
        if not token:
            continue
        # Numeric list index (1-based from table)
        if token.isdigit():
            n = int(token)
            if 1 <= n <= len(slots):
                s = slots[n - 1]
                if s.index not in seen:
                    chosen.append(s)
                    seen.add(s.index)
                continue
            raise ValueError(f"No list entry #{n} (valid 1–{len(slots)})")

        # Save03 / 3 / save3
        low = token.lower().replace(" ", "")
        if low.startswith("save") and low[4:].isdigit():
            idx = int(low[4:])
        elif token.isdigit():
            idx = int(token)
        else:
            idx = None

        if idx is not None:
            match = next((s for s in slots if s.index == idx), None)
            if not match:
                raise ValueError(f"No Save{idx:02d} slot found")
            if match.index not in seen:
                chosen.append(match)
                seen.add(match.index)
            continue

        # Name substring
        name_hits = [s for s in slots if token.lower() in s.name.lower()]
        if not name_hits:
            raise ValueError(f"No character matching {token!r}")
        for s in name_hits:
            if s.index not in seen:
                chosen.append(s)
                seen.add(s.index)
    return chosen


def cmd_fix(
    save_dir: Path,
    selection: str,
    mode: str,
    *,
    include_rotating: bool,
    dry_run: bool,
    backup_dir: Optional[Path],
) -> int:
    slots = list_character_slots(save_dir)
    if not slots:
        print(f"No character saves found in:\n  {save_dir}")
        return 1

    try:
        chosen = _resolve_selection(slots, selection)
    except ValueError as exc:
        print(f"Selection error: {exc}")
        return 1
    if not chosen:
        print("Nothing selected.")
        return 1

    bak = backup_dir or default_backup_dir(save_dir)
    print(f"Mode:     {mode}")
    print(f"Backups:  {bak}")
    print(f"Rotating: {'yes (SaveXX_b1/b2)' if include_rotating else 'main file only'}")
    if dry_run:
        print("DRY RUN — no files will be written")
    print()

    any_error = False
    for slot in chosen:
        print(
            f"→ {slot.slot_label}  {slot.name}  "
            f"Lv{slot.level if slot.level is not None else '?'}  "
            f"({slot.difficulty})"
        )
        results = patch_slot(
            slot,
            mode,
            bak,
            include_rotating=include_rotating,
            dry_run=dry_run,
        )
        _print_results(results)
        if any(r.error for r in results):
            any_error = True
        print()

    if not dry_run:
        print("Done. Fully quit the game before loading, and watch Steam Cloud.")
    return 1 if any_error else 0


def interactive(save_dir: Path) -> int:
    _print_banner()
    print(f"Save folder:\n  {save_dir}\n")
    if not save_dir.is_dir():
        print("Folder not found. Pass --save-dir PATH or install the game once.")
        return 1

    while True:
        slots = list_character_slots(save_dir)
        if not slots:
            print("No character saves found.")
            return 1
        print(format_slot_table(slots))
        print()
        print("Commands:")
        print("  <numbers>   fix those rows (e.g. 3   or  1,3,5)")
        print("  save03      fix by slot name")
        print("  ribs        fix by character name (substring)")
        print("  all         fix every listed character")
        print("  r           refresh list")
        print("  q           quit")
        print()
        raw = input("Select character(s) to set to Veteran [q]: ").strip()
        if not raw or raw.lower() in {"q", "quit", "exit"}:
            print("Bye.")
            return 0
        if raw.lower() in {"r", "refresh", "list"}:
            print()
            continue

        mode = "Veteran"
        mode_in = input("Difficulty mode [Veteran] (Veteran/Legacy): ").strip()
        if mode_in:
            # Accept case-insensitive known modes
            hit = next((m for m in KNOWN_MODES if m.lower() == mode_in.lower()), None)
            mode = hit or mode_in

        rot_in = input("Also patch SaveXX_b1 / _b2 rotating backups? [Y/n]: ").strip().lower()
        include_rotating = rot_in not in {"n", "no"}

        print()
        confirm = input(
            f"Backup originals, then set selected characters to {mode}? [y/N]: "
        ).strip().lower()
        if confirm not in {"y", "yes"}:
            print("Cancelled.\n")
            continue

        code = cmd_fix(
            save_dir,
            raw,
            mode,
            include_rotating=include_rotating,
            dry_run=False,
            backup_dir=None,
        )
        print()
        again = input("Fix another? [Y/n]: ").strip().lower()
        if again in {"n", "no"}:
            return code
        print()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="lotf2-difficulty",
        description=(
            "List Lords of the Fallen (2023) characters and set difficulty "
            "(Veteran / Legacy) on existing saves. Always backs up before writing."
        ),
    )
    p.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    p.add_argument(
        "--save-dir",
        type=Path,
        default=None,
        help="Path to SaveGames folder (default: %%LOCALAPPDATA%%\\LOTF2\\Saved\\SaveGames)",
    )
    p.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Backup folder (default: <save-dir>/_difficulty_fix_backups)",
    )

    sub = p.add_subparsers(dest="command")

    sub.add_parser("list", help="List characters and their difficulty")
    sub.add_parser("interactive", help="Interactive menu (default if no command)")

    fix = sub.add_parser("fix", help="Set difficulty on selected characters")
    fix.add_argument(
        "selection",
        help="List #, Save03, character name, comma-separated list, or 'all'",
    )
    fix.add_argument(
        "--mode",
        default="Veteran",
        help="Difficulty mode (default: Veteran). Legacy also supported.",
    )
    fix.add_argument(
        "--main-only",
        action="store_true",
        help="Only patch SaveXX.sav (skip game rotating _b1/_b2)",
    )
    fix.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing",
    )

    file_p = sub.add_parser("fix-file", help="Patch explicit .sav file path(s)")
    file_p.add_argument("files", nargs="+", type=Path, help="Path to SaveXX.sav")
    file_p.add_argument("--mode", default="Veteran")
    file_p.add_argument("--dry-run", action="store_true")

    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(argv)

    save_dir = Path(args.save_dir) if args.save_dir else default_save_dir()

    if args.command is None:
        return interactive(save_dir)

    if args.command == "list":
        _print_banner()
        return cmd_list(save_dir)

    if args.command == "interactive":
        return interactive(save_dir)

    if args.command == "fix":
        _print_banner()
        return cmd_fix(
            save_dir,
            args.selection,
            args.mode,
            include_rotating=not args.main_only,
            dry_run=args.dry_run,
            backup_dir=args.backup_dir,
        )

    if args.command == "fix-file":
        _print_banner()
        bak = args.backup_dir or default_backup_dir(save_dir)
        print(f"Backups: {bak}")
        any_error = False
        for f in args.files:
            print(f"→ {f}")
            r = patch_save_file(f, args.mode, bak, dry_run=args.dry_run)
            _print_results([r])
            if r.error:
                any_error = True
        return 1 if any_error else 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
