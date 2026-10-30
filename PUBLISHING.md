# Публикация исходников

Рекомендуемое имя репозитория: `horizon-elyby-integration`.
Описание: «Experimental source patch for Horizon: Ely.by accounts, skins and local profiles».
Не выдавайте его за официальный Horizon/Ely.by или проверенный активатор.

1. Прочитайте README и VALIDATION. Сохраните MIT LICENSE и THIRD_PARTY_NOTICES.
2. Создайте свой репозиторий и перенесите публичные файлы пакета. Не загружайте
   `.research`, игровые ресурсы, account/session files, токены или ключницы.
   `.gitignore` исключает рабочие снимки; архиватор использует явный список файлов.
3. Опубликуйте исходники, запустите `Check patch package` и устраните ошибки.
4. Зарегистрируйте собственное совместимое приложение Ely.by и добавьте публичный
   ID в repository variable `HORIZON_ELY_CLIENT_ID`. Не добавляйте client secret.
5. Запустите вручную `Experimental native builds`. Скачанные артефакты содержат
   оба бинарных файла. Проведите проверки из VALIDATION на каждой ОС и укажите
   результаты в release notes. До этого маркируйте релиз experimental/prerelease.
6. Для исходного ZIP выполните `python3 tools/package.py`. Архиватор не запускает
   патчер и не компилирует программы. Получатся:
   `dist/horizon-elyby-integration.zip` и `dist/SHA256SUMS`.
7. Создайте тег, например `v0.1.0-experimental`, и GitHub Release. Приложите ZIP
   и SHA256SUMS. Не меняйте содержимое опубликованного тега. Для новой версии
   используйте новый тег и новую контрольную сумму.

Команды Git ниже предназначены для самостоятельного выполнения:

```bash
git init
git add .
git commit -m "Add experimental Horizon Ely.by source patch"
git branch -M main
git remote add origin https://github.com/sergo-linux/horizon-ely-integration.git
git push -u origin main
git tag v0.1.0-experimental
git push origin v0.1.0-experimental
```

## Загрузка через curl

Замените sergo-linux/horizon-ely-integration, тег и SHA256 из опубликованного SHA256SUMS:

```bash
curl -fL https://raw.githubusercontent.com/sergo-linux/horizon-ely-integration/v0.1.0-experimental/bootstrap.sh -o bootstrap.sh
bash bootstrap.sh sergo-linux/horizon-ely-integration v0.1.0-experimental SHA256 ./horizon-ely-package
```

Bootstrap только скачивает и распаковывает исходный пакет в новый каталог.
Патч не применяется и программы не запускаются. Прочитайте скачанный скрипт
перед выполнением; контрольная сумма архива не проверяет сам bootstrap.

## Загрузка через PowerShell irm

```powershell
$code = irm https://raw.githubusercontent.com/sergo-linux/horizon-ely-integration/v0.1.0-experimental/bootstrap.ps1
# Проверьте содержимое $code перед выполнением.
& ([scriptblock]::Create($code)) -Repo sergo-linux/horizon-ely-integration -Tag v0.1.0-experimental -Sha256 SHA256 -Destination .\horizon-ely-package
```

Для bootstrap нужен Python 3.10+. Существующий каталог не перезаписывается;
без точной SHA-256 распаковки нет. В bootstrap не встроены логины и токены.

## Обновления

Этот пакет не переносит свои изменения на новые коммиты Horizon автоматически.
Upstream-патчи требуют ручного переноса, нового манифеста, тестов и новых сборок.
Официальное самообновление лаунчера отключено в коде. Автоустановка игры по
умолчанию выключена, но пользователь может включить её в настройках; это
не обновит сопутствующий изменённый клиент и не подтвердит совместимость ресурсов.
Рекомендуйте оставлять её выключенной для этой экспериментальной сборки.

Для публикации проверенных обновлений потребуется свой канал сборок обоих
компонентов, подписи и проверка версии формата ресурсов. Такой канал здесь
не развёрнут. Патчер не подписывает и не публикует релизы от вашего имени.
