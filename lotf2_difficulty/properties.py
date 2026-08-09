"""Read/write common LOTF2 save properties from the decompressed payload."""

from __future__ import annotations

import struct
from typing import Optional


def read_int_property(payload: bytes, name: str) -> Optional[int]:
    """Read the first IntProperty with the given name.

    Layout: ``Name\\0`` + ``\\x0c\\0\\0\\0IntProperty\\0`` + size u64 + tag u8 + i32
    """
    key = name.encode("ascii") + b"\x00\x0c\x00\x00\x00IntProperty\x00"
    i = payload.find(key)
    if i < 0:
        return None
    off = i + len(key) + 8  # skip size u64
    off += 1  # tag byte
    if off + 4 > len(payload):
        return None
    return struct.unpack_from("<i", payload, off)[0]


def read_str_property(payload: bytes, name: str) -> Optional[str]:
    """Read the first StrProperty with the given name.

    Layout: ``Name\\0`` + type FString + size u64 + tag u8 + FString value.
    """
    key = name.encode("ascii") + b"\x00\x0c\x00\x00\x00StrProperty\x00"
    i = payload.find(key)
    if i < 0:
        return None
    off = i + len(key)
    if off + 13 > len(payload):
        return None
    # size u64 (FString value bytes only), tag byte, then FString
    _size = struct.unpack_from("<Q", payload, off)[0]
    off += 8
    off += 1  # tag
    n = struct.unpack_from("<I", payload, off)[0]
    off += 4
    if n <= 0:
        return ""
    if off + n > len(payload):
        return None
    raw = payload[off : off + n]
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


def get_difficulty(payload: bytes) -> Optional[str]:
    """Return e.g. ``EDifficultyMode::Veteran``, or None if missing (game = Legacy)."""
    i = payload.find(b"EDifficultyMode::")
    if i < 0:
        return None
    end = payload.find(b"\x00", i)
    if end < 0:
        return None
    return payload[i:end].decode("ascii", "replace")


def difficulty_label(payload: bytes) -> str:
    raw = get_difficulty(payload)
    if raw is None:
        return "Legacy / Normal (flag missing)"
    if raw.startswith("EDifficultyMode::"):
        return raw.split("::", 1)[1]
    return raw


def get_player_name(payload: bytes) -> str:
    name = read_str_property(payload, "PlayerName")
    if name:
        return name
    # Fallbacks some slots use
    for alt in ("CoopCampaignHostsName", "CharacterName"):
        name = read_str_property(payload, alt)
        if name:
            return name
    return "(unknown)"


def get_player_level(payload: bytes) -> Optional[int]:
    return read_int_property(payload, "PlayerLevel")


def make_difficulty_prop(mode: str = "Veteran") -> bytes:
    """Serialize a DifficultyMode EnumProperty set to EDifficultyMode::<mode>."""
    enum_type = b"EDifficultyMode"
    enum_val = f"EDifficultyMode::{mode}".encode("ascii")
    value_size = 4 + len(enum_val) + 1
    prop = b""
    prop += struct.pack("<I", len(b"DifficultyMode") + 1) + b"DifficultyMode\x00"
    prop += struct.pack("<I", len(b"EnumProperty") + 1) + b"EnumProperty\x00"
    prop += struct.pack("<Q", value_size)
    prop += struct.pack("<I", len(enum_type) + 1) + enum_type + b"\x00"
    prop += b"\x00"
    prop += struct.pack("<I", len(enum_val) + 1) + enum_val + b"\x00"
    return prop


def patch_payload_difficulty(payload: bytes, mode: str) -> tuple[bytes, str]:
    """Set DifficultyMode on a decompressed character payload.

    Returns (new_payload, action) where action is:
      - already_set
      - replaced_<old>
      - inserted
    """
    target = f"EDifficultyMode::{mode}"
    current = get_difficulty(payload)
    if current == target:
        return payload, "already_set"

    if current is not None:
        old = current.encode("ascii") + b"\x00"
        new_val = target.encode("ascii") + b"\x00"
        di = payload.find(b"DifficultyMode")
        if di < 0:
            raise ValueError("Found enum value but no DifficultyMode property name")
        vi = payload.find(old, di)
        if vi < 0:
            raise ValueError(f"Could not locate difficulty value {current!r}")
        old_len = struct.unpack_from("<I", payload, vi - 4)[0]
        if old_len != len(old):
            raise ValueError("Enum length prefix mismatch")
        new_block = struct.pack("<I", len(new_val)) + new_val
        old_block = struct.pack("<I", old_len) + old
        ep = payload.find(b"EnumProperty\x00", di)
        if ep < 0:
            raise ValueError("EnumProperty tag not found")
        size_off = ep + len(b"EnumProperty\x00")
        new_size = 4 + len(new_val)
        payload2 = payload[:size_off] + struct.pack("<Q", new_size) + payload[size_off + 8 :]
        vi2 = payload2.find(old, di)
        if vi2 < 0:
            raise ValueError("Lost enum value after size rewrite")
        payload2 = (
            payload2[: vi2 - 4] + new_block + payload2[vi2 - 4 + len(old_block) :]
        )
        return payload2, f"replaced_{current}"

    # Missing flag → game treats as Legacy/Normal. Insert before LevelName.
    ci = payload.find(b"CoopCampaignHostsName")
    if ci < 0:
        raise ValueError(
            "CoopCampaignHostsName not found — this may not be a character save"
        )
    li = payload.find(b"LevelName", ci)
    if li < 0:
        raise ValueError("LevelName not found after CoopCampaignHostsName")
    insert_at = li - 4
    prop = make_difficulty_prop(mode)
    return payload[:insert_at] + prop + payload[insert_at:], "inserted"
