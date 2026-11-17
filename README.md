# GeoStudio — projekt nowoczesnego edytora map geodezyjnych

**Wczesny prototyp v0.1.0; nie do dokumentacji urzędowej ani produkcyjnej.**

GeoStudio ma docelowo umożliwiać edycję plików GEO-MAP `.MAP` z zachowaniem
katalogów `.SYM`, `.LAY`, `.CDF`, a także pomiary, rastry, eksporty DXF/VAL
oraz nowoczesny interfejs Windows.

## Co działa w v0.1

- Otwieranie tekstowych plików GEO-MAP `ver=[8.00]` w kodowaniu Windows-1250;
  odczyt wszystkich rekordów, atrybutów `A1..A6`, `TX`, `KR`, identyfikatorów i wierzchołków.
- Zachowanie nieznanych rekordów w oryginalnej postaci (bez prób ich interpretacji).
- Weryfikacja sumy `CHK` (MD5 wszystkich bajtów poza pierwszym wierszem) i liczby wierszy `N`.
- Widok dużych map, zoom kółkiem myszy, przesuwanie, zaznaczanie obiektów.
- Lista grup/warstw z `.LAY`, nazwy obiektów z `.SYM`, podstawowy odczyt palety `.CDF`.
- Podgląd i edycja wybranych atrybutów, w tym uwag `TX`.
- Wyświetlanie planimetrycznego pola zamkniętych wieloboków na podstawie wierzchołków.
- Eksperymentalne rysowanie wieloboków kodem GEO-MAP.
- `Zapisz jako` z aktualizacją `N` i `CHK`, bez nadpisywania plików wejściowych.
- Uproszczony eksport DXF (wierzchołki i warstwy); obraz do JPG/PNG, TIFF jeśli Qt obsługuje.
- Wczytywanie rastrów z plikiem georeferencyjnym `.tfw/.jgw/.wld` itp.
- Diagnostyka CLI niewymagająca Qt: `python -m geostudio.inspect ...`.

## Czego jeszcze NIE ma

- Pełnej zgodności wyglądu ze znakami `.SYM` (prymitywy, linie, kreskowanie, rotacje,
  podpisy, style i skale); obecny renderer jest poglądowy.
- Potwierdzonej zgodności zmodyfikowanych map z GEO-MAP po ponownym otwarciu.
- Edycji poszczególnych wierzchołków istniejących obiektów (na razie nowe poligony i atrybuty).
- Kalibracji rastera z punktów dostosowania; wczytujemy wyłącznie istniejącą georeferencję.
- Eksportu VAL w formacie GEO-MAP ani obliczania użytków z przecięć działek.
- Transformacji współrzędnych z walidacją układów, współczynników i odwzorowań.
- Zaawansowanego składu arkuszy do wyłożenia: ramki, tabele, legendy, skala,
  podział arkuszy, marginesy i układ strony A0/A1/A2/A3/A4.
- Wiernego eksportu DXF wszystkich symboli oraz atrybutów i niezawodnego TIFF na każdym systemie.

**Nie traktuj wpisów `#POLE` jako automatycznie równych pomiarom z geometrii:**
`#POLE` może być polem ewidencyjnym, zaokrąglonym lub przeliczonym wg innych zasad.
Program pokazuje planimetryczny wynik z wierzchołków (m², ha), a nie równoważnik
powierzchni urzędowej. Układ odniesienia nie jest automatycznie zgadywany.

## Instalacja Windows (PowerShell)

Wymaga **Python 3.11+**. Wypakuj projekt, otwórz terminal w katalogu `GeoStudio`:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
python -m geostudio
```

W razie blokady wykonywania `Activate.ps1` możesz wywołać bezpośrednio
`.\.venv\Scripts\python.exe -m pip install -e .`, a potem
`.\.venv\Scripts\python.exe -m geostudio`.

Po otwarciu `.MAP` użyj **Plik → Wczytaj biblioteki SYM/LAY/CDF…**.
Możesz też uruchomić program ze ścieżką mapy:

```powershell
python -m geostudio "C:\\mapy\\przyklad.MAP"
```

Szybka analiza pliku bez uruchamiania GUI:

```powershell
python -m geostudio.inspect "C:\\mapy\\przyklad.MAP"
```

## Bezpieczeństwo danych i testowanie

- Trzymaj oryginalne pliki map w osobnym katalogu, poza repozytorium.
- Repozytorium z kodem można opublikować, ale pliki `.MAP/.SYM/.LAY/.CDF/.VAL`
  użytkownika nie powinny znaleźć się w repozytorium bez sprawdzenia praw i prywatności.
- **Zapisuj tylko pod nową nazwą**. Użyj licencjonowanego GEO-MAP, aby
  porównać każdy zapisany obiekt, atrybut, opis i warstwę z oryginałem.
- Testy na syntetycznych plikach: `python -m pytest -q`.

## Roadmap / etapy rozwoju

1. Solidny odczyt wszystkich elementów map (w tym tabel i elementów poza mapą),
   renderer prymitywów `.SYM`, prawidłowe kolory i styl linii, legenda.
2. Bezpieczny round-trip `.MAP` testowany na realnych kopiach oraz edycja wierzchołków,
   obiektów i atrybutów z Undo/Redo i kontrolą topologii.
3. Raster: kalibracja 3+ punktami kontrolnymi, GeoTIFF, transformacje EPSG/PROJ,
   korekty odwzorowawcze powierzchni.
4. Eksport DXF pełnej geometrii i etykiet; raport/eksport `.VAL`; druk/wyłożenie,
   tabele, ramki, eksport PDF/TIFF/JPG w skali.
5. Indeksy przestrzenne, szybkie renderowanie dużych map, instalator Windows,
   testy regresyjne na syntetycznych wzorcach.

## Licencja kodu

Ten prototyp można rozwijać jako osobny projekt; przed publiczną publikacją
należy świadomie wybrać licencję i sprawdzić prawa do własnego kodu oraz zależności.
Nie dołączono oryginalnych plików i bibliotek GEO-MAP.
