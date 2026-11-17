# GeoStudio — projekt nowoczesnego edytora map geodezyjnych

**Wczesny prototyp v0.13.0 — wersja testowa, nie do dokumentacji urzędowej ani produkcyjnej.**

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
  Ich styl i położenie nie są jeszcze zgodne 1:1 z GEO-MAP.
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

## Zmiany sterowania v0.4 — QGIS-like

- **S / zaznaczanie**: kolejne zwykłe kliknięcia w tym samym miejscu przełączają nakładające się obiekty (w tym `5216` i `5230`). Kliknięcie w innym miejscu zaczyna od pierwszego dopasowania.
- **Kółko myszy**: obrót rolki powiększa lub pomniejsza mapę we wszystkich trybach; **przytrzymanie środkowego przycisku** przesuwa mapę bez zmiany narzędzia.
- **P / poligon**: klikaj wierzchołki, a następnie kliknij **pierwszy wierzchołek** (po co najmniej trzech różnych punktach), naciśnij **Enter**, użyj prawego przycisku albo przycisku **✓ Zakończ poligon**. Poligon zostanie zamknięty i pojawi się pytanie o etykietę A2. Po zatwierdzeniu powstanie nowa kopia robocza mapy `*_GeoStudio_robocza.MAP` w tym samym katalogu. Oryginalny plik nie jest nadpisywany.
- **E / wierzchołki**: przeciągaj zielone uchwyty, aby przesuwać wierzchołki; kliknij w środek krawędzi istniejącego poligonu, aby **wstawić nowy wierzchołek**, zachowując jej przebieg. Po zmianie narzędzie E pozostaje aktywne, a kopia robocza jest aktualizowana.
- Funkcja automatycznego zapisu kopii jest eksperymentalna. Zawsze otwórz kopię w GEO-MAP i sprawdź poprawność zmian, powierzchni i atrybutów. **Nie zastępuj map wykorzystywanych operacyjnie** bez niezależnej kontroli geodezyjnej.

### Proste uruchamianie i aktualizacja na Windows

Po jednorazowym sklonowaniu prywatnego repozytorium za pomocą Git (wymaga uwierzytelnienia):

```powershell
git clone https://github.com/wskakuj/GeoStudio.git
cd GeoStudio
.\setup_windows.bat
```

Przy kolejnych wersjach uruchamiaj tylko `update_windows.bat` — skrypt wykonuje bezpieczne `git pull --ff-only`, aktualizuje zależności i uruchamia program. Kopie pobrane przez **Download ZIP nie zawierają `.git`** i nie mogą korzystać z `git pull`; w takim przypadku zacznij od powyższego `git clone`.

## v0.5 — dopracowanie edycji, atrybutów i wieloczęściowych obiektów

- **Przybliżanie przy kursorze:** rolka zachowuje współrzędne punktu pod myszką,
  również w trybie zaznaczania, rysowania i edycji.
- **Nowy poligon:** po zakończeniu rysowania otwierany jest formularz z polami
  A1–A6, TX, MP, DT i KR. Możesz zostawić je puste, a po zapisie uzupełnić je
  przez panel atrybutów. Tylko kopia robocza jest zapisywana automatycznie.
- **Delete:** zaznacz obiekt w trybie S, naciśnij Delete i potwierdź usunięcie
  całego rekordu. Obecnie nie ma Ctrl+Z, dlatego zachowuj oryginalny MAP.
- **Widok → Ukryj łączniki między częściami obiektu (P 0):** domyślnie włączone.
  W formacie GEO-MAP P 0 może kończyć podścieżkę obiektu. Dotychczas GeoStudio
  błędnie łączył ją z kolejną podścieżką. Przełącznik wpływa wyłącznie na
  renderowanie, wybieranie i przyciąganie, nie na zapis oryginalnego pliku.
  Przykład: obiekt 5220, A1=105, A2=RV w MOKRA WIEŚ.MAP.
