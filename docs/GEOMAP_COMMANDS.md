# Wybieranie, kod tworzenia, atrybuty i skróty GEO-MAP

## Przełączanie zaznaczenia jednym kliknięciem
Kliknięcie w obrębie budynku kodu **5310** preferuje ten budynek nad
poligonem działki lub użytku pod spodem. Kolejne kliknięcia w to samo
miejsce przełączają zaznaczenie pomiędzy wszystkimi nachodzącymi na
siebie obiektami (nie trzeba stosować wielokrotnego Ctrl+klik).
Kliknięcie etykiety A1 lub A2 budynku zaznacza bezpośrednio jej obiekt.
Podczas zaznaczenia pojedynczego obiektu podświetlane są też obie etykiety
A1/A2; nie są to dodatkowe osobne obiekty w pliku MAP.

Węzły: jednoczesne przesunięcie współdzielonego narożnika dotyczy
wyłącznie poligonów **tego samego kodu**. Nie włączono modyfikacji innych
typów obiektów ani automatycznego wycinania nakładających się powierzchni.
W trybie węzłów można przyciągać edytowany punkt do wierzchołków i krawędzi **dowolnego kodu**, w tym do graniczników. Samo przyciągnięcie nie modyfikuje obiektu docelowego; przy zatwierdzeniu przesunięcia synchronizują się tylko węzły poligonów **tego samego kodu** co edytowany.

## Nowe skróty klawiszowe
| Skrót | Akcja |
| --- | --- |
| **T** | Okno „Podaj kod tworzonego obiektu”: kod 4-cyfrowy, nazwa, lista symboli GEO-MAP |
| **F** | Okno wyszukiwania: kod, A1/A2 i opcjonalny drugi warunek |
| **Ctrl+H** | Szczegółowe zaznaczanie grupy: sam kod albo kod wraz z A1/A2; dokładne dopasowanie lub „zawiera” |
| **Ctrl+F** | Zamiana frazy w wybranym polu A1–A6 lub TX, w zaznaczonych obiektach albo całej mapie |
| **E** | Okno „Parametry aktywnego obiektu”: atrybuty A1–A6, TX, MP, KR oraz zakładka współrzędnych punktów |
| **P** | Edycja węzłów zaznaczonego poligonu |
| **N** | Nowy poligon — dotychczasowe proste rysowanie z pytaniem o kod |
| **S/H/L** | Zaznaczanie / przesuwanie mapy / przesuwanie etykiet |
| **Ctrl+T** | Istniejące przeliczanie współrzędnych — bez zmian |

Przed zamianą frazy GeoStudio pokazuje liczbę obiektów i prosi o
potwierdzenie. Zmiany są grupowane w jednej operacji Undo. Program
modyfikuje wyłącznie kopię roboczą w pamięci i zapisuje nowy plik,
nie nadpisuje źródłowego `.MAP`.

## Kolory i warstwy
- **5230**, A1 = `dr` lub `droga`: bez wypełnienia, nawet gdy ustawiono
  styl całego kodu. Kontur pozostaje na mapie.
- **5230**, A1 zaczynające się od `Ls`: domyślne zielone wypełnienie
  z kryciem 40%. Ręczny styl konkretnego obiektu lub krycie ustawione
  dla kodu nadal są obsługiwane.
- **Graniczniki** przy pierwszym otwarciu MAP są wyłączone; można je
  ponownie zaznaczyć w lewym panelu Warstwy. Nawet przy wyłączonej
  widoczności graniczniki pozostają celami przyciągania,
  jeśli przełącznik **Przyciągaj** jest włączony. Zwykłe ukryte warstwy
  nie są przyciągane.
- Ustawienia widoczności po przełączaniu między otwartymi mapami
  są niezależne, tak jak historia edycji.

## Google Earth i georeferencjonowany podkład
Google Earth Web może być przeglądany w GeoStudio, ale nie jest
georeferencjonowaną warstwą `QGraphicsPixmapItem` pod geometrią.
Nie należy wycinać fragmentów strony Google Earth ani korzystać z
nieudokumentowanych kafelków jako darmowego rastra do odrysowywania.
Do wkreślania obiektów na zdjęciu wykorzystuj oficjalny WMS Geoportalu
lub lokalny raster, oba dostępne pod warstwami wektorowymi.

Google Maps Platform Terms:
https://cloud.google.com/terms/maps-platform/eea
