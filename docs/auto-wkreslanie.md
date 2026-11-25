# Auto Wkreślanie: wspólne granice, dopasowanie do 5216 i odczyt A1

Narzędzie tworzy obrys wydzielenia 5310 ze skalibrowanego obrazu. Wczytywanie JPG, PNG, TIFF/GeoTIFF, WebP i pojedynczego arkusza PDF prowadzi do tego samego algorytmu. Format pliku nie wybiera innego sposobu rozpoznawania granic.

## Użycie

1. Otwórz mapę MAP i dodaj raster. GeoTIFF lub plik world może zawierać położenie; pozostałe obrazy skalibruj punktami GCP.
2. Włącz **Auto Wkreślanie**. Domyślna analiza **Dokładna** zachowuje więcej szczegółów dużego skanu. **Szybsza** zużywa mniej pamięci.
3. Kliknij rozpoznane pole albo zaznacz kilka stykających się fragmentów tworzących jedno wydzielenie.
4. Domyślnie włączone **Dopasuj do 5216** dosuwa bliskie, współbieżne boki wybranego obrysu do granic działek. Bliskie granice już zapisanych 5310 również stanowią odniesienie, aby nowe pole przylegało do sąsiada. W razie potrzeby zmień **Zasięg** w metrach.
5. Sprawdź czerwony obrys i A1. Jednoznacznie odczytany numer program wpisuje przy pierwszej propozycji. Jeśli odczyt rastra jeszcze trwa, numer pojawi się po jego zakończeniu; można też od razu wpisać go ręcznie. Słabszy odczyt z pewnym przypisaniem do pola pojawia się jako **A1 do sprawdzenia**. Przy nieustalonym wysięgniku lub sprzecznych pewnych numerach wpisz A1 ręcznie. Magnes pozwala poprawić węzły; po kontroli zatwierdź 5310.

Zmiana **Kontury**, **Analiza** lub **Prostowanie** ponownie analizuje obraz i usuwa bieżący, niezapisany szkic. Zapisane wydzielenia pozostają na mapie.

## Cała mapa jednym przyciskiem — tryb testowy od 2.0.104

Przycisk **Wkreśl całą mapę (test)** przygotowuje wspólny podgląd wszystkich rozpoznanych propozycji. Nie trzeba klikać każdego pola, żeby otrzymać jego obrys i odczyt A1. Przycisk **Pokaż cały raster** służy wyłącznie do ustawienia widoku; nie uruchamia wkreślania.

1. Po skalibrowaniu rastra otwórz **Auto Wkreślanie** i wybierz **Wkreśl całą mapę (test)**.
2. Program wybierze **Pełny obraz (test)**, kontury **Także cienkie** i prostowanie **Proste boki**. Analiza wykorzystuje do 14 mln pikseli przygotowanego obrazu. Uwzględnianie cienkich konturów ogranicza łączenie sąsiednich pól przez pominiętą cienką granicę.
3. Poczekaj na rozpoznanie pól, odczyt A1 i wspólne dopasowanie do granic. Obrysy pojawią się razem na mapie, a panel pokaże listę numerów oraz liczbę propozycji wymagających kontroli. Dopasowanie 5216 jest obliczane w tle, aby można było anulować długą analizę.
4. Sprawdź obrysy i A1. Kliknięcie pola na mapie wskazuje pozycję na liście. Przycisk z numerem `#` na liście przybliża odpowiedni obrys. Numer `#` oznacza identyfikator propozycji, a nie A1.
5. Popraw numery i zaznacz pola, które chcesz przyjąć. **Zapisz zaznaczone** tworzy wybrane 5310 wraz z A1 w jednej operacji. **Ctrl+Z** cofa całą zapisaną partię.

| Kolor obrysu | Znaczenie | Domyślne zaznaczenie do zapisu |
| --- | --- | --- |
| Zielony | Numer A1 odczytany z wystarczającą pewnością, potwierdzony lub poprawiony ręcznie | Pewny odczyt jest zaznaczony; nadal sprawdź obrys |
| Pomarańczowy | Brak numeru albo propozycja A1 wymagająca sprawdzenia | Nie; sprawdź lub wpisz A1 i zaznacz kratkę |
| Czerwony | Niepoprawny, zajęty lub kolidujący obrys | Zapis zablokowany |

Przy niepewnym numerze widoczny jest znak **?**. Gdy rozpoznano kilka wariantów cyfr, lista pokazuje te warianty. Własne A1 i świadome odznaczenia są zachowywane przy zmianie zasięgu oraz ponownym odczycie numerów. Ponowne rozpoznawanie konturów lub zmiana rozdzielczości tworzy nowy zestaw propozycji i usuwa niezapisane poprawki tego zestawu.