- **Punkt kontrolny:** po każdym usunięciu lub dodaniu obiektu sprawdź kopię
  w oryginalnym GEO-MAP. Nie ma jeszcze gwarancji pełnej zgodności topologii,
  numeracji, powierzchni i atrybutów urzędowych.

**Uwaga:** usuwanie obiektu nie usuwa wspólnych wierzchołków z sąsiednich
obiektów. Nie są także automatycznie przeliczane urzędowe pola A6.

### Aktualizacja programu

Instalacja sklonowana przez Git: uruchom `update_windows.bat`.
Po pobraniu ZIP musisz pobrać ZIP nowej wersji i ponownie zainstalować zależności.

## GeoStudio v0.6 — wygodniejsza edycja i wyszukiwanie

- **Esc podczas rysowania P** cofa wyłącznie ostatnio dodany wierzchołek.
  Ponowne Esc cofa następny; gdy lista jest pusta, narzędzie rysowania pozostaje
  aktywne. Aby wyłączyć rysowanie, wybierz **S — Zaznacz**.
  Do tego samego służy przycisk **↶ Cofnij punkt**.
- **Otwórz MAP** i **Wczytaj biblioteki** pamiętają oddzielnie foldery używane
  ostatnim razem między uruchomieniami (QSettings). Po zmianie komputera ustawienia
  zaczynają się od katalogu domowego.
- Po zamknięciu okien **Warstwy**, **Właściwości**, **Szukaj** i **Pomoc**
  przywróć je małymi przyciskami przy prawej krawędzi programu lub przez
  **Widok → Panele → ...** / **Widok → Przywróć wszystkie panele**.
- Podpisy **5310 (A1 i A2)** są większe, pogrubione i czerwone. Numery działek
  **5216** zachowują poprzednią czcionkę, a opisy użytków **5220/5230**
  są mniejsze i częściowo przezroczyste. To style podglądu GeoStudio.
- **Wypełnienie:** we **Właściwościach** możesz wpisać kolor i krycie
  jako `#RRGGBB@NN`, np. `#D94848@40` = czerwony i 40% krycia;
  dostępna jest też paleta, suwak procentowy i przycisk kopiowania kodu.
  **Zastosuj** zmienia jeden lub wiele zaznaczonych poligonów.
- **Ctrl+klik** dodaje lub usuwa obiekt z zaznaczenia; **Ctrl+H** zaznacza
  wszystkie widoczne obiekty o tym samym czterocyfrowym kodzie, co ostatnio
  wybrany. **Delete** usuwa całą zaznaczoną grupę z kopii roboczej, z jednym
  potwierdzeniem. Nadal nie ma funkcji Cofnij dla usuwania, więc zachowuj
  oryginalne pliki.
- **Ctrl+F** otwiera wyszukiwarkę po kodzie GEO-MAP i dokładnej wartości
  atrybutu (bez rozróżnienia wielkości liter), np. `5310, A1=bx` albo
  `5216, A2=29/16`. Kliknięcie wyniku podświetla obiekt i przybliża mapę;
  przycisk **Zaznacz wszystkie wyniki** pozwala na edycję grupową.

### Ważne: format wypełnień GeoStudio a GEO-MAP

Nie ma jeszcze potwierdzonego sposobu zapisu własnych kolorów przezroczystego
wypełnienia bezpośrednio w formacie GEO-MAP w sposób zgodny 1:1 z oryginałem.
**Własne style nie modyfikują rekordów MAP.** GeoStudio przechowuje je w
towarzyszącym pliku `nazwa.MAP.geostudio.json`, zapisanym obok **nowo
utworzonej kopii roboczej** lub mapy zapisanej przez **Zapisz jako**. Aby
zachować wygląd przy ponownym otwarciu w GeoStudio, przenieś oba pliki.
GEO-MAP nie interpretuje tych ustawień. Brak gwarancji odtworzenia wypełnień
w eksporcie DXF/innym programie.

### Zalecany test na Windows

