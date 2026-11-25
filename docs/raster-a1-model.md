# Lokalny odczyt A1 z rastra

Odczyt numerów korzysta z **RapidOCR 3.10.0**, modeli **PP-OCRv6 small** oraz
**ONNX Runtime 1.32.0** na CPU. Instalator zawiera modele i biblioteki. Pierwsze
uruchomienie nie wymaga pobrania modelu, konta ani usługi chmurowej.

## Co jest rozpoznawane

Program oddziela niebieski i zielony atrament od drukowanej treści mapy, wyszukuje
całe napisy i rozpoznaje ciągi od jednej do pięciu cyfr. Uwzględnia również ciemne
numery w kółkach. Zwykłe czarne napisy na mapie nie są automatycznie uznawane za A1:
mogą być numerami działek, opisami drzewostanu lub innymi drukowanymi danymi.

Odczyt nie zgaduje cyfr na podstawie podobnych liter (`O` → `0`, `l` → `1`).
Zewnętrzny nawias rozpoznany zamiast kółka można pominąć, ale napis zawierający
inne litery, ukośniki lub znaki wymaga ręcznego wpisania. Czerwony atrament służy
w obecnym narzędziu przede wszystkim do rozpoznawania podziałów i nie jest
automatycznie odczytywany jako numer.

## Kółko i wysięgnik

Wynik OCR zawiera położenie napisu, a dla kółka także wykryte zakończenie
wysięgnika. Przypisanie do pola korzysta z zakończenia wysięgnika. Przecięcie
wysięgnika z innym polem nie przypisuje numeru do tego pola. Rozgałęzienie,
przerwa uniemożliwiająca prześledzenie linii lub kilka sprzecznych napisów
pozostawiają propozycję do sprawdzenia.

Krótka przerwa tuż przy kółku nie tworzy dwóch celów wysięgnika: dla pojedynczego
odcinka program odróżnia jego początek przy kółku od zakończenia w polu.
Naprawianie dłuższej przerwy wymaga ciemnego drukowanego śladu w tym miejscu;
przez biały odstęp nie są łączone osobne niebieskie znaki.
Sieć atramentu mająca więcej niż cztery końce nie jest rozsyłana jako wskazanie
do wielu pól. Zapobiega to tworzeniu fałszywych konfliktów przez drukowane linie
mapy połączone z przypadkowo rozpoznanym kółkiem.

Dopiero zgodne wyniki rozpoznania całego napisu i/lub kilku wariantów obrazu
mogą otrzymać status `ok`. Sam wysoki wynik pewności pojedynczego odczytu nie
wystarcza: przycięty numer `189` może wyglądać jak poprawne `18`. Nawet słabszy
wiarygodny dłuższy odczyt blokuje taki skrócony wynik. Program zachowuje
warianty tekstu do sprawdzenia. Pojedyncza cyfra w kółku wymaga
niezależnego wykrycia całego napisu, aby nie odczytać samej końcówki numeru.

Niepełne lub zamazane kółko może uniemożliwić ustalenie wysięgnika. Wykryty
słabszy zarys kółka blokuje przypisanie zwykłego napisu do pola pod jego środkiem.
Podobnie traktowany jest długi, cienki odcinek wychodzący z napisu lub kończący
się tuż obok niego: także numer bez kółka może mieć wysięgnik. Krótkie przerwy
w kolorowej linii są uwzględniane, ale niepewna kotwica nie jest zgadywana.
Ręcznie wpisany A1 pozostaje nadrzędny wobec późniejszej odpowiedzi OCR.

## Pewność numeru i przypisania

Odczyt tekstu i przypisanie do pola są oceniane osobno. Wynik przypisania zawiera
`textStatus`, `assignmentStatus`, `reason` i listę `alternatives`. Niepewny numer
z jednoznacznym zakończeniem wysięgnika może zostać pokazany jako propozycja
do jawnego sprawdzenia. Nieznany wysięgnik lub niejednoznaczna granica pola nie
otrzymują takiego pewnego przypisania.

