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

## Etap 7 — biblioteki kartograficzne i etykiety (PR testowy)

- [ ] Scalone 5310 zachowują albo uzupełniają natywne L 1/L 2/L 3;
  pierwsza wyspa i węzeł bazowego :ID są utrzymywane przy zapisie,
  aby ograniczyć przemieszczenie napisów.
- [ ] Nowo narysowane 5310 z A1/A2 otrzymują natywne rekordy L.
  Wymagany test rzeczywistego opisu po scaleniu A1=l/A2=So120|II-0.3
  z analogicznym wzorcem GEO-MAP A1=b/A2=So80|I-0.5.
- [ ] Zwykły „Pobierz MAP” w Windows **automatycznie** wypala
  wycięcia tego samego kodu, jeśli istnieją maski — bez oddzielnego
  przycisku. Zachowuje dodatkowy JSON v2 do odtwarzania.
- [ ] W przeglądarce pobieranie maskowanych obiektów odbywa
  się jako ZIP (MAP + JSON); bez masek pojedynczy MAP.
- [ ] Import oryginalnych LAY/CDF/SYM z Windows / przeglądarki
  bez ścieżek użytkownika w HTTP API, limit 8 MB, CP1250.
- [ ] Canvas: CDF 0–8 (wypełnienia/hatch/obrysy),
  LAY/SYM przerywane granice oraz SYM proste symbole punktowe.
- [ ] Zaawansowane symbole O/T, niestandardowe kroje/pozycje
  napisów, wszystkie katalogi LAY i pełny wydruk klasycznego
  GEO-MAP nadal wymagają odrębnych badań z rzeczywistymi
  bibliotekami i ręcznych testów zgodności.

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


## Etap 9 — rysowanie z magnesem i etykiety zależne od skali (PR #57, testy)

- [x] Niezależny od trybu P **Magnes G** obok „Nowy poligon”
  (domyślnie włączony); obejmuje także rysowanie linii i podziałów.
  Przyciąga do widocznych węzłów GEO-MAP maks. **7 pikseli** i do linii
  maks. **5 pikseli**; najbliższa krawędź nie jest przegrywana przez
  odległy narożnik. Bez zmian geometrii istniejących obiektów.
- [x] **Alt** chwilowo wyłącza magnes przy pojedynczym kliknięciu,
  przełącznik G umożliwia trwałe wyłączenie. Nie przyciąga do warstw
  wyłączonych. Wskaźnik na mapie pokazuje docelowy węzeł lub krawędź.
- [x] Punkty są próbkowane **w chwili kliknięcia** do GEO-MAP 1 mm.
  Przyciąganie respektuje skalę widoku, działa dla N, L i linii cięcia.
- [x] Rozmiar napisów Canvas zależy od skali mapy, a nie stałych pikseli,
  więc przy oddalaniu nie zasłaniają coraz mniejszych obrysów.
  Zbyt małe opisy są ukrywane; aktywny obiekt pozostaje czytelny.
- [x] **5310 A1 i A2 stanowią jedną grupę układu** (z zachowaniem
  osobno przeniesionych opisów) i nie konkurują ze sobą w antykolizji.
  A2 wielowierszowe z separatorem pionowej kreski pozostaje w całości.
- [x] Testy helpera JS przez Node (węzeł/krawędź, Alt, widoczność),
  test skali i grup A1/A2 oraz zachowania źródłowego MAP/CHK.
  **Wymagany test wzrokowy na rzeczywistej mapie GEO-MAP.**

### Brakujące możliwości z klasycznego GeoStudio 0.14 (Qt)

Kolejność po etapie 9, porównana z implementacją w geostudio/app.py:

1. **Etap 10A — pozycje i reguły etykiet**: tryb dawnego L
   (przesuwanie A1/A2/TX bezpośrednio na mapie), edytor widoczności
   i stylów opisów kodu Ctrl+Alt+L, zapis konfiguracji etykiet
   obok MAP. Zwykłe renderowanie A1/A2 już istnieje.
2. **Etap 10B — wyszukiwanie i masowa edycja**: dawne F (po ID,
   tekście i kodzie), Ctrl+F (zamiana frazy w atrybutach) z podglądem
   i jedną transakcją Undo, dowolny prawidłowy 4-cyfrowy kod przy
   tworzeniu poligonów oraz linii. Ctrl+H i zbiorowe A1/A2 już działają.
3. **Etap 11 — wydruk i eksport**: PNG/JPG/TIFF do druku, prosty DXF,
   ustawiana skala widoku i opracowania, oprawa mapy (legenda, północ,
   ramki i podziałki). Wymaga testów geodezyjnej orientacji X/Y.
4. **Etap 12 — dane podkładowe**: rastry i pliki world,
   GCP/kalibracja, przezroczystość i kolejność warstw,
   WMS w tle, transformacja współrzędnych i eksport
   nowego MAP w innym układzie.
