"""Duplikaty filmow, podejrzane rozpoznania, przypisywanie TMDB i usuwanie przez API Jellyfin."""
import json
import os
import re
import statistics
import threading
import time
from collections import defaultdict

import jf

DATA = os.environ.get("DATA_DIR", "/data")
LOG = os.path.join(DATA, "library_log.json")
HD_MIN_WIDTH = 1800       # po szerokosci, bo 1920x800 (kino) to nadal 1080p
RUNTIME_TOLERANCE = 10    # minut roznicy, od ktorej wersje to raczej rozne filmy

_lock = threading.Lock()
log = json.load(open(LOG)) if os.path.exists(LOG) else []


def _log(action, path, msg):
    log.insert(0, {"action": action, "path": path, "msg": msg, "t": time.time()})
    with open(LOG, "w") as f:
        json.dump(log[:300], f, indent=1, ensure_ascii=False)


def tier(width):
    if width >= 3200:
        return "4K"
    if width >= HD_MIN_WIDTH:
        return "1080p"
    if width >= 1200:
        return "720p"
    return "SD" if width else "?"


def _key(movie):
    ids = {k.lower(): v for k, v in (movie.get("ProviderIds") or {}).items() if v}
    if "tmdb" in ids:
        return "tmdb:" + ids["tmdb"]
    if "imdb" in ids:
        return "imdb:" + ids["imdb"]
    return f"name:{movie['Name'].lower().strip()}:{movie.get('ProductionYear')}"


def versions():
    """Jedna pozycja na plik filmu (wersje scalone przez Jellyfin sa rozbite)."""
    movies = [i for i in jf.items() if i.get("Type") == "Movie"]
    folder_counts = defaultdict(int)
    for m in movies:
        folder_counts[os.path.dirname(m.get("Path") or "")] += 1
    out = {}
    for m in movies:
        sources = m.get("MediaSources") or []
        ids = {k.lower(): v for k, v in (m.get("ProviderIds") or {}).items() if v}
        for src in sources:
            path = src.get("Path")
            v = jf.video_stream(src)
            out[path] = {
                "id": src["Id"], "item_id": m["Id"], "key": _key(m), "name": m["Name"],
                "year": m.get("ProductionYear"), "tmdb": ids.get("tmdb"), "imdb": ids.get("imdb"),
                "path": path, "width": v.get("Width") or 0, "height": v.get("Height") or 0,
                "tier": tier(v.get("Width") or 0), "size": src.get("Size") or 0,
                "minutes": round((src.get("RunTimeTicks") or 0) / 6e8),
                "merged": len(sources) > 1,
                "alone": folder_counts[os.path.dirname(path or "")] == 1,
            }
    return list(out.values())


def _groups():
    groups = defaultdict(list)
    for v in versions():
        groups[v["key"]].append(v)
    return {k: vs for k, vs in groups.items() if len(vs) > 1}


def duplicates():
    result = []
    for key, vers in _groups().items():
        vers.sort(key=lambda v: (v["width"], v["size"]), reverse=True)
        has_hd = any(v["width"] >= HD_MIN_WIDTH for v in vers)
        sizes = defaultdict(int)
        for v in vers:
            sizes[v["size"]] += 1
        runtimes = [v["minutes"] for v in vers if v["minutes"]]
        for i, v in enumerate(vers):
            v["suggest"] = has_hd and 0 < v["width"] < HD_MIN_WIDTH and not v["merged"]
            # Identyczna kopia: ten sam rozmiar co wersja wyzej na liscie
            v["identical"] = v["size"] > 0 and sizes[v["size"]] > 1 and any(w["size"] == v["size"] for w in vers[:i])
            if v["identical"] and not v["merged"]:
                v["suggest"] = True
        result.append({
            "key": key, "name": vers[0]["name"], "year": vers[0]["year"], "tmdb": vers[0]["tmdb"],
            "versions": vers, "has_hd": has_hd,
            "runtime_mismatch": bool(runtimes) and max(runtimes) - min(runtimes) > RUNTIME_TOLERANCE,
        })
    result.sort(key=lambda g: g["name"].lower())
    return {"groups": result, "log": [e for e in log if e["action"] == "usunięto"][:20]}


