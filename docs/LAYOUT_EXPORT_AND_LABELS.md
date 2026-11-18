# GeoStudio — oprawa, eksport wielkoformatowy, WMS i etykiety

## Oprawa mapy
Elementy dodawane przez **Oprawa mapy** pozostają obiektami wektorowymi GeoStudio,
przechowywanymi w pliku `*.geostudio.json` i widocznymi w eksporcie obrazu.
Nie zmieniają natywnych rekordów MAP. Są przezroczyste: bez białych kart,
tła lub ramki. Znak kierunków pokazuje **N, E, S i W**.

Aby zmienić wielkość oprawy, kliknij element na mapie, a następnie przeciągnij
**uchwyt w jego prawym dolnym narożniku**. Dwuklik otwiera edycję treści.
Ctrl+Z cofa obie zmiany.

**Legenda**: dwuklik → tabela „Elementy legendy”. Dodaj pozycję przyciskiem
**+ Dodaj**, zmień nazwę bezpośrednio w komórce, wybierz kolor przyciskiem
**Zmień kolor** lub usuń wskazaną pozycję. Wysokość legendy automatycznie
rośnie razem z liczbą wierszy.

## Eksport PNG, JPG i TIFF
Eksport używa orientacji aktualnego widoku mapy, w tym geodezyjnej zamiany
osi X/Y, zamiast surowego układu sceny Qt. Nie zmienia współrzędnych MAP.
Wybór docelowej **szerokości [px]**: typowo 6000–14000 px do wydruków
wielkoformatowych, jeśli proporcje arkusza i pamięć na to pozwalają.
Limit 120 mln pikseli chroni przed wyczerpaniem RAM. W oknie pojawia się
wskaźnik kolejnych etapów i potwierdzenie zakończenia.

Dane o rozdzielczości drukarskiej są zapisane jako 300 DPI (metadane).
**Ważne:** 300 DPI nie zwiększa rzeczywistych szczegółów danych źródłowych.
Geometria wektorowa jest rysowana na nowo w wybranej rozdzielczości, ale WMS
i zdjęcia rastrowe są ograniczone rozdzielczością pobranych/źródłowych
rastrów. Bardzo duża mapa może wymagać rozdzielenia na arkusze.
Obsługa zapisu TIFF zależy od instalacji kodeków Qt.

## WMS
Menu **Dane → WMS** zawiera:
- Geoportal / ortofotomapa standardowa,
- Geoportal / ortofotomapa wysokiej rozdzielczości,
- granice i numery działek ewidencyjnych GUGiK KIEG,
- własny adres serwera WMS.

Adres HighResolution jest oficjalnym punktem serwisu Geoportalu:
https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/HighResolution

Podkład KIEG jest wyłącznie rastrowym podglądem granic i numerów działek.
Nie zapisuje edytowalnych działek do pliku MAP.

## Warstwy
W zakładce Warstwy kliknij **PPM na nazwie warstwy**, żeby zaznaczyć
wszystkie obiekty, ustawić zbiorczo wartość istniejącego pola A1–A6/TX/MP/KR,
zmienić wspólny kolor krycia (poligony) albo ustawić etykiety wybranego kodu.
Zmiany atrybutów dotyczą tylko istniejących pól i korzystają z jednej
operacji historii (Ctrl+Z); źródłowy MAP nie jest nadpisywany.

## Etykietowanie
Otwórz **Ctrl+Alt+L** po zaznaczeniu obiektu albo **PPM → Etykiety**
w panelu warstw. Dla każdego kodu można włączyć oddzielnie A1–A6, TX,
MP i KR oraz ustawić czcionkę, rozmiar i kolor. Włączone pola są
rysowane jako etykiety nad mapą. Wyłączone nie przesłaniają geometrii.

**S** pozostaje zaznaczaniem. Obok narzędzia zaznaczania na wstążce
znajdziesz **Przesuń etykiety [L]**; w tym trybie przeciąganie przenosi
widoczną etykietę dowolnego atrybutu i zapisuje jej pozycję w GeoStudio.
