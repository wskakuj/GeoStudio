# Usługi mapowe w GeoStudio: WMS i Google Maps

## WMS — podkład pod geometrią

1. Otwórz źródłową mapę `.MAP` i ustal jej poprawny układ współrzędnych
   (preferowany plik `.prj` z identyfikatorem EPSG). GeoStudio nie zgaduje
   układu tylko na podstawie wartości współrzędnych.
2. Przejdź do **Dane → Mapy online → WMS — pod mapą**.
3. W oknie zobaczysz proponowany adres usługi ortofotomapy Geoportalu
   GUGiK: `https://mapy.geoportal.gov.pl/wss/service/PZGIK/ORTO/WMS/StandardResolution`.
   Możesz zastąpić go adresem dowolnej usługi OGC WMS.
4. Kliknij **Pobierz warstwy** (GetCapabilities), wybierz interesującą warstwę
   oraz prawidłowy układ EPSG mapy, np. PL-1992 `EPSG:2180`.
5. Kliknij **Pokaż WMS pod mapą**. GeoStudio wysyła GetMap dla aktualnego
   fragmentu mapy, wyświetla otrzymany obraz **pod poligonami i liniami**,
   pozostawia możliwość zaznaczania i edycji oraz pokazuje atrybucję źródła.
6. Po przesunięciu lub przybliżeniu widoku kliknij ponownie **Pokaż WMS pod mapą**,
   aby odświeżyć fragment i rozdzielczość obrazu.
7. Krycie zmienisz suwakiem. Przyciskiem **Usuń WMS z widoku** usuniesz podkład.

WMS jest podkładem **tymczasowym**: w tej wersji nie zapisujemy żadnych obrazów
z cudzych serwerów na dysku ani do pliku MAP.

### Ważne zasady współrzędnych

GEO-MAP koduje X jako northing i Y jako easting. Usługi WMS w EPSG:2180
używają BBOX w kolejności easting,northing; wersja WMS 1.3.0 dla
EPSG:4326 wymaga kolejności szerokość,długość. GeoStudio obsługuje obie
reguły, ale **nie wykonuje reprojekcji rastra WMS między układami**.
Wybrany EPSG musi odpowiadać współrzędnym MAP i być obsługiwany przez
serwer dla wybranej warstwy.

ebEngine` zależy od aktualnej
strony Google, wersji Chromium/WebEngine, obsługi GPU i WebGL.

