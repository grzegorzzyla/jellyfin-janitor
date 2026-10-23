#!/bin/bash
# Konwersja Dolby Vision profil 7 (UHD BluRay remux) -> profil 8.1, bez przekodowania obrazu.
# Odpala sie na NAS-ie (przez SSH). Narzedzia (ffmpeg, mkvtoolnix, dovi_tool) sa w obrazie Dockera
# "dovi-tools", ktory przy pierwszym uruchomieniu jest budowany i zostaje na NAS-ie na kolejne razy.
#
# Uzycie:  sudo bash dv7_to_p81.sh "/volume1/.../Film.mkv"
# Wynik:   obok oryginalu powstaje "Film.P8.mkv". Oryginal zostaje nietkniety.
# Nowa wersja dovi_tool: sudo docker rmi dovi-tools  (zbuduje sie od nowa z DOVI_VERSION ponizej)
set -euo pipefail

DOVI_VERSION="2.3.4"
IMAGE="dovi-tools"

IN="${1:?Podaj sciezke do pliku .mkv}"
[ -f "$IN" ] || { echo "Nie ma pliku: $IN"; exit 1; }
DIR="$(cd "$(dirname "$IN")" && pwd)"
NAME="$(basename "$IN")"
OUT="${NAME%.mkv}.P8.mkv"
TMP=".${NAME%.mkv}.p81.hevc"
[ -e "$DIR/$OUT" ] && { echo "Plik wynikowy juz istnieje: $DIR/$OUT"; exit 1; }

# Potrzeba miejsca na tymczasowy strumien wideo + nowy plik: ~2,1x rozmiaru oryginalu
SIZE_KB=$(du -k "$IN" | cut -f1)
FREE_KB=$(df -k --output=avail "$DIR" | tail -1)
NEED_KB=$((SIZE_KB * 21 / 10))
echo "Plik: $((SIZE_KB / 1048576)) GB | wolne: $((FREE_KB / 1048576)) GB | potrzeba: $((NEED_KB / 1048576)) GB"
[ "$FREE_KB" -ge "$NEED_KB" ] || { echo "Za malo miejsca."; exit 1; }

if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  echo "== Budowanie obrazu $IMAGE (tylko za pierwszym razem)"
  docker build -q -t "$IMAGE" --build-arg DOVI_VERSION="$DOVI_VERSION" - <<'DOCKERFILE'
FROM debian:bookworm-slim
ARG DOVI_VERSION
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends ffmpeg mkvtoolnix curl ca-certificates \
 && curl -fsSL "https://github.com/quietvoid/dovi_tool/releases/download/${DOVI_VERSION}/dovi_tool-${DOVI_VERSION}-x86_64-unknown-linux-musl.tar.gz" \
    | tar -xz -C /usr/local/bin \
 && rm -rf /var/lib/apt/lists/* \
 && dovi_tool --version && mkvmerge --version
WORKDIR /work
DOCKERFILE
fi

docker run --rm -v "$DIR":/work -e NAME="$NAME" -e OUT="$OUT" -e TMP="$TMP" \
  "$IMAGE" bash -euo pipefail -c '
    trap "rm -f \"$TMP\"" EXIT

    FPS=$(ffprobe -v error -select_streams v:0 -show_entries stream=r_frame_rate -of default=noprint_wrappers=1:nokey=1 "$NAME")
    echo "== Klatki/s: $FPS"

    echo "== 1/2 Wyciaganie wideo i konwersja RPU do profilu 8.1 (bez warstwy EL)"
    ffmpeg -v error -stats -i "$NAME" -map 0:v:0 -c:v copy -bsf:v hevc_mp4toannexb -f hevc - \
      | dovi_tool -m 2 convert --discard - -o "$TMP"

    echo "== 2/2 Skladanie MKV: nowe wideo + audio, napisy i reszta z oryginalu"
    mkvmerge -q -o "$OUT" --language 0:und --default-duration "0:${FPS}p" "$TMP" -D "$NAME"

    chown "$(stat -c %u:%g "$NAME")" "$OUT"
    echo "== Gotowe: $OUT"
  '

echo "Nowy plik: $DIR/$OUT"
echo "Odswiez biblioteke w Jellyfin i sprawdz na TV. Oryginal mozna usunac dopiero po tescie."