1. Wprowadź 4 wierzchołki w P, cofnij dwa klawiszem Esc i dokończ poligon.
2. Otwórz mapę z folderu, zamknij aplikację i sprawdź, czy następne Otwórz
   wskazuje ten sam katalog.
3. Zamknij panel Warstwy i przywróć go prawym paskiem przycisków.
4. Wybierz 5310, naciśnij Ctrl+H, zmień kod wypełnienia na
   `#C03030@50`, sprawdź efekt i plik `*.geostudio.json`.
5. Sprawdź wyszukiwanie 5310/A1 oraz 5216/A2, w tym przejście do wyniku.
6. Usuń grupę tylko z **kopii mapy** i sprawdź ją w oryginalnym GEO-MAP.

**To nadal prototyp, nie certyfikowany edytor geodezyjny.**

## GeoStudio v0.7 — kierunek osi jak w GEO-MAP i kontrola etykiet

Porównanie widoków w oryginalnym GEO-MAP i GeoStudio ujawniło zamianę osi
geodezyjnych: oryginalny plik zapisuje X=northing (północ), Y=easting (wschód),
a starszy ekran GeoStudio rysował scenę według X w poziomie, -Y w pionie.

- **Domyślny widok zgodny z GEO-MAP:** ekranowa oś pozioma to Y (wschód), oś
  pionowa skierowana ku górze to X (północ). Zrealizowano to **wyłącznie
  transformacją widoku**, bez przeliczenia punktów, kątów, pól, atrybutów,
  geometrii czy zapisywanego pliku MAP.
- **Obracanie mapy:** w głównym pasku narzędzi są przyciski obrotu **o 15°
  w lewo/prawo** oraz **N ↑ GEO-MAP** (powrót do orientacji geodezyjnej).
  W menu **Widok → Orientacja i obrót mapy** dostępny jest również obrót
  o 90°, starsza orientacja GeoStudio i reset. Skróty:
  `Ctrl+Alt+←`, `Ctrl+Alt+→`, `Ctrl+Alt+0`. Obrót zachowuje środek
  widoku i aktualne powiększenie.
- **Zoom pod kursorem:** obliczenia powiększenia korzystają z długości
  przekształconej jednostki, nie ze współczynnika `m11`, który przy
  obrocie 90° jest równy 0. Działa również przy ukośnej orientacji.
- **Narzędzia GIS:** promień wybierania, przyciągania i dodawania
  wierzchołków obliczany jest z rzeczywistej odległości na ekranie,
  niezależnie od kąta obrotu.
- **Etykiety zależne od skali:** przy oddaleniu napisów 5310 (A1/A2) oraz
  numerów działek nie wyświetla się, dopóki ich geometria nie osiągnie
  wystarczającego rozmiaru na ekranie. Uproszczone wykrywanie kolizji
  uwzględnia wielkość całego tekstu, zamiast pojedynczych komórek 90×26.
  Wybrany obiekt nadal pokazuje etykietę, a **Pokaż wszystkie podpisy**
  umożliwia ręczne wyłączenie ograniczeń.
- **Ograniczenie:** pozostają różnice względem GEO-MAP w rysowaniu
  symboli z SYM, warstw i wypełnień z LAY/CDF, oraz przygotowaniu
  tytułów, tabel i legend. Sama orientacja i skalowanie etykiet nie
  są jeszcze wiernym rendererem tego programu.

### Szybki test

1. Otwórz kopię `MOKRA WIEŚ.MAP`, ustaw **N ↑ GEO-MAP** i **Cała mapa**.
   Porównaj orientację z GEO-MAP na tych samych danych.
2. Obróć ±15° i 90°, następnie zresetuj. Rolką przybliż pod kursor.
3. Przy całej mapie podpisy 5310 nie powinny jej zasłaniać. Po
   przybliżeniu mają stopniowo się pojawiać. Wyszukany/zaznaczony
   obiekt powinien mieć widoczny opis nawet przy oddaleniu.
4. Sprawdź zaznaczanie pod użytkami, przesuwanie węzłów i przyciąganie
   po zmianie orientacji.
5. Jak dotychczas testuj edycję wyłącznie na kopiach; transformacja widoku
   nie wpływa na wartości zapisanych współrzędnych.


## GeoStudio v0.8 — podpisy, domyślne biblioteki i odczyt kolorów

### Przesuwanie napisów A1/A2 na mapie

- Kliknij **✎ Opisy A1/A2 [L]** lub naciśnij `L`, a następnie **przeciągnij
  widoczny napis** myszą. W przypadku obiektu 5310 napisy A1 i A2 są teraz
  **oddzielnymi elementami**, można je przenieść niezależnie.
- `S` wraca do zaznaczania. Zaznaczony obiekt powinien pokazywać obie etykiety,
  nawet jeżeli automatyczne rozrzedzanie usuwa inne opisy na tym poziomie zoomu.
- Przesunięte pozycje zapisywane są jako współrzędne X/Y w pliku
  `nazwa.MAP.geostudio.json` towarzyszącym **kopii roboczej**, nie wewnątrz MAP.
  Nie są obecnie przenoszone do oryginalnego GEO-MAP. Przenosząc kopię na
  drugi komputer, skopiuj oba pliki. Dane źródłowe MAP pozostają nietknięte.
- Poprawiono wzajemne ukrywanie A1 i A2 tego samego obiektu oraz przywracanie
  podpisów po ukrywaniu i ponownym włączeniu warstwy.

### Automatyczne ładowanie bibliotek

- Wybierz własne `.SYM`, `.LAY`, `.CDF` raz przez
  **Plik → Wczytaj biblioteki SYM/LAY/CDF**. GeoStudio zapamięta osobno ich
  pełne ścieżki w **ustawieniach systemowych QSettings** i przy kolejnych
  uruchomieniach wczyta je automatycznie, nawet gdy mapa jest w innym katalogu.
- Umieść biblioteki w stabilnym folderze poza repozytorium, np.
  `C:\\GeoStudio-biblioteki\\GEO-MAP.sym`,
  `GEO-MAP.lay`, `GEO-MAP.CDF`. **Nie zmieniaj folderu po wybraniu
  plików**, albo wskaż je ponownie. W razie braku domyślnej biblioteki
  GeoStudio spróbuje znaleźć odpowiedni plik obok otwieranej mapy.
- Biblioteki są danymi użytkownika i **nie są dołączane do GitHub/repozytorium**.
  Wersje udostępnione przez producenta mogą podlegać oddzielnej licencji.

### Wypełnienia, kolory, znaki

- Odczytane z mapy COLORREF obrysu oraz — tam gdzie występuje — **kolor
  wypełnienia z trzeciego pola nagłówka obiektu** mają pierwszeństwo przed
  dawnym domyślnym półprzezroczystym wypełnieniem.
- Obsługiwany jest wycinek formatu **CDF**: RGB wypełnienia i obrysu,
  szrafura (przybliżone wzory Qt) i dobór stylu po kodzie / atrybutach.
- **SYM**: wczytywane są typy instrukcji graficznych i wyświetlane
  proste odcinki `L` znaków punktowych. Rekurencyjne definicje `O`,
  opisy `T`, krzywe, symbole zależne od skali i obracane znaki nadal
  wymagają implementacji. **LAY** wciąż dostarcza nazwy warstw/kody;
  odwzorowanie wszystkich parametrów piór, linii i tekstów dopiero powstaje.
- Ręczne wypełnienie `#RRGGBB@NN` z panelu właściwości ma pierwszeństwo
  nad domyślnym kolorem z GEO-MAP, ale jest zapisywane **wyłącznie jako
  styl GeoStudio** i nie będzie widoczne w GEO-MAP.

**To nadal renderer częściowy — różnice w kreskowaniu, symbolach, legendzie,
opisach arkusza i zachowaniu plików mogą być znaczące.** Wszystkie prace
geodezyjne i zapisane kopie weryfikuj w oryginalnym GEO-MAP.

### Test v0.8

