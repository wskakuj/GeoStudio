# GeoStudio — projekt nowoczesnego edytora map geodezyjnych

**Wczesny prototyp v0.3.0 — wersja testowa, nie do dokumentacji urzędowej ani produkcyjnej.**

GeoStudio ma docelowo umożliwiać edycję plików GEO-MAP `.MAP` z zachowaniem
katalogów `.SYM`, `.LAY`, `.CDF`, a także pomiary, rastry, eksporty DXF/VAL
oraz nowoczesny interfejs Windows.

## Co działa w prototypie

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

## Poprawki interakcji w v0.2 (do testów)

- **Zaznaczanie nakładających się obiektów:** kliknięcie preferuje działkę `5216`, a **Alt+klik** przełącza kolejne obiekty pod kursorem (w tym użytek `5230`).
- **Zaznaczony obiekt:** pomarańczowy kontur po rzeczywistych odcinkach, bez prostokątnej ramki Qt.
- **Podpisy:** `5310` wyświetla `A1` i `A2`, natomiast `5216` i `5230` pokazują `A2`. Włączają się po przybliżeniu, aby przy widoku całej mapy nie zasłaniały geometrii. Położenie i style napisów są nadal przybliżone.
- **Rysowanie:** klawisz `P`, wybór czterocyfrowego kodu, kliknięcia wierzchołków, podgląd rysowanej linii, przyciąganie do istniejących punktów i odcinków w promieniu 12 pikseli. Prawy przycisk zamyka; `Esc` anuluje.
- **Edycja istniejących poligonów:** zaznacz zamknięty poligon i naciśnij `E`; przeciągnij zielony uchwyt wierzchołka (z przyciąganiem do innych obiektów). `Esc` kończy tryb. Na razie obsługiwane jest tylko **przesuwanie** wierzchołków, nie ich dodawanie/usuwanie.
- **Zapis:** wyłącznie *Zapisz jako* do nowego pliku. Zmieniona geometria zachowuje nieedytowane rekordy i etykiety punktów, ale zapis nie jest jeszcze zweryfikowany w GEO-MAP.

Testy na plikach użytkownika potwierdziły zachowanie checksum `CHK`, zamknięcia poligonu i pozostałych atrybutów po przesunięciu punktu dla dwóch plików testowych. GUI wymaga niezależnej weryfikacji na Windows; testy Qt w CI używają `offscreen`.


## v0.3: interakcje na wzór QGIS

- **Zaznacz [S]** — kliknięcie wybiera rzeczywisty obiekt na podstawie jego
  geometrii; nie opiera się na widocznym kształcie obiektu Qt. Działka `5216`
  ma pierwszeństwo względem pokrywających ją użytków. **Alt+klik** przełącza
  trafione obiekty, a **prawy przycisk** wyświetla ich listę do wyboru.
  Z menu nad mapą można ograniczyć wybór tylko do działek lub użytków.
- **Przesuń [H]** — osobny tryb nawigacji, dzięki czemu kliknięcie obiektu nie
  zostaje zinterpretowane jako początek przeciągania mapy.
- **Poligon [P]** — wyraźny podgląd obrysu i znacznik każdego wprowadzonego
  wierzchołka; lewy przycisk dodaje punkty, prawy kończy, Esc anuluje.
- **Wierzchołki [E]** — po zaznaczeniu zamkniętego poligonu można przeciągać
  jego zielone węzły; wczytywany rekord `P` jest zachowywany, a przy zapisie
  aktualizowane są dane węzła. Zmiany testuj wyłącznie na kopii `.MAP`.
- **Przyciąganie** — osobny przełącznik; domyślnie włączone, do wierzchołków
  i odcinków widocznych obiektów (12 px).
- **Podpisy A1/A2** — osobny przełącznik, domyślnie włączone; `5310` pokazuje
  A1+A2, `5216` i `5230` pokazują A2, o ile pole występuje w pliku. Podpisy
  nie znikają na podstawie arbitralnego współczynnika zoom. Widoczne etykiety
  są rozrzedzane, żeby się nie nakładały; podpis zaznaczonego obiektu ma priorytet.
  W menu Widok jest dodatkowe polecenie „Pokaż wszystkie podpisy”, które
  wyłącza rozrzedzanie (może powodować nakładanie tekstu). Ich styl i położenie
  nie są jeszcze zgodne 1:1 z GEO-MAP.
- **Dopasuj mapę** — bierze pod uwagę geometrię, a nie wielkości podpisów w
  pikselach; poprawia również wiarygodność testów kliknięć.

### Scenariusz testowy v0.3 (Windows)

1. Uruchom program, otwórz kopię `MOKRA WIEŚ.MAP` i katalogi `.SYM/.LAY/.CDF`.
2. Kliknij `S`, następnie kliknij działkę wewnątrz użytku. `Alt+klik` oraz
   prawy przycisk powinny dać dostęp do obydwu obiektów. W razie potrzeby
   wybierz z listy `Działki 5216`.
3. Sprawdź na różnych przybliżeniach podpisy obiektów `5310`, `5216` i `5230`.
   Zaznaczenie obiektu pokazuje także jego pola w panelu właściwości.
4. Kliknij `P`, wybierz kod `5216`, wskaż trzy różne punkty i zakończ prawym
   przyciskiem. Gdy pojawi się okno A2, wpisz testowy opis.
5. Kliknij `S`, zaznacz istniejący zamknięty poligon, potem `E` i przeciągnij
   zielony wierzchołek. Esc przywraca tryb zaznaczania.
6. Użyj **Zapisz jako** z nową nazwą. Otwórz kopię w GEO-MAP i porównaj
   zachowanie na zapisanym obiekcie oraz na innych warstwach.

**Istotne ograniczenia:** to nie jest jeszcze QGIS ani gotowy silnik GEO-MAP.
Narzędzia nie mają pełnej walidacji topologii sąsiednich działek, automatycznej
edycji wspólnych granic, dodawania/usuwania węzłów ani zgodności podpisów
`.SYM`. Automatyczne testy UI korzystają z Qt `offscreen`; wymagane są testy
manualne na Windows i w oryginalnym GEO-MAP. **Nigdy nie nadpisuj oryginałów.**
