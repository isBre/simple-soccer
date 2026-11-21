"""The web app: one server for both areas of the page.

  Game   play Simple Soccer in the browser: quick match, teams, tournaments, match report (game/: the back end)
  Lab    the experiment pipeline of this machine (Pi or Mac): runs, live demo match, comparisons, docs (lab/dashboard.py: the back end)

  python3 web/app.py [--port 8080]       then open http://<this machine>:8080  (#/game = Game, #/ = Lab)

Pages: web/index.html (shell), web/style.css, web/lab/*.js (the Lab, plain scripts), web/game.js + web/game/*.js (the Game, ES modules),
web/game.css, web/draw.js, web/sound.js.
Routes: everything of lab/dashboard.py (/api/overview, /api/v1/..., /api/live, ...), plus /api/game/... (game/routes.py) and
/ws/match (a live match over a WebSocket, game/session.py). The game needs numpy (net teams); without it the Lab still works.
No login: use it on a trusted network only."""
import argparse
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import unquote

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):   # tiny matrix products: no BLAS thread pools
    os.environ.setdefault(_v, "1")

from lab import dashboard as lab_api   # noqa: E402
import ws                              # noqa: E402  (web/ws.py, next to this script)

_game = None


def game():
    """The game back end, imported on first use (it needs numpy; the Lab does not)."""
    global _game
    if _game is None:
        from game import routes, session
        _game = (routes, session)
    return _game


class Handler(lab_api.Handler):
    def _same_origin(self):
        origin, host = self.headers.get("Origin", ""), self.headers.get("Host", "")
        return not origin or origin.split("://")[-1] == host

    def do_GET(self):
        path = unquote(self.path.split("?")[0])
        if path == "/ws/match":
            return self.match()
        if path.startswith("/api/game/"):
            return self.game_api("GET", path, None)
        return super().do_GET()

    def do_POST(self):
        path = unquote(self.path.split("?")[0])
        if path.startswith("/api/game/"):
            if not self._same_origin():
                return self.send(json.dumps({"error": "not allowed"}).encode(), "application/json", 403)
            try:
                body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 4 << 20)) or b"{}")
            except ValueError:
                return self.send(json.dumps({"error": "bad JSON"}).encode(), "application/json", 400)
            return self.game_api("POST", path, body)
        return super().do_POST()

    def game_api(self, method, path, body):
        try:
            routes, _ = game()
        except ImportError as e:
            return self.send(json.dumps({"error": "the game needs numpy on the server: %s" % e}).encode(), "application/json", 503)
        try:
            code, out = routes.handle(method, path, body)
        except Exception as e:                                       # a bug: report it, keep serving
            code, out = 500, {"error": repr(e)}
        return self.send(json.dumps(out, separators=(",", ":")).encode(), "application/json", code)

    def match(self):
        """A live match: upgrade to a WebSocket and let game/session.py play it (this request's thread owns the connection)."""
        if not self._same_origin():
            return self.send(b"not allowed", "text/plain", 403)
        try:
            _, session = game()
        except ImportError as e:
            return self.send(("the game needs numpy on the server: %s" % e).encode(), "text/plain", 503)
        sock = ws.accept(self)
        if sock is None:
            return self.send(b"WebSocket upgrade expected", "text/plain", 400)
        self.close_connection = True
        try:
            session.run(sock)
        except Exception as e:                                       # a bug in a match must not take the server down
            import traceback
            traceback.print_exc()
            sock.send({"k": "e", "error": repr(e)})
        finally:
            sock.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0", help="0.0.0.0 = the local network can open it; 127.0.0.1 = this machine only")
    ap.add_argument("--no-helpers", action="store_true", help="no health sampler and no live demo match from this server (tests)")
    a = ap.parse_args()
    threading.Thread(target=lab_api.Live.listen, daemon=True).start()
    if not a.no_helpers:
        threading.Thread(target=lab_api.health_sampler, daemon=True).start()
        threading.Thread(target=lab_api.follow_live, daemon=True).start()
    server = ThreadingHTTPServer((a.host, a.port), Handler)
    server.daemon_threads = True
    print("Simple Soccer web app on http://%s:%d  (Game: #/game, Lab: #/)" % ("localhost" if a.host == "0.0.0.0" else a.host, a.port), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
