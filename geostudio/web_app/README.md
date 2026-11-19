# GeoStudio 2.0 — osobny prototyp HTML

Nowy interfejs testowy działa **równolegle** z obecnym GeoStudio/PySide6.

## Uruchomienie w Windows

1. Z gałęzi prototypu uruchom dwuklikiem **start_web_ui.bat**.
2. Skrypt używa własnego środowiska **.venv-web** (nie zmienia starego **.venv**).
3. Poczekaj na jednorazową instalację zależności. Powinno pojawić się
   normalne okno Windows (pywebview / Edge WebView2).
4. Kliknij **Otwórz MAP** i wybierz plik z danymi GEO-MAP.
5. Opcjonalnie wybierz **Style JSON**, aby wczytać pasujący plik
   *.MAP.geostudio.json. Jeśli podgląd używa otwartej kopii mapy,
   wybierz styl tej samej kopii.
6. Na mapie działają: kółko myszy, przesuwanie (H), zaznaczanie (S),
   obrót kółkiem przy kursorze, dopasuj widok (0), ukrywanie warstw i
   klasoużytków Ls, etykiety, inspektor i paleta Ctrl+K.

Gdy pywebview/WebView2 nie wyświetla prawidłowo okna, użyj:

    start_web_ui.bat --browser

To uruchomi tę samą lokalną aplikację w domyślnej przeglądarce.
Wymaga Python 3.11+, lokalnego Edge WebView2 dla natywnego okna.

## Stabilność okna Windows (pywebview / WebView2)

Jeśli w starszej wersji GeoStudio 2.0 pojawiał się ciągły log
`[pywebview] Error while processing window.native.AccessibilityObject...`,
`maximum recursion depth exceeded` albo błędy COM związane z wątkiem UI,
przyczyną było publiczne pole `window` w obiekcie `js_api`.

Pywebview automatycznie analizuje publiczne atrybuty tego obiektu
i próbowało przeglądać wewnętrzne właściwości natywnego okna WinForms.
W aktualnym kodzie obiekt `NativeMapPicker` ma jedynie publiczną
metodę `open_map()`. Okno, workspace i ustawienia są prywatne,
a `__slots__` blokuje przypadkowe dodanie publicznych zależności.

Przed testem zamknij wszystkie poprzednie okna GeoStudio 2.0
i uruchom nową wersję z gałęzi PR #50. W nagłówku zobaczysz
`CTRL+H · STABILNOŚĆ — TEST`.

Jeżeli problem nadal występuje, uruchom awaryjnie
`start_web_ui.bat --browser`. Tryb ten nie używa pywebview,
ale zapamiętywanie ostatniego katalogu działa w nim na zasadach
obsługiwanych przez przeglądarkę.

## Etap 4A — zaznaczanie zaawansowane i ostatni folder map

### Ctrl+H — wybór wg kodu, A1 i A2
Wczytaj plik MAP, a potem kliknij **Filtruj** na wstążce
lub naciśnij **Ctrl+H** (w natywnym oknie GeoStudio).

- **Kod:** wybierz np. `5310`; bez innych warunków wybierze wszystkie
  poligony z tym kodem z **całej mapy**, nie tylko z widocznego kadru.
- **A1 / A2:** opcjonalnie zawężają wybór, np. `5310` z `A2` równym
  konkretnej wartości. Można też filtrować tylko po A1/A2 bez kodu.
- **Dokładnie / zawiera:** dopasowanie bez uwzględniania wielkości liter.
- **Zastąp / Dodaj / Odejmij:** operacje na dotychczasowym zaznaczeniu.
- **Ctrl+klik lub Shift+klik:** dodaje albo usuwa wybrany obiekt.
  Kolejne kliknięcia w nakładające się elementy nadal je przełączają;
  kod `5310` ma wyższy priorytet od leżącej pod nim działki.
