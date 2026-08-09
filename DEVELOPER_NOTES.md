# Developer notes

Technical background for maintainers: why LOTF difficulty breaks, how saves are structured, and how this tool fixes them without corrupting slots.

The product README is aimed at players. This document is for people changing the code.

---

## Problem summary

Lords of the Fallen (2023, package/path `LOTF2`) introduced a **Veteran** difficulty mode (post‑2.5 era “Legacy vs Veteran”). That mode is stored on the character save as a UE property:

```text
DifficultyMode  : EnumProperty
  type  = EDifficultyMode
  value = EDifficultyMode::Veteran
```

If that property is **missing**, the game does **not** error. It treats the run as **Legacy / Normal**. The load-menu icon and combat scaling follow that default.

So a character that *was* Veteran can silently become “Normal” after:

- A playthrough restart / modifier path that rewrites slot metadata without re-writing the enum  
- Save migration across patches  
- Manual save edits that drop the property  
- (In our testing) a full re-save cycle after some progression paths  

Players cannot change difficulty mid-run in the official UI, so a binary save patch is the practical fix.

---

## Why stock tools fail (`uesave`, generic GVAS editors)

The files under `%LOCALAPPDATA%\LOTF2\Saved\SaveGames\` look like Unreal `.sav` / GVAS:

```text
GVAS  +  engine version  +  custom versions  +  class name
  e.g. /Script/LOTF2.LOTF2SaveGame
```

After the class name, LOTF does **not** store a plain property tree. It stores a **custom multi-chunk compressed body**:

```text
u32 total_body_size
repeat:
  8-byte chunk magic   c1 83 2a 9e 22 22 22 22
  41-byte chunk meta   (sizes / flags; see below)
  zlib stream          (78 9c, 78 da, …)
