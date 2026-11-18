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

## Google Maps — niezależny podgląd

W **Dane → Mapy online → Google Maps** dostępny jest osobny podgląd w oknie:

- **Otwórz w przeglądarce bez klucza**: wyświetla oficjalne Google Maps,
  wycentrowane na bieżącym fragmencie mapy po transformacji współrzędnych
  ze zweryfikowanego EPSG do WGS84.
- **Pokaż mapę Google w GeoStudio**: wymaga osobistego klucza Google Maps
  **Embed API** (włączonego w Google Cloud). Klucz wpisujesz na bieżąco,
  GeoStudio go nie zapisuje; widok jest osadzany w oficjalnym iframe
  dostarczonym przez Google i zachowuje oryginalne oznaczenia oraz prawa autorskie.
  Dostępność zależy od konfiguracji Qt WebEngine, klucza i zasad autoryzacji
  Google Cloud.

**Google Maps nie jest w tym etapie warstwą rastra do odrysowywania**.
Nie wolno pobierać kafelków bezpośrednio z nieoficjalnych serwerów Google
ani zapisywać obrazu Google w kopiach projektu. Do georeferencjonowania i
odrysowywania użyj własnych rastrowych materiałów lub licencjonowanego WMS.

Dokumentacja usługi: https://developers.google.com/maps/documentation/embed/embedding-map

## Testowanie

Na mapie w układzie EPSG:2180 sprawdź pobranie ortofotomapy z Geoportalu,
nakładanie na charakterystyczne obiekty, widoczność napisów i działanie
rysowania nad podkładem. Przełącz WMS, odśwież po zmianie zoomu, sprawdź
błędy sieci i pomyłkę układu. Otwórz Google Maps w przeglądarce;
jeśli posiadasz własny klucz Maps Embed API, sprawdź także osadzony podgląd.


## Wybór warstwy WMS bez znajomości kodu

W oknie WMS pole **Warstwa WMS** jest teraz wyłącznie listą wyboru.
Po otwarciu okna ma stan „Kliknij «Pobierz warstwy»” i jest wyłączone.
Kliknięcie **Pobierz warstwy** wysyła GetCapabilities do wpisanego serwera,
po czym włącza listę z nazwami dostarczonymi przez usługę (np.
„Ortofotomapa (ortofoto)”). Nie trzeba wpisywać kodu WMS ręcznie.
Gdy serwer zwraca błąd OGC lub nie udostępnia warstw, pojawia się komunikat
z wyjaśnieniem, a przycisk wyświetlenia mapy pozostaje nieaktywny.

## Google Earth bez klucza

Okno **Dane → Mapy online → Google Maps** ma dwa przyciski bez API:

- **Google Maps — przeglądarka (bez API)**: otwiera aktualny obszar mapy
  w oficjalnej przeglądarkowej usłudze Google Maps.
- **Google Earth — przeglądarka (bez API)**: otwiera stronę Google Earth Web
  z wyszukiwaniem współrzędnych bieżącego obszaru po przeliczeniu z
  potwierdzonego układu EPSG do WGS84. Ten format odnośnika jest
  pomocniczy i Google może zmienić jego obsługę; w takim wypadku należy
  otworzyć https://earth.google.com/web/ i wkleić współrzędne w wyszukiwarkę.

**Nie jest to mapa podkładowa w scenie GeoStudio**. Wyświetlanie obrazów
Google pod poligonami w edytorze przez nieoficjalne kafelki nie jest
wspierane. Do odrysowywania używaj ortofotomapy WMS Geoportalu lub
lokalnego rastra z dozwolonym prawem wykorzystania.
