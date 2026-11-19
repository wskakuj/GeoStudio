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

To pierwsza wersja: przeciąganie dotyczy istniejących węzłów
zamkniętych poligonów z identyfikatorem GEO-MAP. Dodawanie i
usuwanie węzłów, polilinie i rozbudowane operacje topologiczne
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

- Dodawanie/usuwanie węzłów, rysowanie nowych poligonów, zapisywanie oryginału MAP,
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
