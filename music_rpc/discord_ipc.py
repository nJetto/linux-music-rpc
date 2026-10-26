"""Minimal Discord IPC (Rich Presence) client.

No third-party packages are required. The protocol is documented at
https://discord.com/developers/docs/topics/rpc — a Unix socket, an 8-byte
header and JSON payloads.

The code intentionally supports the socket locations used by the official
Discord client, Flatpak, Snap, Vesktop and arRPC.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import stat
import struct
import uuid
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

LOGGER = logging.getLogger(__name__)

OP_HANDSHAKE = 0
OP_FRAME = 1
OP_CLOSE = 2
OP_PING = 3
OP_PONG = 4

MAX_FRAME_SIZE = 8 * 1024 * 1024

# Subdirectories (relative to XDG_RUNTIME_DIR or /tmp) used by different
# Discord packages and alternative clients.
_SOCKET_SUBDIRS = (
    "",
    "snap.discord",
    "app/com.discordapp.Discord",
    "app/com.discordapp.DiscordCanary",
    "app/com.discordapp.DiscordPTB",
    "app/dev.vencord.Vesktop",
    "vesktop",
    "vencord",
)


class DiscordIPCError(RuntimeError):
    """A Discord IPC error (connection, protocol or RPC error)."""


class DiscordNotFound(DiscordIPCError):
    """No reachable Discord IPC socket was found."""


def _unique_paths(paths: Iterable[Path]) -> List[Path]:
    result: List[Path] = []
    seen = set()
    for path in paths:
        try:
            key = os.path.realpath(str(path))
        except OSError:
            key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def discover_sockets(custom_path: Optional[str] = None) -> List[Path]:
    """Return candidate Discord IPC socket paths in priority order.

    Existing Unix sockets are returned even if Discord isn't listening; the
    caller tries each one. A custom path disables automatic discovery.
    """
    if custom_path:
        return [Path(custom_path).expanduser()]

    bases: List[Path] = []
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        bases.append(Path(runtime).expanduser())
    else:
        run_user = Path(f"/run/user/{os.getuid()}")
        if run_user.is_dir():
            bases.append(run_user)
    for variable in ("TMPDIR", "TMP", "TEMP"):
        value = os.environ.get(variable)
        if value:
            bases.append(Path(value).expanduser())
    bases.append(Path("/tmp"))

    home = Path.home()
    bases.extend(
        [
            home / ".config" / "discord",
            home / ".var" / "app" / "com.discordapp.Discord" / "config" / "discord",
        ]
    )
    bases = _unique_paths(bases)

    candidates: List[Path] = []
    for base in bases:
        for subdir in _SOCKET_SUBDIRS:
            directory = base / subdir if subdir else base
            if not directory.is_dir():
                continue
            for index in range(10):
                path = directory / f"discord-ipc-{index}"
                try:
                    mode = os.stat(str(path)).st_mode
                except OSError:
                    continue
                if stat.S_ISSOCK(mode):
                    candidates.append(path)
    return _unique_paths(candidates)


class DiscordIPC:
    """Blocking Discord RPC client for SET_ACTIVITY."""

    def __init__(
        self,
        client_id: str,
        ipc_path: Optional[str] = None,
        timeout: float = 5.0,
    ):
        self.client_id = str(client_id)
        self.ipc_path = ipc_path
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.connected = False
        self.path: Optional[Path] = None

    def is_connected(self) -> bool:
        return self.connected and self.sock is not None

    def connect(self) -> None:
        self.close(send_close=False)
        paths = discover_sockets(self.ipc_path)
        if not paths:
            raise DiscordNotFound(
                "Discord IPC socket not found. Is the Discord desktop client "
                "running? Flatpak, Snap and Vesktop sockets are supported."
            )

        errors: List[str] = []
        for path in paths:
            sock: Optional[socket.socket] = None
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                sock.settimeout(self.timeout)
                sock.connect(str(path))
                self.sock = sock
                self.connected = False
                self._handshake()
                self.connected = True
                self.path = path
                LOGGER.info("Connected to Discord IPC at %s", path)
                return
            except (OSError, DiscordIPCError) as exc:
                errors.append(f"{path}: {exc}")
                if sock is not None:
                    try:
                        sock.close()
                    except OSError:
                        pass
                self.sock = None
                self.connected = False
                message = str(exc).lower()
                if "invalid client id" in message or "invalid clientid" in message:
                    # This error is global, not specific to this socket.
                    raise

        detail = "; ".join(errors[:3]) if errors else "no candidates"
        raise DiscordNotFound(
            "Could not connect to Discord IPC. Tried "
            f"{len(paths)} socket(s): {detail}"
        )

    def _handshake(self) -> None:
        self._send_frame(OP_HANDSHAKE, {"v": 1, "client_id": self.client_id})
        for _ in range(5):
            opcode, data = self._read_frame()
            if opcode == OP_PING:
                self._send_frame(OP_PONG, data)
                continue
            if opcode == OP_CLOSE:
                raise DiscordIPCError("Discord closed the connection during handshake")
            if not isinstance(data, dict):
                raise DiscordIPCError("Unexpected handshake response")
            if data.get("evt") == "ERROR" or (
                "code" in data and "message" in data
            ):
                code = data.get("code")
                message = data.get("message")
                error_data = data.get("data")
                if isinstance(error_data, dict):
                    code = error_data.get("code", code)
                    message = error_data.get("message", message)
                raise DiscordIPCError(f"Discord error {code}: {message}")
            if data.get("evt") == "READY":
                return
        raise DiscordIPCError("Discord did not send a READY handshake")

    def set_activity(self, activity: Optional[dict]) -> Optional[dict]:
        """Set (or clear, when activity is None) Rich Presence."""
        if not self.is_connected():
            self.connect()

        nonce = uuid.uuid4().hex
        payload = {
            "cmd": "SET_ACTIVITY",
            "args": {"pid": os.getpid(), "activity": activity},
            "nonce": nonce,
        }
        try:
            self._send_frame(OP_FRAME, payload)
            for _ in range(20):
                opcode, data = self._read_frame()
                if opcode == OP_PING:
                    self._send_frame(OP_PONG, data)
                    continue
                if opcode == OP_CLOSE:
                    raise DiscordIPCError(
                        "Discord closed the connection while setting activity"
                    )
                if not isinstance(data, dict):
                    continue

                is_response = data.get("nonce") == nonce
                if data.get("evt") == "ERROR" and (
                    is_response or data.get("nonce") is None
                ):
                    code = data.get("code")
                    message = data.get("message")
                    error_data = data.get("data")
                    if isinstance(error_data, dict):
                        code = error_data.get("code", code)
                        message = error_data.get("message", message)
                    raise DiscordIPCError(f"Discord error {code}: {message}")
                if is_response:
                    return data
            raise DiscordIPCError(
                "Timed out waiting for Discord to acknowledge SET_ACTIVITY"
            )
        except (OSError, DiscordIPCError) as exc:
            self.close(send_close=False)
            if isinstance(exc, DiscordIPCError):
                raise
            raise DiscordIPCError(f"Discord IPC write/read failed: {exc}") from exc

    def clear(self) -> Optional[dict]:
        return self.set_activity(None)

    def _send_frame(self, opcode: int, payload: dict) -> None:
        if self.sock is None:
            raise DiscordIPCError("Discord IPC is not connected")
        encoded = json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if len(encoded) > MAX_FRAME_SIZE:
            raise DiscordIPCError("Discord IPC payload is too large")
        header = struct.pack("<II", opcode, len(encoded))
        self.sock.sendall(header + encoded)

    def _recv_exact(self, size: int) -> bytes:
        if self.sock is None:
            raise DiscordIPCError("Discord IPC is not connected")
        chunks: List[bytes] = []
        remaining = size
        while remaining > 0:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise DiscordIPCError("Discord closed the IPC connection")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_frame(self) -> tuple:
        header = self._recv_exact(8)
        opcode, length = struct.unpack("<II", header)
        if length > MAX_FRAME_SIZE:
            raise DiscordIPCError(f"Discord IPC frame is too large ({length} bytes)")
        raw = self._recv_exact(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DiscordIPCError(f"Invalid JSON from Discord IPC: {exc}") from exc
        return opcode, data

    def close(self, send_close: bool = True) -> None:
        sock = self.sock
        self.sock = None
        was_connected = self.connected
        self.connected = False
        if sock is None:
            return
        if send_close and was_connected:
            try:
                payload = json.dumps(
                    {"v": 1, "client_id": self.client_id},
                    separators=(",", ":"),
                ).encode("utf-8")
                sock.sendall(struct.pack("<II", OP_CLOSE, len(payload)) + payload)
            except OSError:
                pass
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass
