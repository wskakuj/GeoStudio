# GeoStudio

Nowoczesny, niezależny edytor map geodezyjnych. **Prototyp v0.1 — nie do dokumentacji urzędowej ani pracy produkcyjnej.**

Cel projektu: edycja tekstowych plików GEO-MAP `.MAP`, katalogi `.SYM`, `.LAY`, `.CDF`, warstwy, atrybuty, poligony, pomiary, rastry, kalibracja, transformacje współrzędnych i eksport DXF, VAL oraz TIFF/JPG.

## Aktualny zakres prototypu

- Odczyt tekstowego GEO-MAP v8 z zachowaniem nieznanych rekordów, ID, kodów, atrybutów i współrzędnych.
- Weryfikacja kontrolnej MD5 `CHK`, liczby wierszy `N`, podstawowy odczyt bibliotek.
- GUI Windows w Pythonie i PySide6: podgląd mapy, wybieranie obiektów, warstwy, atrybuty, proste rysowanie poligonów i powierzchnia planimetryczna.
- Eksperymentalny zapis pod nową nazwą, DXF i eksport obrazu; rastry z istniejącą georeferencją.
- Testy parsera i diagnostyka CLI.

## Czego brakuje

Pełnej zgodności wizualnej symboli GEO-MAP, kalibracji rastra, transformacji układów współrzędnych, eksportu VAL, pełnego DXF, edycji wierzchołków i arkuszy do wyłożenia z tabelami. Poprawność zmodyfikowanych `.MAP` **nie jest jeszcze potwierdzona w GEO-MAP**. Pola obliczone z współrzędnych mogą różnić się od ewidencyjnych wartości `#POLE`.

## Uruchomienie

Wymaga Python 3.11+ na Windows:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m geostudio
```

Diagnostyka bez GUI: `python -m geostudio.inspect "C:\\mapy\\przyklad.MAP"`.

## Ochrona danych

Nie dodawaj do repozytorium rzeczywistych map i bibliotek `.MAP`, `.SYM`, `.LAY`, `.CDF`, `.VAL` bez weryfikacji praw i poufności. Oryginalne mapy pozostaw niezmienione, zapisuj pod nową nazwą i porównuj wynik z licencjonowanym GEO-MAP.

Zobacz dokumentację w katalogu `docs/`.