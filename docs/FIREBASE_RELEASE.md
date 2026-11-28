# Pierwsze wydanie GeoStudio z logowaniem: 2.0.109

## Publikacja po scaleniu PR z przygotowaniem wydania

1. Upewnij się, że testy main zakończyły się powodzeniem, działają oba
   Cloudflare Workery, konto administratora i rejestracja z zaproszeniem.
2. Actions → Build GeoStudio Windows release from main → Run workflow.
   Wybierz gałąź main, source_ref=main, release_tag=v2.0.109.
   Domyślne publish=false tworzy wyłącznie kandydat instalatora do pobrania.
   Po sprawdzeniu można uruchomić ponownie z publish=true. Nie usuwaj
   istniejących tagów i nie nadpisuj już opublikowanych wydań.
3. Build wymaga pięciu dotychczasowych Actions secrets:
   GEOSTUDIO_FIREBASE_PROJECT_ID, GEOSTUDIO_FIREBASE_WEB_API_KEY,
   GEOSTUDIO_OFFLINE_URL, GEOSTUDIO_OFFLINE_PUBLIC_KEY, GEOSTUDIO_ADMIN_URL.
   W EXE znajduje się tylko konfiguracja klienta i publiczny klucz
   offline. Sekrety konta serwisowego i prywatny klucz podpisujący
   pozostają w Cloudflare.
4. Osobny runner Windows bez sekretów testuje aktualizację prawdziwej 108
   do nowego wydania w tej samej lokalizacji instalacji, weryfikuje
   wersję, zachowanie dodatkowego pliku i spakowane moduły.
   To test instalatora i konfiguracji, nie logowanie do produkcji.
5. Przy publish=true, dopiero po udanym teście, workflow tworzy draft
   Release, dołącza gotowy instalator i SHA256SUMS.txt, a potem publikuje
   go jako najnowsze wydanie stabilne. Nie zmieniaj nazw plików.
6. W zainstalowanym GeoStudio 2.0.108 zapisz wszystkie mapy, kliknij
   numer wersji i sprawdź aktualizację. Program pobierze
   GeoStudio2-Setup-2.0.109-x64.exe z v2.0.109 i uruchomi instalator.
   Po ponownym uruchomieniu obowiązuje logowanie (lub zapamiętana sesja).
   Rejestracja wymaga ważnego zaproszenia i potwierdzenia e-maila.
   Jeśli instalacja była portable, użyj instalatora ręcznie i zachowaj
   oddzielny katalog z mapami. Nie usuwaj kopii zapasowych.

## Granice tego wydania

Updater 108 nie obsługuje weryfikacji podpisu ani SHA-256. Plik
SHA256SUMS.txt pozwala na ręczne sprawdzenie; nie jest podpisem cyfrowym.
Updater chronionego klienta pozostaje wyłączony, dopóki nie przygotujemy
weryfikowanego kanału aktualizacji 109 → następne wersje. Nie należy
udostępniać starszych niezabezpieczonych wersji jako nowych wydań.
Stare kopie EXE nie zostają zdalnie zablokowane przez publikację 109.