- Aktywny obiekt ma podświetlone również etykiety **A1 i A2**, o ile
  są widoczne w obecnej skali.

Wyszukiwanie nie zmienia pliku MAP ani historii edycji. Przy ponad
50 000 trafień prosi o doprecyzowanie kryteriów, zamiast zwracać
niepełne zaznaczenie.

### Zapamiętywanie folderu z mapami

**Natywne okno GeoStudio 2.0 uruchamiane przez `start_web_ui.bat`:**
przycisk Otwórz / Ctrl+O używa natywnego dialogu Windows. Po
pomyślnym wyborze MAP zapamiętuje jego katalog w ustawieniach
użytkownika (`%LOCALAPPDATA%\\GeoStudio2\\preferences.json`).
Przy kolejnym otwieraniu, również po restarcie aplikacji,
zaczyna od tego katalogu.

Jest to tylko lokalna preferencja katalogu; nie zapisujemy
w niej danych MAP i nie czytamy automatycznie poprzedniej mapy.
Oryginał i sposób bezpiecznej edycji pozostają bez zmian.

**Tryb `--browser`:** od teraz preferuje stały port localhost
`63871`, żeby Chromium mogło pamiętać folder dla identyfikatora
systemowego okna wyboru plików. Jeśli ten port jest zajęty,
aplikacja wybiera port awaryjny, a przeglądarka może utracić
zapamiętaną lokalizację. W starszych przeglądarkach,
które nie obsługują File System Access API, działa nadal
standardowy wybór pliku bez gwarancji zapamiętania ścieżki.

## Etap 3D — usuwanie wybranego węzła

W trybie **P — Węzły** kliknij pojedynczy istniejący węzeł.
Uchwyt podświetli się na żółto. Naciśnij **Delete** (lub
**Backspace**) albo wybierz **Usuń węzeł** na wstążce.

- **Wspólne węzły wyłączone:** usunięcie jednego P dotyczy tylko
  aktywnego poligonu.
- **Wspólne węzły włączone:** identyczne węzły w sąsiednich
  poligonach **tego samego kodu** są usuwane jednym krokiem.
  Inne kody są zawsze nietykalne.
- **Ograniczenia bezpieczeństwa:** co najmniej trzy niezależne
  wierzchołki, bez duplikatów, z zerwanych domknięć,
  samoprzecięć i niewidocznych łączników P0.
  Niejednoznaczne styki typu T bez odpowiadającego punktu
  na drugim poligonie są blokowane.
- **Ctrl+Z / Ctrl+Y** przywracają lub ponawiają całe usunięcie.
  Wszystkie zmiany pozostają w pamięci do pobrania nowego MAP.

Węzły nie są usuwane przy samym przeciąganiu. Przycisk
**Usuń węzeł** staje się aktywny dopiero po wybraniu konkretnego punktu.

## Etap 3C — dodawanie wierzchołka przez dwuklik

1. Zaznacz zamknięty poligon w trybie **S** i włącz **P — Węzły**.
2. Najedź na **jego obrys** pomiędzy dwoma istniejącymi punktami.
   Na linii pojawi się małe oznaczenie **+**.
3. **Kliknij dwukrotnie** oznaczenie +. GeoStudio wstawi w tym
   miejscu nowy rekord `P` GEO-MAP.
4. Jeśli **Wspólne węzły (ten sam kod)** są włączone i dokładnie
   w tym miejscu istnieje pokrywająca się krawędź innego poligonu
   o tym samym kodzie, dostanie on również nowy wierzchołek.
   Poligon `5220` nigdy nie zostanie zmieniony przy edycji `5310`.
5. **Ctrl+Z** usuwa dodane punkty w jednej operacji,
   **Ctrl+Y** je przywraca. Wyeksportowana kopia `.MAP`
   otrzyma zaktualizowane `N` i `CHK`.

