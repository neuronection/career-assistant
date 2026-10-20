"""Kernel-isolation wall for the T2 child (plan 37 Phase 5)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.extensions import isolation


@pytest.mark.skipif(not isolation.available(), reason="bubblewrap unavailable")
def test_wrapper_contains_kernel_boundary() -> None:
    argv = isolation.wrap_child_command(
        interpreter=[sys.executable],
        child_path=Path("/tmp/x.py"),
        content_dir=Path("/tmp"),
        child_args=["--content-dir", "/tmp"],
    )
    assert argv[0].endswith("bwrap")
    assert "--unshare-all" in argv
    assert "--die-with-parent" in argv
    assert "--clearenv" in argv
    assert "--ro-bind" in argv
    assert "/ext" in argv
    # The real content path is rewritten to the sandbox mount.
    assert argv[argv.index("--content-dir") + 1] == "/ext"


@pytest.mark.skipif(not isolation.available(), reason="bubblewrap unavailable")
def test_child_cannot_read_host_fs_or_open_sockets(tmp_path: Path) -> None:
    child = tmp_path / "child.py"
    child.write_text(
        "import socket\n"
        "try:\n"
        "    open('/etc/passwd', 'rb').read(1)\n"
        "    print('READ')\n"
        "except Exception:\n"
        "    print('DENIED-FS')\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 80), timeout=1)\n"
        "    print('NET')\n"
        "except Exception:\n"
        "    print('DENIED-NET')\n",
        encoding="utf-8",
    )
    argv = isolation.wrap_child_command(
        interpreter=[sys.executable],
        child_path=child,
        content_dir=tmp_path,
        child_args=[],
    )
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "DENIED-FS" in result.stdout
    assert "DENIED-NET" in result.stdout


def test_escape_matrix_is_the_contract() -> None:
    """The fixture wall (sandbox-isolation.fixtures.json, plan 39) is the
    normative probe set — every backend is measured against exactly these
    cases, and the kernel probes run above are matrix cases."""
    cases = isolation.escape_matrix(
        Path(__file__).resolve().parents[2] / "contracts"
    )
    groups = {case["group"] for case in cases}
    for required in (
        "fs-read-outside",
        "fs-write-outside",
        "net-connect",
        "net-dns",
        "proc-spawn",
        "env-read",
        "watchdog-kill",
        "orphan-after-parent-death",
        "memory-bomb",
        "cpu-loop",
    ):
        assert required in groups, f"isolation matrix lost the {required!r} group"
    by_name = {case["name"]: case for case in cases}
    assert by_name["fs-read-etc-passwd"]["expect"]["kernel"] == "denied"
    assert by_name["net-connect-arbitrary"]["expect"]["kernel"] == "denied"
    # process grade must DISCLAIM what it cannot deny (disclosure law).
    assert by_name["net-connect-arbitrary"]["expect"]["process"] == "disclosed"


def test_posture_never_overstates_the_boundary() -> None:
    assert isolation.posture() == ("kernel" if isolation.available() else "none")


def test_process_grade_scrubs_the_environment(tmp_path: Path) -> None:
    """Grade `process` denies host-env inheritance (sandbox-isolation.md
    §4.2) — secrets travel in env on real machines."""
    options = isolation.process_spawn_options(workdir=tmp_path, memory_mb=256)
    assert options["cwd"] == str(tmp_path)
    assert set(options["env"]) <= set(isolation.PROCESS_ENV_ALLOWLIST)
    assert options["close_fds"] is True
    assert options["start_new_session"] is True
