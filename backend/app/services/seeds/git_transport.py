"""Public git transport for seed providers (plan 218 §3.7).

HTTPS only, anonymous, pinned ref, shallow, no hooks and no inherited
credential helpers. A checkout is a temporary directory discarded after the
pack's ``manifest.json`` + ``items/**.json`` are read; nothing from the
repository becomes code in the process.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from app.core.seed_pack.errors import (
    GIT_CLONE_FAILED,
    GIT_TIMEOUT,
    GIT_TOO_LARGE,
    GIT_UNAVAILABLE,
    GIT_URI_DENIED,
    MANIFEST_MISSING,
    PATH_DENIED,
    SeedPackError,
)
from app.core.seed_pack.manifest import MAX_PACK_BYTES

GIT_TIMEOUT_SECONDS = 120
GIT_MAX_BYTES = MAX_PACK_BYTES


@dataclass(frozen=True)
class GitPack:
    files: dict[str, bytes]
    commit_sha: str


def git_available() -> bool:
    return shutil.which("git") is not None


def _is_private_literal(host: str) -> bool:
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host.lower() in {"localhost", "localhost.localdomain"}
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    )


def validate_public_git_uri(uri: str) -> str:
    """Reject anything but an anonymous public HTTPS repository URL."""
    parts = urlsplit((uri or "").strip())
    if parts.scheme != "https" or not parts.hostname:
        raise SeedPackError(GIT_URI_DENIED, "git provider URIs must be https")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise SeedPackError(GIT_URI_DENIED, "git URIs must not carry credentials/query/fragment")
    if _is_private_literal(parts.hostname):
        raise SeedPackError(GIT_URI_DENIED, "git URIs must target a public host")
    return parts.geturl()


def validate_subpath(subpath: str) -> str:
    raw = (subpath or "").strip()
    if not raw:
        return ""
    if raw.startswith("/") or "\\" in raw or "\x00" in raw:
        raise SeedPackError(PATH_DENIED, f"subpath is not a relative POSIX path: {subpath!r}")
    value = raw.strip("/")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise SeedPackError(PATH_DENIED, f"subpath traversal is forbidden: {subpath!r}")
    return value


def _validate_ref(ref: str) -> str:
    value = (ref or "").strip()
    if not value or value.startswith("-") or "\x00" in value or "\n" in value:
        raise SeedPackError(GIT_URI_DENIED, "a pinned tag/commit is required")
    return value


def _git_env(home: Path) -> dict[str, str]:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/bin/true",
        "GIT_SSH_COMMAND": "/bin/true",
        "LC_ALL": "C",
    }
    return env


async def _run_git(args: list[str], *, cwd: Path, env: dict[str, str], timeout: float) -> str:
    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise SeedPackError(
            GIT_UNAVAILABLE, "git is not installed; use the official registry mirror"
        ) from exc
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError as exc:
        process.kill()
        await process.wait()
        raise SeedPackError(GIT_TIMEOUT, f"git operation exceeded {timeout:.0f}s") from exc
    if process.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace").strip().splitlines()
        raise SeedPackError(GIT_CLONE_FAILED, detail[-1][:400] if detail else "git exited non-zero")
    return stdout.decode("utf-8", errors="replace").strip()


def read_pack_tree(root: Path, subpath: str) -> dict[str, bytes]:
    base = (root / subpath).resolve() if subpath else root.resolve()
    if base != root.resolve() and root.resolve() not in base.parents:
        raise SeedPackError(PATH_DENIED, subpath)
    if not base.is_dir():
        raise SeedPackError(PATH_DENIED, f"pack subpath does not exist: {subpath!r}")
    files: dict[str, bytes] = {}
    total = 0
    for candidate in sorted(base.rglob("*")):
        if candidate.is_symlink():
            raise SeedPackError(PATH_DENIED, f"symlink in pack: {candidate.name}")
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(base).as_posix()
        if relative != "manifest.json" and not (
            relative.startswith("items/") and relative.endswith(".json")
        ):
            continue
        size = candidate.stat().st_size
        total += size
        if total > GIT_MAX_BYTES:
            raise SeedPackError(GIT_TOO_LARGE, "pack checkout exceeds 64 MB")
        files[relative] = candidate.read_bytes()
    if "manifest.json" not in files:
        raise SeedPackError(MANIFEST_MISSING, f"manifest.json is missing under {subpath or '.'}")
    return files


class GitTransport:
    """Fetch one pack from a pinned public git ref."""

    def __init__(
        self,
        *,
        allow_local: bool = False,
        timeout: float = GIT_TIMEOUT_SECONDS,
        max_bytes: int = GIT_MAX_BYTES,
    ) -> None:
        self.allow_local = allow_local
        self.timeout = timeout
        self.max_bytes = max_bytes

    async def fetch(self, uri: str, ref: str, subpath: str = "") -> GitPack:
        if not git_available():
            raise SeedPackError(
                GIT_UNAVAILABLE, "git is not installed; use the official registry mirror"
            )
        target = uri.strip()
        if not self.allow_local or "://" in target:
            target = validate_public_git_uri(target)
        pinned = _validate_ref(ref)
        pack_subpath = validate_subpath(subpath)

        work = Path(tempfile.mkdtemp(prefix="career-seedpack-"))
        repo = work / "repo"
        try:
            env = _git_env(work / "home")
            (work / "home").mkdir(parents=True, exist_ok=True)
            repo.mkdir()
            await _run_git(["init", "-q"], cwd=repo, env=env, timeout=self.timeout)
            await _run_git(
                ["remote", "add", "origin", "--", target], cwd=repo, env=env, timeout=self.timeout
            )
            await _run_git(
                [
                    "-c",
                    "core.hooksPath=/dev/null",
                    "-c",
                    "submodule.recurse=false",
                    "fetch",
                    "--depth",
                    "1",
                    "--no-tags",
                    "origin",
                    "--",
                    pinned,
                ],
                cwd=repo,
                env=env,
                timeout=self.timeout,
            )
            await _run_git(
                ["-c", "core.hooksPath=/dev/null", "checkout", "-q", "--detach", "FETCH_HEAD"],
                cwd=repo,
                env=env,
                timeout=self.timeout,
            )
            commit_sha = await _run_git(
                ["rev-parse", "HEAD"], cwd=repo, env=env, timeout=self.timeout
            )
            files = read_pack_tree(repo, pack_subpath)
            total = sum(len(data) for data in files.values())
            if total > self.max_bytes:
                raise SeedPackError(GIT_TOO_LARGE, "pack exceeds 64 MB")
            return GitPack(files=files, commit_sha=commit_sha)
        finally:
            shutil.rmtree(work, ignore_errors=True)


__all__ = [
    "GitPack",
    "GitTransport",
    "git_available",
    "read_pack_tree",
    "validate_public_git_uri",
    "validate_subpath",
]
