"""Pack-only zip extractor (plan 218 §3.7).

A pack archive is data, never a filesystem operation: entries are read into a
memory mapping and never written through ``extractall``. The allowlist is
exactly ``manifest.json`` plus ``items/**.json``; traversal, symlinks, special
files, encryption, duplicates, and decompression bombs are typed refusals.
"""

from __future__ import annotations

import io
import stat
import zipfile

from app.core.seed_pack.errors import (
    ARCHIVE_DUPLICATE_ENTRY,
    ARCHIVE_ENCRYPTED,
    ARCHIVE_INVALID,
    ARCHIVE_PATH_TRAVERSAL,
    ARCHIVE_TOO_LARGE,
    ARCHIVE_UNSUPPORTED_ENTRY,
    SeedPackError,
)
from app.core.seed_pack.manifest import (
    MAX_ITEM_FILE_BYTES,
    MAX_MANIFEST_BYTES,
    MAX_PACK_BYTES,
)

MAX_ARCHIVE_ENTRIES = 512
MAX_COMPRESSION_RATIO = 100


def _check_entry_name(name: str) -> None:
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or "\x00" in name
        or (len(name) > 1 and name[1] == ":")
    ):
        raise SeedPackError(ARCHIVE_PATH_TRAVERSAL, name[:200])
    parts = name.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise SeedPackError(ARCHIVE_PATH_TRAVERSAL, name[:200])


def _is_allowed(name: str) -> bool:
    return name == "manifest.json" or (name.startswith("items/") and name.endswith(".json"))


def _is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return stat.S_ISLNK(mode)


def extract_pack_archive(data: bytes) -> dict[str, bytes]:
    """Read one pack zip into ``relative path -> bytes`` with every guard."""
    if len(data) > MAX_PACK_BYTES:
        raise SeedPackError(ARCHIVE_TOO_LARGE, "archive exceeds 64 MB")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise SeedPackError(ARCHIVE_INVALID, str(exc)) from exc

    result: dict[str, bytes] = {}
    total = 0
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ARCHIVE_ENTRIES:
            raise SeedPackError(ARCHIVE_TOO_LARGE, f"archive exceeds {MAX_ARCHIVE_ENTRIES} entries")
        for info in infos:
            if info.is_dir():
                continue
            if info.flag_bits & 0x1:
                raise SeedPackError(ARCHIVE_ENCRYPTED, info.filename[:200])
            if _is_symlink(info):
                raise SeedPackError(ARCHIVE_UNSUPPORTED_ENTRY, info.filename[:200])
            name = info.filename
            _check_entry_name(name)
            if not _is_allowed(name):
                raise SeedPackError(ARCHIVE_UNSUPPORTED_ENTRY, name[:200])
            if name in result:
                raise SeedPackError(ARCHIVE_DUPLICATE_ENTRY, name[:200])
            limit = MAX_MANIFEST_BYTES if name == "manifest.json" else MAX_ITEM_FILE_BYTES
            if info.file_size > limit:
                raise SeedPackError(ARCHIVE_TOO_LARGE, f"{name[:200]} exceeds its byte cap")
            if (
                info.compress_size > 0
                and info.file_size > info.compress_size * MAX_COMPRESSION_RATIO
            ):
                raise SeedPackError(ARCHIVE_TOO_LARGE, f"{name[:200]} has a suspicious ratio")
            with archive.open(info) as handle:
                payload = handle.read(limit + 1)
            if len(payload) > limit:
                raise SeedPackError(ARCHIVE_TOO_LARGE, f"{name[:200]} exceeds its byte cap")
            total += len(payload)
            if total > MAX_PACK_BYTES:
                raise SeedPackError(ARCHIVE_TOO_LARGE, "archive exceeds 64 MB uncompressed")
            result[name] = payload

    if "manifest.json" not in result:
        raise SeedPackError(ARCHIVE_UNSUPPORTED_ENTRY, "manifest.json is missing")
    return result


def build_pack_archive(files: dict[str, bytes]) -> bytes:
    """Deterministic pack zip for export (sorted entries, fixed timestamp)."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


__all__ = ["build_pack_archive", "extract_pack_archive"]