Domyślny filtr **Tylko obszar działek 5216** pomija propozycje leżące poza zasięgiem działek MAP, np. kolorowe prostokąty legendy skanu. Wymaga prawidłowego położenia rastra. Można go wyłączyć, gdy potrzebny obszar wykracza poza działki; wtedy dokładnie sprawdź dodatkowe propozycje. Jeżeli mapa nie zawiera zamkniętych 5216, filtr nie ogranicza obszaru.

Do zestawu trafiają pola wyróżnione kolorem lub granicą oraz pola z rozpoznanym A1, także białe. Pewnie umiejscowione kółko z nieczytelnym numerem również może wskazać pole do przeglądu — jego A1 pozostaje puste. Program nie zakłada, że każdy biały fragment i każdy napis drukowany na arkuszu jest wydzieleniem. Obszary istniejących 5310 są wykluczone. Wspólne boki nowych pól są uzgadniane razem, a przed zapisem serwer sprawdza całą wybraną grupę. Partie nie scalają istniejących obiektów o takim samym A1; opcja **Scalaj po A1** dotyczy trybu pojedynczego.

To tryb próbny: nie obiecuje kompletnego rozpoznania każdego wydzielenia. Nieczytelny numer, urwany kontur, kilka numerów w jednym wykrytym polu lub nieustalony wysięgnik mogą wymagać korekty. Pola wymagające poprawienia geometrii pomiń przy zapisie, a następnie skorzystaj z **Wróć do pojedynczego**. Przycisk ten odrzuca niezapisany zestaw propozycji.

Jedna partia obejmuje do **1000 propozycji**, **50 000 węzłów łącznie** i **500 węzłów jednego obrysu**. Przed dopasowaniem kontrolowana jest także złożoność całej sieci rozpoznanych granic. Przekroczenie limitu daje komunikat, zamiast pomijać część mapy bez informacji. Przy zbyt szczegółowym obrazie wybierz grubsze kontury lub mocniejsze prostowanie.

## Dopasowanie do granic działek 5216

Gruba kreska na rastrze może zostać rozpoznana kilka pikseli obok właściwej granicy działki. Opcja **Dopasuj do 5216** porównuje gotowy obrys wybranego pola lub kilku scalonych fragmentów z geometrią 5216 w MAP. Bliskie odcinki biegnące w tym samym kierunku dopasowuje do granicy wektorowej, również wtedy, gdy składa się ona z kilku kolejnych odcinków. Efekt widać w czerwonym obrysie przed zatwierdzeniem.

**Zasięg** określa dopuszczalną odległość wyszukiwania w metrach. Program mierzy tusz wzdłuż długich rozpoznanych boków i dobiera początkową wartość do grubości kreski, prostowania oraz kalibracji. Dzięki temu gruba kreska zachodząca na 5216 nie jest traktowana jak cienka kreska oddalona od granicy. Automatyczna wartość mieści się w przedziale 0,5–20 m. Gdy pomiar nie jest wiarygodny, pozostaje wartość z rozdzielczości podglądu i kalibracji, 0,5–5 m.

Zasięg można zmienić ręcznie w zakresie **0,1–20 m**. Ręczny wybór ma pierwszeństwo. Ustawienie obejmuje także dopasowanie do sąsiednich 5310 i pozostaje dostępne po wyłączeniu opcji **Dopasuj do 5216**. Przybliżanie mapy, przełączenie jakości **Dokładna / Szybsza** i zapis kolejnego pola nie zmieniają ustawionej odległości. Nie należy jej mylić z limitem prostowania kreski opisanym niżej. Przy dwóch dopasowanych bokach rzeczywisty narożnik może leżeć w przekątnej ich pasów tolerancji.

Od wersji 2.0.104 zwiększanie zasięgu rozszerza poszukiwanie granic, bez proporcjonalnego zwiększania wymaganego rozmiaru boku. Najpierw sprawdzane jest bliskie dopasowanie potwierdzone grubością kreski; dalsze odniesienia są rozważane, gdy takiego rozwiązania brak. Usuwa to błąd, przez który większy zasięg potrafił odrzucić wcześniej poprawnie dopasowane sąsiednie pola.

Status w panelu podaje liczbę odcinków odniesienia 5216, dopasowanych boków i pominiętych niejednoznacznych zmian. Boki już leżące na 5216 też są liczone jako dopasowane. Dzięki temu można odróżnić brak danych referencyjnych, brak dopasowania i obrys już zgodny z granicami.

Dopasowanie korzysta z granic 5216 całego obszaru rastra, także gdy ich warstwa jest ukryta. Geometria działek pozostaje bez zmian; dopasowywany jest nowy obrys 5310. Program nie dzieli automatycznie wydzielenia wzdłuż wszystkich działek — korzysta z tych granic, wzdłuż których przebiega rozpoznany obrys.

