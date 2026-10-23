"""Wspolny klient API Jellyfin. Adres i klucz sa w config.json obok skryptow."""
import json
import os
import urllib.request

_CFG = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")))
URL = _CFG["url"].rstrip("/")
# Jellyfin 12.x akceptuje tylko ten naglowek (X-Emby-Token i ?api_key= daja 401)
_H = {"Authorization": f'MediaBrowser Token="{_CFG["api_key"]}"', "Content-Type": "application/json"}


def request(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method, headers=_H)
    with urllib.request.urlopen(req, timeout=120) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def get(path):
    return request("GET", path)


def movies(fields="ProviderIds,MediaSources,Path,ProductionYear"):
    items = get(f"/Items?IncludeItemTypes=Movie&Recursive=true&Fields={fields}")["Items"]
    # Kolekcje (boxsety) tez przychodza jako filmy - pomijamy je
    return [i for i in items if not (i.get("Path") or "").startswith("/config/")]