1. Załaduj biblioteki raz, zamknij i ponownie uruchom program.
   Sprawdź, czy mapa otwarta z innego folderu ma zdefiniowane warstwy.
2. Wybierz `5310`, przybliż obiekt, naciśnij `L` i przesuń **oddzielnie A1
   i A2**. Sprawdź, czy po ponownym otwarciu kopii roboczej oba napisy
   zachowują pozycję.
3. Wyłącz i włącz warstwę — opisy widocznych obiektów powinny powrócić,
   a podpisy A1/A2 jednego obiektu nie powinny wzajemnie się ukrywać.
4. Porównaj obiekty z wypełnieniami `5310` i klasyfikację z oryginalnym
   GEO-MAP. Jeśli różnica dotyczy szrafury, symbolu lub legendy, zapisz
   zrzut obu programów przy tej samej skali i orientacji.


## GeoStudio v0.9 — stały rozmiar napisów i dokładniejsze kolory

- **Wielkość napisów na ekranie jest stała podczas przybliżania i oddalania**
  mapy — tekst pozostaje w pikselowym rozmiarze i nie jest skalowany razem
  z geometrią (Qt `ItemIgnoresTransformations` + `QFont.setPixelSize`).
  Budynki 5310 mają czerwone, pogrubione podpisy A1/A2 (16 px),
  działki 5216 mają neutralne numery (12 px), użytki 5220/5230
  zielone, subtelniejsze opisy (11 px). Dotyczy widoku; nie modyfikuje
  formatowania oryginalnego GEO-MAP.
- Aby napisy **nie zasłaniały mapy przy oddaleniu**, silnik nadal ogranicza
  **liczbę widocznych napisów** zależnie od powiększenia i kolizji.
  To nie jest zmiana wielkości czcionki. Wybrany obiekt zachowuje etykietę.
  W menu Widok → `Pokaż wszystkie podpisy` można wyłączyć ograniczenie.
- Kontury z definicji CDF uwzględniają szerokość linii ograniczoną do
  bezpiecznego zakresu 0.8–3 px, bez zwiększania szerokości podczas zoomu.
  Dotychczasowe natywne wypełnienia, RGB i częściowe szrafury z CDF/SYM
  pozostają włączone.
- **Wierność wyglądu jest nadal częściowa**: oznaczenia w SYM, style
  linii w LAY, drukowane legendy i skomplikowane szrafury potrzebują dalszej
  implementacji oraz porównania z oryginalnym GEO-MAP.
- Test automatyczny w Qt sprawdza identyczny wymiar ekranu napisu przy
  zoomie 3× i 0.11× oraz kolory/pióra odczytane z CDF.

### Sprawdź w Windows
1. Otwórz `MOKRA WIEŚ.MAP` z tymi samymi bibliotekami.
2. Powiększ i pomniejsz obiekt 5310: wielkość jego A1/A2 powinna być
   taka sama w pikselach, choć liczba widocznych podpisów może się zmieniać.
3. Zweryfikuj kolor zielonych użytków, czerwonych budynków i grubości konturów
   względem mapy otwartej w GEO-MAP. Oryginalne pliki pozostają nietknięte.


## GeoStudio v0.10 — granice działek nad wydzieleniami

Porównanie zrzutów MOKRA WIEŚ.MAP w GEO-MAP i GeoStudio wykazało
problem kolejności malowania: wcześniej kolor dużego wydzielenia był
nakładany zgodnie z kolejnością rekordów MAP i zasłaniał linie działek.

- Renderowanie odbywa się teraz w osobnych płaszczyznach:
  **wypełnienia poligonów** są rysowane pod spodem, **kontury**
  nad nimi, z pierwszeństwem granic działek 5216. Następnie znaki
  punktowe i napisy A1/A2. Włączanie/wyłączanie warstw ukrywa
  zarówno wypełnienia, powiązane linie, jak i etykiety.
- Granice działek 5216 pozostają widoczne nawet pod całkowicie
  nieprzezroczystym wydzieleniem 5310.
