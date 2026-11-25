# Auto Wkreślanie: wspólne granice, dopasowanie do 5216 i odczyt A1

Narzędzie tworzy obrys wydzielenia 5310 ze skalibrowanego obrazu. Wczytywanie JPG, PNG, TIFF/GeoTIFF, WebP i pojedynczego arkusza PDF prowadzi do tego samego algorytmu. Format pliku nie wybiera innego sposobu rozpoznawania granic.

## Użycie

1. Otwórz mapę MAP i dodaj raster. GeoTIFF lub plik world może zawierać położenie; pozostałe obrazy skalibruj punktami GCP.
2. Włącz **Auto Wkreślanie**. Domyślna analiza **Dokładna** zachowuje więcej szczegółów dużego skanu. **Szybsza** zużywa mniej pamięci.
3. Kliknij rozpoznane pole albo zaznacz kilka stykających się fragmentów tworzących jedno wydzielenie.
4. Domyślnie włączone **Dopasuj do 5216** dosuwa bliskie, współbieżne boki wybranego obrysu do granic działek. Bliskie granice już zapisanych 5310 również stanowią odniesienie, aby nowe pole przylegało do sąsiada. W razie potrzeby zmień **Zasięg** w metrach.
5. Sprawdź czerwony obrys i A1. Jednoznacznie odczytany numer program wpisuje przy pierwszej propozycji. Jeśli odczyt rastra jeszcze trwa, numer pojawi się po jego zakończeniu; można też od razu wpisać go ręcznie. Niepewny odczyt wymaga wpisania A1 ręcznie. Magnes pozwala poprawić węzły; po kontroli zatwierdź 5310.

Zmiana **Kontury**, **Analiza** lub **Prostowanie** ponownie analizuje obraz i usuwa bieżący, niezapisany szkic. Zapisane wydzielenia pozostają na mapie.

## Dopasowanie do granic działek 5216

Gruba kreska na rastrze może zostać rozpoznana kilka pikseli obok właściwej granicy działki. Opcja **Dopasuj do 5216** porównuje gotowy obrys wybranego pola lub kilku scalonych fragmentów z geometrią 5216 w MAP. Bliskie odcinki biegnące w tym samym kierunku dopasowuje do granicy wektorowej, również wtedy, gdy składa się ona z kilku kolejnych odcinków. Efekt widać w czerwonym obrysie przed zatwierdzeniem.

**Zasięg** określa dopuszczalną odległość wyszukiwania w metrach. Program mierzy tusz wzdłuż długich rozpoznanych boków i dobiera początkową wartość do grubości kreski, prostowania oraz kalibracji. Dzięki temu gruba kreska zachodząca na 5216 nie jest traktowana jak cienka kreska oddalona od granicy. Automatyczna wartość mieści się w przedziale 0,5–20 m. Gdy pomiar nie jest wiarygodny, pozostaje wartość z rozdzielczości podglądu i kalibracji, 0,5–5 m.

Zasięg można zmienić ręcznie w zakresie **0,1–20 m**. Ręczny wybór ma pierwszeństwo. Ustawienie obejmuje także dopasowanie do sąsiednich 5310 i pozostaje dostępne po wyłączeniu opcji **Dopasuj do 5216**. Przybliżanie mapy, przełączenie jakości **Dokładna / Szybsza** i zapis kolejnego pola nie zmieniają ustawionej odległości. Nie należy jej mylić z limitem prostowania kreski opisanym niżej. Przy dwóch dopasowanych bokach rzeczywisty narożnik może leżeć w przekątnej ich pasów tolerancji.

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

Podgląd obrazu ma ograniczony rozmiar. Analiza dokładna wykorzystuje do 12 mln pikseli, szybsza do 6 mln. Współrzędne GCP i transformacja nadal odnoszą się do oryginalnych pikseli źródła. Przełączenie jakości nie zmienia położenia rastra ani zapisanych poligonów.

PDF jest renderowany lokalnie. Stała siatka źródłowa odpowiada 300 dpi, a sam podgląd powstaje od razu w ograniczonym rozmiarze. To nie dodaje szczegółów do niskiej jakości skanu. PDF wielostronicowy wymaga zapisania wybranego arkusza osobno; program nie wybiera strony bez wskazania użytkownika.

Przy mapie pogniecionej, złożonej lub nierównomiernie zeskanowanej rozmieść punkty GCP po całym obszarze i sprawdź także miejsca niewykorzystane do dopasowania. Sama zgodność na trzech punktach nie dowodzi, że cały arkusz jest dobrze dopasowany.

## Numery A1 i wysięgniki

Przy otwieraniu narzędzia rozpoczyna się lokalne rozpoznawanie numerów, równolegle do analizy granic. Jednoznaczna propozycja wypełnia **A1 po pierwszym kliknięciu**. Jeśli rozpoznawanie jeszcze trwa, panel informuje o tym, a wynik uzupełnia aktualnie wybrane pole po zakończeniu odczytu. Można w tym czasie poprawiać obrys lub wpisać numer ręcznie. Wynik jest zapamiętywany dla rastra, więc kolejne kliknięcia nie uruchamiają odczytu całego arkusza ponownie. Program nie wysyła skanu do usługi OCR i nie wymaga dodatkowego konta ani klucza API.

Dla numeru w kółku z wysięgnikiem liczy się wskazane pole; samo położenie kółka najbliżej innego poligonu nie wystarcza. Numer bez wysięgnika musi należeć do wnętrza pola. Jeśli odczyt lub przypisanie są niepewne, A1 pozostaje do wpisania ręcznie, a panel wyświetla informację. Zaznaczenie pól z różnymi rozpoznanymi numerami nie wybiera jednego z nich losowo.

Ręcznie wpisany lub poprawiony A1 ma pierwszeństwo. Zmiana zasięgu, dopasowania albo dołączenie sąsiedniego fragmentu nie zastępują go odczytem z rastra. Po zapisie numer jest czyszczony przed następnym polem. Sprawdź propozycję przed zatwierdzeniem, szczególnie przy włączonym **Scalaj po A1**.

Odczyt obejmuje niebieskie i zielone numery oraz ciemne numery w rozpoznanym kółku. Zwykłe czarne napisy podkładu i czerwone linie podziału nie są traktowane jako samodzielne numery A1. Skuteczność zależy od jakości skanu, rozdzielczości cyfr, zetknięcia znaków z kółkiem i przebiegu wysięgników. Nie każdy numer będzie rozpoznany automatycznie. Szczegóły lokalnego modelu, jego pochodzenie i ograniczenia opisuje [dokumentacja modelu A1](raster-a1-model.md).
