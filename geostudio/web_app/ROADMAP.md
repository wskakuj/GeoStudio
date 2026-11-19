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

## Potwierdzony etap 4B (PR #51, scalony do main)

- [x] **Zbiorowo A1/A2**: jawne checkboxy dla pól, obsługa pustych wartości.
- [x] Podgląd: liczby zmian, pola niedostępne, przykłady przed/po.
- [x] Zmiany w wybranych (a nie wszystkich tego samego kodu), limit 5 000.
- [x] Jedna transakcja Cofnij/Ponów, ochrona niezmienionych rekordów MAP.
- [x] Zapis bez nadpisywania źródła, walidacja CP1250 i blokada starej rewizji.

## W tym PR — etap 5A + 5B, wymaga próby użytkownika

- [ ] **Przesuwanie poligonów**: M + przeciągnięcie na mapie, podgląd zarysu na Canvas.
- [ ] Dokładne przesunięcie X/Y (w natywnych metrach GEO-MAP), Ctrl+Shift+M.
- [ ] Zaznaczenie pojedyncze lub do 5 000 poligonów przez Ctrl+H.
- [ ] Podgląd przed zastosowaniem, ochrona niezmienionych obiektów i innych kodów.
- [ ] Wspólna granica z nieruchomym sąsiadem tego samego kodu blokuje zmianę;
      można świadomie zezwolić na rozłączenie granicy.
- [ ] Jedno Cofnij/Ponów, odrzucenie niepoprawnej rewizji, kontrola poprawności
      zamkniętych poligonów i eksport kopii z CHK.

### Poprawki do etapu 5A

- [ ] Przeciwdziałanie nakładaniu się powierzchni poligonów tego samego kodu
      **po** przesunięciu, niezależnie od opcji rozłączenia granicy.
- [ ] Przyciąganie bliskich krawędzi (przede wszystkim wspólne odcinki), bez
      przesuwania niezaznaczonych kodów; brak automatycznej unii dwóch rekordów.
- [ ] Natywne okno Windows **Zapisz jako** z pełną ścieżką pliku wynikowego;
      w przeglądarce pobieranie do folderu wybranego w ustawieniach przeglądarki.
- [ ] Pasek narzędzi przewijany poziomo w mniejszym oknie, bez ukrywania sekcji.

### Etap 5B — operacje na obiektach

- [ ] Kopiowanie poligonów z zachowaniem natywnych rekordów/atrybutów i nowym :ID,
      w miejscu bez nakładania na poligony tego samego kodu.
- [ ] Usuwanie zaznaczonych obiektów z potwierdzeniem i jedną transakcją historii.
- [ ] Rysowanie nowego poligonu kliknięciami na mapie, kod 5216/5220/5230/5310,
      A1/A2 i walidacja obrysu przed zapisem.
- [ ] Testy API, walidacji, wycofania zmian, ochrony źródłowego MAP i CHK.

## Etap 6A — geometria i odwracalne nakładanie (w tym PR, do testów)

- [ ] **Odwracalne wycinanie w widoku**: przesuwany poligon zasłania i
  geometrycznie wycina część niższego poligonu *tego samego kodu*, ale oba
  surowe rekordy P pozostają nietknięte. Przesunięcie górnego w inne miejsce
  od razu przywraca pełny kształt niższego.
