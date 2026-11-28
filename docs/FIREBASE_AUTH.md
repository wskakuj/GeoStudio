# GeoStudio 2.0 — logowanie Firebase

> Poniżej historyczna instrukcja konfiguracji gałęzi rozwojowej. Logowanie, zaproszenia i administracja są już w main. Aktualny proces wydawania: [FIREBASE_RELEASE.md](FIREBASE_RELEASE.md).

## Stan i zakres

Wydanie Windows ma wymagać potwierdzenia konta online przed uruchomieniem
edytora. Nie ma rejestracji w programie. Firebase Authentication obsługuje
e-mail/hasło, a Firestore zawiera niezależną listę uprawnionych UID.
Żadne pliki MAP, rastry, współrzędne ani biblioteki nie trafiają do Firebase.
Wszystkie operacje GIS pozostają lokalne.

Publikację chronionego instalatora opisuje osobna instrukcja wydania.

## Konfiguracja Firebase Console

1. Utwórz oddzielny projekt Firebase na planie Spark. Włącz Authentication /
   Sign-in method / Email/Password (nie logowanie linkiem).
2. Utwórz Cloud Firestore w trybie produkcyjnym. Rozważ region UE. Nie używaj
   reguł trybu testowego; opublikuj reguły z `firebase/firestore.rules`.
   Są przeznaczone dla oddzielnego projektu GeoStudio, nie zastępuj nimi reguł
   projektu używanego do innych celów.
3. W Authentication / Users utwórz konto i skopiuj jego UID. W Firestore
   utwórz kolekcję `geostudio_access`, dokument o identyfikatorze dokładnie
   równym UID, z polami:
   - `active` — boolean, true;
   - `expiresAt` — null (bezterminowo) lub Timestamp z właściwą datą i godziną.
   Brak dokumentu, active=false, brak wymaganego pola lub upływ daty odmawia
   dostępu. Reguły weryfikują czas po stronie Firebase. Użytkownik nie może
   zmienić własnego uprawnienia, odczytać cudzego ani listować kolekcji.
4. W Project settings / General zarejestruj aplikację webową i odczytaj
   Project ID oraz Web API Key (konfiguracja publicznego klienta). NIE używaj
   klucza prywatnego konta serwisowego, Firebase Admin SDK ani tokenu GitHub.
   Ustaw odpowiednie ograniczenia API i monitoruj limity w konsoli.
5. Przy testowaniu źródeł ustaw w PowerShell:
   `$env:GEOSTUDIO_FIREBASE_PROJECT_ID = "twoj-project-id"` oraz
   `$env:GEOSTUDIO_FIREBASE_WEB_API_KEY = "twoj-web-api-key"`.
   Uruchom `python -m geostudio.web_app` (lub istniejący start_web_ui.bat).
   W spakowanym EXE wartości pochodzą z modułu firebase_settings.py
   wygenerowanego na czas budowania. Po ustawieniu tych dwóch zmiennych
   uruchom w PowerShell:

   ```powershell
   ./tools/windows/build.ps1 -SkipInstaller -RequireFirebaseConfig
   ```

   Skrypt sprawdza konfigurację, umieszcza ją w EXE i automatycznie
   przywraca pusty szablon źródłowy, również po błędzie. Nie przyjmuje
   konfiguracji ze zmiennych środowiska już zainstalowanego EXE.
   Testuj przenośne `dist/GeoStudio2/GeoStudio2.exe` w oddzielnym katalogu:
   instalator nadal używa identyfikatora istniejącego GeoStudio, więc
   mógłby nadpisać Twoją zwykłą instalację. Nie buduj publicznego wydania.
   Bez obu zmiennych zwykły build podglądowy pozostaje zablokowany;
   build z `-RequireFirebaseConfig` odmawia pakowania.
   Skrypt odrzuca budowanie z RELEASE_TAG na tej gałęzi.
6. Zablokuj konto zmieniając active na false (lub usuń dokument), ewentualnie
   wyłącz konto w Authentication. Nowe uruchomienie wymaga poprawnej sesji i
   aktualnego uprawnienia. Testuj także termin ważności i reset hasła.

## Zachowanie aplikacji

Logowanie odbywa się w małym oknie natywnym, przed utworzeniem serwera
edytora. Opcja zapamiętania przechowuje tylko zaszyfrowany token odświeżania
(DPAPI dla bieżącego użytkownika Windows) w lokalnym katalogu GeoStudio2.
Brak konfiguracji, złe hasło lub brak internetu przy starcie nie otwierają
edytora. Przy kolejnych uruchomieniach zapamiętany token zawsze przechodzi
online przez Firebase. Hasło nie jest przechowywane na dysku.

