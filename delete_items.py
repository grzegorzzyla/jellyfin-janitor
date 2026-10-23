#!/usr/bin/env python3
"""Usuwa z Jellyfin (biblioteka + plik na dysku) pozycje z listy JSON [{"id", "path"}]. TRWALE.

Uzycie: python3 delete_items.py lista.json
Usuwanie omija kosz UGOS. Film lezacy sam w folderze zostaje usuniety razem z folderem.
Pozycje, ktorych juz nie ma, sa pomijane - mozna bezpiecznie uruchomic ponownie.
"""
import json
import sys
import urllib.error

import jellyfin

if len(sys.argv) != 2:
    raise SystemExit(__doc__)

present = []
for t in json.load(open(sys.argv[1])):
    if jellyfin.get(f"/Items?Ids={t['id']}")["TotalRecordCount"] == 0:
        print("  (juz nie ma)", t["path"])
    else:
        present.append(t)
        print("  ", t["path"])

if not present:
    raise SystemExit("Nic do usuniecia.")
if input(f"\nUsunac TRWALE {len(present)} plikow? [tak/nie] ").strip().lower() != "tak":
    raise SystemExit("Przerwano.")

for t in present:
    try:
        jellyfin.request("DELETE", f"/Items/{t['id']}")
        print("OK  ", t["path"])
    except urllib.error.HTTPError as e:
        print("BLAD", e.code, t["path"])
