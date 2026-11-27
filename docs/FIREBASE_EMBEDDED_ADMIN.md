# Wbudowana administracja GeoStudio (preview)

Panel jest opcjonalny. Przy aktualizacji polityki offline zaktualizuj oba Workery
zgodnie z FIREBASE_OFFLINE.md, bez zmiany sekretów. Bez nowego adresu
ADMIN_URL w EXE logowanie i licencje offline nadal działają jak wcześniej.
Nie publikować release przed testami z dwoma kontami.

## Konfiguracja właściciela (na zaufanym komputerze)

1. Użyj tego samego lokalnego środowiska tools/admin z działającym ADC
   (Google Cloud CLI). Pobierz set_admin_claim.py z tej gałęzi, uruchom:
   python set_admin_claim.py --project TWOJ_PROJECT_ID
   Wpisz e-mail konta GeoStudio, sprawdź projekt i potwierdź GRANT.
   Skrypt zachowuje inne custom claims i zwraca ADMIN_UID. Zapisz UID.
2. W Google Cloud Console, IAM & Admin > Service Accounts, utwórz oddzielne
   konto usługi geostudio-admin-worker w projekcie Firebase. Nadaj role
   Firebase Authentication Admin (roles/firebaseauth.admin) i
   Cloud Datastore User (roles/datastore.user), nie Owner/Editor.
   To konto ma uprzywilejowany dostęp do projektu; stosuj w dedykowanym
   projekcie GeoStudio. Utwórz klucz JSON, tylko jeśli polityka organizacji
   dopuszcza klucze kont usługi. Jeśli blokuje, nie wyłączaj globalnych
   zabezpieczeń. Zachowaj awaryjny panel ADC i uzgodnij dozwoloną alternatywę.
   Klucz jest sekretem: nie wysyłaj go do chatu, repo, EXE, logów ani e-maila.
3. W Cloudflare utwórz osobny Worker geostudio-admin, bez Cloudflare Access
   (weryfikuje Firebase ID token). Wklej cały firebase/worker/admin.mjs i Deploy.
   Ustaw zmienne produkcyjne PROJECT_ID, ADMIN_UID i FIREBASE_WEB_API_KEY
   (ten sam publiczny klucz Web API Firebase). Dodaj SECRET o dokładnej
   nazwie GOOGLE_SERVICE_ACCOUNT_JSON zawierający cały JSON konta usługi.
   Wyłącz logowanie i ślady żądań w Observability. Nie loguj nagłówków ani ciał.
   Wdrażanie kodu nie wymaga prywatnego klucza offline.
4. W GitHub Actions > Repository secrets dodaj GEOSTUDIO_ADMIN_URL z
   adresem HTTPS nowego Workera (*.workers.dev). Pozostałe cztery sekrety
   Firebase i offline zostają bez zmian. NIE dodawaj klucza konta usługi
   do GitHuba. Zbuduj manualnie preview z ai2/feat-firebase-auth.
   Odblokuj ZIP przed rozpakowaniem. Użyj nowego folderu.
5. Wyloguj się i zaloguj na konto administratora online, aby otrzymać nowy
   token z claimem admin:true. Otwórz Panel administratora z menu konta.
   Przycisk odświeżenia uprawnień jest dostępny również zwykłym użytkownikom.
   Nie trzeba zmieniać reguł Firestore dla działania nowego Workera:
   poprzednie reguły domyślnie odrzucają geostudio_activity. Zaktualizowany
   firebase/firestore.rules dodatkowo jawnie odrzuca ten zbiór.

## Model bezpieczeństwa

Przycisk to wyłącznie warstwa prezentacji. Worker wymaga aktywnego
dokumentu własnego konta (Firestore weryfikuje podpis ID tokenu), dokładnego
ADMIN_UID, claimu admin:true w tokenie oraz aktualnego claimu w Authentication.
Sprawdza także disabled i validSince przy każdej operacji administracyjnej.
Google OAuth dla konta usługi ma zakresy datastore i identitytoolkit; wyłącznie
krótkotrwałe access tokeny są buforowane w izolacie. Każde przekierowanie
odrzucane, błędy są ograniczone do stałych kodów. Worker ma zamkniętą listę
operacji i nie przyjmuje dowolnych adresów lub nazw kolekcji. W kliencie
nie ma poświadczeń administracyjnych. Panel nie działa offline. Owner
nie może sam siebie zablokować, ograniczyć terminowo, usunąć ani usunąć
swojej rejestracji w tym panelu. Cofnięcie admina przez set_admin_claim.py
--revoke lub wyłączenie konta działa na serwerze; nowa rola wymaga nowego tokenu.
Jeśli klucz konta usługi wycieknie, niezwłocznie usuń go w IAM, wyłącz Workera,
wygeneruj nowy klucz i sprawdź konta/uprawnienia. Klucz usługi i klucz offline
są niezależne.