- LAY pozostaje źródłem parametrów pióra; dokładniejszy wzór konturu
  jest teraz odczytywany z makr SYM: 5220 przez O 4003, 5230 przez
  O 4002, 5216 przez 4216 → 4001. W prostych przykładach kreski i
  przerwy mają proporcje 2:1 lub 1:1; rzeczywiste odstępy w pikselach
  pozostają przybliżone. Gdy biblioteka SYM nie podaje rozpoznawalnego
  wzoru, dla LAY 2.008 pozostaje awaryjna linia przerywana Qt.
- Symbole z SYM: rysowanie zweryfikowanych instrukcji A pełnych
  okręgów, np. dwóch współśrodkowych pierścieni dla granicznika
  1246. Zmniejszono wielkość domyślnych kropek, gdzie nie
  rozpoznano znaku.
- Zmiany **nie modyfikują danych MAP, geometrii ani powierzchni**
  i nie zmieniają plików bibliotecznych.

### Sprawdź na Twojej mapie
1. Uruchom GeoStudio v0.10 i załaduj MOKRA WIEŚ.MAP z bibliotekami
   SYM, LAY, CDF (zapamiętanymi przez GeoStudio).
2. Odszukaj dużą jednolicie wypełnioną powierzchnię na zrzutach.
   **Linie działek powinny pozostać na wierzchu**.
3. Wyłącz i włącz warstwy działek oraz wydzieleń. Sprawdź zaznaczanie
   i przyciąganie oraz odczyt mapy w oryginalnym GEO-MAP.
4. Porównaj graniczniki 1246 i kontury klasyfikacyjne 5220.

**Ograniczenia:** Kolory części wydzieleń mogą się jeszcze różnić
od oryginalnego GEO-MAP. Złożone makra O / opisy T z SYM, pełne
legendy, arkusze i nieudokumentowane style linii nie zostały
odtworzone w tej wersji.


## GeoStudio v0.11 — opisy jak na mapie, skala 1:N i transformacje

### Napisy A1/A2 i numery działek — skala mapowa

- Zmieniono sposób wyświetlania wszystkich podpisów z dotychczasowego
  `ItemIgnoresTransformations` na **rozmiar związany ze współrzędnymi mapy**.
  Przy oddalaniu podpisy zmniejszają się **razem z geometrią**, a przy
  przybliżaniu rosną dokładnie tak jak mapa. Nie występuje efekt pozornie
  rosnącego tekstu na malejącej działce.
- **Wyłączono automatyczne ukrywanie podpisów** ze względu na skalę lub
  nakładanie się na inne napisy. Tekst będzie obecny nawet na dużych
  oddaleniach, choć może stać się drobny w pikselach. Widok → Podpisy
  A1/A2 pozwala jedynie ukryć wszystkie opisy ręcznie.
- Zachowano czerwony, pogrubiony 5310 (A1, A2), numery działek 5216,
  zielone opisy użytków 5220/5230 oraz możliwość przesuwania A1/A2
  narzędziem **L**.
- Przesuwanie A1/A2 rozpoznaje teraz rzeczywisty obszar napisu po
  przekształceniu i aktualnym obrocie mapy.

### Skala widoku 1:N

- W dolnym pasku znajduje się edytowalne pole **Skala widoku: 1:N**,
  np. `1:500`, `1:1000`, `1:2000`, `1:5000`.
- Można również użyć **Widok → Ustaw skalę widoku 1:N…** lub
  **Ctrl+M**. Zmiana skali zachowuje środek mapy i jej obrót.
- Wartość skali automatycznie aktualizuje się przy używaniu rolki i
  przycisku Cała mapa. Obliczana jest z układu w metrach i
  **logicznego DPI ekranu Qt**.
- **Ważne:** jest to przybliżona **skala widoku na ekranie**,
  **nie ustawienie skali urzędowego wydruku**. Dokładne skalowanie
  wydruków wymaga osobnego modułu druku.

### Układy współrzędnych

- W menu **Trans → Przelicz współrzędne / eksportuj kopię MAP…**
  pojawił się kalkulator, używający `pyproj` (biblioteki PROJ).
