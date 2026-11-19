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

## W tym PR — wymaga jeszcze próby na rzeczywistej mapie

- [ ] **Ctrl+H**: zaznaczanie wszystkich obiektów według kodu oraz A1/A2.
- [ ] Dopasowanie dokładne / zawiera, zastąp / dodaj / odejmij.
- [ ] Ctrl/Shift+klik dla wielu obiektów, szybciej wybierany kod 5310.
- [ ] Podświetlanie A1/A2 aktywnego obiektu.
- [ ] Pamięć ostatniego folderu w natywnym oknie Windows.
- [ ] Stabilny port w trybie --browser i systemowy picker z pamięcią katalogu (z ograniczeniami przeglądarki).

## Pozostałe duże obszary

1. **Edycja zbiorowa**: aktualizacja A1/A2 u wielu obiektów, transakcja dla wielu rekordów i kontrola zakresu.
2. **Nowe obiekty**: tworzenie polygonów i linii, usuwanie/kopiowanie obiektów, przesuwanie całych geometrii.
3. **Zaawansowane GIS**: podział i łączenie poligonów, edycja polilinii, pomiary, snapping i kontrola topologii.
4. **Pełna kartografia**: biblioteki LAY / CDF / SYM, etykiety, wzory, symbole; możliwie wierny klasyczny renderer.
5. **Wersja produkcyjna**: wydajność na wielkich mapach, zapis bezpośredni z kopią zapasową, odzyskiwanie awaryjne, instalator, testy rzeczywistych plików.

## Orientacyjny postęp

To przybliżony **zakres funkcji**, nie wskaźnik jakości/testów:

- Użyteczny edytor do codziennej pracy: **około 70%** po potwierdzeniu tego PR.
- Całkowity zamiennik klasycznego GeoStudio: **około 45%**.

Najwięcej pozostałej pracy to integracja wielu operacji na obiektach oraz pełna zgodność renderowania i formatów.
Do pracy produkcyjnej używaj zweryfikowanej aplikacji klasycznej lub dokładnie sprawdzonej wyeksportowanej kopii MAP.
