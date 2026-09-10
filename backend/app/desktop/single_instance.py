"""Single-instance lock: lockfile + Unix-socket handshake in DATA_DIR.

A second launch detects the first via the bound socket, sends a `focus`
ping over the handshake and exits — the running instance raises its
window. A stale lock (dead PID, unbindable socket) is recovered on boot.
"""

import json
import os
import socket
import threading
from pathlib import Path
from typing import Callable, Optional

LOCK_FILE = "app.lock"
SOCKET_FILE = "app.sock"
FOCUS_COMMAND = b"focus\n"


class SingleInstance:
    """First instance: binds the handshake socket in a listener thread."""

    def __init__(self, data_dir: Path, on_focus_request: Callable[[], None]):
        self.data_dir = data_dir
        self.on_focus_request = on_focus_request
        self._socket: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stopping = threading.Event()

    @property
    def lock_path(self) -> Path:
        return self.data_dir / LOCK_FILE

    @property
    def socket_path(self) -> Path:
        return self.data_dir / SOCKET_FILE

    def acquire(self) -> bool:
        """Claim the lock; False when another live instance owns it."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self._another_instance_alive():
            return False
        self._recover_stale_lock()
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            server.bind(str(self.socket_path))
        except OSError:
            server.close()
            return False
        server.listen(2)
        server.settimeout(0.5)
        self._socket = server
        self.lock_path.write_text(
            json.dumps({"pid": os.getpid(), "socket": str(self.socket_path)}),
            encoding="utf-8",
        )
        self._thread = threading.Thread(
            target=self._listen, name="single-instance", daemon=True
        )
        self._thread.start()
        return True

    def release(self) -> None:
        """Drop the socket + lockfile (graceful quit)."""
        self._stopping.set()
        if self._socket is not None:
            try:
                self._socket.close()
            except OSError:
                pass
            self._socket = None
        if self._thread is not None:
            self._thread.join(timeout=2)
        for path in (self.socket_path, self.lock_path):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _another_instance_alive(self) -> bool:
        """Handshake probe: a connectable socket means the first is live."""
        if not self.socket_path.exists():
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(1.0)
                client.connect(str(self.socket_path))
                client.sendall(FOCUS_COMMAND)
            return True
        except OSError:
            return False

    def _recover_stale_lock(self) -> None:
        """Dead PID or dead socket ⇒ the previous owner died hard."""
        try:
            raw = json.loads(self.lock_path.read_text(encoding="utf-8"))
            pid = int(raw.get("pid", 0))
        except (OSError, ValueError):
            pid = 0
        if pid and _pid_alive(pid):
            # Live PID but no responsive socket — treat as stale anyway;
            # the socket bind below is the real arbiter.
            pass
        try:
            self.socket_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _listen(self) -> None:
        assert self._socket is not None
        while not self._stopping.is_set():
            try:
                conn, _ = self._socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                try:
                    if conn.recv(64):
                        self.on_focus_request()
                except OSError:
                    continue


def focus_existing_instance(data_dir: Path) -> bool:
    """Second-launch path: ping the running instance to focus; True when a
    live instance answered."""
    socket_path = data_dir / SOCKET_FILE
    if not socket_path.exists():
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1.0)
            client.connect(str(socket_path))
            client.sendall(FOCUS_COMMAND)
        return True
    except OSError:
        return False


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