- Dostępne:
  - PL-1992 / 19° **EPSG:2180**
  - PL-2000 strefy 5,6,7,8 **EPSG:2176–2179**
  - Historyczne układy 1965 strefy I–V **EPSG:2171–2175**
    tylko dla pojedynczych punktów, z ograniczeniami wynikającymi
    z transformacji historycznych i wymaganej dokładności.
- Przyjmujemy kolejność **GEO-MAP: X (północ) i Y (wschód)**;
  `pyproj` ma `always_xy=True` (wschód, północ), więc osie są
  świadomie zamieniane podczas przeliczania.
- Gdy oryginalny `.MAP` ma wiarygodny sąsiedni `.prj`, program
  odczytuje układ automatycznie; bez niego **użytkownik musi ręcznie
  potwierdzić źródłowy EPSG**. Program **nie zgaduje układu** na
  podstawie podobieństwa współrzędnych.
- **Nowa kopia MAP:** eksport całej mapy z PL-1992 do PL-2000
  (i odwrotnie, oraz między strefami 2000) jest na razie
  **eksperymentalny**. Przeliczane są wszystkie rekordy `P`,
  aktualizowany jest prosty zakres `EXT` i suma kontrolna `CHK`.
  Tworzony jest osobny plik `.MAP` i `.prj` z układem docelowym.
  Oryginalne pliki nigdy nie są nadpisywane.
- **Ostrzeżenie geodezyjne:** elementy arkusza (legenda, tabela),
  georeferencja rastrów, miary powierzchni zapisane w atrybutach
  oraz nieznane typy rekordów **nie są kompleksowo obsługiwane**.
  Konwersja całej MAP może zmienić pozycje obiektów arkusza;
  wszystkie dane wymagają porównania w GEO-MAP przed zastosowaniem
  w jakichkolwiek pracach.
- Warszawa 25/75, lokalny Poznań oraz niejednoznaczne warianty
  Układu 1942 **nie są pozornie przeliczane**: należy najpierw
  ustalić oficjalne parametry i osnowę odniesienia.

### Test na Windows

1. Otwórz kopię MOKRA WIEŚ.MAP i zrób duże oddalenie. Napisy
   pozostają na mapie i maleją razem z nią — nie znikają z powodu
   algorytmu automatycznego rozrzedzania.
2. Sprawdź przybliżanie i zmiany skali przez wpisanie 1:1000, 1:2000,
   1:5000. To nie zmienia źródłowych współrzędnych.
3. W Trans przelicz znany punkt X/Y z PL-1992 do PL-2000 strefy 7
   i z powrotem. Wynik porównaj z GEO-MAP.
4. Eksport całej mapy wykonuj **wyłącznie na kopii do testów**.
   Sprawdź jej geometrię, punkty wspólne, powierzchnie, elementy
   legendy i tabele. Nie używaj eksperymentalnego wyniku do pracy
   urzędowej bez walidacji.


## GeoStudio v0.12 — czytelne, nieodbite podpisy A1/A2

Naprawiono błąd zgłoszony po v0.11 na `MOKRA WIEŚ_EPSG2178.MAP`:
napisy przy poprawnej orientacji geodezyjnej były odwrócone/lustrzane.

- Napisy `A1` i `A2` budynków 5310, numery działek 5216 oraz opisy
  użytków 5220/5230 są **zawsze poziome i czytane od lewej do prawej**;
  obrót, lustrzane przekształcenie lub przełączenie orientacji GEO-MAP
  nie obraca samych znaków pisma.
- Zachowano **rozmiar związany ze skalą mapy**: podczas oddalania napisy
  maleją razem z geometrią, a podczas przybliżania rosną razem z nią.
  Nie działa automatyczne ukrywanie ze względu na skalę ani kolizje.
  Ukrycie warstwy lub ręczne wyłączenie podpisów nadal działa.