Słaby odczyt nie usuwa niezależnie potwierdzonego numeru tego samego pola.
Dwa różne potwierdzone numery nadal tworzą konflikt i wymagają decyzji
użytkownika. Osobny, wiarygodny drugi napis z jednoznaczną kotwicą również
kieruje obrys do sprawdzenia, nawet jeśli jego OCR jest słabszy. Może to
oznaczać pominiętą granicę między dwoma polami. Najlepszy numer pozostaje
propozycją. Niepewne propozycje nie są domyślnie zatwierdzane do zbiorczego zapisu
mapy.

Dobrze rozpoznane kolorowe kółko z nieczytelnym numerem pozostaje znacznikiem
do sprawdzenia (`unread_callout`), bez zgadywania cyfr. Osobny taki znak z pewną
kotwicą w tym samym obrysie także blokuje jego domyślne zatwierdzenie. Nieznana
kotwica oraz nieczytelna drukowana pętla nie blokują poprawnego odczytu A1.

## Przetwarzanie i formaty

Analizowany jest przygotowany podgląd PNG, więc ta sama ścieżka działa dla JPG,
PNG, TIFF/GeoTIFF, WebP i zaimportowanego pojedynczego arkusza PDF. Przezroczystość
jest składana na białym tle tak samo jak podczas analizy konturów.

OCR działa w tle, niezależnie od obliczania geometrii. Duży arkusz jest dzielony
na nakładające się fragmenty, aby małe numery nie znikały przy pomniejszeniu
całej mapy. Wynik jest przechowywany w ograniczonej pamięci podręcznej dla danego
rastra. Kolejne kliknięcia korzystają z tego wyniku; nie uruchamiają ponownie
rozpoznawania całego arkusza. Pierwsze rozpoznanie dużej mapy może trwać kilka
lub kilkanaście sekund, zależnie od komputera i treści skanu.

Odczyt pozostaje propozycją do weryfikacji. Słaba rozdzielczość, skreślenia,
cyfry złączone z kółkiem lub granicą, pionowy zapis i trudne pismo mogą wymagać
ręcznego A1. Poprawność modelu dla pojedynczych cyfr nie jest miarą poprawności
rozpoznania numerów i wysięgników na mapie.

## Prywatność i pakowanie

`raster_a1.py` sprawdza obecność i SHA-256 obu lokalnych plików modelu przed
utworzeniem silnika. Brak lub uszkodzenie modelu zgłasza błąd; kod nie pobiera
zamiennika. `ORT_DISABLE_TELEMETRY=1` jest ustawiane **przed importem** ONNX
Runtime; następnie wywoływane jest `disable_telemetry_events()` przed utworzeniem
sesji. Tryb CPU jest ustawiony jawnie. Testy sprawdzają tę kolejność, lokalne
ścieżki i wykonanie prawdziwego OCR przy zablokowanym połączeniu sieciowym.

Kontrola instalatora `--selftest` generuje własny obraz numeru `21` w kółku
z wysięgnikiem i wymaga poprawnego odczytu przez spakowane modele. Żaden skan
użytkownika nie jest częścią testów ani dystrybucji.

| Plik modelu | SHA-256 |
| --- | --- |
| `PP-OCRv6_det_small.onnx` | `090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f` |
| `PP-OCRv6_rec_small.onnx` | `6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884` |

## Licencje komponentów

RapidOCR oraz wymienione modele PP-OCRv6 są udostępniane na licencji Apache 2.0.
Noty i tekst licencji są pakowane w `geostudio.web_app/third_party/rapidocr`.
Dotyczy to wyłącznie tych zewnętrznych komponentów; nie zmienia warunków praw
do aplikacji GeoStudio ani do map użytkownika. Modele pozostają niezmodyfikowane
i nie są trenowane na skanach użytkownika.

Źródła:

- [RapidOCR: użycie i lokalne modele](https://rapidai.github.io/RapidOCRDocs/main/en/install_usage/rapidocr/usage/)
- [RapidOCR: pochodzenie i licencje modeli](https://github.com/RapidAI/RapidOCR/blob/main/python/MODEL_LICENSES.md)
- [ONNX Runtime: wyłączanie telemetrii](https://github.com/microsoft/onnxruntime/blob/main/docs/Privacy.md)
- [ONNX Runtime: API Pythona](https://onnxruntime.ai/docs/api/python/api_summary.html)