W trakcie pracy kontrola odnawia token i uprawnienie co około 15 minut.
Po odmowie lub braku możliwości potwierdzenia aktywnego dostępu edycja i
otwieranie nowych plików są zablokowane na poziomie lokalnego API oraz mostka
natywnego. Zachowujemy wąskie ścieżki odczytu i zapisu otwartych map, by nie
utracić pracy. Przejściowy błąd sieci jest ponawiany, wyraźna odmowa i
wylogowanie wymagają ponownego uruchomienia. Nie ma podpisanej licencji
offline ani limitu urządzeń.

Publiczny updater jest tymczasowo wyłączony w chronionej ścieżce startu:
w przeciwnym razie wersja testowa mogłaby zainstalować publiczne, nadal
niechronione wydanie. Przed scaleniem ustal sposób dystrybucji chronionych
wydań, minimalną wersję i weryfikację integralności. Nie publikowano żadnych
instalatorów ani nie zmieniano widoczności repozytorium.

## Ograniczenia i testy

To kontrola oficjalnej aplikacji GeoStudio 2.0, nie DRM. Publiczne źródła,
stare EXE, lokalna modyfikacja programu i starszy interfejs PySide6 pozostają
poza tą ochroną. Wydanie Windows 2.0 nie zawiera PySide6. Bez konfiguracji
projektu Firebase nie można zweryfikować produkcyjnych kont ani reguł.
Testy z atrapą transportu nie zastępują testów z realnym projektem i na
Windows, w tym działania DPAPI, wyglądu okna, zapisu wszystkich rodzajów MAP
oraz instalatora. Self-test pakowania nie ma dostępu do operacji API ani
danych użytkownika.

Dokumentacja:
- https://firebase.google.com/docs/reference/rest/auth
- https://firebase.google.com/docs/firestore/use-rest-api
- https://firebase.google.com/docs/firestore/security/rules-conditions
- https://firebase.google.com/pricing

## GitHub Actions — ręczny test Windows

W Settings / Secrets and variables / Actions dodaj dwa repository secrets:
GEOSTUDIO_FIREBASE_PROJECT_ID oraz GEOSTUDIO_FIREBASE_WEB_API_KEY.
To konfiguracja klienta, nie dane administratora. Nie dodawaj hasła
użytkownika, klucza konta serwisowego ani tokenu odświeżania.
W Actions wybierz "Windows GeoStudio2 preview installer", Run workflow,
gałąź ai2/feat-firebase-auth. Ręczne uruchomienie na tej gałęzi tworzy
wyłącznie przenośny artefakt z konfiguracją. Uruchomienia PR nie otrzymują
konfiguracji i są diagnostyczne. Artefakt publicznego repo może pobrać
zalogowany użytkownik GitHuba; Web API Key i Project ID są dostępne w EXE,
więc nie stanowią sekretu ani mechanizmu autoryzacji.
Nie publikujemy Release, nie nadpisujemy istniejącej instalacji.

## Rozszerzenia na gałęzi logowania

Nowsze commity dodają menu konta, limit komputerów i opcjonalne podpisane
licencje offline. Domyślna polityka istniejących kont nadal wymaga internetu
oraz nie ogranicza komputerów. Szczegóły konfiguracji:

- [Panel administratora i urządzenia](FIREBASE_ADMIN.md)
- [Opcjonalna licencja offline i podpisująca usługa](FIREBASE_OFFLINE.md)


## Diagnostyka przenośnego EXE Windows

Jeśli po zalogowaniu pojawia się `Failed to resolve Python.Runtime.Loader.Initialize`,
sprawdź, czy ZIP z zaufanego własnego GitHub Actions został oznaczony jako
pobrany z internetu. Właściwości ZIP → Odblokuj (jeśli opcja jest dostępna)
→ ponownie wypakuj cały ZIP do nowego folderu. Nie przenoś samego EXE
bez katalogu _internal i nie wyłączaj ochrony Windows. Program nie usuwa
oznaczeń bezpieczeństwa automatycznie. Jeśli błąd pozostaje, sprawdź
kompletność DLL i .NET Framework. Test pakowania ładuje teraz CLR oraz
System.Windows.Forms; nie symuluje oznaczeń pobranego archiwum ani nie
otwiera rzeczywistego okna.
