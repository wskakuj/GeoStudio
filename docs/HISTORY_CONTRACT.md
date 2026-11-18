# Kontrakt Undo/Redo

Dokument opisuje silnik historii w `geostudio/history.py`: co dokładnie jest
zapisywane, kiedy wpis powstaje, jak przebiega cofanie i ponawianie, oraz jak
historia współpracuje z kopiami roboczymi i sidecarami. Etap 1 obejmuje sam
silnik i testy jednostkowe; podłączenie do interfejsu to osobne zadanie.

## Jednostka historii

Jeden wpis to **jedna akcja użytkownika**, zastosowana atomowo w trzech
magazynach:

1. `GeoMap.lines` — surowe bajty rekordów pliku MAP,
2. `visual_styles` — wypełnienia i krycie obiektów,
3. `label_positions` — ręcznie ustawione pozycje etykiet.

Akcja, która nie zmienia żadnego z nich, nie tworzy wpisu.

## Łatki

```python
@dataclass(frozen=True)
class Hunk:
    start: int                  # indeks w doc.lines
    removed: tuple[bytes, ...]
    added: tuple[bytes, ...]

@dataclass(frozen=True)
class StylesPatch:
    visual_before / visual_after: dict[str, dict | None]
    labels_before / labels_after: dict[str, dict | None]
```

`None` oznacza „klucza nie było". Wartości w łatce to **niezależne kopie**
(`copy.deepcopy`), więc nic nie jest współdzielone z żywymi słownikami ani
między wpisami.

### Bajty bez zmian

Łatki trzymają dokładnie te `bytes`, które były w `lines`. Nic nie jest
dekodowane, kodowane ponownie, przycinane ani normalizowane. Tekst CP1250,
końce linii CRLF lub LF, brak końcowego znaku nowej linii i nieznane rekordy
GEO-MAP (`:ZZZ[...]`, `L ...`) wracają identyczne. Ponowne `_parse()` po
cofnięciu odtwarza model obiektów z tych samych bajtów.

### Dzielenie na wiele fragmentów

Naiwna różnica „wspólny prefiks i sufiks" obejmowałaby **wszystko** między
dwiema odległymi zmianami. Przykład zmierzony na mapie 112 000 wierszy, gdy
zmieniono wiersz 10 i wiersz 111 990:

| Podejście | Fragmenty | Rozmiar łatki |
|---|---|---|
| sam prefiks/sufiks | 1 | 6 498 570 B |
| kotwice blokowe | 2 | 96 B |

Dlatego region po przycięciu prefiksu i sufiksu jest porównywany w blokach po
64 wiersze, a różniące się bloki są docinane wiersz po wierszu. Duża, ciągła
zmiana (np. usunięcie 10 000 wierszy) słusznie pozostaje jednym fragmentem
272 000 B. Czas liczenia różnicy dla mapy 112 000 wierszy to kilkadziesiąt
milisekund.

## Transakcja

```python
with history.begin('Zmiana A2 obiektu 12/3') as tx:
    doc.update_field(uid, 'A2', 'nowa nazwa')
    tx.set_selection_after([uid])
```

Wejście zapisuje stan: kopię listy `lines` (kopiowane są wskaźniki do
niezmiennych `bytes`) oraz głębokie kopie obu słowników sidecara. Wyjście:

- sukces → różnica linii i stylów tworzy jeden wpis,
- brak różnic → brak wpisu,
- wyjątek albo nieudane `reparse()` → **przywrócenie stanu wejściowego**
  (linie i oba słowniki), ponowne parsowanie, brak wpisu; wyjątek leci dalej.

Dzięki temu nieudana operacja nie zostawia dokumentu w połowie zmienionego.

## Cofanie i ponawianie

Przed zastosowaniem wpisu silnik sprawdza, czy dokument jest w stanie, którego
wpis oczekuje:

- linie: `lines[start : start+len(...)]` muszą być równe oczekiwanemu
  fragmentowi (dla undo — fragment „po", dla redo — „przed"),
- sidecar: bieżąca wartość dla każdego `uid` z łatki musi być równa wartości
  oczekiwanej.

Niezgodność → `HistoryConflict`, **nic nie jest zmieniane**, historia zostaje
nietknięta. To zabezpieczenie przed cichym zniszczeniem pliku, gdy coś zmieniło
dane poza historią.

Zastosowanie jest atomowe: fragmenty linii są podmieniane od końca, potem
sidecar, potem `reparse()`. Jeśli którykolwiek krok zawiedzie (łącznie z
parsowaniem), silnik przywraca stan sprzed operacji i parsuje ponownie —
użytkownik nigdy nie zostaje z na wpół zastosowaną łatką.

