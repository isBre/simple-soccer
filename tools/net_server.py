"""Tiny numpy inference server for the live viewer: the game's GDScript MLP is ~15x too slow for real time on a Pi.
Protocol per request: 54 float32 in -> 10 float32 out. On every new connection the model is (re)loaded:
  --model FILE            fixed game-model JSON
  --tag TAG --ckpt DIR    newest DIR/TAG_u*.json (falls back to --model)
  --best-file FILE        the model named in logs/<tag>_best.json ("model": path relative to the project; written by
                          rl/eval_checkpoint.py), falls back to --model until the first evaluation has chosen one
"""
import argparse, glob, json, os, re, socket, threading
import numpy as np


def newest(ckpt, tag, fallback):
    best, path = -1, fallback
    for f in glob.glob(os.path.join(ckpt, tag + "_u*.json")):
        m = re.search(r"_u(\d+)\.json$", f)
        if m and int(m.group(1)) > best:
            best, path = int(m.group(1)), f
    return path


def load(path):
    d = json.load(open(path))
    s = d["sizes"]
    W = [np.array(w, np.float32).reshape(s[i + 1], s[i]) for i, w in enumerate(d["W"])]
    B = [np.array(b, np.float32) for b in d["B"]]
    return W, B


def serve(conn, path):
    W, B = load(path)
    print("serving", path, flush=True)
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    buf = b""
    while True:
        while len(buf) < 216:
            c = conn.recv(4096)
            if not c:
                return
            buf += c
        x, buf = np.frombuffer(buf[:216], np.float32), buf[216:]
        for i, (w, b) in enumerate(zip(W, B)):
            x = w @ x + b
            if i < len(W) - 1:
                x = np.maximum(x, 0)
        conn.sendall(x.astype(np.float32).tobytes())


ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--model", default="")
ap.add_argument("--tag", default="")
ap.add_argument("--ckpt", default="out_5v5/ckpt")
ap.add_argument("--best-file", default="")
a = ap.parse_args()
srv = socket.socket()
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind(("127.0.0.1", a.port))
srv.listen(8)
while True:
    c, _ = srv.accept()
    p = newest(a.ckpt, a.tag, a.model) if a.tag else a.model
    if a.best_file and os.path.exists(a.best_file):
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), json.load(open(a.best_file))["model"])
    threading.Thread(target=lambda c=c, p=p: serve(c, p), daemon=True).start()