5. **Etap 13 — zaawansowana kartografia**: pełniejsze reguły
   i symbole bibliotek LAY/CDF/SYM, desenie i style wydruku,
   większa zgodność optyczna z klasycznym GeoStudio.

Bezpieczeństwo pozostaje wymaganiem w każdym etapie:
kopie w pamięci, ochrona innych kodów, bezpieczny eksport, Ctrl+Z.
Przed etapem 10A test magnetu i napisów na mapie użytkownika.


## Etap 10A — interaktywne etykiety i skala (draft, do ręcznych testów)

- [x] Usunięto widoczną opcję „Δ X/Y” i skrót Ctrl+Shift+M.
  Przesuwanie M wielu zaznaczonych obiektów nadal jest domyślnie
  bez okna z magnetycznym przyciąganiem.
- [x] Dwa **niezależne** opisy A1 i A2 dla 5310:
  bez wzajemnej kolizji, z rozdzielnymi hitboxami i przesuwaniem
  narzędziem **Alt+L**, zapisywanym w Undo/Ponów bez zmian MAP P.
- [x] **Ctrl+Alt+L**: edytor per-kod dla pojedynczego pola A1/A2/TX:
  widoczność, wielkość, kolor i pogrubienie; zmiana A1
  nie ukrywa A2.
- [x] Skala widoku 1:N (Ctrl+M) i skala opracowania
  1:N (Ctrl+F5), wykrywanie źródła z legendy przy braku
  ustawienia 1:5000, współrzędne kursora X/Y GEO-MAP w metrach.
- [x] Przesunięcia opisów i skala opracowania zachowywane
  w oddzielnym, SHA256 związanym z nowym MAP pliku
  .geostudio.json, automatyczny import w Windows,
  przeglądarkowe pobieranie ZIP i testy odzyskiwania zmian.
- [x] Poprawiona czytelność małych napisów przy normalnej
  pracy, bez nadmiernie dużych etykiet przy oddalaniu.
- [x] Przy rysowaniu Esc usuwa ostatni P. Magnes G przy
  pierwszym punkcie po min. trzech punktach daje „DOMKNIJ”
  i jedno kliknięcie kończy szkic z normalną walidacją.
- [x] Canvas korzysta z przeskalowanej ostatniej
  klatki w trakcie odświeżania widoku; zamiast białego
  obszaru podczas każdego zoomu.
- [ ] Ręczna weryfikacja klasycznego GEO-MAP + GeoStudio 2.0
  po zapisaniu realnej mapy, umiejscowienie etykiet
  A1/A2 na różnych skalach, zachowanie przy przybliżaniu
  i cofanie szkicu w Windows WebView2.

Dalszy etap po potwierdzeniu 10A: wyszukiwanie F,
zamiana fraz Ctrl+F, dobieranie dowolnych kodów 4-cyfrowych,
następnie eksport i druk PNG/TIFF/DXF, WMS/rastry i GCP.


## Etap 10B — wyszukiwanie, zamiana i nawigacja bez sieci (testowy)

- [x] F / Znajdź: pełno-mapowe wyszukiwanie po źródłowym ID, kodzie i polach A1–A6, TX, MP, KR albo dowolnym tekście. Zawiera / dokładna wartość, bez rozróżniania wielkości liter; opcjonalny czterocyfrowy kod. Wyniki pokazują źródłowe ID, kod i A1/A2/TX, kliknięcie centruje oraz zaznacza obiekt. Przy liczbie ponad 120 wyników informujemy o obcięciu listy.
- [x] Ctrl+F / Zamień: tylko istniejący wskazany atrybut, ciąg znaków, dowolny zamiennik (także pusty), opcjonalny kod; zaznaczone obiekty lub świadomie cała mapa. PreviewKey zależny od dokumentu, rewizji i operacji, podgląd 16 par przed → po. Sprawdzamy kodowanie CP1250 i limit 512 bajtów. Do 5000 zmienianych obiektów, jedna transakcja Ctrl+Z. MAP źródłowa bez zmian.
- [x] Stałe rozmiary etykiet ekranowych: font A1/A2/TX nie zmienia wielkości w pikselach podczas przybliżania lub oddalania, odrębna kontrola wielkości przez ustawienia kodu i skalę opracowania. Przy odległym widoku etykiety niektórych mikroskopijnych obiektów są ukrywane, lecz nie powiększane.
- [x] Bez sieci po pierwszym otwarciu: mapy do 12000 obiektów / 150000 wierzchołków pobierają pełną geometrię raz, następnie zoom i pan renderują na lokalnym Canvas, bez HTTP. Większe mapy używają nadal przestrzennego ładowania z podglądem ostatniej klatki. Eksport, edycje i zmiana bibliotek odświeżają dane w razie potrzeby.
- [x] Zapytanie o cały obszar mapy bez promieniowego przybliżenia indeksu; brak pominięć w narożnikach wydłużonych arkuszy.
- [x] Testy backendu, regresje tekstów, historii, tokenów, HTTP, niezmienności MAP/CHK oraz JS.
- [ ] Weryfikacja ręczna na rzeczywistej MOKRA WIEŚ.MAP w Windows/WebView2, przede wszystkim wydajność pełnego Canvas i szybki zoom.