## Stan dokumentu: zmieniony czy zapisany

`is_dirty` **nie** porównuje licznika pozycji. Każdy wpis ma unikalny
`state_id`, a bieżący stan to identyfikator ostatnio zastosowanego wpisu (albo
`ROOT_STATE`). Zapis ustawia `saved_state_id = current_state_id`.

To rozróżnia gałęzie: cofnięcie i nowa edycja dają inną gałąź o tym samym
liczbie kroków, więc dokument pozostaje „zmieniony", mimo że licznik by się
zgadzał.

`mark_saved()` wolno wywołać **dopiero po pełnym sukcesie zapisu** — MAP i
wymagany sidecar. Zapis częściowy (MAP tak, sidecar nie) nie jest zapisem i
nie przesuwa punktu zapisu.

## Kopie robocze

`_autosave_work_copy()` pozostaje bez zmian i jest wołany po każdej udanej
transakcji, także po cofnięciu i ponowieniu. Zasady:

1. Silnik historii **nie dotyka plików**. Nie zna ścieżek, nie zapisuje.
2. Oryginalny `.MAP` użytkownika nie jest zapisywany nigdy — ani przez edycję,
   ani przez cofanie.
3. Kopia robocza `*_GeoStudio_robocza[_N].MAP` powstaje wyłącznie przez
   `open('xb')`, a jej nadpisanie jest dozwolone tylko wtedy, gdy suma
   kontrolna zgadza się z tym, co aplikacja zapisała.
4. Sidecar kopii roboczej jest zapisywany przez `_persist_work_copy_styles()`
   z tym samym mechanizmem digestów.
5. **Nieudany autosave nie blokuje cofnięcia.** Cofnięcie działa w pamięci,
   a użytkownik dostaje wyraźne ostrzeżenie, że kopia robocza nie została
   zaktualizowana. Blokowanie undo z powodu problemu z plikiem odbierałoby
   możliwość naprawienia błędu.
6. Zapis częściowy (MAP zapisany, sidecar nie) jest raportowany jako
   niepełny — nigdy jako sukces.

## Limity

Stos jest ograniczony liczbą wpisów (domyślnie 200) i budżetem ładunku
(domyślnie 32 MB). Przekroczenie usuwa najstarsze wpisy. Przesunięcie
wierzchołka to dwie linie po kilkadziesiąt bajtów, więc w normalnej pracy
limit pamięci nigdy nie zadziała.

## Coalescencja (etap podłączenia)

| Gest | Wpisy |
|---|---|
| przeciąganie etykiety | jeden wpis po puszczeniu myszy |
| przeciąganie wierzchołka | jeden wpis po zatwierdzeniu |
| edycja pola w panelu | jeden wpis na zatwierdzoną wartość |
| usunięcie wielu obiektów | jeden wpis |
| rysowanie poligonu | jeden wpis po zamknięciu; punkty szkicu poza historią |

## Usuwanie obiektów

`delete_selected()` już dziś usuwa wpisy `visual_styles` i `label_positions`
usuwanych obiektów, więc nie trzeba tu żadnej zmiany funkcjonalnej: cofnięcie
przywraca geometrię, atrybuty, kolor i pozycje etykiet w jednym wpisie,
ponieważ wszystkie trzy magazyny są w jednej transakcji.

## Czego historia nie obejmuje

Otwierania i zamykania mapy, ładowania bibliotek, zoomu i obrotu widoku,
widoczności warstw, zaznaczania (jest przywracane jako skutek uboczny wpisu,
ale samo nie jest cofalne), eksportu i transformacji zapisujących nowe pliki.

Otwarcie innej mapy czyści historię — wpisy odnoszą się do linii innego pliku.
Przy niezapisanych zmianach interfejs zapyta, czy zapisać.

## Interfejs (etap 3)

`Ctrl+Z` cofa, `Ctrl+Y` i `Ctrl+Shift+Z` ponawiają. Menu **Edycja** pokazuje
„Cofnij: <opis>" i „Ponów: <opis>" i jest wyszarzone przy pustym stosie.
Podczas rysowania poligonu `Ctrl+Z` najpierw usuwa ostatni punkt szkicu.

## Etapy

1. **Silnik** — `history.py`, ten dokument, testy jednostkowe. Bez zmian w GUI.
2. Podłączenie operacji edycyjnych, sidecarów, `is_dirty` i autosave.
3. Interfejs: menu, skróty, pasek, pierwszeństwo szkicu poligonu.
4. Utwardzenie zapisu: atomowy zapis, ponowny odczyt i weryfikacja `CHK`.
