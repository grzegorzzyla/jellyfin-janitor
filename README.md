# jellyfin-janitor

**Polski** · [English](README_en.md)

Narzędzia do porządków w bibliotece [Jellyfin](https://jellyfin.org) przez jego API:

- **wyszukiwanie duplikatów filmów** (SD/720p obok wersji 1080p+) i ich bezpieczne usuwanie,
- **poprawianie źle rozpoznanych filmów** (przypisanie właściwego TMDB),
- **konwersja Dolby Vision profil 7 → 8.1** bez przekodowania obrazu, żeby remuxy UHD Blu-ray działały na telewizorach i przystawkach.

Wszystko jest dostępne na **stronie w przeglądarce** (`web/`, Docker) oraz jako skrypty w Pythonie, które korzystają tylko z biblioteki standardowej (Python 3.9+), więc nie trzeba nic instalować.

## Zawartość

| Plik | Co robi |
|---|---|
| `find_dupes.py [lista.json]` | Raport duplikatów. Tylko odczyt. Opcjonalnie zapisuje listę gorszych wersji do usunięcia. |
| `delete_items.py lista.json` | Usuwa pozycje z listy (wpis w bibliotece **i plik na dysku**). Najpierw pokazuje listę i pyta o `tak`. |
| `identify.py <item_id> <tmdb_id>` | Przypisuje filmowi właściwy identyfikator TMDB i pobiera metadane. |
| `web/` | Strona w przeglądarce: Dolby Vision, duplikaty, rozpoznanie (Docker). |
| `dv7_to_p81.sh <plik.mkv>` | Konwersja DV z wiersza poleceń, na serwerze z plikami. |
| `jellyfin.py` | Wspólny klient API używany przez skrypty. |

## Strona w przeglądarce (`web/`)

Trzy zakładki:

- **Dolby Vision** – lista plików w DV profil 7, konwersja do 8.1 z kolejką i postępem, podmiana oryginału ([szczegóły niżej](#dolby-vision-profil-7--81)).
- **Duplikaty** – grupy filmów z kilkoma wersjami.
  - Gorsze wersje (poniżej 1080p obok HD) i identyczne kopie są zaznaczone od razu, ale zaznaczenie możesz zmienić.
  - Strona nie pozwoli usunąć wszystkich wersji filmu ani wersji scalonych.
  - Ostrzega, gdy razem z plikiem zniknie cały folder.
- **Rozpoznanie** – lista filmów, które mogą być źle rozpoznane: rok w nazwie pliku inny niż w Jellyfin albo wersje o różnej długości. Osobno są filmy bez TMDB/IMDb. Każdy film możesz wyszukać w TMDB (z plakatami) i przypisać jednym kliknięciem.

### Instalacja

Na serwerze, na którym leżą pliki (np. NAS z Dockerem):

```
cd web
cp .env.example .env    # adres Jellyfin, klucz API, MEDIA_DIR
docker compose up -d --build
```

`MEDIA_DIR` to folder na hoście zamontowany w kontenerze Jellyfin jako `/media`. Strona montuje go pod tą samą ścieżką, dzięki czemu ścieżki z API Jellyfin pasują wprost.

Jeśli Twój Jellyfin używa innej ścieżki niż `/media`, zmień `MEDIA` w `dv.py` i montowanie w `compose.yaml`.

Strona: `http://<serwer>:8097`

> ⚠️ Strona nie ma logowania i potrafi usuwać pliki. Uruchamiaj ją tylko w sieci domowej i nie wystawiaj portu na zewnątrz.

## Konfiguracja skryptów

1. W Jellyfin: **Panel sterowania → Klucze API → +**.
2. Skopiuj `config.example.json` do `config.json` i wpisz adres serwera oraz klucz.

```
cp config.example.json config.json
```

`config.json` jest w `.gitignore`.

## Duplikaty

```
python3 find_dupes.py do_usuniecia.json   # raport + lista do usunięcia
# przejrzyj raport, w razie potrzeby popraw do_usuniecia.json
python3 delete_items.py do_usuniecia.json
```

Jak działa raport:

- Filmy są grupowane po identyfikatorze **TMDB**, potem **IMDb**, a w ostateczności po tytule i roku.
- **Jakość jest oceniana po szerokości obrazu**, a nie wysokości, bo film kinowy 1920×800 to nadal 1080p.
- Do usunięcia trafiają wersje poniżej 1080p, ale tylko w grupach, w których jest też wersja 1080p lub lepsza. Grupy z samymi wersjami HD skrypt tylko pokazuje i niczego w nich nie wybiera.
- Przy każdej wersji jest jej długość. **Różna długość w jednej grupie** zwykle oznacza źle rozpoznany film, a nie duplikat. Napraw go przez `identify.py`.
- **`[sam w folderze]`**: film jest jedynym plikiem w swoim folderze. Jellyfin usunie wtedy **cały folder**.
- **`[scalone]`**: kilka plików Jellyfin połączył w jeden film z wyborem wersji. Usunięcie takiej pozycji przez API może skasować wszystkie wersje. Bezpieczniej usunąć plik ręcznie.

> ⚠️ Usuwanie przez API Jellyfin jest **trwałe** – pliki nie trafiają do kosza systemu/NAS-a.

## Źle rozpoznany film

```
python3 identify.py <item_id> <tmdb_id>
```

`item_id` jest w adresie strony filmu w Jellyfin (`…/details?id=…`), a `tmdb_id` w adresie filmu na themoviedb.org.

Częsta przyczyna złego rozpoznania: Jellyfin rozpoznaje film po nazwie folderu. Przykład: plik `Blade.Runner.2049…mkv` w folderze `Blade Runner/` zostanie rozpoznany jako film z 1982 roku.

## Dolby Vision profil 7 → 8.1

**Problem:** remuxy UHD Blu-ray mają często Dolby Vision **profil 7**. W Jellyfin wygląda to tak: „Dolby Vision Profile 7.6”, `DOVIWithEL`. Ten profil ma dodatkową warstwę (EL), którą obsługują praktycznie tylko odtwarzacze Blu-ray. Telewizory z Google TV, webOS i Tizen, przystawki i większość aplikacji pokazują czarny ekran albo złe kolory.

**Rozwiązanie:** [dovi_tool](https://github.com/quietvoid/dovi_tool) odrzuca warstwę EL i konwertuje metadane do **profilu 8.1**.

- Obraz nie jest przekodowywany, tylko przepakowywany. Trwa to kilka minut, a jakość się nie zmienia.
- Telewizor z Dolby Vision gra w DV, a pozostałe urządzenia w zwykłym HDR10.
- Audio, napisy i rozdziały przechodzą bez zmian.

### Użycie (zakładka Dolby Vision)

- Lista plików w DV profil 7 jest pobierana z Jellyfin automatycznie.
- **Konwertuj**: obok oryginału powstaje `<nazwa>.P8.mkv`, a Jellyfin odświeża bibliotekę. Kilka konwersji trafia do kolejki i idzie po kolei. Widać postęp i log.
- **Podmień oryginał**: używasz po teście na telewizorze. Plik P8 przejmuje nazwę oryginału, a oryginał zostaje trwale usunięty. Ścieżka się nie zmienia, więc w Jellyfin zostają historia oglądania, okładki i napisy.
- Potrzeba około **2,1× rozmiaru pliku** wolnego miejsca: plik roboczy plus wynik.

### Bez strony: `dv7_to_p81.sh`

```
sudo bash dv7_to_p81.sh "/ścieżka/do/Film.mkv"
```

Przy pierwszym uruchomieniu skrypt buduje obraz Dockera `dovi-tools` (ffmpeg, mkvtoolnix, dovi_tool), a potem z niego korzysta. Oryginał zostaje nietknięty.

## Ciekawostki z API Jellyfin

- Nowsze wersje przyjmują tylko nagłówek `Authorization: MediaBrowser Token="<klucz>"`. `X-Emby-Token` i `?api_key=` zwracają 401.
- `DELETE /Items/{id}` usuwa plik z dysku. Jeśli film leży sam w folderze, usuwa cały folder.
- Kolekcje (boxsety) pojawiają się na liście filmów ze ścieżką `/config/...`. Skrypty je pomijają.

## Licencja

[MIT](LICENSE)
