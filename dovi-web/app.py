#!/usr/bin/env python3
"""dovi-web: strona do konwersji Dolby Vision profil 7 -> 8.1 (bez przekodowania obrazu).

Liste plikow bierze z Jellyfin (DvProfile == 7). Biblioteka jest zamontowana pod /media,
tak samo jak w kontenerze Jellyfin, wiec sciezki z API pasuja 1:1.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

JF_URL = os.environ["JELLYFIN_URL"].rstrip("/")
JF_KEY = os.environ["JELLYFIN_API_KEY"]
MEDIA = "/media"
DATA = "/data"
HISTORY = os.path.join(DATA, "history.json")
LOG = os.path.join(DATA, "current.log")
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")

lock = threading.Lock()
queue = []   # sciezki czekajace na konwersje
job = None   # biezaca konwersja
history = json.load(open(HISTORY)) if os.path.exists(HISTORY) else []
_cache = {"t": 0, "items": []}


def jf(method, path):
    req = urllib.request.Request(JF_URL + path, method=method,
                                 headers={"Authorization": f'MediaBrowser Token="{JF_KEY}"'})
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def save_history():
    with open(HISTORY, "w") as f:
        json.dump(history[:200], f, indent=1, ensure_ascii=False)


def p8_path(path):
    return path[:-4] + ".P8.mkv"


def dv7_items(force=False):
    if force or time.time() - _cache["t"] > 60:
        items = jf("GET", "/Items?IncludeItemTypes=Movie,Episode&Recursive=true&Fields=MediaSources")["Items"]
        found = []
        for it in items:
            for src in it.get("MediaSources") or []:
                v = next((s for s in src.get("MediaStreams", []) if s.get("Type") == "Video"), {})
                if v.get("DvProfile") == 7 and (src.get("Path") or "").startswith(MEDIA + "/"):
                    name = (it["SeriesName"] + " – " if it.get("SeriesName") else "") + it["Name"]
                    found.append({"id": src["Id"], "name": name, "year": it.get("ProductionYear"),
                                  "path": src["Path"], "size": src.get("Size") or 0,
                                  "dv": v.get("VideoDoViTitle") or "Dolby Vision 7"})
        _cache.update(t=time.time(), items=sorted(found, key=lambda i: i["name"].lower()))
    return _cache["items"]


def convert(path):
    d, name = os.path.split(path)
    out = p8_path(path)
    # Pliki robocze z kropka na poczatku - Jellyfin ich nie indeksuje
    tmp = os.path.join(d, "." + name[:-4] + ".p81.hevc")
    part = os.path.join(d, "." + os.path.basename(out))
    if shutil.disk_usage(d).free < os.path.getsize(path) * 2.1:
        return False, "Za mało miejsca na dysku (potrzeba ~2,1× rozmiaru pliku)"
    probe = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=r_frame_rate:format=duration", "-of", "json", path],
                           capture_output=True, text=True)
    info = json.loads(probe.stdout or "{}")
    if not info.get("streams"):
        return False, "ffprobe nie odczytał pliku: " + probe.stderr.strip()[-300:]
    fps = info["streams"][0]["r_frame_rate"]
    job["duration"] = float(info["format"]["duration"])
    q = shlex.quote
    steps = [
        ("Etap 1/2: wideo + metadane DV 8.1",
         f"ffmpeg -v error -stats -i {q(path)} -map 0:v:0 -c:v copy -bsf:v hevc_mp4toannexb -f hevc - "
         f"| dovi_tool -m 2 convert --discard - -o {q(tmp)}", (0,)),
        # mkvmerge: 1 = same ostrzezenia, plik jest poprawny
        ("Etap 2/2: składanie MKV",
         f"mkvmerge -o {q(part)} --language 0:und --default-duration 0:{fps}p {q(tmp)} -D {q(path)}", (0, 1)),
    ]
    try:
        with open(LOG, "w") as log:
            for i, (label, cmd, ok_codes) in enumerate(steps):
                job.update(phase=label, step=i)
                rc = subprocess.run(["bash", "-o", "pipefail", "-c", cmd], stdout=log, stderr=log).returncode
                if rc not in ok_codes:
                    return False, f"{label}: błąd (kod {rc}), szczegóły w logu"
        st = os.stat(path)
        os.chown(part, st.st_uid, st.st_gid)
        os.rename(part, out)
        return True, os.path.basename(out)
    finally:
        for f in (tmp, part):
            if os.path.exists(f):
                os.remove(f)


def worker():
    global job
    while True:
        with lock:
            path = queue.pop(0) if queue else None
            if path:
                job = {"path": path, "phase": "Start", "step": 0, "started": time.time()}
        if not path:
            time.sleep(2)
            continue
        try:
            ok, msg = convert(path)
        except Exception as e:  # nie zabijaj workera
            ok, msg = False, f"Wyjątek: {e}"
        with lock:
            history.insert(0, {"path": path, "status": "gotowe" if ok else "błąd", "msg": msg,
                               "started": job["started"], "ended": time.time()})
            save_history()
            job = None
        if ok:
            try:
                jf("POST", "/Library/Refresh")
            except Exception:
                pass


def progress():
    """Postep biezacego etapu w % na podstawie konca logu."""
    try:
        with open(LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(LOG) - 8192))
            lines = [l for l in re.split(r"[\r\n]+", f.read().decode(errors="replace")) if l.strip()]
    except OSError:
        return 0, []
    pct = 0
    if job and job.get("step") == 0 and job.get("duration"):
        times = [m for l in lines for m in re.findall(r"time=(\d+):(\d+):([\d.]+)", l)]
        if times:
            h, m, s = times[-1]
            pct = (int(h) * 3600 + int(m) * 60 + float(s)) / job["duration"] * 100
    elif job:
        found = [int(m) for l in lines for m in re.findall(r"Progress: (\d+)%", l)]
        pct = found[-1] if found else 0
    return min(round(pct), 100), lines[-8:]


def state():
    replaced = {h["path"] for h in history if h["status"] == "podmieniony" and time.time() - h["ended"] < 86400}
    items = []
    for it in dv7_items():
        p = it["path"]
        if job and job["path"] == p:
            status = "trwa"
        elif p in queue:
            status = "kolejka"
        elif p in replaced:
            status = "podmieniony"
        elif not os.path.exists(p):
            status = "brak"
        elif os.path.exists(p8_path(p)):
            status = "gotowe"
        else:
            status = "do_konwersji"
        items.append({**it, "status": status, "p8": os.path.basename(p8_path(p))})
    pct, log = progress() if job else (0, [])
    cur = dict(job, progress=pct, log=log, elapsed=round(time.time() - job["started"])) if job else None
    return {"items": items, "job": cur, "queue": list(queue), "history": history[:15],
            "free_gb": round(shutil.disk_usage(MEDIA).free / 2**30)}


def replace(item):
    p = item["path"]
    os.replace(p8_path(p), p)  # P8 przejmuje nazwe oryginalu, oryginal znika
    history.insert(0, {"path": p, "status": "podmieniony", "msg": "oryginał zastąpiony wersją P8",
                       "started": time.time(), "ended": time.time()})
    save_history()
    try:
        jf("POST", f"/Items/{item['id']}/Refresh?metadataRefreshMode=FullRefresh&imageRefreshMode=Default"
                   "&replaceAllMetadata=false&replaceAllImages=false")
        jf("POST", "/Library/Refresh")
    except Exception:
        pass


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
            self.send(200, open(PAGE, "rb").read(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            try:
                self.send(200, state())
            except Exception as e:
                self.send(502, {"error": f"Jellyfin: {e}"})
        else:
            self.send(404, {"error": "nie ma"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or "{}")
        if self.path == "/api/refresh":
            dv7_items(force=True)
            return self.send(200, {"ok": True})
        item = next((i for i in dv7_items() if i["path"] == body.get("path")), None)
        if not item:
            return self.send(400, {"error": "Tego pliku nie ma na liście DV profil 7"})
        with lock:
            busy = (job and job["path"] == item["path"]) or item["path"] in queue
            if self.path == "/api/convert":
                if busy or os.path.exists(p8_path(item["path"])):
                    return self.send(409, {"error": "Plik jest już w kolejce albo ma wersję P8"})
                queue.append(item["path"])
                return self.send(200, {"ok": True})
            if self.path == "/api/replace":
                if busy or not os.path.exists(p8_path(item["path"])):
                    return self.send(409, {"error": "Brak gotowej wersji P8"})
                replace(item)
                return self.send(200, {"ok": True})
        self.send(404, {"error": "nie ma"})

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    print("dovi-web na porcie 8080", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
