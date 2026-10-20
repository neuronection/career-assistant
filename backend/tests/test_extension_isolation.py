"""Kernel-isolation wall for the T2 child (plan 37 Phase 5)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from app.extensions.runtime.sandbox import isolation


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
