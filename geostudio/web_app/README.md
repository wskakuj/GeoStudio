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
- Żadna z tych operacji **nie zapisuje ani nie zmienia** pliku .MAP.

## Celowo NIEZAIMPLEMENTOWANE w tym etapie

- Edycja węzłów, topologia, rysowanie poligonów, zapisywanie MAP,
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
