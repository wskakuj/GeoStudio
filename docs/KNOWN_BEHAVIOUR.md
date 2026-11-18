# Zaobserwowane zachowania interfejsu

Ten plik zbiera zachowania, które wyglądają na niezamierzone albo zaskakujące,
ale **są obecne w kodzie i nie zostały zmienione**. Spisujemy je, żeby:

- refaktoryzacja nie „naprawiła" ich przypadkiem, bo wtedy nie da się odróżnić
  skutków przeniesienia kodu od skutków zmiany zachowania,
- decyzja o ewentualnej poprawce była świadoma, a nie skutkiem ubocznym,
- testy pilnujące obecnego zachowania miały uzasadnienie w dokumentacji.

Wpis w tym pliku **nie oznacza zgody na zmianę**. Każda poprawka wymaga osobnej
decyzji właściciela projektu i osobnego Pull Requesta, poza refaktoryzacją.

## Ctrl+kliknięcie w to samo miejsce cykluje zamiast przełączać

**Gdzie:** `GeoStudioWindow.select_at` (`geostudio/app.py`), wykorzystywane przez
`Ctrl+klik` na kanwie.

**Co się dzieje:** pierwsze `Ctrl+kliknięcie` na obiekt dodaje go do zaznaczenia,
a kolejne `Ctrl+kliknięcie` **w to samo miejsce** nie usuwa go, tylko przechodzi
na następny obiekt leżący pod kursorem — tak jak zwykłe kliknięcie w miejscu
nakładających się obiektów. Dopiero kliknięcie w innym miejscu na ten sam obiekt
usuwa go z zaznaczenia.

**Przykład z testu** (`tests/test_selection.py`,
`test_ctrl_click_on_the_same_spot_cycles_to_the_next_object`): mapa z poligonem
użytku `5230` i leżącą na nim działką `5216`.

1. klik w środek → zaznaczona działka `PARCEL`,
2. `Ctrl+klik` w narożnik → dochodzi `NEIGHBOUR`,
3. `Ctrl+klik` w ten sam narożnik → zamiast usunąć `NEIGHBOUR`, dochodzi `LANDUSE`.

**Przyczyna:** wykrywanie „powtórzonego kliknięcia" (ten sam punkt w promieniu
12 px i ta sama lista kandydatów) działa niezależnie od trybu dodawania.
W `select_at` warunek `repeat` jest równoważny `cycle`, a `resolve_click`
przesuwa wybór na kolejnego kandydata, zanim tryb `additive` zdecyduje o
dodaniu lub usunięciu.

**Stan:** zachowanie utrwalone testem, **niezmienione**. Poprawka wymaga decyzji,
czy `Ctrl+klik` w to samo miejsce ma zawsze przełączać ten sam obiekt — co jest
zgodne z intuicją z QGIS-a — czy zachować możliwość cyklowania przy wciśniętym
Ctrl.
