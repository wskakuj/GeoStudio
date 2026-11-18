# Bezpieczna aktualizacja GeoStudio na Windows

`update_windows.bat` od tej zmiany:
- pobiera zawsze `origin/main` i przełącza się z gałęzi testowej na `main`;
- zatrzymuje się przy niezapisanych modyfikacjach plików śledzonych przez Git;
- aktualizuje zwykłą gałąź `main` metodą fast-forward;
- gdy lokalny `main` ma inne commity niż `origin/main`, **najpierw**
  tworzy gałąź `backup/main-before-update-YYYYMMDD-HHMMSS`;
- przed przestawieniem rozbieżnego `main` na GitHuba pyta o zgodę
  (klawisz T = tak, N = nie). Komenda `git reset --hard` nie wykonuje się
  bez jawnej zgody i pomyślnego stworzenia kopii lokalnych commitów.

Skrypt **nie usuwa** plików nieśledzonych przez Git. Nie usuwa kopii
roboczych `*.MAP`, ale jeśli masz niezapisane zmiany w plikach śledzonych
przez Git, musisz je zachować oddzielnie przed aktualizacją.

## Jak jednorazowo naprawić STARĄ wersję update_windows.bat

Ponieważ stary skrypt nie potrafi pobrać własnej poprawki, przy istniejącej
rozbieżności wykonaj poniższe kroki tylko jeden raz.

1. Zamknij GeoStudio. Otwórz katalog projektu w Eksploratorze i wpisz
   `cmd` w pasku adresu (otworzy się wiersz polecenia w folderze repo).
2. Sprawdź:
   ```cmd
   git status
   git branch --show-current
   ```
   Jeżeli są zmienione pliki śledzone przez Git, **nie wykonuj resetu** —
   zrób commit, odłóż je do stash albo zachowaj w osobnym miejscu.
3. Jeżeli nie jesteś na `main`, przełącz się:
   ```cmd
   git switch main
   ```
4. Pobierz historię i utwórz kopię lokalnej gałęzi PRZED resetem:
   ```cmd
   git fetch origin main
   git branch "backup/main-before-manual-sync-%RANDOM%" main
   ```
   Sprawdź, czy `git branch` wypisał sukces (brak błędu).
5. Jeżeli Twoja kopia jest bez zmian lokalnych, a poprzednia komenda
   utworzyła gałąź backup, dopiero wtedy:
   ```cmd
   git reset --hard origin/main
   ```
6. Uruchom `update_windows.bat` — odtąd kolejna rozbieżność zostanie
   wykryta i zabezpieczona automatycznie.

## Diagnostyka i odzyskiwanie

```cmd
git status
git branch -v
git log --oneline --left-right main...origin/main
git branch --list "backup/*"
```

W gałęzi `backup/...` pozostają wcześniejsze lokalne commity, nawet
po przestawieniu `main`. Nie usuwaj ich, dopóki nie zweryfikujesz, czy
były potrzebne. Chęć odzyskania części tych zmian nie oznacza, że należy
scalać całą starą gałąź z nowym `main`: do wybranych commitów służy
`git cherry-pick`, po wcześniejszym przejrzeniu różnic.

**Najbezpieczniejsza alternatywa**, jeśli nie znasz stanu lokalnego repo:
sklonuj aktualny `main` do NOWEGO folderu, zostawiając starą instalację
bez żadnych zmian.
