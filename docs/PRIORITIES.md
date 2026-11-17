# Następne kamienie milowe i kryteria akceptacji

## P0 — krytyczna zgodność z GEO-MAP

- [x] Sprawdź nagłówek, liczbę wierszy i algorytm CHK na dwóch MAP.
- [x] Zachowuj nieznane rekordy bez uszkadzania podczas no-op round-trip.
- [x] Wczytaj kody, identyfikatory, proste punkty, atrybuty i teksty.
- [x] Wczytaj symbole, palety i warstwy z katalogów; w tym wildcard `?` w LAY.
- [ ] Odwzoruj wszystkie rodzaje prymitywów, opisów, ramek i tabel z próbki.
- [ ] Przetestuj w oryginalnym GEO-MAP plik z edytowanym A2, TX i nowym obiektem.
- [ ] Dodaj testy porównawcze round-trip dla wszystkich typów rekordów.
- [ ] Dodaj kopie zapasowe, Undo/Redo, wybór wierzchołka i kontrolę topologii.

## P1 — geodezja

- [ ] Ustal układy współrzędnych i ich orientację osi na danych testowych.
- [ ] Transformacje PL-2000/1992/1965 oraz wielkości poprawek odwzorowawczych.
- [ ] Obliczanie długości i powierzchni zgodne z zasadami GEO-MAP (testy referencyjne).
- [ ] Zamykanie, wycinanie, łączenie, przecięcia poligonów, przyciąganie punktów.

## P2 — rastry i eksport

- [ ] Kalibracja rastrów z punktów GCP, kontrola reszt i odwzorowania.
- [ ] GeoTIFF, wydruki rastrowe z siatką i kontrolą skali.
- [ ] Pełny DXF: symbole, opisy, kolory, szrafury i warstwy.
- [ ] VAL: rozliczenia użytków, raporty porównane z próbką DĄBRÓWKA.
- [ ] Arkusze do wyłożenia: ramki, opisy, tabelki, legenda, marginesy.

## P3 — UI i wydajność

- [ ] Konfigurowalne doki, jasny i ciemny motyw, wyszukiwanie kodów 5310/5216.
- [ ] Indeksy przestrzenne i renderowanie w tle dużych zbiorów.
- [ ] Instalator Windows + automatyczne aktualizacje z GitHub Releases.