- Mechanizm: Qt `ItemIgnoresTransformations` neutralizuje obrócenie i
  odbicie liter; aktualizacja widoku ustawia rozmiar etykiety na iloczyn
  `0.55 × powiększenie widoku`. Ustawienie dotyczy wyłącznie **widoku**,
  nie zmienia współrzędnych, atrybutów ani formatu `.MAP`.
- Działają nadal oddzielne pozycje podpisów A1/A2 (`L`), obrót widoku,
  zoom rolką oraz skala `1:N` w dolnym pasku.

### Test na Windows

1. Otwórz `MOKRA WIEŚ_EPSG2178.MAP` lub oryginalną mapę.
2. Sprawdź `5310`, numery działek i `RV` — litery powinny być normalne,
   nieobrócone i nieodbite, niezależnie od orientacji mapy.
3. Przybliż i oddal kilka razy rolką, wpisz `1:1000` i `1:5000`:
   proporcje napisów do geometrii powinny pozostać takie same.
4. Obróć mapę o 15° i 90°, użyj `N ↑ GEO-MAP` i przesuń A1/A2
   narzędziem L. W razie różnic zrób zrzut ekranu.


## GeoStudio v0.13 — zakotwiczone napisy i odtworzenie elementów arkusza

Na podstawie rzeczywistego `MOKRA WIEŚ.MAP` i bibliotek
`GEO-MAP(3).SYM/.LAY/.CDF` (nieprzekazywanych do repozytorium):

- **Koniec przesuwania się podpisów przy zmianie zoomu.** Każdy podpis
  A1/A2, numer działki i napis legendy ma punkt zakotwiczenia w
  współrzędnych mapy. Renderer kompensuje odbicie i obrót wyłącznie
  w orientacji glifów; tekst nie przeskakuje, pozostaje normalnie
  czytelny i zmniejsza się/rośnie **razem z mapą**. Nie jest ukrywany
  automatycznie przy oddalaniu.
- **5214 (granica obrębu):** odtwarzana jest linia przerywana według
  makra `4010` z `.SYM` (proporcja kreska/przerwa 3:2).
  Dodatkowo może być widoczna nazwa obrębu z atrybutu A3.
- **6900:** napisy `N`, `S`, `E`, `W` oraz oznaczenia `1`,
  `2`, `3` pojawiają się w miejscu ich rekordów P i mają
  wielkość wynikającą z źródłowego pola `A1`, zamiast rysowania
  niewidocznych symboli.
- **Tytuł, legenda i wykonawca:** kody `7900`, `6000` oraz
  `6301` używają teraz źródłowej treści `TX` i nominalnej
  wielkości `A1`; separator `||` wyświetlany jest jako kilka
  oddzielnie wyśrodkowanych linii. Nie rysuje się już fałszywych
  kresek pod tekstem pomiędzy dwoma punktami P.
- **Róża wiatrów:** cztery trójkątne ćwiartki `5200` z
  `:FA[0]` są wypełnione na ciemno, zamiast pozostawać
  białymi obrysami.

**Zakres:** poprawiono wyświetlanie w GeoStudio, bez modyfikowania
oryginalnego `.MAP`. Proporcje/krój tekstów i bardziej złożone
elementy arkusza wciąż mogą się różnić od oryginalnego GEO-MAP.
Nie jest to pełny interpreter firmowych makr graficznych.

### Test na Windows

1. Otwórz `MOKRA WIEŚ.MAP`, przybliż i oddal numer działki,
   `5310` A1/A2 i tytuł arkusza. Zawartość tekstu nie może
   przesuwać się względem jego współrzędnych (nie licząc
   zamierzonego odstępu A1/A2).
2. Porównaj granicę obrębu `5214` (symbol `4010`).
3. Sprawdź znak północy i duże litery N/S/E/W (`6900`).
4. Porównaj tytuł, wiersze legendy i podpis agencji (`7900`,
   `6000`, `6301`). Zwróć uwagę na skalę czcionki i przerwy
   między wierszami; zrzuty przy tej samej skali pomogą dopracować
   te parametry.
