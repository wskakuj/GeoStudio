# Klasoużytki leśne i oprawa mapy w GeoStudio

## Warstwa Użytki Leśne
Obiekty GEO-MAP kodu **5230** opisane jako `Ls`, `LsI`, `LsII`,
`LsIII`, `LsIV`, `LsV`, `LsVI` (oraz warianty literowe)
są prezentowane wspólnie w panelu Warstwy pod nazwą **Użytki Leśne**.
Aplikacja sprawdza klasyfikację w A1, a jeśli tam nie ma oznaczenia
leśnego — również w A2. Inne oznaczenia kodu 5230, np. `dr` /
`droga`, pozostają w ich pierwotnej warstwie, np. „Użytki”.

Kliknij **PPM na Użytki Leśne → Klasoużytki — widoczność**. Na liście
każda klasa ma własny checkbox oraz liczbę obiektów. Możesz pokazywać
i ukrywać poszczególne klasy, użyć „Pokaż wszystkie” lub „Ukryj wszystkie”.
Znikają jednocześnie obrysy, wypełnienia, napisy i możliwość
zaznaczania/przyciągania do wyłączonych klas. **Ctrl+Z** cofa zmianę.

Reguły nie modyfikują kodu, atrybutów ani geometrii `.MAP`.
Stan wyłączeń jest zapisywany w towarzyszącym pliku `*.geostudio.json`
i zachowany w niezależnych sesjach mapy.

## Serwery WMS
SmartSDI usunięto z okna WMS. Pozostają usługi Geoportalu:
ortofotomapa standardowa i wysokorozdzielcza, KIEG (granice i numery
działek), oraz własny adres zgodnego serwera WMS.

## Oprawa mapy
Tablica tytułowa, metryka wykonawcy i legenda pozostają przezroczyste.
W edycji dwuklikiem można zmieniać wszystkie teksty; podtytuł
to osobne pole. Opisy pod nagłówkiem są rysowane w kolejnych wierszach
z uwzględnieniem szerokości, a wysokość jest dopasowywana do objętości
tekstu. W legendzie obowiązują wiersze w tabeli „Elementy legendy”
z indywidualnym kolorem, a nie ukryty surowy tekst opisu.
Duża legenda nadal ma układ wielokolumnowy.

Przed wydrukiem sprawdź widoczność tekstów po zmianie skali.
Oprawa mapy przechowywana jest w GeoStudio sidecar i nie staje się
natywnymi rekordami GEO-MAP.
