# GEO-MAP v8 — ustalenia z przesłanych plików (bez reprodukowania danych)

Zbadano dwa pliki tekstowe `ver=[8.00]` zapisane programem GMW 10.50:

- Pierwsza linia: `N=[liczba linii]`, `CHK=[32-znakowe MD5]`.
- `CHK` jest MD5 z **dokładnie wszystkich bajtów za pierwszą linią**
  (łącznie z CRLF i końcową linią). Potwierdzono w obydwu próbkach.
- Obiekty zaczynają się linią `*NNNN ...` (4 cyfry kodu).
- Kolejne wiersze `:ID[...]`, `:A1[...]`…`:A6[...]`, `:TX[...]`,
  `:MP[...]`, `:FA[...]`, `:KR[...]` to metadane.
- Współrzędne wierzchołków: `P 1 X Y` (niekiedy `,identyfikator punktu`).
- Wiersze `L ...` i inne zachowujemy, ale ich znaczenie nie zostało jeszcze
  zrekonstruowane; mogą wpływać na pozycję opisów, orientację i styl.
- Łańcuchy wyglądają na Windows-1250, ale część danych zawiera nietypowe bajty;
  weryfikacja kodowania i bezstratne zachowanie surowych rekordów jest istotna.

**Weryfikacja**: obie mapy przechodzą kontrolę deklarowanej liczby linii i
MD5; podgląd struktury oraz no-op eksport zachowują dokładnie te same bajty.

Pierwsza próbka: 112 062 wiersze, 7 225 obiektów, 34 022 punkty,
3 394 zamknięte poligony. Druga: 41 516 wierszy, 2 086 obiektów,
16 725 punktów, 2 079 zamkniętych poligonów.

## Uwagi

Przy rysowaniu sceny nie zakładamy z góry EPSG. Dokładne pomiary dla mapy
w określonym odwzorowaniu mogą wymagać korekt odwzorowawczych i uwzględnienia
zasad stosowanych w GEO-MAP. Pola `#POLE` mogą różnić się od wyniku wzoru
shoelace z wierzchołków (np. przez zaokrąglenia i rodzaj powierzchni).

Nie należy nigdy publikować map klientów, współrzędnych szczegółowych,
autorskich bibliotek symboli lub danych identyfikujących osoby bez uprawnień.
