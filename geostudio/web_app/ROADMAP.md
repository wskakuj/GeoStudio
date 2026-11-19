# GeoStudio 2.0 — status i kolejne etapy

Aktualizacja: 19 listopada 2026. Dokument będziemy uzupełniać po każdym zweryfikowanym etapie.

## Zrobione i potwierdzone

- [x] Osobny interfejs GeoStudio 2.0 (Windows / pywebview, tryb przeglądarki).
- [x] Otwieranie GEO-MAP MAP, nawigacja, warstwy, inspektor.
- [x] Kolorystyka geometrii z oryginalnego MAP — podstawowa zgodność.
- [x] Edycja istniejących atrybutów A1–A6 / TX / MP / KR.
- [x] Przesuwanie węzłów P, przyciąganie i kontrola poprawności.
- [x] Przylegające 5310↔5310: wspólne narożniki i połączenia do boku (T).
- [x] Ochrona innych kodów (np. 5310 nie zmienia geometrii 5220).
- [x] Dwuklik na krawędzi dodaje węzeł.
- [x] Delete usuwa węzeł, z kontrolą liczby punktów i domknięcia.
- [x] Cofnij/Ponów oraz eksport nowej kopii MAP z przeliczonym CHK.
- [x] Testy automatyczne wraz z kontrolą niezmienności rekordów innych kodów.
- [x] Ctrl+H: wybór wg kodu oraz A1/A2, operacje na zaznaczeniu (potwierdzone).
- [x] Priorytet wyboru 5310, aktywne etykiety A1/A2 (wstępne).
- [x] Zapamiętywanie ostatniego folderu MAP i awaryjne „Z dysku” (potwierdzone).
- [x] Zabezpieczenie pywebview przed rekurencją natywnego WebView2 (testowane).

## W tym PR — etap 4B, wymaga próby użytkownika

- [ ] **Zbiorowo A1/A2**: jawne checkboxy dla pól, obsługa pustych wartości.
- [ ] Podgląd: liczby zmian, pola niedostępne, przykłady przed/po.
- [ ] Zmiany w wybranych (a nie wszystkich tego samego kodu), limit 5 000.
- [ ] Jedna transakcja Cofnij/Ponów, ochrona niezmienionych rekordów MAP.
- [ ] Zapis bez nadpisywania źródła, walidacja CP1250 i blokada starej rewizji.

## Pozostałe duże obszary

1. **Dopracowanie zaznaczania**: wybór według geometrii, wykluczanie nakładających się obiektów, testy bardzo dużych map.
2. **Nowe obiekty**: tworzenie polygonów i linii, usuwanie/kopiowanie obiektów, przesuwanie całych geometrii.
3. **Zaawansowane GIS**: podział i łączenie poligonów, edycja polilinii, pomiary, snapping i kontrola topologii.
4. **Pełna kartografia**: biblioteki LAY / CDF / SYM, etykiety, wzory, symbole; możliwie wierny klasyczny renderer.
5. **Wersja produkcyjna**: wydajność na wielkich mapach, zapis bezpośredni z kopią zapasową, odzyskiwanie awaryjne, instalator, testy rzeczywistych plików.

## Orientacyjny postęp

To przybliżony **zakres funkcji**, nie wskaźnik jakości/testów:

- Użyteczny edytor do codziennej pracy: **około 75%** po potwierdzeniu etapu 4B.
- Całkowity zamiennik klasycznego GeoStudio: **około 48%** po potwierdzeniu etapu 4B.

Najwięcej pozostałej pracy to integracja wielu operacji na obiektach oraz pełna zgodność renderowania i formatów.
Do pracy produkcyjnej używaj zweryfikowanej aplikacji klasycznej lub dokładnie sprawdzonej wyeksportowanej kopii MAP.
