# jellyfin-janitor

[Polski](README.md) · **English**

Tools for cleaning up a [Jellyfin](https://jellyfin.org) library through its API:

- **finding duplicate movies** (SD/720p next to a 1080p+ copy) and removing them safely,
- **fixing misidentified movies** (assigning the correct TMDB id),
- **dovi-web** – a small browser UI that converts **Dolby Vision profile 7 → 8.1** without re-encoding, so UHD Blu-ray remuxes play on TVs and streaming boxes.

The Python scripts use only the standard library (Python 3.9+), so there is nothing to install. dovi-web runs in Docker.

> The UI, console output and code comments are in Polish.

## Contents

| File | What it does |
|---|---|
| `find_dupes.py [list.json]` | Duplicate report. Read-only. Optionally saves the lower-quality versions to a list for deletion. |
| `delete_items.py list.json` | Deletes the items on the list (library entry **and the file on disk**). Shows the list first and asks you to type `tak` ("yes"). |
| `identify.py <item_id> <tmdb_id>` | Assigns the correct TMDB id to a movie and fetches its metadata. |
| `dovi-web/` | Browser UI for DV profile 7 → 8.1 conversion (Docker). |
| `dv7_to_p81.sh <file.mkv>` | Same as dovi-web, but from the command line on the server that holds the files. |
| `jellyfin.py` | Shared API client used by the scripts. |

## Setup

1. In Jellyfin: **Dashboard → API Keys → +**.
2. Copy `config.example.json` to `config.json` and fill in the server address and the key.

```
cp config.example.json config.json
```

`config.json` is in `.gitignore`.

## Duplicates

```
python3 find_dupes.py to_delete.json   # report + list of files to delete
# review the report, edit to_delete.json if needed
python3 delete_items.py to_delete.json
```

How the report works:

- Movies are grouped by **TMDB** id, then **IMDb** id, and as a last resort by title and year.
- **Quality is judged by frame width**, not height, because a 1920×800 scope movie is still 1080p.
- Versions below 1080p are marked for deletion, but only in groups that also contain a version of 1080p or better. Groups that contain only HD versions are shown, and nothing in them is marked.
- Each version shows its runtime. **Different runtimes in one group** usually mean a misidentified movie rather than a duplicate. Fix it with `identify.py`.
- **`[sam w folderze]`** ("alone in folder"): the movie is the only file in its folder, and Jellyfin will delete **the whole folder**.
- **`[scalone]`** ("merged"): Jellyfin has combined several files into one movie with selectable versions. Deleting such an item through the API may remove every version, so it is safer to delete the file by hand.

> ⚠️ Deleting through the Jellyfin API is **permanent** – files do not go to the OS/NAS recycle bin.

## Misidentified movie

```
python3 identify.py <item_id> <tmdb_id>
```

`item_id` is in the URL of the movie's page in Jellyfin (`…/details?id=…`), and `tmdb_id` is in the movie's URL on themoviedb.org.

A common cause of misidentification: Jellyfin identifies movies by folder name. For example, `Blade.Runner.2049…mkv` inside a `Blade Runner/` folder gets identified as the 1982 movie.

## Dolby Vision profile 7 → 8.1 (dovi-web)

**Problem:** UHD Blu-ray remuxes often use Dolby Vision **profile 7**. In Jellyfin it shows up as "Dolby Vision Profile 7.6", `DOVIWithEL`. This profile carries an enhancement layer (EL) that practically only Blu-ray players support. Google TV, webOS and Tizen TVs, streaming boxes and most apps show a black screen or wrong colours.

**Solution:** [dovi_tool](https://github.com/quietvoid/dovi_tool) drops the enhancement layer and converts the metadata to **profile 8.1**.

- The video is remuxed, not re-encoded. It takes a few minutes and quality does not change.
- TVs with Dolby Vision play the result in DV, and other devices play it as plain HDR10.
- Audio, subtitles and chapters are kept as they are.

### Installation

On the server that holds the media files (e.g. a NAS with Docker):

```
cd dovi-web
cp .env.example .env    # Jellyfin URL, API key, MEDIA_DIR
docker compose up -d --build
```

`MEDIA_DIR` is the host folder that your Jellyfin container mounts as `/media`. dovi-web mounts it at the same path, so the paths returned by the Jellyfin API match directly.

If your Jellyfin uses a path other than `/media`, change `MEDIA` in `app.py` and the mount in `compose.yaml`.

UI: `http://<server>:8097`

### Usage

- The list of DV profile 7 files is fetched from Jellyfin automatically.
- **Konwertuj** (Convert): `<name>.P8.mkv` is created next to the original, and Jellyfin refreshes the library. Several conversions go into a queue and run one at a time, with progress and a log.
- **Podmień oryginał** (Replace original): use it after testing on your TV. The P8 file takes over the original's name, and the original is permanently deleted. Because the path stays the same, Jellyfin keeps the watch history, artwork and subtitles.
- You need about **2.1× the file size** of free space: the working file plus the output.

> ⚠️ The UI has no authentication, and "Replace original" deletes files. Run it only on your home network and don't expose the port to the internet.

### Without the UI: `dv7_to_p81.sh`

```
sudo bash dv7_to_p81.sh "/path/to/Movie.mkv"
```

On first run the script builds a `dovi-tools` Docker image (ffmpeg, mkvtoolnix, dovi_tool) and reuses it afterwards. The original file is left untouched.

## Jellyfin API notes

- Newer versions only accept the header `Authorization: MediaBrowser Token="<key>"`. `X-Emby-Token` and `?api_key=` return 401.
- `DELETE /Items/{id}` deletes the file from disk. If the movie is alone in its folder, it deletes the whole folder.
- Collections (box sets) appear in the movie list with a `/config/...` path. The scripts skip them.

## License

[MIT](LICENSE)
