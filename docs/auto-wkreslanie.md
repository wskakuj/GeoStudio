# Auto Wkreślanie: proste granice, dopasowanie do 5216 i dokładność

Narzędzie tworzy obrys wydzielenia 5310 ze skalibrowanego obrazu. Wczytywanie JPG, PNG, TIFF/GeoTIFF, WebP i pojedynczego arkusza PDF prowadzi do tego samego algorytmu. Format pliku nie wybiera innego sposobu rozpoznawania granic.

## Użycie

1. Otwórz mapę MAP i dodaj raster. GeoTIFF lub plik world może zawierać położenie; pozostałe obrazy skalibruj punktami GCP.
2. Włącz **Auto Wkreślanie**. Domyślna analiza **Dokładna** zachowuje więcej szczegółów dużego skanu. **Szybsza** zużywa mniej pamięci.
3. Kliknij rozpoznane pole albo zaznacz kilka stykających się fragmentów tworzących jedno wydzielenie.
4. Domyślnie włączone **Dopasuj do 5216** dosuwa bliskie, współbieżne boki wybranego obrysu do granic działek. W razie potrzeby zmień **Zasięg** w metrach.
5. Sprawdź czerwony obrys. Magnes nadal pozwala ręcznie dopasować węzły i boki do geometrii MAP. Wpisz A1 i zatwierdź 5310.

Zmiana **Kontury**, **Analiza** lub **Prostowanie** ponownie analizuje obraz i usuwa bieżący, niezapisany szkic. Zapisane wydzielenia pozostają na mapie.

## Dopasowanie do granic działek 5216

Gruba kreska na rastrze może zostać rozpoznana kilka pikseli obok właściwej granicy działki. Opcja **Dopasuj do 5216** porównuje gotowy obrys wybranego pola lub kilku scalonych fragmentów z geometrią 5216 w MAP. Bliskie odcinki biegnące w tym samym kierunku dopasowuje do granicy wektorowej, również wtedy, gdy składa się ona z kilku kolejnych odcinków. Efekt widać w czerwonym obrysie przed zatwierdzeniem.

**Zasięg** określa dopuszczalną odległość wyszukiwania w metrach. Program dobiera wartość początkową na podstawie kalibracji i rozdzielczości podglądu, w przedziale od 0,5 do 5 m. Można ją zmienić w zakresie od 0,1 do 20 m. Ustawiony zasięg pozostaje taki sam przy przybliżaniu mapy oraz przełączaniu analizy między **Dokładną** a **Szybszą**. Nie należy go mylić z limitem prostowania kreski opisanym niżej.

Dopasowanie korzysta z granic 5216 całego obszaru rastra, także gdy ich warstwa jest ukryta. Geometria działek pozostaje bez zmian; dopasowywany jest nowy obrys 5310. Program nie dzieli automatycznie wydzielenia wzdłuż wszystkich działek — korzysta z tych granic, wzdłuż których przebiega rozpoznany obrys.

Sąsiadujące pola uzgadniają wspólne narożniki i boki. Jeżeli dopasowanie nadmiernie zmienia wąski fragment albo daje niepoprawny obrys, wspólna granica pozostaje spójna po obu stronach. Zaznaczenie kilku pól łączy ich uzgodnione obrysy, bez ponownego niezależnego dopasowania granicy z pikseli.

Zmiana zasięgu lub włączenie i wyłączenie dopasowania przelicza automatyczny szkic bez ponownego rozpoznawania pól i zachowuje wpisane A1. Szkic poprawiony ręcznie pozostaje bez zmian po zmianie tych ustawień; informuje o tym komunikat w panelu. Ręczne poprawianie węzłów i przyciąganie magnesem są nadal dostępne.

Rzeczywista linia podziału może przebiegać bardzo blisko i równolegle do granicy działki. W takim miejscu sprawdź podgląd, zmniejsz zasięg albo wyłącz **Dopasuj do 5216**. Przyciąganie nie zastępuje dobrej kalibracji rastra.

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

## Numery i wysięgniki

Aktualne narzędzie nie rozpoznaje odręcznych numerów A1. Niebieskie i zielone opisy nie są traktowane jako granice, ale ich treść i wysięgniki nie są jeszcze interpretowane. Numery wpisuje się ręcznie.

Pełne wkreślenie arkusza wymaga osobnego etapu odczytu cyfr i przypisania ich do wydzieleń. Dla numeru poza poligonem decydujące jest zakończenie wysięgnika, a dla numeru wewnętrznego jego położenie w polu. Odległość od środka kółka do najbliższego poligonu nie wystarcza. Niepewne odczyty i przecięcia wysięgników powinny trafiać do kontroli przed zapisem i przed scalaniem po A1.