Dwuklik nie przesuwa punktów ani nie przełącza wybranego
obiektu, jeśli jest wykonywany na jego obrysie. Zbyt krótki
segment lub dwuklik tuż przy istniejącym węźle nie tworzy
duplikatu — przybliż mapę i kliknij między wierzchołkami.

Pozycja nowego punktu jest **rzutowana dokładnie na wybraną
krawędź w geometrii źródłowej**, bez przyciągania do innych
kodów. Przy włączonym trybie wspólnym jedynie jednoznaczne,
dokładnie przyległe krawędzie tego samego kodu zostają
podzielone. Wszelkie zmiany nadal są wyłącznie w pamięci.

## Wspólny bok dwóch poligonów tego samego kodu (łączenie T)

W trybie **P / Wspólne węzły** program łączy nie tylko
dwa identyczne węzły `5310 + 5310`. Jeśli węzeł pierwszego
`5310` leży na **boku** drugiego `5310` (a drugi nie ma tam
jeszcze rekordu P), wstawia na tym boku brakujący rekord P i
przesuwa go razem z pierwszym poligonem. Dodanie węzła oraz
przesunięcie obu poligonów to **jedna operacja** historii.

Tryb wspólnych węzłów ogranicza także **przyciąganie** do
tego samego kodu. Nie przyciąga do `5220` i `5230` nawet
gdy te obiekty nakładają się na edytowany `5310`.
Nie przyciąga też węzła do **starej krawędzi sąsiada 5310**,
który ma zostać przesunięty wraz z nim.

W P wybór kolejnych obiektów pozostaje ograniczony do kodu
aktualnie zaznaczonego poligonu; żeby wybrać inny kod,
wróć do narzędzia **S — Zaznacz**.

**Wyjątek:** zmiany są realizowane tylko dla jednoznacznie
sąsiadujących segmentów w granicach dokładności pliku MAP
(około 1,5 mm). Niejednoznaczne, wielokrotne przecięcia
boków są odrzucane, a nie automatycznie poprawiane.

## Bezpieczeństwo: wspólne węzły i różne kody

**Wspólne węzły** nigdy nie powinny zmieniać obiektów o innym kodzie.
Jeśli wybrany jest kod `5310`, przesunięcie wspólnego punktu może
zmienić inne `5310`, ale nie `5220` ani `5230`.

**Przyciąganie** działa niezależnie: węzeł `5310` może zostać
*przyciągnięty do nieruchomego* punktu lub linii `5220`.
To nie oznacza przesunięcia `5220`. Podczas przeciągania zobaczysz
etykietę z kodem obiektu przyciągania; po zakończeniu komunikat
wyświetli kod rzeczywiście zmodyfikowanych obiektów.

Wczytywane pliki GEO-MAP mogą zawierać duplikaty wartości `:ID`.
Pierwotny indeks `GeoMap.by_id` wskazuje w takim przypadku ostatni
rekord o danym ID, także gdy jest innego kodu. W edycji webowej
blokujemy teraz takie niejednoznaczne ID zamiast ryzykować zmianę
niewłaściwego poligonu. Dodatkowo przed edycją i po edycji sprawdzamy
zawartość wszystkich rekordów obiektów o innych kodach. Gdyby
jakikolwiek taki rekord się zmienił, cała transakcja jest wycofywana.

Jeżeli edytor wyświetli **Niejednoznaczny identyfikator :ID**,
nie wymuszaj zapisu: należy zbadać źródłową mapę, aby bezpiecznie
ustalić, które obiekty mają powtórzone identyfikatory.

## Etap 3B — edycja węzłów poligonów

1. Otwórz prawdziwy MAP i kliknij zamknięty poligon.
2. Naciśnij **P** lub wybierz **Węzły** na wstążce.
3. Uchwyty wybranego poligonu są rysowane na mapie. Złap węzeł
   i przeciągnij w nowe miejsce. Kreskowany obrys pokazuje podgląd.
