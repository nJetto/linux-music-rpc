from __future__ import annotations

import json
import os
import socket
import struct
import tempfile
import threading
import unittest
from pathlib import Path

from music_rpc.discord_ipc import (
    OP_CLOSE,
    OP_FRAME,
    OP_HANDSHAKE,
    OP_PING,
    OP_PONG,
    DiscordIPC,
    DiscordIPCError,
    discover_sockets,
)


def recv_exact(sock: socket.socket, size: int) -> bytes:
    chunks = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise ConnectionError("closed")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(sock: socket.socket):
    header = recv_exact(sock, 8)
    opcode, length = struct.unpack("<II", header)
    return opcode, json.loads(recv_exact(sock, length).decode("utf-8"))


def send_frame(sock: socket.socket, opcode: int, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    sock.sendall(struct.pack("<II", opcode, len(data)) + data)


class FakeDiscord(threading.Thread):
    def __init__(self, path: str, invalid_client: bool = False):
        super().__init__(daemon=True)
        self.path = path
        self.invalid_client = invalid_client
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen(1)
        self.received_activity = None
        self.received_clear = None
        self.received_close = None
        self.error = None
        self.ready = threading.Event()

    def run(self):
        try:
            conn, _ = self.server.accept()
            conn.settimeout(5)
            with conn:
                opcode, handshake = read_frame(conn)
                assert opcode == OP_HANDSHAKE
                if self.invalid_client:
                    send_frame(
                        conn,
                        OP_FRAME,
                        {
                            "cmd": "DISPATCH",
                            "evt": "ERROR",
                            "data": {
                                "code": 4000,
                                "message": "Invalid Client ID",
                            },
                        },
                    )
                    return
                send_frame(
                    conn,
                    OP_FRAME,
                    {
                        "cmd": "DISPATCH",
                        "evt": "READY",
                        "data": {"v": 1, "user": {}},
                    },
                )
                self.ready.set()

                opcode, activity = read_frame(conn)
                assert opcode == OP_FRAME
                self.received_activity = activity
                send_frame(
                    conn,
                    OP_FRAME,
                    {
                        "cmd": "SET_ACTIVITY",
                        "data": {},
                        "evt": None,
                        "nonce": activity["nonce"],
                    },
                )

                opcode, clear = read_frame(conn)
                assert opcode == OP_FRAME
                self.received_clear = clear
                send_frame(
                    conn,
                    OP_FRAME,
                    {
                        "cmd": "SET_ACTIVITY",
                        "data": None,
                        "evt": None,
                        "nonce": clear["nonce"],
                    },
                )

                opcode, close = read_frame(conn)
                self.received_close = (opcode, close)
        except Exception as exc:  # pragma: no cover - reported by assertions
            self.error = exc
            self.ready.set()
        finally:
            self.server.close()

    def stop(self):
        try:
            self.server.close()
        except OSError:
            pass


class DiscordIPCTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "discord-ipc-0"
        self.server = FakeDiscord(str(self.path))
        self.server.start()

    def tearDown(self):
        self.server.stop()
        self.temp.cleanup()

    def test_connect_and_set_activity(self):
        ipc = DiscordIPC("123456789012345678", str(self.path), timeout=3.0)
        ipc.connect()
        self.assertTrue(ipc.is_connected())
        self.assertEqual(str(ipc.path), str(self.path))
        activity = {
            "type": 2,
            "details": "Song",
            "state": "Artist",
            "instance": False,
        }
        ipc.set_activity(activity)
        ipc.clear()
        ipc.close()
        self.server.join(timeout=3.0)

        self.assertIsNone(self.server.error)
        self.assertEqual(self.server.received_activity["cmd"], "SET_ACTIVITY")
        self.assertEqual(
            self.server.received_activity["args"]["activity"]["type"], 2
        )
        self.assertEqual(
            self.server.received_activity["args"]["activity"]["details"], "Song"
        )
        self.assertIsNone(self.server.received_clear["args"]["activity"])
        self.assertEqual(self.server.received_close[0], OP_CLOSE)

    def test_invalid_client_id_is_not_swallowed(self):
        self.server.stop()
        try:
            os.unlink(self.path)
        except OSError:
            pass
        self.server = FakeDiscord(str(self.path), invalid_client=True)
        self.server.start()
        ipc = DiscordIPC("bad", str(self.path), timeout=3.0)
        with self.assertRaises(DiscordIPCError) as context:
            ipc.connect()
        self.assertIn("Invalid Client ID", str(context.exception))

    def test_custom_socket_discovery(self):
        paths = discover_sockets(str(self.path))
        self.assertEqual(paths, [self.path])


class AutomaticDiscoveryTests(unittest.TestCase):
    def test_discover_existing_socket(self):
        with tempfile.TemporaryDirectory() as temp:
            runtime = Path(temp) / "runtime"
            runtime.mkdir()
            path = runtime / "discord-ipc-0"
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                server.bind(str(path))
                server.listen(1)
                old_runtime = os.environ.get("XDG_RUNTIME_DIR")
                old_tmpdir = os.environ.get("TMPDIR")
                os.environ["XDG_RUNTIME_DIR"] = str(runtime)
                os.environ["TMPDIR"] = str(runtime)
                try:
                    found = discover_sockets()
                finally:
                    if old_runtime is None:
                        os.environ.pop("XDG_RUNTIME_DIR", None)
                    else:
                        os.environ["XDG_RUNTIME_DIR"] = old_runtime
                    if old_tmpdir is None:
                        os.environ.pop("TMPDIR", None)
                    else:
                        os.environ["TMPDIR"] = old_tmpdir
                self.assertIn(path, found)
            finally:
                server.close()


if __name__ == "__main__":
    unittest.main()
