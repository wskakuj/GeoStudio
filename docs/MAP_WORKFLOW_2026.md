# GeoStudio — edycja map i oprawy (18 listopada 2026)

## Zaznaczanie
- Kliknij obiekt, a następnie **B**: utrwala podświetlenie tego obiektu.
- Kliknij następny, **B**: oba pozostają zaznaczone; dalej można dodawać kolejne.
- Naciśnięcie **B** na już utrwalonym obiekcie usuwa go z utrwalonej grupy.
- **Ctrl+Shift+B** czyści utrwaloną grupę.
- **Ctrl+L** zaznacza wszystkie widoczne obiekty o takim samym kodzie jak aktywny obiekt.
- **F** jest jedynym skrótem okna wyszukiwania po kodzie/A1/A2 (Ctrl+H zwolniono).
- **S** przełącza zwykłe zaznaczanie. **Ctrl+klik** nadal pozwala łączyć obiekty ręcznie.

## Węzły i linie
- **P** aktywuje edycję węzłów aktualnie wybranego poligonu.
- Przełącznik **Wspólne węzły** w zakładce **Edycja**, sekcja **Szkic**,
  decyduje, czy przy przesunięciu wierzchołka przesuną się również wspólne
  wierzchołki zamkniętych poligonów tego samego kodu. Można go wyłączyć.
- **Przyciąganie** jest niezależnym przełącznikiem i może wskazywać wierzchołki
  lub segmenty **różnych kodów**, także graniczniki ukryte na mapie.
- **6900** jest automatycznie linią. Wstaw co najmniej dwa różne punkty i
  zakończ Enterem lub prawym przyciskiem. Powstaje otwarta geometria.
- **I** uruchamia rysowanie otwartej linii dowolnego kodu.
- **N** uruchamia dotychczasowy kreator poligonu. Pozostałe kody nadal są
  traktowane jako poligon, chyba że ręcznie użyjesz narzędzia **I**.

## Oprawa mapy i kompozycja
Z menu **Oprawa mapy** albo z kontekstowego menu **PPM** na płótnie można
wstawić cztery edytowalne elementy:
1. Kompas z literą N.
2. Tablicę tytułową (miejscowość, gmina, stan, okres, powierzchnia — teksty do uzupełnienia).
3. Metrykę wykonawcy i opracowujących.
4. Legendę z opisami znaków i kolorów.

Przeciąganie zmienia położenie elementu, **dwuklik** otwiera edycję opisów
i przycisk „Usuń element”. Historia Ctrl+Z obejmuje dodawanie, przesuwanie,
edycję oraz usuwanie. Obrazy mapy eksportowane przez GeoStudio zawierają oprawę.

Zaznacz stary element kodu **5200, 6000 lub 7900**, aby użyć polecenia
„Ukryj zaznaczony dawny element”. Działa tylko na wybrany rekord, nie usuwa
go z mapy i można to cofnąć przez „Przywróć ukryte elementy”.

**Ważne:** oprawa mapy jest własnym wektorowym systemem GeoStudio,
przechowywanym w towarzyszącym pliku `*.geostudio.json`.
Nie jest natywną geometrią GEO-MAP. Eksport PNG/JPG/TIFF z GeoStudio
zawiera te elementy, ale sam plik .MAP otwarty w GEO-MAP nie odtworzy
tych nowych nakładek bez pliku stylów i GeoStudio.

## Kopie robocze
Po edycji program zapisuje jedną aktywną sesję w lokalnym katalogu aplikacji,
np. `%LOCALAPPDATA%/GeoStudio/autosave/`, poza folderem z mapami.
Kolejne edycje aktualizują ten sam plik. Po ponownym otwarciu oryginału
proponowane jest wznowienie zapisanej sesji.

Jeśli odmówisz przywrócenia, poprzedni autosave pozostaje nienaruszony,
a nową pracę zapisujesz ręcznie przez **Zapisz jako**.
Oryginał .MAP nie jest nadpisywany automatycznie; wcześniej utworzone
`*_GeoStudio_robocza_2.MAP` itd. **nie są automatycznie usuwane**.
Otwieraj i sprawdzaj pliki zgodnie z zaleceniami programu GEO-MAP.
