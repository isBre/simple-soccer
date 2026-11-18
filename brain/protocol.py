"""Wire format between Godot (scripts/core/brain_link.gd) and the brain server. Little-endian. Every message in both directions
is a frame: u32 payload length, then the payload.

1. Setup (Godot -> server), JSON:
     {"protocol": PROTOCOL, "pitch": {half_w, half_h, goal_half, out_x, out_y, center_r}, "ball_radius", "duration",
      "styles": [style dict team 0, team 1], "nets": [null | {"model": path} | {"port": n}, ...], "temperature",
      "players": [{uid, team, slot, role, home: [x, y], spawn: [x, y], radius, seed,
                   attrs: {finishing, passing, defending, positioning, reaction}}, ...]   (team 0 first, slot order)}
   Reply, JSON: {"ok": true, "protocol", "teams": [{"kind": "rules" | "net", "n_in"}, ...], "warnings": [...]}
                or {"ok": false, "error": "..."}

2. Then one frame per request. The payload starts with a command byte and a snapshot of the match:
     SNAP_HEAD  i32 tick, u8 state, u8 flags (1 = kickoff active, 2 = update the team brains), i8 kickoff taker uid,
                i32 kickoff_go, u8 score 0, u8 score 1, f32 time_left, i8 last touch uid, i8 controlled (human) uid,
                u16 resets (counts kickoff resets), f32 ball x, y, vx, vy, f32 x, y of the ball's last HIST positions (newest first)
     per player (setup order): f32 x, y, vx, vy, u8 flags (1 = human, 2 = decide this tick)
   'D' decide:  reply per deciding player (setup order): f32 dir x, dir y, u8 kick, u8 intent (INTENTS index);
                then i8 keeper uid of team 0 and of team 1 (-1 = none)
   'O' observe: after the snapshot u8 mode (1 = team observation, 2 = ego observation with slot, 3 = both), u8 n, n x i8 uid;
                reply: the observations, f32, in the order asked
   'Q' quit
   A uid of -1 means "nobody"."""
import struct

from .match import HIST

PROTOCOL = 1
INTENTS = ["", "pass", "shoot", "clear", "long"]
INTENT_CODE = {k: i for i, k in enumerate(INTENTS)}
CMD_DECIDE, CMD_OBSERVE, CMD_QUIT = ord("D"), ord("O"), ord("Q")
FLAG_KICKOFF, FLAG_UPDATE = 1, 2
P_HUMAN, P_DECIDE = 1, 2

HEAD = struct.Struct("<iBBbiBBfbbH4f%df" % (2 * HIST))
PLAYER = struct.Struct("<4fB")
DECISION = struct.Struct("<ffBB")
KEEPERS = struct.Struct("<bb")


def recv_exact(sock, n):
    buf = bytearray()
    while len(buf) < n:
        c = sock.recv(n - len(buf))
        if not c:
            return None
        buf += c
    return bytes(buf)


def recv_frame(sock):
    h = recv_exact(sock, 4)
    if h is None:
        return None
    n = struct.unpack("<I", h)[0]
    return recv_exact(sock, n) if n else b""


def send_frame(sock, payload: bytes):
    sock.sendall(struct.pack("<I", len(payload)) + payload)


def read_snapshot(m, buf, off=1):
    """Updates the Match from a snapshot starting at buf[off]. Returns (flags, deciding players, offset after it)."""
    v = HEAD.unpack_from(buf, off)
    off += HEAD.size
    (m.tick, m.state, flags, taker, m.kickoff_go, s0, s1, m.time_left, lt, ctrl, resets) = v[:11]
    m.kickoff_active = bool(flags & FLAG_KICKOFF)
    m.kickoff_taker = m.by_uid.get(taker)
    m.scores = [s0, s1]
    m.last_touch = m.by_uid.get(lt)
    m.controlled = m.by_uid.get(ctrl)
    m.ball_pos = complex(v[11], v[12])
    m.ball_vel = complex(v[13], v[14])
    h = v[15:]
    m.hist = [complex(h[2 * i], h[2 * i + 1]) for i in range(HIST)]
    if resets != m.resets:
        m.resets = resets
        for b in m.brains:
            b.reset()
    deciders = []
    for p in m.players:
        x, y, vx, vy, pf = PLAYER.unpack_from(buf, off)
        off += PLAYER.size
        p.pos = complex(x, y)
        p.vel = complex(vx, vy)
        p.is_human = bool(pf & P_HUMAN)
        if pf & P_DECIDE:
            deciders.append(p)
    return flags, deciders, off
