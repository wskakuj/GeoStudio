# Obracanie oznaczeń na mapie

W zakładce **Wstawianie → Oznaczenie na mapie** można obracać wszystkie dziewięć oznaczeń: płazowinę iglastą, płazowinę liściastą, zrąb, bagno, linię energetyczną, gazociąg, granice lasów, ścieżki i współwłasność z ALP.

## Obrót myszą

1. Wstaw oznaczenie. Naciśnij **Esc**, aby zakończyć wielokrotne wstawianie.
2. Kliknij oznaczenie w trybie zaznaczania albo w zakładce **Wstawianie**.
3. Przeciągnij okrągły uchwyt nad znakiem. W czasie przeciągania widać pełny obrócony znak oraz jego ramkę.
4. Puść przycisk myszy, aby zapisać zmianę. **Ctrl+Z** cofa cały obrót.

Przytrzymanie **Shift** ustawia kąt co 15°. Można także przytrzymać prawy przycisk na znaku i obrócić go ruchem myszy. **Esc** podczas przeciągania odrzuca obrót. Anulowanie gestu lub utrata przechwycenia myszy również zachowuje poprzednie ustawienie.

## Kąt i skróty klawiaturowe

Po zaznaczeniu oznaczenia sekcja **Wybrany element** pokazuje suwak **Obrót** i pole kąta w stopniach. Dodatni kąt obraca znak zgodnie z ruchem wskazówek zegara. Przycisk **0°** przywraca pierwotny kierunek.

Klawisze **[** i **]** obracają zaznaczony znak co 5°, a z klawiszem **Shift** — co 15°. Skróty nie działają podczas wpisywania tekstu, w polach formularza ani podczas otwartego okna atrybutów A1.

Ramka zaznaczenia obraca się razem ze znakiem. Znak można nadal przesunąć albo proporcjonalnie powiększyć przez przeciągnięcie kwadratowego uchwytu w narożniku. Powiększanie zachowuje przeciwległy narożnik.

## Zapis

Obrót zmienia rzeczywiste współrzędne elementów oznaczenia w kopii roboczej MAP. Po zapisaniu mapy położenie jest zachowane także w natywnych danych, wydruku i eksporcie. Towarzyszący plik stylów GeoStudio zachowuje grupowanie i kontrolki oznaczeń przy ponownym otwarciu projektu.

W wersji 2.0.105 poprawiono również zapis zmiany samego kąta. W starszej wersji taka zmiana mogła pozostawić nieobróconą geometrię, mimo zmiany ustawienia. Znane oznaczenia ze starszych zapisów są rozpoznawane na podstawie ich rzeczywistych punktów; odczyt nie przesuwa istniejącej geometrii ani nie zastępuje ręcznie zmienionych obiektów.