Sąsiadujące pola uzgadniają wspólne narożniki i boki. Jeżeli dopasowanie nadmiernie zmienia wąski fragment albo daje niepoprawny obrys, wspólna granica pozostaje spójna po obu stronach. Zaznaczenie kilku pól łączy ich uzgodnione obrysy, bez ponownego niezależnego dopasowania granicy z pikseli.

Krótkie współliniowe fragmenty są rozpatrywane jako część całego boku. Małe ścięcia narożników pozostawione przez grubą kreskę mogą przejść przez rzeczywisty węzeł 5216, gdy potwierdzają go oba sąsiednie boki. Samo pobliskie przecięcie obcych linii nie jest wystarczającą podstawą do zmiany kształtu.

Zmiana zasięgu lub włączenie i wyłączenie dopasowania przelicza automatyczny szkic bez ponownego rozpoznawania pól i zachowuje wpisane A1. Szkic poprawiony ręcznie pozostaje bez zmian po zmianie tych ustawień; informuje o tym komunikat w panelu. Ręczne poprawianie węzłów i przyciąganie magnesem są nadal dostępne.

Rzeczywista linia podziału może przebiegać bardzo blisko i równolegle do granicy działki. W takim miejscu sprawdź podgląd, zmniejsz zasięg albo wyłącz **Dopasuj do 5216**. Przyciąganie nie zastępuje dobrej kalibracji rastra.

## Sąsiednie i już wkreślone 5310

Wnętrza istniejących 5310 są wykluczone z rozpoznawania. Kliknięcie na istniejący 5310 jest odrzucane także na podstawie pełnej geometrii wektorowej, niezależnie od widoczności warstwy. Kontrola serwera ponownie sprawdza kliknięte miejsca, podgląd i zapis. Odrzucony automatyczny obrys nie pojawia się jako propozycja do zatwierdzenia.

Referencyjne 5216, 5220 i 5230 pozostają dostępne do wkreślania nowych wydzieleń. Wspólna nazwa warstwy „Użytki Leśne” nie oznacza, że taki obszar jest już zajęty przez 5310.

Przy bliskiej, zgodnej kierunkowo granicy istniejącego 5310 dopasowywany jest cały wspólny bok lub jego rzeczywiście wspólna część. Program zachowuje załamania i punkty styku w środku boku. Tak ustalona granica ma pierwszeństwo przy dopasowaniu do sąsiada. Obrys po dopasowaniu przechodzi ponowną kontrolę nakładania, a do zapisu trafiają współrzędne pokazane w podglądzie. Położenie źródłowych poligonów pozostaje bez zmian.

Jeśli odjęcie istniejących pól pozostawi osobne fragmenty albo otwór, program prosi o zmianę zaznaczenia. Nie wybiera sam przypadkowego fragmentu. Ręcznie poprawiony szkic nie jest ponownie automatycznie dosuwany do sąsiadów; nadal obowiązuje kontrola nakładania przy zapisie.

## Magnes przy poprawianiu węzłów

W Auto Wkreślaniu magnes daje pierwszeństwo dokładnemu węzłowi w promieniu **26 pikseli ekranu**, nawet gdy kursor leży już na krawędzi. Przechwycony węzeł pozostaje zaczepiony przy małym ruchu ręki; wyraźnie bliższy węzeł może przejąć zaczepienie, a odciągnięcie kursora poza **34 piksele** je zwalnia. Krawędzie mają zasięg **10 pikseli**.

Węzły pochodzą z pełnej geometrii MAP, więc uproszczenie widoku nie usuwa punktów przyciągania. Odległości ekranowe zachowują się tak samo przy różnych przybliżeniach. **Alt** chwilowo wyłącza magnes; można go też wyłączyć w panelu. Ręcznie poprawione punkty mają pierwszeństwo przed automatycznym dopasowaniem.

## Jak działa prostowanie

Program dopasowuje proste do całych boków, zamiast zachowywać każde załamanie pikselowej kreski. Dopasowanie ma ograniczenie odległości od odczytanego konturu. Prawdziwe narożniki, wklęsłości i miejsca styku kilku pól pozostają punktami podziału. Wspólna granica sąsiednich pól jest obliczana raz i używana po obu stronach.

| Ustawienie | Maksymalne odchylenie od konturu w pikselach analizy | Zastosowanie |
| --- | ---: | --- |
| Delikatne | 1 | Wyraźny skan, małe szczegóły i narożniki |
| Proste boki | 2,5 | Zwykła kreska; ustawienie domyślne |
| Drżąca kreska | 4 | Większe drobne drgania odręcznego obrysu |

