"""A minimal WebSocket (RFC 6455) on top of http.server: the handshake, text messages in both directions, ping / close.
Standard library only. One writer (the thread that owns the connection)."""
import base64
import hashlib
import json
import select
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def accept(handler):
    """Answers the upgrade request of a BaseHTTPRequestHandler; returns a WebSocket on its socket, or None."""
    key = handler.headers.get("Sec-WebSocket-Key")
    if not key or "websocket" not in handler.headers.get("Upgrade", "").lower():
        return None
    acc = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
    handler.protocol_version = "HTTP/1.1"          # the upgrade answer must be HTTP/1.1 (http.server defaults to 1.0)
    handler.send_response(101, "Switching Protocols")
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", acc)
    handler.end_headers()
    handler.wfile.flush()
    return WebSocket(handler.connection)


class WebSocket:
    def __init__(self, sock):
        self.sock = sock
        self.buf = b""
        self.parts = []
        self.closed = False

    def send(self, obj):
        data = (obj if isinstance(obj, str) else json.dumps(obj, separators=(",", ":"))).encode()
        n = len(data)
        head = bytes([0x81]) + (bytes([n]) if n < 126 else bytes([126]) + struct.pack(">H", n) if n < 65536 else bytes([127]) + struct.pack(">Q", n))
        try:
            self.sock.sendall(head + data)
        except OSError:
            self.closed = True

    def _control(self, opcode, payload=b""):
        try:
            self.sock.sendall(bytes([0x80 | opcode, len(payload)]) + payload)
        except OSError:
            self.closed = True

    def poll(self, timeout):
        """Waits up to `timeout` seconds for data; returns the complete messages received (parsed JSON), or None once closed."""
        if self.closed:
            return None
        try:
            r, _, _ = select.select([self.sock], [], [], max(0.0, timeout))
            if r:
                chunk = self.sock.recv(65536)
                if not chunk:
                    self.closed = True
                    return None
                self.buf += chunk
        except OSError:
            self.closed = True
            return None
        out = []
        while True:
            if len(self.buf) < 2:
                break
            b0, b1 = self.buf[0], self.buf[1]
            n, i = b1 & 0x7F, 2
            if n == 126:
                if len(self.buf) < 4:
                    break
                n, i = struct.unpack(">H", self.buf[2:4])[0], 4
            elif n == 127:
                if len(self.buf) < 10:
                    break
                n, i = struct.unpack(">Q", self.buf[2:10])[0], 10
            mask = b""
            if b1 & 0x80:
                mask, i = self.buf[i:i + 4], i + 4
            if len(self.buf) < i + n:
                break
            payload = self.buf[i:i + n]
            self.buf = self.buf[i + n:]
            if mask:
                payload = bytes(c ^ mask[k % 4] for k, c in enumerate(payload))
            opcode = b0 & 0x0F
            if opcode == 8:                                   # close
                self._control(8, payload[:2])
                self.closed = True
                return out or None
            if opcode == 9:                                   # ping
                self._control(10, payload[:125])
                continue
            if opcode in (0, 1, 2):
                self.parts.append(payload)
                if b0 & 0x80:                                 # final fragment
                    text = b"".join(self.parts).decode("utf-8", "replace")
                    self.parts = []
                    try:
                        out.append(json.loads(text))
                    except ValueError:
                        pass
        return out

    def close(self):
        if not self.closed:
            self._control(8, struct.pack(">H", 1000))
            self.closed = True