4. **Przyciąganie** (domyślnie włączone) przyciąga do najbliższych
   wierzchołków i krawędzi z całej mapy, także graniczników i
   elementów obecnie niewidocznych na ekranie.
5. **Wspólne węzły (ten sam kod)** (domyślnie wyłączone) włącza
   przesunięcie współrzędnych wszystkich dotykających się węzłów
   **wyłącznie kodu aktualnie edytowanego poligonu**. Poligony
   o innych kodach są chronione, nawet gdy współdzielą narożnik.
6. **Ctrl+Z / Ctrl+Y** cofają i ponawiają całą zmianę jednym krokiem,
   także przy przesunięciu kilku poligonów.
7. **Pobierz kopię** generuje nową mapę z poprawioną sumą kontrolną.

Backend sprawdza poprawność wszystkich zamkniętych poligonów objętych
operacją. Próby utworzenia degeneracji lub nieprawidłowych współrzędnych
są odrzucane bez częściowych zmian. Węzły i geometria są zmieniane
**wyłącznie w pamięci**. Oryginał na dysku nigdy nie jest nadpisywany.

Edycja dotyczy istniejących węzłów oraz dodawania nowych
węzłów na krawędziach zamkniętych poligonów z ID GEO-MAP.
Edycja polilinii i rozbudowane operacje topologiczne
są przewidziane w kolejnych etapach. Przyciąganie wyświetla
podgląd najbliższych obiektów załadowanych w kadrze, natomiast
ostateczne współrzędne potwierdza parser Python na całej mapie.

**Poprawka E:** otwarcie edycji atrybutów skrótem E nie wpisuje
automatycznie litery „e” do pierwszego pola.

## Etap 3A — pierwsze funkcje edycji (testowe)

W GeoStudio 2.0 możesz teraz zaznaczyć obiekt na mapie i otworzyć
**Inspektor → Edytuj** (skrót **E**). Edytowane są wyłącznie **istniejące**
pola A1–A6, TX, MP, KR z identyfikatorem GEO-MAP `:ID`:
nie są dodawane nowe pola, nie można zmienić kodu obiektu ani geometrii.
Wartości muszą dać się zapisać w kodowaniu CP1250; odrzucane są
niedozwolone znaki i zbyt długie dane.

- **Ctrl+Z / Cofnij** i **Ctrl+Y / Ponów** korzystają z dotychczasowego
  silnika historii GeoStudio. Kilka pól obiektu zapisanych naraz to
  **jedna operacja cofania**.
- **Pobierz kopię** generuje nowy plik
  `Nazwa_GeoStudio2_kopia.MAP` z poprawionymi `N` i `CHK`,
  ale **nie zapisuje nic na dysku po stronie serwera**.
  Przeglądarka pyta o miejsce lub używa katalogu Pobrane.
- Oryginał MAP jest nietknięty; wprowadzone zmiany istnieją tylko
  w pamięci aż do pobrania kopii. Zamykanie lub otwieranie innej mapy
  pokazuje ostrzeżenie o niepobranej kopii.
- Nie ma jeszcze edycji węzłów / geometrii ani zapisu oryginału.
  Nie używaj tego prototypu jako jedynego źródła dokumentacji.

**Ważne:** jeśli wczytasz osobny plik stylów `*.geostudio.json`,
pobierany MAP nie zawiera tego sidecara. Stylów nadal należy używać
osobno, wraz z tą samą wersją mapy.

## Co jest naprawdę zaimplementowane

- Otwieranie prawdziwego .MAP przez dotychczasowy parser **GeoMap**.
- Kody i atrybuty obiektów, warstwy, widoczność Ls / LsV / LsVI itd.
- HTML Canvas 2D z geodezyjnym układem widoku (poziomo Y, pionowo -X),
  viewportem pobierającym tylko pobliskie geometrie przez istniejący
  **GeometryIndex**, obsługą pan / zoom i lokalnym hit-testingiem.
