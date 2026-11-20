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

## Awaryjne otwieranie mapy — Z dysku

Od tej poprawki w nagłówku jest dodatkowy przycisk **Z dysku**.
Bezpośrednio otwiera ukryte pole `input type=file` poprzez etykietę HTML;
nie korzysta z `pywebview.api`, niezależnych wątków, Tk ani WebView2 COM.
W razie awarii lub braku dialogu wybierania przez **Otwórz MAP** można
zawsze kliknąć **Z dysku**, wczytać MAP i kontynuować edycję.

**Otwórz MAP** w natywnym oknie pywebview korzysta teraz z krótkotrwałego
dialogu Tk/Windows, który jest tworzony oraz niszczony na tym samym wątku
wywołania, zapamiętuje ostatni katalog w
`%LOCALAPPDATA%\\GeoStudio2\\preferences.json`. Nie korzysta już z
`Window.create_file_dialog`, którego wywołanie mogło przestać pokazywać
okno lub zawieszać UI. Jeśli Tk/Python nie ma obsługi dialogów,
próba daje czytelny błąd i należy kliknąć **Z dysku**.

Zamknięcie okna, pliki źródłowe i zapis pozostają bez zmian.

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

## Etap 4B — zbiorowa edycja atrybutów A1 i A2

1. Otwórz MAP, użyj **Ctrl+H** i zaznacz np. wszystkie obiekty `5310`
   albo wyłącznie `5310` z określoną wartością A2. Możesz też
   dodać kilka elementów przez Ctrl+klik.
2. Kliknij **Zbiorowo A1/A2** na wstążce lub **Ctrl+Shift+E**.
3. Zaznacz checkbox przy **A1**, **A2** albo przy obu. Wprowadź nowe
   wartości. Puste pole po zaznaczeniu checkboxa **celowo czyści
   istniejącą wartość** — nie usuwa samego atrybutu.
4. Kliknij **Sprawdź zmiany**. Zobaczysz liczbę zaznaczonych obiektów,
   liczbę faktycznych zmian, kod(y), brakujące pola (pominięte),
   wartości już zgodne oraz przykłady **przed / po**.
5. Jeśli wszystko się zgadza, kliknij **Zastosuj zmiany**.
   Przy 100+ obiektach pojawia się dodatkowe potwierdzenie.
6. **Ctrl+Z** cofa **całą serię** jako jedną operację, **Ctrl+Y**
   ją ponawia. **Pobierz kopię** eksportuje osobny MAP.

Zasady bezpieczeństwa:

- Co najwyżej **5 000 obiektów na jedną serię**. Dla większych zbiorów
  zawęź wybór w Ctrl+H i podziel pracę na partie.
- Edycja obejmuje **wyłącznie jawnie zaznaczone obiekty**.
  Nie wolno automatycznie zmieniać wszystkich obiektów tego samego kodu.
- Jeśli na niektórych obiektach nie istnieje pole A1 lub A2, program
  **pomija brakujące pole**, wskazując liczbę pominiętych w podglądzie.
  Nie dodaje nowych atrybutów do GEO-MAP.
- Przed jakąkolwiek zmianą sprawdza format CP1250, długość, niepowtarzalne
  ID, wersję mapy oraz identyczność zakresu i wartości względem podglądu.
- Po modyfikacji porównuje pełne rekordy wszystkich niezaznaczonych
  obiektów. Każdy nieoczekiwany zapis oznacza cofnięcie całej transakcji.
- Oryginalny plik nigdy nie jest nadpisywany.

**Status:** funkcja nadal weryfikowana na rzeczywistych plikach przed
scaleniem PR do `main`.

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
przycisk Otwórz / Ctrl+O używa niezależnego dialogu Tk/Windows
(nie zależy od natywnych obiektów WebView2). Po
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

- Nadpisywanie oryginału MAP, import WMS, eksport wielkoformatowy,
  pełne renderowanie symboli
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
przez HTTP API i nie oferuje serwerowego endpointu zapisu MAP do dysku.
W natywnym oknie pywebview użytkownik wybiera ścieżkę **Zapisz jako**;
oryginalny plik wejściowy nie może zostać nadpisany.
Oryginalne PySide6 uruchamiasz nadal przez start_windows.bat.