def delete(ids):
    """Usuwa wskazane wersje (wpis + plik). Odmawia, gdyby w grupie nie zostala zadna wersja."""
    groups = _groups()
    by_id = {v["id"]: v for vs in groups.values() for v in vs}
    chosen = [by_id.get(i) for i in ids]
    if not ids or None in chosen:
        return None, "Część pozycji nie jest już na liście duplikatów – odśwież stronę"
    if any(v["merged"] for v in chosen):
        return None, "Wersji scalonych nie usuwam przez API (mogłyby zniknąć wszystkie) – usuń plik ręcznie"
    for key, vs in groups.items():
        if all(v["id"] in ids for v in vs):
            return None, f"„{vs[0]['name']}”: nie można usunąć wszystkich wersji filmu"
    done = []
    with _lock:
        for v in chosen:
            try:
                jf.request("DELETE", f"/Items/{v['item_id']}")
                _log("usunięto", v["path"], f"{v['tier']}, {v['size'] / 2**30:.1f} GB")
                done.append({"path": v["path"], "ok": True})
            except Exception as e:
                done.append({"path": v["path"], "ok": False, "error": str(e)})
    jf.invalidate()
    return done, None


def _file_years(path):
    return [int(y) for y in re.findall(r"(?<!\d)(19[2-9]\d|20[0-3]\d)(?!\d)", os.path.basename(path or ""))]


def movies():
    """Wszystkie filmy z powodami, dla ktorych rozpoznanie moze byc bledne."""
    vers = versions()
    by_key = defaultdict(list)
    for v in vers:
        by_key[v["key"]].append(v)
    out = {}
    for v in vers:
        reasons = []
        years = _file_years(v["path"])
        if years and v["year"] and all(abs(y - v["year"]) > 1 for y in years):
            reasons.append(f"rok w nazwie pliku {years[-1]}, w Jellyfin {v['year']}")
        others = [w["minutes"] for w in by_key[v["key"]] if w is not v and w["minutes"]]
        if others and v["minutes"] and abs(v["minutes"] - statistics.median(others)) > RUNTIME_TOLERANCE:
            reasons.append(f"trwa {v['minutes']} min, inne wersje ~{round(statistics.median(others))} min – inna wersja (np. reżyserska) albo inny film")
        item = out.setdefault(v["item_id"], {**{k: v[k] for k in ("item_id", "name", "year", "tmdb", "imdb",
                                                                  "path", "minutes")}, "reasons": [],
                                     "unidentified": not v["tmdb"] and not v["imdb"]})
        item["reasons"] += [r for r in reasons if r not in item["reasons"]]
    result = sorted(out.values(), key=lambda m: m["name"].lower())
    return {"movies": result, "log": [e for e in log if e["action"] == "rozpoznanie"][:20]}


def search(item_id, name=None, year=None, tmdb=None):
    info = {"ProviderIds": {"Tmdb": str(tmdb)}} if tmdb else {"Name": name, "Year": year or None}
    results = jf.request("POST", "/Items/RemoteSearch/Movie", {"SearchInfo": info, "ItemId": item_id}) or []
    return [{"name": r.get("Name"), "year": r.get("ProductionYear"), "tmdb": (r.get("ProviderIds") or {}).get("Tmdb"),
             "imdb": (r.get("ProviderIds") or {}).get("Imdb"), "image": r.get("ImageUrl"),
             "overview": (r.get("Overview") or "")[:300]}
            for r in results if (r.get("ProviderIds") or {}).get("Tmdb")][:12]


def apply(item_id, tmdb):
    tmdb = str(tmdb)
    results = jf.request("POST", "/Items/RemoteSearch/Movie",
                         {"SearchInfo": {"ProviderIds": {"Tmdb": tmdb}}, "ItemId": item_id}) or []
    match = next((r for r in results if (r.get("ProviderIds") or {}).get("Tmdb") == tmdb), None)
    if not match:
        return f"TMDB nie zwróciło filmu {tmdb}"
    jf.request("POST", f"/Items/RemoteSearch/Apply/{item_id}?replaceAllImages=true", match)
    path = next((m["path"] for m in movies()["movies"] if m["item_id"] == item_id), item_id)
    _log("rozpoznanie", path, f"→ {match.get('Name')} ({match.get('ProductionYear')}), TMDB {tmdb}")
    jf.invalidate()
