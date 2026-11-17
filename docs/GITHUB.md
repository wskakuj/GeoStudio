# Publikacja GeoStudio na GitHubie

1. Utwórz **prywatne** repozytorium `GeoStudio` na swoim koncie GitHub.
   Nie dodawaj README ani pliku `.gitignore` przy tworzeniu, bo są w tym pakiecie.
2. Wypakuj archiwum i wykonaj w terminalu w folderze projektu:

```powershell
git init
git add .
git commit -m "feat: initial GeoStudio GEO-MAP viewer and safe parser"
git branch -M main
git remote add origin https://github.com/wskakuj/GeoStudio.git
git push -u origin main
```

Jeżeli w repozytorium znajduje się już gałąź `main`, nie używaj `--force`:
zrób `git pull --rebase origin main` i rozwiąż ewentualne konflikty.

Uwaga: `.gitignore` celowo pomija prywatne mapy i biblioteki. Przed każdym
`git push` sprawdź `git status` i `git diff --cached --name-only`.