Potencjalne następne etapy: wydruk/eksport PNG/TIFF/DXF; rastry/WMS z kalibracją GCP; transformacje X/Y i pełniejsze LAY/CDF/SYM.

## Etap 12 — podkłady WMS, raster i współrzędne (wersja testowa)

### 12A: ortofotomapy WMS Geoportalu

1. Otwórz MAP w GeoStudio 2.0 i kliknij **Podkłady WMS**.
2. Wskaż **zweryfikowany układ EPSG mapy**. GeoStudio nie zgaduje CRS
   na podstawie liczbowych wartości współrzędnych. Obsługiwane są
   PL-1992 EPSG:2180 i PL-2000 EPSG:2176–2179.
3. Wybierz standardową lub wysokorozdzielczą ortofotomapę i kliknij
   **Pobierz warstwy**. Wskaż warstwę zgodną z EPSG, po czym
   **Pokaż pod mapą**. Suwak reguluje przezroczystość.
4. Obraz jest rysowany *pod* liniami, obrysami i etykietami GEO-MAP.
   Przy zoomie i przesunięciu poprzedni obraz przesuwa się wraz z
   geometrią; po ~420 ms bez ruchu pobierany jest nowy fragment.
   Błędy pobrania nie usuwają poprzedniego obrazu.

Obraz pochodzi z oficjalnego WMS GUGiK. Lokalny serwer zezwala tylko
na dwa predefiniowane hostowane na HTTPS adresy Geoportalu, blokuje
przekierowania, narzuca limity odpowiedzi i wymaga tokenu dostępu.
Zaznaczone obiekty, atrybuty i zawartość MAP nie są wysyłane do WMS.
W tej wersji **nie ma reprojekcji podkładu**: EPSG mapy musi zgadzać
się z wybraną warstwą. Niepoprawny EPSG może spowodować wyświetlenie
niepasujących danych — sprawdź położenie na znanym punkcie.

### 12B: raster lokalny, GeoTIFF, world file i GCP

W tym samym oknie wybierz PNG/JPG/WebP/TIFF/GeoTIFF. TIFF/GeoTIFF
jest dekodowany przez serwer lokalny do PNG (Pillow); pliki PNG/JPG
pozostają w pamięci przeglądarki. Limity: **48 MB plik TIFF**
i **24 mln pikseli**. To limity bezpieczeństwa wersji testowej.

- GeoTIFF: próba odczytu georeferencji i EPSG z tagów TIFF; obrazy
  z nieobsługiwanym lub różnym EPSG nie są nakładane na mapę.
- World file (.pgw, .jgw, .tfw, .wld): współczynniki
  A/D/B/E/C/F, z korektą środka piksela na narożnik. Ten plik
  nie podaje EPSG — wybierz świadomie CRS odpowiadający MAP.
- GCP: minimum **trzy niewspółliniowe punkty** w osobnych wierszach
  `u v X Y`, gdzie u/v są współrzędnymi piksela (od lewego górnego
  narożnika), a X=północ/Y=wschód to współrzędne GEO-MAP w metrach.
  W wyniku pokazywany jest RMSE dopasowania afinicznego.
  Przed trasowaniem sprawdź kilka niezależnych punktów.

Po zmianie EPSG raster skalibrowany w poprzednim układzie pozostaje
ukryty; konieczne jest ponowne potwierdzenie georeferencji.
Rastry w tej wersji są **tymczasowym podkładem w sesji**, nie trafiają
do MAP i nie są jeszcze dołączane do eksportu PNG/TIFF z etapu 11.

### 12C: weryfikacja PRJ i przeliczenie punktu

Opcjonalnie wybierz plik .prj zawierający WKT. GeoStudio weryfikuje
EPSG przy wysokim progu pewności; nie wnioskuje go z nazw folderów
lub samych liczb. Przycisk **Przelicz współrzędne środka mapy**
pokazuje X/Y środka bieżącego widoku w innym obsługiwanym EPSG.
Przeliczenie jest *tylko podglądem punktu* — nie zmienia MAP.

**Jeszcze niezaimplementowane w tym etapie:** reprojekcja całej mapy
MAP w nowym interfejsie, trwały zapis kalibracji podkładu, rastry
w eksporcie arkusza, kalibracja GCP bezpośrednio klikaniem parami
na obrazie i mapie, duże GeoTIFF-y oraz pełny GeoTIFF z warstwami
i różnymi rodzajami pikseli. Pozostają osobnym zadaniem.

Do testów używaj kopii MAP. Nie zakładaj, że poprawny rezultat
testów API oznacza sprawdzoną zgodność terenową.