4-byte trailer CRC32   of everything *before* the trailer
```

`uesave to-json` typically dies with something like:

```text
Error: at offset N: io error: failed to fill whole buffer
```

because it parses standard GVAS properties after the class string and then hits zlib/binary layout it does not understand.

**Implication:** any real editor for these saves must implement LOTF’s container, not only UE’s property format.

Core implementation: `lotf2_difficulty/save_format.py`.

---

## Chunk meta (the bug that deleted characters from the load list)

Each chunk’s meta block is **exactly 41 bytes** on disk (as written by the game):

```text
u16  0
u32  2
u16  0
u8   3
u64  compressed_size     (twice, as a pair of identical size pairs)
u64  uncompressed_size
u64  compressed_size
u64  uncompressed_size
```

There is **no** trailing null after those fields. Zlib starts immediately.

Uncompressed payload is split into **128 KiB** blocks (`131072` bytes), last chunk shorter.

### What we did wrong first

An early fixer rebuilt *every* chunk and appended an extra `0x00` to meta (**42 bytes**).  

- Our Python decompressor still worked (it *searches* for a zlib signature).  
- The **game** trusts the fixed layout / sizes and failed to load the slot.  
- Result in the UI: **character missing** from the load list (empty gap), not a friendly error.

### Correct write path

1. Parse all chunks (meta + compressed bytes + raw).  
2. Join raw → full property payload.  
3. Patch the payload in memory.  
4. Re-split into 128 KiB blocks.  
5. **Surgical rebuild:** copy original compressed chunks while raw is unchanged; only recompress from the first dirty block to the end.  
6. Emit **41-byte** meta, zlib level 6 (typically `78 9c`, matching many in-game chunks).  
7. Append `CRC32(file_without_trailer)` as little-endian `u32`.  
8. Verify by re-parse + CRC + difficulty string before replace.

This minimizes rewrite risk on multi‑MB endgame saves (often 200+ chunks).

---

## Property-level fix

Decompressed payload is standard UE-style named properties (FString name, type, size, tag, value).

### Reading values

Int/Str properties use a **tag byte** after the size field before the value. Forgetting it mis-parses `PlayerName` / `PlayerLevel` (classic “empty name”, absurd level numbers).

Helpers: `lotf2_difficulty/properties.py`.

### Difficulty

- Present: `EDifficultyMode::Veteran` or other `EDifficultyMode::*` string.  
- Absent: UI label **“Legacy / Normal (flag missing)”** — matches game default.

### Patch strategies

1. **Already correct** → no write.  
2. **Enum present, wrong value** → rewrite enum FString + `EnumProperty` size (`u64` = 4 + value length including null).  
3. **Enum missing** → **insert** a full `DifficultyMode` `EnumProperty` immediately before `LevelName`, after `CoopCampaignHostsName` / host name. That matches layouts seen on known-good Veteran saves (e.g. mid-run Ribs / Kicknm host field).

Property blob for Veteran is 94 bytes when serialized as in `make_difficulty_prop("Veteran")`.

### Name fields (don’t confuse them)

| Property | Meaning in practice |
|----------|---------------------|
| `PlayerName` | Character name on the load screen (e.g. **Ribs**) |
| `CoopCampaignHostsName` | Often account / host string (e.g. **Kicknm**) |

Listing must prefer `PlayerName`.

### Rotating backups

The game also keeps `SaveXX_b1.sav` / `SaveXX_b2.sav`. Patching only `SaveXX.sav` can lose the fix if the game reloads a rotating copy. Default behavior patches **main + rotating** companions for that slot index.

Versioned archives like `Save03_2_5_550.sav` are ignored for the character list (migration snapshots).

---

## CLI vs GUI

| Path | Role |
|------|------|
| [lotf2-difficulty-fix](https://github.com/Dedrich/lotf2-difficulty-fix) | CLI / library-first (now typically private) |
| **This repo** | Portable **GUI** + PyInstaller one-file EXE |

Both ship the same `lotf2_difficulty` package (`save_format`, `properties`, `slots`, `patch`). The GUI (`app.py`) is a thin Tk front end:

- List slots, select rows, choose Veteran/Legacy  
- Always backup under `SaveGames\_difficulty_fix_backups\`  
- Worker thread for long patches so the UI stays responsive  

### Packaging gotchas already hit

1. **`ModuleNotFoundError: queueinter`**  
   Source corruption merged lines into `import queueinter as tk`. Fix: keep `import threading` and `import tkinter as tk` on separate clean lines; rebuild EXE.

2. **“No Apply button”**  
   Apply control was packed *below* an expanding Treeview with no main-window scroll. On shorter / high-DPI windows it sat off-screen. Fix: pack a **fixed bottom green Apply bar** (`side=BOTTOM`) before the expanding list; optional double-click to apply.

3. **PyInstaller**  
   One-file windowed build; hidden-imports for the package submodules; Tcl/Tk via stock hooks. Output: `dist/LOTF2_Difficulty_Fix.exe`.

---

## Safety rules for future changes

1. **Never write saves while the game is running** (players must quit fully). Document Steam Cloud races.  
2. **Always backup** before any replace (`patch.make_backup`).  
3. **Verify** re-parse + CRC + difficulty string before overwriting.  
4. Do **not** reintroduce 42-byte chunk meta or “search-only” zlib writers without size fields matching the stream.  
5. Prefer **surgical** recompress over full-file rewrite.  
6. When testing, prefer dry-run / copies under a throwaway folder — never assume the user’s live slot is disposable.  
7. Keep player-facing README non-technical; put format detail **here**.

---

## Quick map of the code

```text
app.py                      Tk GUI, layout, confirm dialogs
lotf2_difficulty/
  save_format.py            Chunk parse / surgical rebuild / CRC
  properties.py             PlayerName, level, DifficultyMode R/W
  slots.py                  Discover SaveNN + b1/b2, table rows
  patch.py                  Backup + apply to slot paths
  cli.py                    Optional terminal UI (same engine)
build_exe.bat               PyInstaller one-file windowed build
```

### Manual format experiment (Python)

```python
from pathlib import Path
from lotf2_difficulty.save_format import parse_save, payload_from_chunks
from lotf2_difficulty.properties import get_difficulty, get_player_name, get_player_level

data = Path(r"%LOCALAPPDATA%\LOTF2\Saved\SaveGames\Save03.sav").expanduser().read_bytes()
# expanduser won't expand %LOCALAPPDATA% — use os.environ in real scripts
header, chunks, trailer = parse_save(data)
payload = payload_from_chunks(chunks)
print(get_player_name(payload), get_player_level(payload), get_difficulty(payload))
```

---

## Timeline of the original incident (condensed)

1. Player: Veteran character (**Ribs**, ~70) showed as Normal; wanted a fix; had installed `uesave` (unusable on raw LOTF files).  
2. Investigation: zlib multi-chunk container; `DifficultyMode` missing on the active slot; other slots still had `EDifficultyMode::Veteran` as a template.  
3. First patch: insert enum + full recompress with **wrong meta length** → slot vanished from load list.  
4. Restore from pre-patch backups; **surgical** 41-byte meta rewrite → character returned as Veteran.  
5. GUI packaging for non-CLI users; fix import corruption; pin Apply button; document for players + this file for devs.

---

## License / affiliation

MIT. Unofficial. Not affiliated with CI Games or HEXWORKS. Save editing can destroy slots if done carelessly — backups are mandatory, not optional.