## Sposób testowania

    py -m pip install -e ".[dev]"
    py -m pytest -q tests/test_web_preview.py

Dla lokalnego testu bez pywebview:

    python -m geostudio.web_app --browser


## Test 5A/5B — przesuwanie, nowe poligony i zapis Windows

- **M**: przeciągnij jeden lub wiele zaznaczonych poligonów; wyświetli się
  podgląd przed zatwierdzeniem. **Ctrl+Shift+M**: dokładne przesunięcie X/Y.
  Wspólne granice ze statycznym poligonem tego samego kodu blokują ruch,
  dopóki nie zaznaczysz świadomego rozłączenia. W wersji 6A/6B
  poligony tego samego kodu mogą nachodzić na siebie: dolny ma
  odwracalną maskę, bez utraty oryginalnych punktów.
- **Przyciąganie do granicy** (domyślnie zaznaczone): dla małych odchyleń
  snapuje całą grupę do bliskiej krawędzi; nie wykonuje automatycznej
  operacji unii ani rozpuszczenia poligonów. Wyłącz, aby podać dokładne X/Y.
- **Ctrl+D**: skopiuj zaznaczone poligony. Każda kopia ma nowy :ID, zachowuje
  pierwotny kod, styl, atrybuty i flagi P; Ctrl+D umieszcza kopię obok
  i aktywuje M, aby można było od razu przeciągnąć ją myszą.
- **Ctrl+Delete**: usuń obiekty z zaznaczenia po potwierdzeniu.
- **N**: rysuj nowy poligon kliknięciami. **Enter** lub dwuklik kończy obrys,
  **Esc** anuluje. Wybierz kod i opcjonalne A1/A2, kliknij
  **Sprawdź obrys**, potem **Utwórz poligon**.
- **Pobierz kopię**: w aplikacji Windows otwiera natywne **Zapisz jako**,
  z wyborem katalogu i końcową pełną ścieżką pliku. W samodzielnej
  przeglądarce używa systemu pobierania przeglądarki (zazwyczaj
  **Pobrane**, skrót Ctrl+J) i nie zapisuje automatycznie w katalogu MAP.
- Jeśli pasek narzędzi nie mieści się w oknie, przewijaj poziomo po
  sekcjach **Projekt / Nawigacja / Widok mapy / Edycja węzłów**.

Operacje pozostają na osobnej gałęzi testowej. Zweryfikuj eksportowane
pliki MAP w klasycznym programie przed wykorzystaniem do pracy.


## Etap 6A — odwracalne wycinanie i geometria (test)

1. **Przesuwanie (M)**: gdy nałożysz poligon na drugi poligon tego samego
   kodu, GeoStudio 2.0 obliczy obrys widocznej części tego drugiego jako
   różnicę geometryczną. Jego oryginalne wierzchołki pozostają zachowane.
   Kiedy odsuniesz górny poligon, dolny odzyskuje obrys. Ctrl+Z/Y obejmuje
   zarówno ruch, jak i kolejność nakładania. Początkowa wspólna granica
   niezaznaczonego sąsiada nadal domyślnie chroniona przed rozłączeniem.
2. **Magnetyczne przyciąganie**: pomarańczowy znacznik węzła/krawędzi.
   Przyciąganie działa tylko do NIEZAZNACZONYCH poligonów TEGO SAMEGO KODU.
   Wyłączyć można „Przyciąganie” w narzędziach geometrii.
3. **Ctrl+D**: zaznacz poligon, naciśnij skrót; kopia pojawi się obok,
   będzie zaznaczona i od razu aktywuje się M. Następnie przeciągnij kopię
   myszą. Ctrl+K -> „Kopiuj z dokładnym przesunięciem” pozostaje dostępne.
4. **Pole +**: zaznacz poligon (np. 5310/A1=xd/A2=So03) i kliknij
   narzędzie. Zapisana kopia MAP będzie miała w tym obiekcie dodatni
   zwrot obrysu, a powierzchnia w klasycznym GEO-MAP powinna być dodatnia.
   Nowe poligony mają orientację dodatnią już przy tworzeniu.