## Funkcje i ograniczenia

- Nowe konto: domyślnie 2 urządzenia, aktywne, bezterminowe, bez offline.
  Własne hasło startowe (12–128 znaków) lub losowe niewyświetlane; opcja
  wysłania resetu przez Firebase. Hasło jest przesyłane HTTPS, nie jest
  przechowywane przez GeoStudio. Operacje e-mail podlegają limitom Firebase.
- Edycja aktywności, terminu, notatek, nazwy, limitu i trybu offline
  (wyłączony, 72 h lub bezterminowy; niezależnie od limitu komputerów).
  Ochrona współbieżności updateTime zapobiega nadpisaniu nowych rejestracji.
  Blokada dostępu zmienia entitlement GeoStudio; nie wyłącza automatycznie
  Authentication, aby nadal można było resetować hasło. Można jawnie
  włączyć istniejące wyłączone konto Authentication.
- Nazwy komputerów: systemowa nazwa raportowana przez klienta (nie dowód
  sprzętowy) oraz ręczna nazwa administratora. Usunięcie rejestracji nie
  jest banem urządzenia; może zarejestrować się, jeśli jest wolne miejsce.
- Aktywność: tylko udane połączenia nowej wersji online. Rejestrujemy
  pseudonimowy ID, zgłoszoną nazwę komputera, czas serwera oraz typ zdarzenia.
  Ostatnie logowanie Firebase z Authentication. Historia uruchomień do 50
  wpisów z 30 dni (starsze ukryte przy odczycie, usuwane przy kolejnym zapisie),
  do 20 obserwowanych urządzeń na konto. Zapisy ograniczone czasowo;
  heartbeat przy sprawdzeniu uprawnień, nie śledzimy czynności w edytorze.
  Nie jest to kompletny dziennik bezpieczeństwa ani dowód obecności.
  Dane starych EXE i pracy bez internetu nie są raportowane. Przed
  dystrybucją poinformuj użytkowników o zakresie, celu i retencji danych
  oraz ustal odpowiednie zasady prywatności/usuwania.
- Wysyłanie resetu hasła używa Firebase. Usunięcie konta wymaga dokładnego
  adresu e-mail i potwierdzenia, najpierw blokuje entitlement, usuwa Auth,
  następnie dokument dostępu i historii. Auth i Firestore nie stanowią
  jednej transakcji: częściowe błędy są jawnie raportowane; przy osieroconym
  dokumencie wyczyść go w konsoli Firebase. Odwołana licencja offline może
  działać do końca podpisanego terminu lub bezterminowo, jeśli go nie ma.
- Lista/statystyki: do 500 wyników na każdą kolekcję; ostrzeżenie przy
  niepełnych wynikach. "Połączenie ≤ 20 min" oznacza ostatni kontakt,
  nie gwarantuje obecności online. Darmowe plany mają limity, kontroluj zużycie.
- Stary panel tools/admin/geostudio_admin.py pozostaje niezależną ścieżką
  awaryjną z Google ADC. Nie instalujemy go ani klucza usługi w EXE.

## Testy przed dystrybucją

1. Admin online: lista, utwórz testowe konto, sprawdź wiadomość resetowania,
   zapisz limit i datę, nazwij urządzenie, usuń rejestrację, zablokuj, przywróć,
   usuń testowe konto (nigdy nie testuj usuwania na swoim koncie).
2. Zwykłe konto: brak przycisku i odmowa bezpośredniej operacji na Workerze.
3. Admin offline: brak panelu; praca na mapie i zapis nadal zgodnie z licencją.
4. Cofnięcie claimu: odmowa z istniejącym tokenem. Przywróć claim lokalnym
   narzędziem i zaloguj się ponownie.
5. Zachowanie starych map po zmianie konta, ponowna walidacja online,
   limit drugiego/trzeciego komputera i wygaśnięcie licencji.
