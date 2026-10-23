#!/usr/bin/env python3
"""Raport duplikatow filmow: wersje SD/720p obok wersji >= 1080p. Tylko odczyt.

Uzycie: python3 find_dupes.py [lista_do_usuniecia.json]
Lista (jesli podana) nadaje sie wprost do delete_items.py - przejrzyj ja przed uzyciem.
"""
import json
import os
import sys
from collections import defaultdict

import jellyfin

HD_MIN_WIDTH = 1800  # po szerokosci, bo 1920x800 (kino) to nadal 1080p


def tier(width):
    if width >= 3200:
        return "4K"
    if width >= HD_MIN_WIDTH:
        return "1080p"
    if width >= 1200:
        return "720p"
    return "SD" if width else "?"


items = jellyfin.movies()
folder_counts = defaultdict(int)
for it in items:
    folder_counts[os.path.dirname(it.get("Path") or "")] += 1

groups = defaultdict(dict)  # klucz -> {path: wersja}
for it in items:
    ids = {k.lower(): v for k, v in (it.get("ProviderIds") or {}).items() if v}
    if "tmdb" in ids:
        key = "tmdb:" + ids["tmdb"]
    elif "imdb" in ids:
        key = "imdb:" + ids["imdb"]
    else:
        key = f"name:{it['Name'].lower().strip()}:{it.get('ProductionYear')}"
    sources = it.get("MediaSources") or [{"Id": it["Id"], "Path": it.get("Path"), "MediaStreams": []}]
    for src in sources:
        video = next((s for s in src.get("MediaStreams", []) if s.get("Type") == "Video"), {})
        w = video.get("Width") or 0
        groups[key][src.get("Path")] = {
            "id": src.get("Id"), "merged": len(sources) > 1,
            "alone": folder_counts[os.path.dirname(src.get("Path") or "")] == 1,
            "name": it["Name"], "year": it.get("ProductionYear"), "path": src.get("Path"),
            "width": w, "height": video.get("Height") or 0, "tier": tier(w), "size": src.get("Size") or 0,
            "minutes": round((src.get("RunTimeTicks") or 0) / 6e8),
        }

dupes = [list(v.values()) for v in groups.values() if len(v) > 1]
to_remove = []
for vers in sorted(dupes, key=lambda vs: vs[0]["name"].lower()):
    vers.sort(key=lambda v: v["width"], reverse=True)
    has_hd = any(v["width"] >= HD_MIN_WIDTH for v in vers)
    low = [v for v in vers if 0 < v["width"] < HD_MIN_WIDTH] if has_hd else []
    print(f"\n{vers[0]['name']} ({vers[0]['year']})")
    for v in vers:
        flags = ("[scalone] " if v["merged"] else "") + ("[sam w folderze] " if v["alone"] else "")
        print(f"  {'USUN ' if v in low else 'zost.'} {v['tier']:>5} {v['width']}x{v['height']:<5} "
              f"{v['minutes']:>4} min {v['size']/2**30:6.1f} GB  {flags}{v['path']}")
    to_remove += low

print(f"\n=== Filmow: {len(items)} | grup z duplikatami: {len(dupes)} | "
      f"do usuniecia: {len(to_remove)} plikow, {sum(v['size'] for v in to_remove)/2**30:.1f} GB")
print("Uwaga: rozna dlugosc (min) w grupie = prawdopodobnie zle rozpoznany film, nie duplikat.")
print("[sam w folderze] = Jellyfin usunie caly folder. [scalone] = wersje jednego filmu, usuwanie ryzykowne.")

if len(sys.argv) > 1:
    with open(sys.argv[1], "w") as f:
        json.dump([{"id": v["id"], "path": v["path"]} for v in to_remove], f, indent=1, ensure_ascii=False)
    print(f"Zapisano liste: {sys.argv[1]}")