5. **Scal** (Ctrl+Shift+G): w etapie 6B wynik może zawierać
   kilka rozłącznych wysp lub styk tylko w węźle. Jedna grupa ma jeden
   :ID, ten sam kod oraz jednakowe A1/A2. Powierzchnia jest sumowana.
6. **Podziel** (Ctrl+Shift+X): wybierz jeden poligon, klikaj linię cięcia
   zaczynając i kończąc poza jego obrysem, Enter/dwuklik, podgląd,
   zatwierdzenie. Podział tworzy nowe ID.
7. **L**: narysuj linię, Enter/dwuklik otwiera formularz kodu i A1/A2.
   **Shift+L** po zaznaczeniu linii pozwala narysować jej nowy przebieg.

**UWAGA O EKSPORCIE:** odwracalny widok wycięć jest funkcją GeoStudio 2.0,
nie natywną zmianą geometrii w MAP. Natywne Windows **Zapisz jako**
tworzy plik MAP zawierający bazowe wierzchołki oraz dodatkowy plik
\`.geostudio-topology.json\` (zapisany z taką samą nazwą bazową).
**Zachowaj i otwieraj oba pliki razem**. Sam plik MAP otwarty w
klasycznym GEO-MAP w tym etapie pokaże poligony bazowe, bez odwracalnej
maski. Klasyczna zgodność trwale wyciętej geometrii to przyszły etap 6B.
Nie stosuj masek z 6A jako dokumentacji ewidencyjnej bez walidacji.

Przy scalaniu i podziale zachowywane są atrybuty pierwszego obiektu,
ale wartości powierzchni ewidencyjnych w polach A4/A6 nie są automatycznie
aktualizowane — należy je sprawdzić ręcznie w klasycznym programie.
To samo dotyczy specyficznych kodów i stylów używających nietypowych
wieloczęściowych rekordów P0, których nie zmieniamy w tym etapie.


## Etap 6B — natywne kontury MAP i automatycznie dodatnie pola (test)

**Scalanie:** Zaznacz dwa lub więcej poligonów **jednego kodu i o
jednakowych A1/A2**. Ctrl+Shift+G / „Scal” tworzy jeden rekord
GEO-MAP (jedno :ID) również wtedy, gdy poszczególne wyspy nie mają
wspólnej krawędzi ani wierzchołka, albo dotykają się tylko punktem.
Wiele konturów jest zapisywanych osobnymi komponentami z flagą końca
komponentu **P 0**. Nie dodajemy sztucznych odcinków łączących wyspy.
Działa Cofnij/Ponów. Wartości ewidencyjne A4/A6 pozostają do sprawdzenia.

**Dodatnie pola automatycznie:** Rysowanie nowych obrysów, kopiowanie
prostych obrysów oraz zapisywanie MAP w natywnym Windows **Zapisz jako**
stosuje dodatnią orientację prostych, zamkniętych poligonów niezależnie
od kierunku kliknięć. Dotyczy to również prostych starych poligonów
w nowej zapisywanej kopii. Źródłowy MAP nadal jest chroniony.
Dla wieloczęściowych obiektów orientacja poszczególnych obrysów pozostaje
odpowiednia: obwody zewnętrzne dodatnie, otwory ujemne.
Przycisk „Pole + (stare)” to wyłącznie pomocnicza ręczna naprawa
oryginalnego obrysu w pamięci.

**Dwa tryby eksportu Windows:**

- **„Pobierz kopię”**: zapisuje zwykły MAP, normalizuje dodatnią
  orientację prostych obrysów, a odwracalne nałożenia zachowuje przez
  plik \`.geostudio-topology.json\` v1 (bez wycinania źródłowych konturów).
- **„Zapisz wycięcia 6B”**: oblicza prawdziwe różnice geometryczne
  nakładających się poligonów **tego samego kodu** i zapisuje ich
  obcięte obrysy (wieloczęściowe kontury i otwory) w nowej kopii
  GEO-MAP \`.MAP\`. Zachowuje wszystkie kody nieobjęte maską.
  Jednocześnie zapisuje powiązany SHA256 plik
  \`.geostudio-topology.json\` v2 z oryginalnymi rekordami P.
  Przy ponownym otwarciu obu plików w GeoStudio 2.0 program odtwarza
  **oryginalne, niewycięte kontury** w pamięci i nakłada maski ponownie.
  Odczyt bez JSON pokazuje wycięte kontury zapisane w MAP.

**Bezpieczeństwo:** eksport 6B wymaga nowej nazwy (nie nadpisuje
istniejącej pary), przygotowuje oba pliki przed zatwierdzeniem i
sprawdza CHK, liczbę wierszy, identyfikatory, sumę powierzchni oraz
poprawność otworów po zakodowaniu z dokładnością do 1 mm.
Nie usuwa obiektu całkowicie przykrytego — taki eksport jest blokowany,
aby nie utracić jego :ID. Obsługa tego przypadku pozostaje na 6C.
Zachowaj **oba pliki**, najlepiej dodatkowo osobną kopię oryginału.

**Ograniczenie zgodności:** implementacja flag P0 i kierunku obrysu
wynika z konwencji parsera GEO-MAP, ale wymaga jeszcze ręcznego
testu otwarcia i sprawdzenia obiektów wieloczęściowych oraz otworów w
klasycznym programie GEO-MAP. Nie traktuj eksportu 6B jako zweryfikowanej
dokumentacji ewidencyjnej. Podział złożonych otworów,
automatyczne wartości A4/A6 i eksport obiektów całkowicie zakrytych
nie są jeszcze obsługiwane.

**Test Windows:**
1. Zaznacz dwa budynki 5310 o tych samych A1/A2, nieprzylegające do
   siebie lub stykające się w jednym węźle; kliknij **Scal**.
2. Obejrzyj wieloczęściowy obrys i powierzchnię, wykonaj Cofnij/Ponów.
3. Narysuj drugi poligon wewnątrz pierwszego, przesuń górny (M),
   kliknij „Zapisz wycięcia 6B”. Zapisz nowy MAP + JSON.
4. Sprawdź wycięty obiekt w klasycznym GEO-MAP, w tym powierzchnię.
5. Otwórz ponownie zapisany MAP w GeoStudio 2.0 razem z JSON:
   pełny obrys dolnego poligonu powinien zostać odtworzony,
   a wycięcie ponownie obliczone i pokazane na ekranie.
6. Sprawdź dodatnią powierzchnię nowo narysowanego poligonu przy
   zwykłym „Pobierz kopię”. Nie trzeba używać przycisku „Pole +”.


## Etap 7 — kartografia LAY/CDF/SYM, natywne etykiety i automatyczne wycięcia

### Etykiety A1/A2 po scaleniu GEO-MAP 5310

Klasyczny GEO-MAP używa **osobnych rekordów L 1/L 2/L 3**
dla położenia natywnych napisów. Samo zachowanie A1/A2 nie wystarcza.
W scaleniu jednego kodu i identycznych atrybutów GeoStudio:
- zachowuje rekordy L z obiektu zachowanego jako :ID i pierwszy
  punkt/referencyjną wyspę tak stabilnie, jak pozwala wynik unii;
- jeśli brak części L, pobiera zgodne rekordy z pozostałych scalanych
  poligonów przed ich usunięciem;
- gdy żadna część nie posiada L, tworzy pełny zestaw w formacie
  zaobserwowanym w oryginalnym GEO-MAP v8;
- nowo narysowane poligony 5310 z A1/A2 również otrzymują L.
Nie zmienia się kod, wartość A1/A2 ani niezaznaczone obiekty.
**Do ręcznego sprawdzenia w klasycznym GEO-MAP**, szczególnie
złożone obiekty rozłączne — rekordy L zawierają także informacje
o zakotwiczeniu napisów i mogą wymagać dodatkowego dopasowania.

### Zwykłe „Pobierz MAP” zapisuje wycięcia automatycznie

Przy nakładaniu poligonów tego samego kodu i zapisaniu:
- W **Windows** standardowe „Pobierz MAP” otwiera Zapisz jako,
  automatycznie zapisuje wynikowe obrysy z otworami do pliku
  \`.MAP\` i obok \`.geostudio-topology.json\` v2;
- W **przeglądarce** przy obecnych maskach jeden plik ZIP
  zawiera oba pliki MAP oraz JSON. Rozpakuj obydwa do jednego folderu,
  otwórz MAP, a następnie kliknij **„Odtwórz kontury”** i wskaż
  `.geostudio-topology.json`. To przywraca pełne obrysy do dalszej edycji.
- Bez masek powstaje zwykły MAP z dodatnio zorientowanymi
  prostymi obrysami; bez konieczności użycia „Pole +”.
- Zachowano zaawansowane **„Zapisz wycięcia 6B”** (ręczne
  wymuszenie zapisu). Dostępny jest też awaryjny eksport
  bazowej kopii bez wycięć, gdy złożony przypadek jest
  celowo blokowany, np. całkowite przykrycie obiektu.

Natywne P 0 / otwory wymagają nadal porównania w klasycznym GEO-MAP.
Gdy obiekt jest całkowicie zakryty, eksport 6B nie usuwa jego :ID
ani nie próbuje niebezpiecznie zapisać pustego poligonu — zwraca błąd.

### Biblioteki kartograficzne

Kliknij **LAY/CDF/SYM** w sekcji Projekt.
W oknie Windows wskaż pliki bibliotek (maksymalnie 1 plik każdego
typu, 8 MB na plik); w trybie przeglądarki otwiera się
systemowe okno wyboru plików.

Biblioteki są wczytywane w pamięci jako **CP1250**, bez modyfikacji
ich zawartości i bez zapisywania w źródłowym MAP. Można ładować je
przed mapą lub już po otwarciu; status pokazuje liczbę rozpoznanych
wpisów w LAY/CDF/SYM.

- **LAY** — znane definicje linii (np. identyfikator 2.008),
  bez dorabiania niezrozumianych stylów;
- **CDF** — kolory wypełnienia i obrysu, grubość obrysu,
  prosty szraf 0–8 zgodny z wcześniejszym rendererem Qt;
- **SYM** — zweryfikowane wzory kreskowane z katalogu 400x
  oraz linie/okręgi prostych symboli punktowych.
- Oryginalne kolory z MAP, klasoużytki leśne, wyjątek 5230
  z A1=dr/droga oraz ręczne jawne style nadal zachowują
  pierwszeństwo zgodne z wcześniejszym modelem GeoStudio.

**Zakres celowo częściowy:** SYM ma też złożone komendy O/T,
łuki i makra; w tym etapie nie udajemy, że renderujemy
niezweryfikowane instrukcje. Dokładna zgodność z klasycznym GEO-MAP
wymaga dostarczenia tych samych bibliotek używanych przez program,
testów wielu kodów oraz oceny wydruków w tej samej skali.


## Etap 8 — stabilizacja, natywne etykiety GMW, odzyskiwanie i Windows

### Zgodność z klasycznym GEO-MAP (odkryta na rzeczywistych test.MAP)

W GMW 10.52 poligon z wieloma osobnymi konturami P 0 ma dodatkowe
**końcowe \`P 1\`, które ponownie wskazuje pierwszy punkt całego obiektu**,
już po zamknięciu ostatniej części. Sam komplet L 1/L 2/L 3 nie
wystarczył: GEO-MAP nie pokazywał etykiet 5310 A1=l,
A2=So120|II-0.3. Plik poprawiony w GMW różnił się właśnie
tym końcowym rekordem. W tym etapie zapis multipart dodaje taki
rekord, a parser rozpoznaje go jako domknięcie obiektu, nie jako
dodatkową krawędź geometrii. Testy regresji nie zawierają
prywatnych fragmentów z rzeczywistej mapy użytkownika, tylko
syntetyczny równoważny przypadek.

### Przesuwanie wielu poligonów

Tryb **M** przesuwa cały poligon albo wszystkie zaznaczone przez
Ctrl+H poligony po przeciągnięciu jednego z nich. Po puszczeniu
przycisku myszy przesunięcie odbywa się **bez formularza i okna
zatwierdzenia**, z aktywnym magnetycznym przyciąganiem do granic
obiektów tego samego kodu i z dozwolonym rozłączeniem dotychczas
wspólnej granicy. Serwer nadal sprawdza revision/documentToken,
topologię, liczbę wybranych węzłów oraz niezmienność wszystkich
pozostałych obiektów. Cała grupa stanowi jedną operację Ctrl+Z.
Ręczny dialog \`Ctrl+Shift+M\` pozostaje dla liczbowego DX/DY.

### Automatyczne migawki awaryjne — tylko aplikacja Windows

Po edycji kopia stanu aktualnej mapy oraz odwracalnych nakładań
zapisywana jest po krótkim opóźnieniu do
\`%LOCALAPPDATA%\GeoStudio2\recovery\`. Oryginalna mapa nie jest
nadpisywana. Zapis idzie przez pliki tymczasowe, fsync i atomową
podmianę manifestu na końcu. Manifest zawiera SHA256 oryginalnej
mapy, kopii roboczej i topologii; niekompletne pliki są ignorowane.

Po awaryjnym zamknięciu wybierz **ten sam plik MAP przez „Otwórz MAP”
(w natywnym oknie plików)**. Jeśli źródło nadal jest identyczne,
GeoStudio zapyta, czy przywrócić sesję. Po odtworzeniu dokument jest
oznaczony jako niezapisany; zapisz go jako **nową kopię MAP**.
Migawka nie przenosi pełnej historii Undo — odzyskuje bieżący
stan MAP oraz priorytet odwracalnych masek. To funkcja testowa;
**nie zastępuje ręcznego Zapisz jako**, zwłaszcza dla danych
produkcyjnych. W zwykłej przeglądarce automatyczne migawki na
dysku nie są jeszcze dostępne.

### Duże mapy

Parser i eksport mają regresję z mapą 112 tys. linii, testy
niezmienności źródła, checksum CHK oraz konturów wieloczęściowych.
Indeks obiektów pozwala żądaniom małego viewportu uniknąć
ponownego skanowania całej mapy przy przesuwaniu i powiększaniu.
Historia Undo nadal ma ograniczoną pamięć, a renderer
limituje liczbę geometrii przesyłanych jednorazowo.

### Biblioteki LAY/CDF/SYM

Po wybraniu bibliotek, przy kartografii pojawia się informacja
\`CDF: zastosowania/dopasowania\`, analogicznie dla LAY i SYM.
Zera oznaczają, że aktualnie widoczna część mapy nie zawiera
rozpoznanych kodów lub ich reguł renderer nie stosuje — nie
oznacza to błędnego importu. **Graniczniki domyślnie są ukryte**,
więc SYM może być niewidoczny. Włącz tę warstwę w lewym panelu.
Złożone makra SYM, wszystkie desenie i pełna zgodność
wydruku nadal nie są zaimplementowane.

### Instalator Windows x64 — wersja testowa

Pipeline \`Windows GeoStudio2 preview installer\` buduje pakiet
**portable** przez PyInstaller i instalator **per-user**
przez Inno Setup 6, bez uprawnień administratora.
Po przejściu workflow pliki dostępne są jako GitHub Actions
Artifacts na stronie przebiegu workflow PR — instalator nie
jest oficjalnym podpisanym wydaniem.

Lokalne komendy na Windows z Pythonem 3.12 i Inno Setup 6:

\`\`\`powershell
cd C:\GeoStudio-2-preview
.\tools\windows\build.ps1
# Samodzielny folder portable bez Inno Setup:
.\tools\windows\build.ps1 -SkipInstaller
\`\`\`

Build trafia do \`dist/GeoStudio2\`, a instalator do
\`dist/installer\`. WebView2 Runtime musi być dostępny
w systemie; instalator preview go nie doinstalowuje.
W razie problemów w pierwszej kolejności użyj
\`.\start_web_ui.bat\`, który uruchamia tę samą aplikację
ze środowiska Pythona.

Przed akceptacją: użyj testowego scalania i eksportu w
klasycznym GEO-MAP, przesuń grupy 5310 oraz 5216, przeprowadź
restart po edycji i odtwórz sesję, porównaj wygląd LAY/CDF/SYM
z rzeczywistymi bibliotekami, przetestuj instalator na
Windows 11. Gałąź jest draft i **nie modyfikuje main**.
