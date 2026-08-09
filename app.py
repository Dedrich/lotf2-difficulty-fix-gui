#!/usr/bin/env python3
"""User-friendly GUI for LOTF2 difficulty fixing — no CLI required."""

from __future__ import annotations

import os
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List

from lotf2_difficulty import __version__
from lotf2_difficulty.patch import default_backup_dir, patch_slot
from lotf2_difficulty.slots import CharacterSlot, default_save_dir, list_character_slots

APP_TITLE = "LOTF2 Difficulty Fix"
APP_WIDTH = 920
APP_HEIGHT = 640


def _short_diff(label: str) -> str:
    if "missing" in label.lower() or label.startswith("Legacy"):
        return "Legacy / Normal"
    if "Veteran" in label:
        return "Veteran"
    if label.startswith("ERROR"):
        return "Error"
    return label


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_TITLE}  v{__version__}")
        self.geometry(f"{APP_WIDTH}x{APP_HEIGHT}")
        self.minsize(780, 520)

        self.save_dir = tk.StringVar(value=str(default_save_dir()))
        self.mode = tk.StringVar(value="Veteran")
        self.include_rotating = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Ready. Quit the game before applying a fix.")
        self._slots: List[CharacterSlot] = []
        self._busy = False

        self._build_style()
        self._build_ui()
        self.after(100, self.refresh_list)

        # Center on screen
        self.update_idletasks()
        x = (self.winfo_screenwidth() - APP_WIDTH) // 2
        y = max(20, (self.winfo_screenheight() - APP_HEIGHT) // 2)
        self.geometry(f"+{x}+{y}")

    def _build_style(self) -> None:
        style = ttk.Style(self)
        # Prefer a clean native theme
        for name in ("vista", "xpnative", "clam", "default"):
            if name in style.theme_names():
                style.theme_use(name)
                break
        style.configure("Title.TLabel", font=("Segoe UI", 16, "bold"))
        style.configure("Subtitle.TLabel", font=("Segoe UI", 10))
        style.configure("Warn.TLabel", font=("Segoe UI", 9), foreground="#8a4b08")
        style.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=10)
        style.configure("Treeview", font=("Segoe UI", 10), rowheight=28)
        style.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 9))

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Frame(root)
        header.pack(fill=tk.X)
        ttk.Label(header, text=APP_TITLE, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            header,
            text="Change Veteran / Legacy difficulty on an existing character save.",
            style="Subtitle.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))

        warn = ttk.Label(
            root,
            text=(
                "⚠  Fully quit Lords of the Fallen before applying. "
                "A backup is created automatically. "
                "If Steam Cloud is on, it may overwrite your fix — go offline once if needed."
            ),
            style="Warn.TLabel",
            wraplength=APP_WIDTH - 60,
            justify=tk.LEFT,
        )
        warn.pack(fill=tk.X, pady=(10, 8))

        # Folder row
        folder_fr = ttk.LabelFrame(root, text="Save folder", padding=8)
        folder_fr.pack(fill=tk.X, pady=(0, 8))
        row = ttk.Frame(folder_fr)
        row.pack(fill=tk.X)
        ent = ttk.Entry(row, textvariable=self.save_dir)
        ent.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        ttk.Button(row, text="Browse…", command=self.browse_folder).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(row, text="Refresh list", command=self.refresh_list).pack(side=tk.LEFT)

        # Character table
        list_fr = ttk.LabelFrame(root, text="Your characters  (click to select — Ctrl/Shift for multiple)", padding=8)
        list_fr.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        cols = ("slot", "name", "level", "difficulty", "modified")
        self.tree = ttk.Treeview(
            list_fr,
            columns=cols,
            show="headings",
            selectmode="extended",
        )
        self.tree.heading("slot", text="Slot")
        self.tree.heading("name", text="Character name")
        self.tree.heading("level", text="Level")
        self.tree.heading("difficulty", text="Difficulty")
        self.tree.heading("modified", text="Last saved")
        self.tree.column("slot", width=70, anchor=tk.CENTER)
        self.tree.column("name", width=220, anchor=tk.W)
        self.tree.column("level", width=70, anchor=tk.CENTER)
        self.tree.column("difficulty", width=160, anchor=tk.W)
        self.tree.column("modified", width=150, anchor=tk.CENTER)

        vsb = ttk.Scrollbar(list_fr, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.tag_configure("veteran", background="#e8f5e9")
        self.tree.tag_configure("legacy", background="#fff8e1")
        self.tree.tag_configure("error", background="#ffebee")

        # Options
        opt = ttk.LabelFrame(root, text="Fix options", padding=10)
        opt.pack(fill=tk.X, pady=(0, 8))

        mode_row = ttk.Frame(opt)
        mode_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(mode_row, text="Set difficulty to:").pack(side=tk.LEFT, padx=(0, 12))
        ttk.Radiobutton(mode_row, text="Veteran  (harder)", variable=self.mode, value="Veteran").pack(
            side=tk.LEFT, padx=(0, 16)
        )
        ttk.Radiobutton(mode_row, text="Legacy / Normal", variable=self.mode, value="Legacy").pack(side=tk.LEFT)

        ttk.Checkbutton(
            opt,
            text="Also update the game’s automatic backup copies (SaveXX_b1 / _b2)  — recommended",
            variable=self.include_rotating,
        ).pack(anchor=tk.W)

        # Actions
        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=(0, 6))
        self.apply_btn = ttk.Button(
            actions,
            text="Apply fix to selected character(s)",
            style="Big.TButton",
            command=self.apply_fix,
        )
        self.apply_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(actions, text="Open backups folder", command=self.open_backups).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(actions, text="Open save folder", command=self.open_save_folder).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(actions, text="Help", command=self.show_help).pack(side=tk.RIGHT)

        # Log
        log_fr = ttk.LabelFrame(root, text="Activity log", padding=6)
        log_fr.pack(fill=tk.BOTH, expand=False, pady=(0, 6))
        self.log = tk.Text(
            log_fr,
            height=7,
            wrap=tk.WORD,
            font=("Consolas", 9),
            state=tk.DISABLED,
            background="#f7f7f7",
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        # Status bar
        ttk.Label(root, textvariable=self.status, style="Status.TLabel").pack(anchor=tk.W)

    # ----- helpers -----

    def log_line(self, msg: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, msg + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        self.apply_btn.configure(state=state)

    def browse_folder(self) -> None:
        initial = self.save_dir.get() or str(Path.home())
        chosen = filedialog.askdirectory(title="Select LOTF2 SaveGames folder", initialdir=initial)
        if chosen:
            self.save_dir.set(chosen)
            self.refresh_list()

    def open_save_folder(self) -> None:
        path = Path(self.save_dir.get())
        if not path.is_dir():
            messagebox.showwarning(APP_TITLE, f"Folder not found:\n{path}")
            return
        os.startfile(path)  # type: ignore[attr-defined]

    def open_backups(self) -> None:
        path = default_backup_dir(Path(self.save_dir.get()))
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(path)  # type: ignore[attr-defined]

    def show_help(self) -> None:
        messagebox.showinfo(
            f"{APP_TITLE} — Help",
            (
                "How to use\n"
                "──────────\n"
                "1. Quit Lords of the Fallen completely.\n"
                "2. Click Refresh list (folder is usually auto-detected).\n"
                "3. Click the character you want (Ctrl+click for more).\n"
                "4. Choose Veteran or Legacy / Normal.\n"
                "5. Click Apply fix.\n"
                "6. Start the game and check the load menu icon.\n\n"
                "Backups\n"
                "───────\n"
                "Every change is copied first into:\n"
                "  SaveGames\\_difficulty_fix_backups\\\n"
                "Use “Open backups folder” to find them.\n\n"
                "Steam Cloud\n"
                "───────────\n"
                "If the difficulty reverts, Cloud may have restored the old file.\n"
                "Play offline once after fixing, rest at a vestige, then go online.\n\n"
                f"Version {__version__}\n"
                "Unofficial tool — not affiliated with CI Games / HEXWORKS."
            ),
        )

    def refresh_list(self) -> None:
        if self._busy:
            return
        folder = Path(self.save_dir.get().strip().strip('"'))
        self.tree.delete(*self.tree.get_children())
        self._slots = []

        if not folder.is_dir():
            self.status.set(f"Folder not found: {folder}")
            self.log_line(f"ERROR: folder not found — {folder}")
            return

        try:
            slots = list_character_slots(folder)
        except Exception as exc:  # noqa: BLE001
            self.status.set(f"Could not read saves: {exc}")
            self.log_line(f"ERROR reading {folder}: {exc}")
            return

        self._slots = slots
        if not slots:
            self.status.set("No character saves found in that folder.")
            self.log_line(f"No characters in {folder}")
            return

        for s in slots:
            lvl = "—" if s.level is None else str(s.level)
            diff = _short_diff(s.difficulty)
            if s.error:
                tag = "error"
                diff = "Unreadable"
            elif "Veteran" in s.difficulty:
                tag = "veteran"
            else:
                tag = "legacy"
            self.tree.insert(
                "",
                tk.END,
                iid=str(s.index),
                values=(
                    s.slot_label,
                    s.name,
                    lvl,
                    diff,
                    s.modified.strftime("%Y-%m-%d %H:%M"),
                ),
                tags=(tag,),
            )

        self.status.set(f"Found {len(slots)} character(s) in {folder}")
        self.log_line(f"Loaded {len(slots)} character(s) from {folder}")

    def _selected_slots(self) -> List[CharacterSlot]:
        selected = self.tree.selection()
        by_idx = {s.index: s for s in self._slots}
        out: List[CharacterSlot] = []
        for iid in selected:
            try:
                idx = int(iid)
            except ValueError:
                continue
            if idx in by_idx:
                out.append(by_idx[idx])
        return out

    def apply_fix(self) -> None:
        if self._busy:
            return
        chosen = self._selected_slots()
        if not chosen:
            messagebox.showinfo(
                APP_TITLE,
                "Select at least one character in the list first.\n\n"
                "Click a row to select it. Hold Ctrl to select several.",
            )
            return

        mode = self.mode.get()
        names = ", ".join(f"{s.name} (Lv{s.level})" for s in chosen)
        backup_dir = default_backup_dir(Path(self.save_dir.get()))

        ok = messagebox.askyesno(
            "Confirm fix",
            (
                f"Set difficulty to:  {mode}\n\n"
                f"Characters:\n  {names}\n\n"
                f"Backups will be saved to:\n  {backup_dir}\n\n"
                "Make sure the game is fully closed.\n\n"
                "Continue?"
            ),
            icon="question",
        )
        if not ok:
            self.log_line("Cancelled by user.")
            return

        self.set_busy(True)
        self.status.set("Working… please wait.")
        self.update_idletasks()

        # Run patch on a worker thread so UI stays responsive for large saves
        def worker() -> None:
            results_summary: List[str] = []
            errors = 0
            try:
                for slot in chosen:
                    results_summary.append(
                        f"── {slot.slot_label} {slot.name} Lv{slot.level} ──"
                    )
                    try:
                        results = patch_slot(
                            slot,
                            mode,
                            backup_dir,
                            include_rotating=self.include_rotating.get(),
                            dry_run=False,
                        )
                    except Exception as exc:  # noqa: BLE001
                        errors += 1
                        results_summary.append(f"  ERROR: {exc}")
                        results_summary.append(traceback.format_exc())
                        continue

                    for r in results:
                        if r.error:
                            errors += 1
                            results_summary.append(f"  ERROR  {r.path.name}: {r.error}")
                        elif r.action == "already_set":
                            results_summary.append(
                                f"  OK     {r.path.name}: already {mode}"
                            )
                        else:
                            bak = r.backup.name if r.backup else "?"
                            results_summary.append(
                                f"  FIXED  {r.path.name}: {r.action} "
                                f"({r.before} → {r.after})"
                            )
                            results_summary.append(f"         backup: {bak}")
            finally:
                self.after(0, lambda: self._apply_done(results_summary, errors, mode))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_done(self, lines: List[str], errors: int, mode: str) -> None:
        for line in lines:
            self.log_line(line)
        self.set_busy(False)
        self.refresh_list()

        if errors:
            self.status.set(f"Finished with {errors} error(s). See the activity log.")
            messagebox.showerror(
                APP_TITLE,
                f"Some files failed ({errors} error(s)).\n\n"
                "Check the activity log. Your backups are still in the backups folder.",
            )
        else:
            self.status.set(f"Done — difficulty set to {mode}.")
            messagebox.showinfo(
                APP_TITLE,
                (
                    f"Success! Selected characters are now set to {mode}.\n\n"
                    "Next steps:\n"
                    "1. Start Lords of the Fallen\n"
                    "2. Open Load Game — check the difficulty icon\n"
                    "3. Load the character and rest at a vestige\n\n"
                    "Backups are in SaveGames\\_difficulty_fix_backups\\"
                ),
            )


def main() -> None:
    # High-DPI awareness on Windows (best-effort)
    try:
        from ctypes import windll

        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
