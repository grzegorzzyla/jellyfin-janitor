#!/usr/bin/env python3
"""Poprawia zle rozpoznany film: przypisuje mu wskazany identyfikator z TMDB i pobiera metadane.

Uzycie: python3 identify.py <item_id> <tmdb_id>
item_id widac w adresie strony filmu w przegladarce (...details?id=<item_id>), tmdb_id w adresie themoviedb.org.
"""
import sys

import jellyfin

if len(sys.argv) != 3:
    raise SystemExit(__doc__)
item_id, tmdb_id = sys.argv[1], sys.argv[2]

results = jellyfin.request("POST", "/Items/RemoteSearch/Movie",
                           {"SearchInfo": {"ProviderIds": {"Tmdb": tmdb_id}}, "ItemId": item_id})
match = next((r for r in results if (r.get("ProviderIds") or {}).get("Tmdb") == tmdb_id), None)
if not match:
    raise SystemExit(f"TMDB nie zwrocilo filmu {tmdb_id}.")

print(f"Przypisuje: {match.get('Name')} ({match.get('ProductionYear')})")
jellyfin.request("POST", f"/Items/RemoteSearch/Apply/{item_id}?replaceAllImages=true", match)
print("Gotowe - odswiez strone filmu w przegladarce.")
