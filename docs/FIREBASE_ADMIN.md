# GeoStudio — panel administratora i komputery

Panel administratora jest niezależnym lokalnym programem Python/Tk,
nie jest częścią GeoStudio2.exe i nie korzysta z uprawnień użytkownika map.
Nie udostępnia lokalnego HTTP ani nie przechowuje haseł użytkowników.

## Uruchomienie na komputerze administratora

1. W Firebase Console / Firestore / Rules opublikuj zaktualizowany plik
   firebase/firestore.rules z gałęzi ai2/feat-firebase-auth.
   Istniejące dokumenty bez deviceLimit nadal działają bez limitu.
2. Pobierz tę gałąź do osobnego katalogu (nie do istniejącej instalacji).
3. Zainstaluj zależności w oddzielnym środowisku:

       py -3.12 -m venv .venv-admin
       .\.venv-admin\Scripts\python.exe -m pip install -r tools/admin/requirements.txt

4. Skonfiguruj Google Application Default Credentials (ADC) na zaufanym
   komputerze administratora. Preferowany jest OAuth użytkownika z
   odpowiednimi rolami IAM (Firebase Authentication Admin i Cloud Datastore
   User). Dla lokalnego Firebase Admin SDK użyj własnego OAuth Desktop
   client ID i gcloud auth application-default login --client-id-file=...
   zgodnie z https://firebase.google.com/docs/admin/setup.
   Alternatywnie możesz wskazać przez GOOGLE_APPLICATION_CREDENTIALS lokalny
   plik klucza dedykowanego konta usługi o minimalnych potrzebnych rolach.
   Nie wysyłaj tego pliku na GitHub, do czatu ani do aplikacji użytkownika.
5. Uruchom:

       .\.venv-admin\Scripts\python.exe tools/admin/geostudio_admin.py --project TWOJ_PROJECT_ID

Panel łączy listę użytkowników Authentication z dokumentami Firestore po UID.
Możesz wyszukiwać konta, tworzyć nowe konta, ustawiać aktywność, datę ważności
(ISO ze strefą), opisy, limit oraz usuwać poszczególne rejestracje komputerów.
Nowy użytkownik ma wygenerowane losowe hasło i limit 2; wygeneruj jednorazowy
link ustawienia hasła i przekaż wyłącznie właścicielowi. Panel nie wysyła
automatycznie wiadomości e-mail; link jest poufny.

## Rejestracje komputerów

deviceLimit = 0 lub brak pola oznacza brak limitu. Dodatnia liczba 1–20
oznacza maksymalną liczbę zarejestrowanych komputerów. devices to lista
64-znakowych skrótów SHA-256. Administrator może zmieniać politykę i usuwać
rejestracje, klient może wyłącznie dopisać jeden nowy identyfikator do
własnego aktywnego dokumentu, jeśli jest wolny slot. REST używa warunku
updateTime; przy równoczesnych logowaniach ponownie odczytuje dokument.

Identyfikator to skrót identyfikatora instalacji systemu i ID projektu,
nie surowy numer sprzętowy. Na Windows źródłem jest MachineGuid. Zmiana
instalacji systemu może wymagać zwolnienia slotu. Usunięty identyfikator
może ponownie zająć wolny slot; to nie trwała blokada konkretnego sprzętu.
Wyłączenie active blokuje całe konto. Limit chroni liczbę rejestracji,
ale nie jest atestacją sprzętu, nie zapobiega klonowaniu identyfikatora
i można go ominąć zmodyfikowanym klientem/starszą wersją. Nie jest DRM.

Reguły wymagają sprawdzenia w emulatorze lub Rules Playground i testu
na oddzielnym koncie, zanim włączysz limit dla kont produkcyjnych.

## Opcjonalny tryb offline

Panel pozwala wybrać pracę offline: wyłączona (domyślnie), 72 godziny lub
bezterminowo, niezależnie od limitu komputerów. Wymaga aktualnej usługi
podpisującej i klienta. Bezterminowy offline jest ograniczony tylko ważnością
konta; jeśli komputer nie wraca do internetu, zdalna blokada jest niemożliwa.
Przeczytaj [FIREBASE_OFFLINE.md](FIREBASE_OFFLINE.md) przed jej użyciem.
Identyfikator wyświetlany w menu konta GeoStudio to pierwsze 12 znaków
skrótu, dzięki czemu można dopasować go do pełnego ID w panelu.
