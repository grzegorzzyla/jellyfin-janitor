"""Konwersja Dolby Vision profil 7 -> 8.1 (bez przekodowania obrazu): kolejka, postep, podmiana oryginalu."""
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time

import jf

MEDIA = "/media"
DATA = os.environ.get("DATA_DIR", "/data")
HISTORY = os.path.join(DATA, "history.json")
LOG = os.path.join(DATA, "current.log")

lock = threading.Lock()
queue = []   # sciezki czekajace na konwersje
job = None   # biezaca konwersja
history = json.load(open(HISTORY)) if os.path.exists(HISTORY) else []


def save_history():
    with open(HISTORY, "w") as f:
        json.dump(history[:200], f, indent=1, ensure_ascii=False)


def p8_path(path):
    return path[:-4] + ".P8.mkv"


def dv7_items():
    found = []
    for it in jf.items():
        for src in it.get("MediaSources") or []:
            v = jf.video_stream(src)
            if v.get("DvProfile") == 7 and (src.get("Path") or "").startswith(MEDIA + "/"):
                name = (it["SeriesName"] + " – " if it.get("SeriesName") else "") + it["Name"]
                found.append({"id": src["Id"], "name": name, "year": it.get("ProductionYear"),
                              "path": src["Path"], "size": src.get("Size") or 0,
                              "dv": v.get("VideoDoViTitle") or "Dolby Vision 7"})
    return sorted(found, key=lambda i: i["name"].lower())


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
                jf.request("POST", "/Library/Refresh")
                jf.invalidate()
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


def find(path):
    return next((i for i in dv7_items() if i["path"] == path), None)


def enqueue(path):
    item = find(path)
    if not item:
        return "Tego pliku nie ma na liście DV profil 7"
    with lock:
        if (job and job["path"] == path) or path in queue or os.path.exists(p8_path(path)):
            return "Plik jest już w kolejce albo ma wersję P8"
        queue.append(path)


def replace(path):
    item = find(path)
    if not item:
        return "Tego pliku nie ma na liście DV profil 7"
    with lock:
        if (job and job["path"] == path) or path in queue or not os.path.exists(p8_path(path)):
            return "Brak gotowej wersji P8"
        os.replace(p8_path(path), path)  # P8 przejmuje nazwe oryginalu, oryginal znika
        history.insert(0, {"path": path, "status": "podmieniony", "msg": "oryginał zastąpiony wersją P8",
                           "started": time.time(), "ended": time.time()})
        save_history()
    try:
        jf.request("POST", f"/Items/{item['id']}/Refresh?metadataRefreshMode=FullRefresh&imageRefreshMode=Default"
                           "&replaceAllMetadata=false&replaceAllImages=false")
        jf.request("POST", "/Library/Refresh")
        jf.invalidate()
    except Exception:
        pass