- Kontury, uproszczone kolory wypełnień i etykiety, z uwzględnieniem
  opcjonalnego sidecara wizualnego GeoStudio.
- Inspektor kodu, pól opisowych, punktów i powierzchni geometrycznej,
  a także zaznaczanie (również zatrzymane B).
- Wszystko działa bez zewnętrznych CDN i bez wysyłania danych mapy
  do chmury. FastAPI nasłuchuje wyłącznie na losowym porcie
  **127.0.0.1**, z lokalnym tokenem żądania.
- Otwarty źródłowy plik `.MAP` nigdy nie jest nadpisywany;
  nowe pola atrybutów modyfikujemy tylko w kopii w pamięci.

## Jak porównać nową i starą mapę?

1. W starym GeoStudio wykonaj **Zapisz jako**, jeśli pasek tytułowy
   pokazuje gwiazdkę `*` (niezapisane zmiany). Porównuj dokładnie
   ten sam zapisany `.MAP` w obu aplikacjach.
2. Jeżeli korzystasz z indywidualnych kolorów i etykiet, w nowej wersji
   wczytaj osobno **Style JSON** (`*.geostudio.json` tej samej mapy).
3. Graniczniki domyślnie są wyłączone, ale można je włączyć z panelu warstw.
4. Kolory granic pochodzą z oryginalnego GEO-MAP COLORREF. Wypełnienie
   pojawia się tylko wtedy, gdy wynika z natywnego stylu MAP, reguły
   leśnej albo jawnej zmiany w pliku stylów; nie wymuszamy już niebieskiego
   wypełnienia wszystkich działek.
5. Wypełnienia są rysowane pod wszystkimi granicami, a etykiety
   odpowiednio do skali (napisy tytułowe z wysokości A1 w jednostkach mapy).
   Klikanie i powiększanie nie edytują źródłowego MAP.

**Ograniczenia zgodności:** Stare GeoStudio może korzystać z osobnych
bibliotek `.LAY`, `.CDF`, `.SYM`, przechowywanych poza plikiem MAP.
Ten prototyp jeszcze ich nie importuje, więc nazwy warstw, hatchowanie,
znaki geodezyjne oraz niektóre grubości i symbole mogą wciąż różnić się
od klasycznego renderer Qt. Dokładna zgodność kartograficzna wymaga
podłączenia tych samych bibliotek i testów na tej samej wersji mapy.

## Celowo NIEZAIMPLEMENTOWANE w tym etapie

- Usuwanie węzłów, rysowanie nowych poligonów, zapisywanie oryginału MAP,
  import WMS, eksport wielkoformatowy, pełne renderowanie symboli
  .SYM/.LAY/.CDF, raster i georeferencja.
- PixiJS/WebGL: Canvas 2D jest pierwszym rendererem do sprawdzenia
  geometrii, orientacji i kontroli na prawdziwych plikach. Rendering
  GPU jest zaplanowany jako wymienny adapter w następnym etapie.
- Wczytywanie oryginalnych bibliotek .SYM, .LAY i .CDF.
  Obecnie warstwy bazują na podstawowych kodach obiektów.
- Synchronizacja zaawansowanych sesji wielozakładkowych z PySide6.
- Trwałe zapisywanie zmian wyglądu w web UI.

To jest **wyłącznie podgląd testowy**, nie zamiennik GeoStudio
przy przygotowywaniu dokumentacji geodezyjnej.

## Dlaczego bezpiecznie?

Python wczytuje wybrane pliki do pamięci, nie przyjmuje ścieżek plików
przez API i nie oferuje endpointu zapisu MAP. Oryginalne PySide6
uruchamiasz nadal przez start_windows.bat.

## Sposób testowania

    py -m pip install -e ".[dev]"
    py -m pytest -q tests/test_web_preview.py

Dla lokalnego testu bez pywebview:

    python -m geostudio.web_app --browser
