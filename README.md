# LOTF2 Difficulty Fix — Portable GUI

A **simple Windows app** that sets **Veteran** or **Legacy / Normal** difficulty on an existing *Lords of the Fallen* (2023) character.

No command line. No Python install needed if you use the pre-built EXE.

---

## For players (use the EXE)

1. **Quit** Lords of the Fallen completely.
2. Download **`LOTF2_Difficulty_Fix.exe`** (see [Releases](../../releases) or the `dist` folder if you built it yourself).
3. Double-click the EXE (portable — put it anywhere).
4. Your save folder is usually found automatically.
5. Click your character in the list.
6. Choose **Veteran** or **Legacy / Normal**.
7. Click **Apply fix to selected character(s)** and confirm.
8. Start the game → Load Game → check the difficulty icon → rest at a vestige.

### Backups

Every change is copied first to:

```text
%LOCALAPPDATA%\LOTF2\Saved\SaveGames\_difficulty_fix_backups\
```

Use the **Open backups folder** button in the app.

### Steam Cloud

If the difficulty snaps back, Cloud may have restored the old file.  
After fixing: play **offline** once, rest at a vestige, then go online again.

---

## Build the portable EXE yourself

Requirements: Windows, Python 3.10+

```bat
cd /d H:\lotf2-difficulty-fix-gui
build_exe.bat
```

Output:

```text
dist\LOTF2_Difficulty_Fix.exe
```

That single file is portable. Share only the EXE if you want; users do not need this source folder.

Or with the spec file:

```bat
python -m PyInstaller --noconfirm LOTF2_Difficulty_Fix.spec
```

---

## Run from source (developers)

```bat
python app.py
```

Uses the bundled `lotf2_difficulty` package (same engine as the CLI tool).

---

## Safety

| | |
|--|--|
| Backups | Always created before writing |
| Game must be closed | Yes — recommended |
| Official | No — community tool, use at your own risk |

Not affiliated with CI Games / HEXWORKS.

---

## License

MIT — see [LICENSE](LICENSE).
