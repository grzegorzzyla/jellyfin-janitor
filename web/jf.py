"""Klient API Jellyfin i wspolny cache pozycji z biblioteki."""
import json
import os
import threading
import time
import urllib.request

URL = os.environ["JELLYFIN_URL"].rstrip("/")
KEY = os.environ["JELLYFIN_API_KEY"]
# Nowsze wersje Jellyfin akceptuja tylko ten naglowek (X-Emby-Token i ?api_key= daja 401)
_H = {"Authorization": f'MediaBrowser Token="{KEY}"', "Content-Type": "application/json"}

_cache = {"t": 0, "items": []}
_lock = threading.Lock()


def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method, headers=_H)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def items(force=False):
    """Filmy i odcinki z biblioteki (bez kolekcji), odswiezane co 60 s."""
    with _lock:
        if force or time.time() - _cache["t"] > 60:
            data = request("GET", "/Items?IncludeItemTypes=Movie,Episode&Recursive=true"
                                  "&Fields=ProviderIds,MediaSources,Path,ProductionYear")["Items"]
            # Kolekcje (boxsety) tez przychodza jako filmy - pomijamy je
            _cache.update(t=time.time(), items=[i for i in data if not (i.get("Path") or "").startswith("/config/")])
        return _cache["items"]


def invalidate():
    _cache["t"] = 0


def video_stream(source):
    return next((s for s in source.get("MediaStreams", []) if s.get("Type") == "Video"), {})
