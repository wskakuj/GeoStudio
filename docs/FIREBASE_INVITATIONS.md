# Rejestracja GeoStudio z kodem zaproszenia

## Aktualizacja

1. Wgraj cały aktualny firebase/worker/admin.mjs do dotychczasowego
   Cloudflare Workera geostudio-admin. Zachowaj jego zmienne i sekrety.
   Nie generuj nowego klucza usługi. Jeśli nie wdrożyłeś wcześniejszej
   aktualizacji bezterminowego offline, zaktualizuj też geostudio-license
   zgodnie z FIREBASE_OFFLINE.md.
2. Zalecane: opublikuj aktualne firebase/firestore.rules. Stare reguły
   domyślnie odrzucają nowe kolekcje, więc nie rozszerzaj dostępu klientów.
3. Po zielonym CI zbuduj EXE na ai2/feat-firebase-auth i rozpakuj
   nowy ZIP po odblokowaniu w Windows. Nie zmieniaj GitHub Secrets.
4. Zaloguj się jako administrator online, otwórz Panel administratora >
   Zaproszenia. Zaznacz rejestrację z kodem i zapisz ustawienie.
   Rejestracja domyślnie wyłączona, ręczne tworzenie kont pozostaje.
5. Utwórz jednorazowe zaproszenie testowe, skopiuj pełny kod (widoczny
   tylko raz). W innym oknie logowania użyj przycisku Utwórz konto z kodem,
   wprowadź e-mail, hasło (12–128 znaków), powtórzenie hasła i kod.
   Kliknij Utwórz konto i wyślij link. Sprawdź pocztę, w tym spam.
   Po kliknięciu linku wpisz hasło ponownie i zakończ rejestrację.
   Wymagana jest aktualna wersja kodu i połączenie z internetem.
6. Jeśli kod wymaga akceptacji: na liście użytkowników wybierz
   Oczekujące na akceptację, zaznacz Aktywny dostęp i zapisz.
   W przeciwnym razie można zalogować się od razu po zakończeniu rejestracji.
   Ważność konta w dniach liczona od zakończenia rejestracji, nie akceptacji.

## Model bezpieczeństwa

Kod GS ma 128 bitów losowości. Firestore przechowuje SHA-256 kodu jako
identyfikator dokumentu, końcówkę i metadane; nigdy pełny kod. Ustawienia
administracyjne są chronione przez istniejącą weryfikację ADMIN_UID,
claimu i bieżącego konta. Publiczny endpoint POST /registration akceptuje
wyłącznie sprawdzenie zaproszenia, weryfikację rejestracji i status
własnego konta (wymaga tokena). Nie otrzymuje hasła — hasło jest
przesyłane do Firebase Authentication bezpośrednio przez klienta.
Worker sprawdza aktualny zweryfikowany e-mail i UID za pomocą Google
accounts:lookup, nie ufa samemu zdekodowanemu tokenowi.

Dostęp, licznik, ustawienie rejestracji i historia są zapisywane atomowo
z preconditions Firestore. Jednorazowy kod można wykorzystać tylko
raz do przyznania dostępu, także przy równoczesnych żądaniach. Kod jest
sprawdzany na początku oraz przy zakończeniu. Wygaszenie/unieważnienie
lub wyłączenie rejestracji blokuje dalsze aktywacje, nie cofa już
przyznanych uprawnień. Istniejącego dokumentu dostępu nie można zastąpić
kodem, także jeśli konto jest zablokowane.

Firebase Email/Password na bezpłatnym planie udostępnia publiczne
accounts:signUp. Osoba omijająca EXE może utworzyć sam rekord
Authentication bez zaproszenia, ale nie otrzyma dostępu do GeoStudio,
licencji offline ani praw administracyjnych. Rozpoczęte, niedokończone
rejestracje mogą pozostać w Authentication bez dokumentu dostępu.
Limit kodu dotyczy zakończonych rejestracji; użytkownik musi zachować kod
do potwierdzenia e-maila. Ręczne utworzenie konta w panelu jest niezależne.

Opcjonalne wzmocnienie: Cloudflare Rate Limiting binding
REGISTRATION_RATE_LIMITER, np. 10 żądań/60 s per klucz.
Kod używa CF-Connecting-IP wyłącznie jako klucza limitera; nie zapisuje
IP w Firestore. Wiążąc publiczne zaproszenia z określonym e-mailem,
ustawiamy jedno użycie. Bez bindingu losowość chroni przed zgadywaniem,
ale nie przed atakami zużywającymi limit usługi. Binding wymaga konfiguracji
Cloudflare (https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/).
Nie włączaj logowania ciał żądań, tokenów ani kodów.

## Dane i ograniczenia

- Kody: 0 = bez limitu użyć / bezterminowo, poza tym 1–100000 użyć
  oraz 1–3650 dni ważności kodu i konta; limit urządzeń 0–20.
- Historia zawiera UID, czas użycia i informację o wymaganej akceptacji.
  Nie przechowuje hasła ani pełnego kodu; adres e-mail pobierany z listy
  aktualnych kont w panelu, usunięte konta pozostawiają pseudonimowy UID.
  Lista i historia mają limit 500 wyświetlanych dokumentów.
- Kody bezterminowe lub z wieloma użyciami wymagają ostrożności.
  Bezterminowy offline może działać bez możliwości zdalnego cofnięcia,
  gdy komputer nigdy nie połączy się z internetem.
- Koszty i limity Firebase/Cloudflare (w tym e-maili weryfikacyjnych)
  obowiązują nadal. Testuj na oddzielnych kontach, nie na administratorze.
