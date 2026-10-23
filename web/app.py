#!/usr/bin/env python3
"""jellyfin-janitor web: Dolby Vision 7 -> 8.1, duplikaty i poprawianie rozpoznania filmow.

Biblioteka jest zamontowana pod /media, tak samo jak w kontenerze Jellyfin,
wiec sciezki z API pasuja 1:1.
"""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import dv
import jf
import library

PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

GET = {
    "/api/dv": lambda: dv.state(),
    "/api/dupes": lambda: library.duplicates(),
    "/api/movies": lambda: library.movies(),
}


def post_refresh(body):
    jf.items(force=True)


def post_dupes_delete(body):
    done, err = library.delete(body.get("ids") or [])
    return err or {"done": done}


POST = {
    "/api/refresh": post_refresh,
    "/api/dv/convert": lambda b: dv.enqueue(b.get("path")),
    "/api/dv/replace": lambda b: dv.replace(b.get("path")),
    "/api/dupes/delete": post_dupes_delete,
    "/api/identify/search": lambda b: {"results": library.search(b["item_id"], b.get("name"), b.get("year"), b.get("tmdb"))},
    "/api/identify/apply": lambda b: library.apply(b["item_id"], b["tmdb"]),
}


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            return self.send(200, open(PAGE, "rb").read(), "text/html; charset=utf-8")
        handler = GET.get(self.path)
        if not handler:
            return self.send(404, {"error": "nie ma"})
        try:
            self.send(200, handler())
        except Exception as e:
            self.send(502, {"error": f"Jellyfin: {e}"})

    def do_POST(self):
        handler = POST.get(self.path)
        if not handler:
            return self.send(404, {"error": "nie ma"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or "{}")
            result = handler(body)
        except Exception as e:
            return self.send(502, {"error": f"Błąd: {e}"})
        # Handler zwraca None (ok), tekst bledu albo dane do odeslania
        if isinstance(result, str):
            return self.send(409, {"error": result})
        self.send(200, result or {"ok": True})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    os.makedirs(dv.DATA, exist_ok=True)
    threading.Thread(target=dv.worker, daemon=True).start()
    print("jellyfin-janitor na porcie 8080", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
