# GeoStudio — działki EGiB, obrysy i oprawa mapy (19.11.2026)

## Granice i numery działek ewidencyjnych
Otwórz **Dane → WMS** i wybierz źródło **Działki ewidencyjne + numery (GUGiK KIEG)**.
Kliknij **Pobierz warstwy**, wybierz pozycję **Działki i numery ewidencyjne**
(kombinacja natywnych warstw `dzialki,numery_dzialek`; dostępna tylko,
gdy obie są ogłoszone w GetCapabilities) i ustaw **rzeczywisty EPSG** mapy.
Kliknij **Pokaż wybraną warstwę WMS**. Działki i numery są rysowane\n**nad wypełnieniami poligonów**, natomiast ortofotomapa pozostaje\npod geometrią. Przybliżaj widok, jeśli numerów jest
niewiele: ich widoczność zależy od skali i powiatowych serwerów źródłowych.

Źródło: Główny Urząd Geodezji i Kartografii, usługa
[Krajowa Integracja Ewidencji Gruntów (KIEG)](https://integracja.gugik.gov.pl/cgi-bin/KrajowaIntegracjaEwidencjiGruntow).

**Ważne:** ta integracja jest **rastrową nakładką WMS**. Granice i numery
z KIEG nie stają się edytowalnymi poligonami ani węzłami w pliku `.MAP`.
Do rzeczywistego wektorowego pobierania danych należy w przyszłości dodać
osobny import odpowiedzi zbiorczej WFS EGiB lub geometrii ULDK z określoną
transformacją układu i weryfikacją pochodzenia danych. Nie należy mieszać
warstw opisowych EGiB z własnymi granicami bez kontroli zgodności.

## Wygląd i kolorystyka obrysów
Zaznacz dowolny obiekt (np. kod **5310**). W inspektorze **Wygląd**
znajdziesz nowy panel **Obrys wszystkich obiektów kodu**:
wybierz kolor i grubość linii (0,5–12 pikseli), potem kliknij
**Zastosuj obrys do całego kodu**. W jednym działaniu zmieniają się wszystkie
obrysy tego kodu, niezależnie od zmian w pliku `.MAP`.
Efekt można cofnąć przez **Ctrl+Z**.

W tym samym inspektorze zapisany procent krycia wypełnienia jest przywracany
po ponownym zaznaczeniu obiektu, zamiast pokazywać mylące 100%.
Po kliknięciu PPM na warstwie i wybraniu **Ustaw kolor poligonów całej
warstwy** ten kolor ma pierwszeństwo nawet przed dawnymi kolorami
ustawionymi na poszczególnych obiektach (bez naruszania źródłowego MAP).

## Paleta etykiet
**Ctrl+Alt+L**: kliknij pole w kolumnie **Kolor** w dowolnym wierszu A1–A6
lub TX/MP/KR. Teraz każdy kolor jest samodzielnym przyciskiem otwierającym
paletę Windows/Qt; nie trzeba wpisywać kodu HEX ani klikać dużego,
niezwiązanego z wierszem przycisku pod tabelą.
Wiersze są wyższe dla lepszej czytelności na Windows/HiDPI.

## Niezależne przesuwanie oprawy
Znak północy, podpis wykonawcy, tytuł mapy i legenda mają teraz
**precyzyjne obszary klikalności** dopasowane do ich faktycznej treści.
Nie można przeciągnąć kilku elementów jednocześnie: wybór elementu
czyści zaznaczenie pozostałych. Uchwyt w prawym dolnym rogu nadal pozwala
zmienić wielkość pojedynczej dekoracji. W celu edycji kliknij dwukrotnie
bezpośrednio na napisie albo symbolu.

Nowo dodawana legenda pobiera używane kody z otwartej mapy, nazwy z SYM/LAY
i istniejące kolory GEO-MAP. Pozycje można nadal edytować ręcznie.
Większe legendy tworzą **kilka kolumn**, zamiast jednej ogromnej ramki
chwytającej kliknięcia w pobliskich obszarach mapy. Oprawa i style są
przechowywane w pliku towarzyszącym `*.geostudio.json`.

## Weryfikacja
Sprawdź działanie na kopii mapy i zapisz obok pliku `.MAP` towarzyszący
plik `*.geostudio.json` — bez niego nowe style i dekoracje nie pojawią się
po przeniesieniu mapy na inne stanowisko GeoStudio.
