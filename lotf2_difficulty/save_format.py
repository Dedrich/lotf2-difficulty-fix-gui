"""LOTF2 save container: GVAS header + multi-chunk zlib + CRC32 trailer.

Stock tools like uesave cannot read these files because the game wraps the
property tree in a custom compressed body. Chunk meta is exactly 41 bytes.
"""

from __future__ import annotations

import re
import struct
import zlib
from typing import Any

CHUNK_HDR = bytes.fromhex("c1832a9e22222222")
UNCOMP_CHUNK = 128 * 1024
ZLIB_SIGS = (b"\x78\x9c", b"\x78\xda", b"\x78\x01", b"\x78\x5e")
CLASS_RE = re.compile(rb"/Script/LOTF2\.[A-Za-z0-9_]+\x00")


def build_chunk_meta(comp_size: int, uncomp_size: int) -> bytes:
    """Build the 41-byte per-chunk meta block LOTF expects (no trailing null)."""
    meta = b""
    meta += struct.pack("<H", 0)
    meta += struct.pack("<I", 2)
    meta += struct.pack("<H", 0)
    meta += struct.pack("<B", 3)
    pair = struct.pack("<Q", comp_size) + struct.pack("<Q", uncomp_size)
    meta += pair + pair
    if len(meta) != 41:
        raise ValueError(f"chunk meta must be 41 bytes, got {len(meta)}")
    return meta


def compress_chunk(raw: bytes, level: int = 6) -> bytes:
    """Compress one 128KiB (or smaller) payload block.

    Level 6 matches the common in-game zlib header ``78 9c``.
    """
    return zlib.compress(raw, level)


def parse_save(data: bytes) -> tuple[bytes, list[dict[str, Any]], bytes]:
    """Parse a ``.sav`` file into header, chunks, and trailer.

    Returns:
        header: bytes through the save class FString (inclusive)
        chunks: list of dicts with keys meta, comp, raw
        trailer: usually 4-byte CRC32 of everything before it
    """
    m = CLASS_RE.search(data)
    if not m:
        raise ValueError("Not a LOTF2 save (missing /Script/LOTF2.* class name)")
    ce = m.end()
    if ce + 4 > len(data):
        raise ValueError("Truncated save (no body size field)")
    tot = struct.unpack_from("<I", data, ce)[0]
    body_start = ce + 4
    body_end = body_start + tot
    if body_end > len(data):
        raise ValueError("Truncated save (body size exceeds file)")
    body = data[body_start:body_end]
    header = data[:ce]
    trailer = data[body_end:]

    chunks: list[dict[str, Any]] = []
    pos = 0
    while pos < len(body):
        if body[pos : pos + 8] != CHUNK_HDR:
            raise ValueError(f"Bad chunk header at body offset {pos}")
        pos += 8
        z = -1
        for sig in ZLIB_SIGS:
            j = body.find(sig, pos, pos + 200)
            if j >= 0 and (z < 0 or j < z):
                z = j
        if z < 0:
            raise ValueError(f"Missing zlib stream near body offset {pos}")
        meta = body[pos:z]
        pos = z
        d = zlib.decompressobj()
        raw = d.decompress(body[pos:])
        used = len(body[pos:]) - len(d.unused_data)
        if used <= 0:
            raise ValueError("Empty zlib stream in chunk")
        chunks.append(
            {
                "meta": meta,
                "comp": body[pos : pos + used],
                "raw": raw,
            }
        )
        pos += used

    if not chunks:
        raise ValueError("Save has no compressed chunks")
    return header, chunks, trailer


def payload_from_chunks(chunks: list[dict[str, Any]]) -> bytes:
    return b"".join(c["raw"] for c in chunks)


def surgical_rebuild(
    header: bytes,
    old_chunks: list[dict[str, Any]],
    new_payload: bytes,
    *,
    zlib_level: int = 6,
) -> bytes:
    """Rebuild a save, keeping original compressed chunks until the first change.

    Only the trailing 128KiB blocks that differ are recompressed. This minimizes
    risk versus rewriting the entire multi-megabyte body.
    """
    new_raws = [
        new_payload[i : i + UNCOMP_CHUNK]
        for i in range(0, len(new_payload), UNCOMP_CHUNK)
    ]
    new_chunks: list[dict[str, Any]] = []
    for i, raw in enumerate(new_raws):
        if i < len(old_chunks) and old_chunks[i]["raw"] == raw:
            new_chunks.append(old_chunks[i])
            continue
        for j in range(i, len(new_raws)):
            rawj = new_raws[j]
            comp = compress_chunk(rawj, zlib_level)
            new_chunks.append(
                {
                    "meta": build_chunk_meta(len(comp), len(rawj)),
                    "comp": comp,
                    "raw": rawj,
                }
            )
        break

    body = b"".join(CHUNK_HDR + c["meta"] + c["comp"] for c in new_chunks)
    out = header + struct.pack("<I", len(body)) + body
    out += struct.pack("<I", zlib.crc32(out) & 0xFFFFFFFF)
    return out


def verify_save_bytes(data: bytes) -> bytes:
    """Re-parse a built save and return its payload; raises on structural errors."""
    _header, chunks, trailer = parse_save(data)
    if len(trailer) == 4:
        expected = struct.unpack("<I", trailer)[0]
        actual = zlib.crc32(data[:-4]) & 0xFFFFFFFF
        if expected != actual:
            raise ValueError(
                f"CRC mismatch: trailer={expected:#010x} computed={actual:#010x}"
            )
    for i, c in enumerate(chunks):
        if len(c["meta"]) != 41:
            raise ValueError(f"Chunk {i} has meta length {len(c['meta'])}, expected 41")
    return payload_from_chunks(chunks)
