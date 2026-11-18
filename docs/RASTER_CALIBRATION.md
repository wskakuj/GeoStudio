# Podkłady rastrowe i kalibracja GCP

GeoStudio pozwala nałożyć skan mapy lub ortofotomapę **pod geometrią GEO-MAP** i
rysować na obrazie podobnie jak na kalce. Plik źródłowy `.MAP` pozostaje nietknięty.

## Import i kalibracja

1. Otwórz mapę `.MAP` i upewnij się, że jej współrzędne są poprawne.
2. W zakładce **Dane → Rastry → Dodaj raster** wybierz PNG, JPEG, TIFF lub BMP.
3. Jeśli obok obrazu istnieje `.tfw`, `.jgw`, `.pgw` lub `.wld`, podkład
   zostanie ustawiony według georeferencji z pliku world.
4. Bez pliku world otworzy się okno **Kalibracja rastra**. Kliknij szczegół
   na obrazie (np. narożnik budynku lub punkt graniczny), następnie kliknij
   **Wybierz odpowiednik na mapie** i wskaż ten sam punkt na mapie GEO-MAP.
   Powtórz dla kolejnych charakterystycznych punktów.
5. Po co najmniej trzech parach kliknij **Oblicz dopasowanie**, aby zobaczyć
   błąd RMS i odchyłkę każdego punktu. Zalecamy 6–10 par rozłożonych po całej
   powierzchni, nie tylko na jednym fragmencie.
6. **Zastosuj i zapisz podkład** nałoży raster pod wektory. W panelu **Rastry**
   można go ukrywać, usuwać i regulować krycie bez zmiany pliku MAP.

Główny widok pozostaje aktywny podczas kalibracji; okno kalibracji jest
niemodalne. Można przybliżać rastry kółkiem myszy, aby dokładniej wyznaczać
wspólne punkty.

## Dokładność

Wersja początkowa używa transformacji **afinicznej** (obrót, przesunięcie,
skala, ścinanie), dopasowanej metodą najmniejszych kwadratów dla 3+ par.
Wartości RMS i odchyłek są wyrażone w **jednostkach współrzędnych mapy** —
zazwyczaj metrach dla układów metrycznych. Nie zakładaj metrów, jeżeli dane
mapy używają innych jednostek.

Siedem punktów pomaga wykryć błędne dopasowanie, ale nie gwarantuje idealnej
zgodności, jeśli obraz ma lokalne zniekształcenia (zagięty papier, sfotografowana
pod kątem mapa, nierównomierna deformacja skanera). W takim przypadku potrzebna
jest później transformacja wielomianowa lub rubber-sheeting, nie samo dodanie
większej liczby punktów do modelu afinicznego.

## Trwałość i format

Ustawienia są przechowywane w osobnym pliku
`nazwa.MAP.geostudio.rasters.json`: ścieżki obrazów, punkty kontrolne,
macierze kalibracji, kolejność, widoczność i przezroczystość.

- Oryginalny MAP nie jest modyfikowany przez dodanie rastra.
- Brak obrazu po przeniesieniu projektu nie zatrzymuje odczytu mapy.
- Najwygodniej przechowywać rastry obok MAP; wtedy ścieżki w sidecarze są
  względne i działają po przeniesieniu całego katalogu.
- Format pliku world dotyczy centrów pikseli, a grafika Qt używa ich
  narożników — GeoStudio uwzględnia korektę pół piksela.

## Do testów przed pracą produkcyjną

Na kopii przykładowej mapy skalibruj raster z 7 parami i sprawdź pozycję
niezależnych punktów, których nie użyto do kalibracji. Zamknij i otwórz MAP,
sprawdź ponowne nałożenie obrazu, krycie oraz widoczność działek nad rastrami.
Sprawdź też, czy rysowanie i zaznaczanie działa nadal tak samo.
