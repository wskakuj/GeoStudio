# Opcjonalny tryb offline — 72 godziny lub bezterminowo

Domyślnie wyłączony. Zwykłe konto nadal wymaga internetu. Nigdy nie
odmrażamy dostępu po wyraźnej odmowie Firebase (np. active=false, usunięte
konto, zły token). Licencja podpisana przez zaufaną usługę może być
użyta tylko po błędzie sieci, po wcześniejszym prawidłowym logowaniu.
Przy starcie offline potrzebne jest także "Zapamiętaj mnie".

## Uruchomienie podpisującej usługi

Firebase Cloud Functions do wdrożenia wymaga planu Blaze. Dla projektu
Spark można użyć bezpłatnego Cloudflare Workers (w ramach jego limitów).
Nie potrzebujemy konta usługi Firebase ani domeny. Nie zmieniaj planu Firebase.

1. Na zaufanym komputerze administratora z zainstalowanym cryptography
   uruchom narzędzie tools/admin/generate_offline_keys.py, podając nowy
   plik JWK w prywatnym katalogu POZA repo. Zapisz publiczny klucz
   GEOSTUDIO_OFFLINE_PUBLIC_KEY. Plik JWK zawiera prywatny klucz.
2. Utwórz Worker na Cloudflare, użyj firebase/worker/offline-license.mjs.
   W ustawieniach zmiennych ustaw PROJECT_ID na prawidłowy Firebase Project ID.
   Dodaj SECRET o nazwie SIGNING_KEY_JWK, wklejając zawartość prywatnego
   JWK bezpośrednio w Cloudflare. Nie wysyłaj klucza do GitHub ani czatu.
   Wdróż Worker i skopiuj jego adres HTTPS (workers.dev).
3. Na GitHub dodaj repository secrets GEOSTUDIO_OFFLINE_URL (adres
   Workera HTTPS) oraz GEOSTUDIO_OFFLINE_PUBLIC_KEY (tylko publiczny klucz
   z punktu 1). Ręcznie zbuduj EXE na gałęzi logowania. Jeśli żadnego
   z tych dwóch wpisów nie ma, aplikacja działa nadal w trybie online.
4. Opublikuj aktualne reguły Firestore. W panelu admina wybierz dla konta
   niezależnie limit komputerów i tryb offline. Najpierw testuj na koncie
   testowym. Włącz internet i zaloguj się z zaznaczoną opcją zapamiętania.
   Menu konta powinno pokazać termin licencji offline lub „bezterminowo”. Wyłącz internet,
   uruchom ponownie i sprawdź. Po ponownym połączeniu aplikacja wraca do
   online i weryfikuje aktywność. Nie używaj testowego EXE jako release.

## Bezpieczeństwo i ograniczenia

Worker przekazuje Firebase ID token użytkownika do Firestore (nie hasło
ani refresh token). Firestore weryfikuje podpis ID tokenu i uprawnienie do
własnego aktywnego dokumentu. Worker sprawdza politykę offline, limit,
rejestrację komputera (jeśli limit jest dodatni) i termin ważności. Podpisuje
licencję ECDSA P-256 powiązaną z konkretnym urządzeniem także bez limitu.
Tryb 72 h wygasa po maksymalnie 72 h. Tryb bezterminowy wygasa tylko z datą
ważności konta, jeśli ją ustawiono. EXE ma
wyłącznie publiczny klucz weryfikujący. Nie przesyłamy map.

Zaszyfrowana DPAPI licencja jest wiązana z projektem i identyfikatorem
instalacji systemu. Program kontroluje czas monotoniczny podczas sesji
oraz ostatni zaobserwowany czas ścienny, a online próbuje sprawdzać
dostęp również w trybie offline. Usunięcie sesji usuwa lokalną licencję.
Wyłączenie konta lub offline jest skuteczne po kontakcie z Firebase;
bez internetu istniejąca licencja może działać do końca terminu, a przy
bezterminowej licencji bez ważności konta — bez ograniczenia czasu.
Takie uprawnienie nadaj tylko zaufanym użytkownikom.
Nie można zagwarantować natychmiastowej blokady offline ani odporności
na modyfikację programu, klonowanie systemu lub przywrócenie migawki
dysku przez właściciela komputera.

Worker i konfigurację należy zweryfikować na żywo przed włączeniem
tej funkcji dla użytkowników. Zachowaj kopię klucza prywatnego w
bezpiecznym miejscu. Rotacja klucza wymaga ponownego zbudowania EXE.

## Aktualizacja istniejącej instalacji

Wdróż aktualne pliki firebase/worker/offline-license.mjs w geostudio-license
i firebase/worker/admin.mjs w geostudio-admin, zachowując istniejące zmienne
i sekrety. Zbuduj nowe EXE. Nie ma potrzeby regenerowania kluczy, zmiany
adresów Workerów, sekretów GitHub ani reguł Firestore.
Pole offlineHours: 0 = wyłączona, 72 = 72 godziny, -1 = bezterminowo.
Pole deviceLimit: 0 = bez limitu, 1–20 = limit komputerów.
Dotychczasowe licencje 72 h z limitem urządzeń zachowują format v1 i ważność.
Nowe kombinacje używają formatu v2. Stare EXE nie rozpoznają v2, dlatego
przed włączeniem nowych ustawień użytkownik musi mieć nową wersję.
