# Praca dwóch asystentów AI nad jednym repozytorium

Dokument opisuje uzgodniony sposób pracy, gdy nad GeoStudio równolegle
pracuje więcej niż jeden asystent AI oraz człowiek- właściciel projektu.
Obowiązuje wszystkich, niezależnie od tego, kto pisze kod.

## Zasady nadrzędne

1. Gałąź `main` jest zawsze w stanie, który przechodzi testy. Nikt nie commituje
   bezpośrednio na `main`.
2. Przed rozpoczęciem zadania sprawdź aktualny stan `main` (`git fetch`, `git log`)
   oraz otwarte Pull Requesty. Jeżeli ktoś inny pracuje nad tym samym plikiem,
   ustal kolejność przed napisaniem kodu.
3. Każde zadanie dostaje własną gałąź i własny Pull Request.
4. Zmiany trafiają wyłącznie na gałąź zadania.
5. Pull Requesta nie scala asystent. Scala go właściciel repozytorium po akceptacji.
6. Kod drugiego asystenta nie jest usuwany ani nadpisywany bez analizy i zgody.
7. Jeżeli `main` zmieni się w trakcie pracy, zsynchronizuj gałąź
   (`git fetch origin && git rebase origin/main`) i ponownie uruchom testy.
8. Do repozytorium nie trafiają prywatne mapy, firmowe biblioteki GEO-MAP,
   klucze API ani żadne dane użytkownika.
9. Format `.MAP` i geometria nie mogą zostać zmienione w sposób zrywający
   zgodność z GEO-MAP. Pracuj na kopiach; oryginałów nigdy nie nadpisuj.

## Nazewnictwo gałęzi

| Prefiks | Zastosowanie | Przykład |
|---|---|---|
| `ai2/feat-…` | nowa funkcja | `ai2/feat-undo-redo` |
| `ai2/fix-…` | poprawka błędu | `ai2/fix-legenda` |
| `ai2/test-…` | wyłącznie testy i infrastruktura testowa | `ai2/test-infra-fixtures` |
| `ai2/docs-…` | wyłącznie dokumentacja | `ai2/docs-collaboration` |

Prefiks `ai2/` jednoznacznie oznacza autora zmian i pozwala odróżnić gałęzie
od tych tworzonych przez drugiego asystenta.

## Podział pracy: które pliki są "gorące"

Ryzyko konfliktu rośnie z rozmiarem pliku i liczbą osób, które go dotykają.
Stan na v0.14.0:

| Plik | Rozmiar | Ryzyko | Uwaga |
|---|---|---|---|
| `geostudio/app.py` | ~2 300 linii, ~95 metod w jednej klasie | **wysokie** | każda zmiana UI tu trafia |
| `geostudio/geomap.py` | ~380 linii | średnie | rdzeń formatu, wymaga ostrożności |
| `tests/*` | ~10 plików | niskie | nowe pliki testowe prawie nie kolidują |
| `docs/*` | małe | niskie | |

Praktyczna reguła: **zadania infrastrukturalne i testowe pisz jako nowe pliki.**
Zmiany w `app.py` planuj pojedynczo, jedno zadanie naraz, i informuj o nich
w opisie Pull Requesta, zanim ktoś inny zacznie pracę w tym samym obszarze.

## Protokół zgłaszania kolizji

W opisie każdego Pull Requesta podaj:

- które pliki zmieniasz (lista),
- czego **nie** zmieniasz, choć mogłoby się wydawać, że wypada,
- czy w `main` są otwarte zmiany w tych samych plikach.

Jeżeli dwa zadania dotykają tego samego fragmentu `app.py`, pierwszeństwo ma
to, które zostało zgłoszone wcześniej. Drugie czeka na scalenie pierwszego
albo przenosi pracę do nowego modułu.

## Dług techniczny do zaplanowania wspólnie

`app.py` w obecnym kształcie jest głównym źródłem konfliktów. Docelowy podział
na moduły (kolejność proponowana, każdy krok osobny Pull Request):

1. `scene_builder.py` — budowa sceny QGraphicsScene z `GeoMap` (bez UI).
2. `map_tools.py` — zaznaczanie, przyciąganie, przesuwanie etykiet, rysowanie.
3. `sheet_layout.py` — ramka, legenda, tabelka, skala opracowania.
4. `exporters.py` — DXF, obraz, raster.
5. `main_window.py` — samo okno i menu, spinające powyższe.

Dopiero po tym podziale dwa zadania mogą iść naprawdę równolegle bez konfliktów.

## Wymagania wobec Pull Requesta

- `python -m compileall -q geostudio` przechodzi.
- `python -m pytest -q` przechodzi w całości (CI uruchamia też `tests/test_gui.py`
  z `QT_QPA_PLATFORM=offscreen`).
- Nowe funkcje mają testy; poprawki błędów mają test odtwarzający błąd.
- Opis zawiera: co zmieniono, jak to sprawdzono, jakie są ograniczenia
  i czego świadomie nie zrobiono.
- Brak plików `.MAP`, `.SYM`, `.LAY`, `.CDF`, `.VAL` i danych osobowych.