- [ ] Kolejność nakładania jest częścią pojedynczej transakcji Cofnij/Ponów.
  Natywne „Zapisz jako” zapisuje obok MAP powiązany checksumem plik
  \`.geostudio-topology.json\`; należy zachować oba pliki razem.
- [ ] **OGRANICZENIE**: klasyczny GEO-MAP wczytuje MAP bez tej dodatkowej
  informacji o wycinaniu. GEO-MAP widzi bazową, nieobciętą geometrię.
  Produkcyjny „wypalony” eksport maskowanych obrysów wymaga odrębnego,
  sprawdzonego zapisu geometrii z otworami (etap 6B).
- [ ] Ctrl+D tworzy kopię obok zaznaczenia i aktywuje M do przesuwania.
  Oddzielne „Kopiuj z dokładnym przesunięciem” pozostaje w Ctrl+K.
- [ ] **M**: magnetyczne przyciąganie do węzłów i odcinków tylko tego
  samego kodu podczas przeciągania, podgląd na mapie.
- [ ] **Pole +**: normalizacja kierunku wybranych prostych zamkniętych
  obrysów (jedno Cofnij/Ponów); nowe poligony są zawsze zapisywane z
  orientacją dodatnią. Wieloczęściowe P0 nie są normalizowane automatycznie.
- [ ] **Scal**: zgodny kod i A1/A2, geometryczny Polygon union, bez otworów;
  zachowuje pierwszy identyfikator oraz jego pozostałe atrybuty.
- [ ] **Podziel**: prosty zamknięty poligon cięty linią, nowe unikalne :ID,
  zachowanie sumy powierzchni, Cofnij/Ponów.
- [ ] **L**: nowa linia 6900/6000/6301/2364; **Shift+L**: narysowanie
  nowego przebiegu zaznaczonej linii.
- [ ] Podział i scalenie nie mogą bezpiecznie przeliczać ewidencyjnych
  A4/A6, więc aplikacja wyświetla ostrzeżenie o ręcznej weryfikacji.

## Etap 6B — testowa geometria wieloczęściowa i zapis prawdziwych wycięć

- [ ] **Scalanie bez styku**: jeden obiekt :ID może zawierać wiele wysp
  nieprzylegających i stykających się tylko w pojedynczym węźle. Używamy
  natywnego P 0 do kończenia każdej części, bez fałszywych krawędzi.
  Otwory są oddzielnymi konturami; suma powierzchni ma poprawny znak.
- [ ] **Auto dodatnie pole**: zwykłe Windows „Zapisz jako” zawsze
  normalizuje orientację prostych zamkniętych obrysów w NOWYM pliku.
  Nie modyfikuje oryginalnego MAP ani historii. Nowe poligony i kopie
  są także tworzone z dodatnim kierunkiem.
- [ ] **Eksport natywnych wycięć 6B**: oddzielny przycisk generuje
  rzeczywiste różnice geometryczne w MAP (P0 — wiele części i otwory)
  dla tego samego kodu. Sprawdzamy poprawność po ponownym parsowaniu,
  numery ID, CHK, sumę pól, niezmienność obcych obiektów i siatkę 1 mm.
- [ ] **Odtwarzanie oryginału**: obok MAP powstaje dodatkowy
  \`.geostudio-topology.json\` v2 związany SHA256, zawierający
  kopię pierwotnych rekordów P zmienionych poligonów. Przy otwieraniu
  obu plików w GeoStudio 2.0 oryginalna geometria zostaje
  zweryfikowana i odtworzona do edycji w pamięci.
- [ ] **Bezpieczeństwo zapisu**: natywny eksport wycięć wymaga
  nowej nazwy MAP, przygotowuje oba pliki na dysku przed publikacją,
  w razie błędu usuwa nowy plik towarzyszący.
  **Pełne przykrycie poligonu na razie blokuje eksport**, aby nie zgubić ID.
- [ ] **Zgodność klasycznego GEO-MAP DO POTWIERDZENIA:** poprawność
  składni i obliczeń sprawdzają testy automatyczne, ale w klasycznym
  programie trzeba zweryfikować otwarcie i reprezentację P0
  z otworami oraz wieloma wyspami. Nie stosować produkcyjnie bez testu.
- [ ] Ręczny test eksportu wieloczęściowych 5310, 5220 i 5230
  oraz otwartych linii przy rzeczywistej MOKRA WIEŚ.MAP.

## Pozostałe duże obszary

1. **Dopracowanie zaznaczania**: wybór według geometrii, wykluczanie nakładających się obiektów, testy bardzo dużych map.
2. **Obiekty i topologia**: rysowanie/edycja linii, scalanie i cięcie poligonów, zaawansowane granice i dzielenie powierzchni.
3. **Zaawansowane GIS 6C**: zgodność P0 z klasycznym GEO-MAP, poprawny eksport w pełni przykrytych poligonów z odzyskaniem ID, podział złożonych wielokonturowych obiektów, weryfikacja A4/A6, pomiary i topologia.
4. **Pełna kartografia**: biblioteki LAY / CDF / SYM, etykiety, wzory, symbole; możliwie wierny klasyczny renderer.
5. **Wersja produkcyjna**: wydajność na wielkich mapach, zapis bezpośredni z kopią zapasową, odzyskiwanie awaryjne, instalator, testy rzeczywistych plików.

## Orientacyjny postęp

To przybliżony **zakres funkcji**, nie wskaźnik jakości/testów:

- Użyteczny edytor do codziennej pracy: **około 75%** po potwierdzeniu etapu 4B.
- Całkowity zamiennik klasycznego GeoStudio: **około 48%** po potwierdzeniu etapu 4B.

Najwięcej pozostałej pracy to integracja wielu operacji na obiektach oraz pełna zgodność renderowania i formatów.
Do pracy produkcyjnej używaj zweryfikowanej aplikacji klasycznej lub dokładnie sprawdzonej wyeksportowanej kopii MAP.