Wąskie pola mogą wymagać mniejszej tolerancji niż wybrana. Algorytm ogranicza ją dodatkowo, aby nie spłaszczać takiego pola. Nie wymusza czterech narożników ani kątów prostych. Rzeczywisty wielobok może mieć więcej boków. Wynik przecinający sam siebie albo nadmiernie zmieniający powierzchnię nie jest przyjmowany w tej postaci.

Pod ustawieniami widoczne są rozmiar piksela analizy i limit prostowania przeliczone przez kalibrację na jednostki mapy (metry). Ten limit opisuje uproszczenie odczytanego konturu. Nie jest miarą całkowitego błędu położenia na gruncie: na wynik wpływają też skala i jakość skanu, grubość kreski oraz kalibracja.

## Duże rastry i kalibracja

Podgląd obrazu ma ograniczony rozmiar. Analiza dokładna wykorzystuje do 12 mln pikseli, szybsza do 6 mln, a **Pełny obraz (test)** do 14 mln pikseli dostępnego podglądu. Mniejszy obraz nie jest sztucznie powiększany; obraz przygotowany z przezroczystością może mieć niższy limit. Jest to rozdzielczość analizy, nie deklaracja dokładności geodezyjnej. Współrzędne GCP i transformacja nadal odnoszą się do oryginalnych pikseli źródła. Przełączenie jakości nie zmienia położenia rastra ani zapisanych poligonów.

PDF jest renderowany lokalnie. Stała siatka źródłowa odpowiada 300 dpi, a sam podgląd powstaje od razu w ograniczonym rozmiarze. To nie dodaje szczegółów do niskiej jakości skanu. PDF wielostronicowy wymaga zapisania wybranego arkusza osobno; program nie wybiera strony bez wskazania użytkownika.

Przy mapie pogniecionej, złożonej lub nierównomiernie zeskanowanej rozmieść punkty GCP po całym obszarze i sprawdź także miejsca niewykorzystane do dopasowania. Sama zgodność na trzech punktach nie dowodzi, że cały arkusz jest dobrze dopasowany.

## Numery A1 i wysięgniki

Przy otwieraniu narzędzia rozpoczyna się lokalne rozpoznawanie numerów, równolegle do analizy granic. Jednoznaczna propozycja wypełnia **A1 po pierwszym kliknięciu**. Jeśli rozpoznawanie jeszcze trwa, panel informuje o tym, a wynik uzupełnia aktualnie wybrane pole po zakończeniu odczytu. Można w tym czasie poprawiać obrys lub wpisać numer ręcznie. Wynik jest zapamiętywany dla rastra, więc kolejne kliknięcia nie uruchamiają odczytu całego arkusza ponownie. Program nie wysyła skanu do usługi OCR i nie wymaga dodatkowego konta ani klucza API.

Dla numeru w kółku z wysięgnikiem liczy się wskazane pole; samo położenie kółka najbliżej innego poligonu nie wystarcza. Numer bez wysięgnika musi należeć do wnętrza pola. Pewność odczytu cyfr jest oceniana osobno od przypisania do pola. Słabszy tekst przy jednoznacznej kotwicy jest widoczny w A1 jako propozycja do sprawdzenia. Przy nieustalonym wysięgniku pole pozostaje puste. Zaznaczenie pól z różnymi pewnymi numerami wymaga ręcznego wyboru A1.

Odczyt odrzuca rozgałęzione drukowane sieci mylone z wysięgnikami i sprawdza, czy skrócony wynik nie zgubił pierwszej cyfry dłuższego numeru. Numery wskazujące różne części jednego rozpoznanego obrysu mogą oznaczać brakującą granicę i wymagają kontroli. Gdy lokalny odczyt nie może się wykonać, panel pokazuje konkretną przyczynę oraz **Ponów odczyt A1**. Błąd OCR nie wyłącza ręcznego wpisywania numerów.

Ręcznie wpisany lub poprawiony A1 ma pierwszeństwo. Zmiana zasięgu, dopasowania albo dołączenie sąsiedniego fragmentu nie zastępują go odczytem z rastra. Po zapisie numer jest czyszczony przed następnym polem. Sprawdź propozycję przed zatwierdzeniem, szczególnie przy włączonym **Scalaj po A1**.

Odczyt obejmuje niebieskie i zielone numery oraz ciemne numery w rozpoznanym kółku. Zwykłe czarne napisy podkładu i czerwone linie podziału nie są traktowane jako samodzielne numery A1. Skuteczność zależy od jakości skanu, rozdzielczości cyfr, zetknięcia znaków z kółkiem i przebiegu wysięgników. Nie każdy numer będzie rozpoznany automatycznie. Szczegóły lokalnego modelu, jego pochodzenie i ograniczenia opisuje [dokumentacja modelu A1](raster-a1-model.md).
