# CDN для каталога zStore (VDS)

Старые сборки zStore **не меняются**: они по-прежнему качают `repo-lite.json`, `details/*.json` и `d0e4/*` с GitHub.  
После включения CDN в JSON попадают ссылки на `https://cdn.zstoreplus.ru/...` — иконки и скрины грузятся с VDS.

## Что вынести на VDS (тяжёлое)

| Папка | Назначение |
|-------|------------|
| `icons/` | Исходные иконки + `icons/s/`, `icons/m/` |
| `shots/` | Скрины для карточек приложений (build_lite) |
| `screenshots/` | Закреплённые скрины (Telegram+, Instagram+ и т.д.) |
| `about/` | Картинки для «О приложении» |
| `d0e4/covers/` | Обложки новостей |
| `d0e4/icons/` | Иконки в новостях |
| `d0e4/screenshots/` | Скрины в новостях |
| `d0e4/videos/` | Видео для новостей |

## Что оставить на GitHub (лёгкое, точки входа приложения)

| Файлы / папки | Зачем |
|---------------|--------|
| `repo-lite.json`, `repo.json` | Каталог |
| `details/*.json` | Страницы приложений |
| `d0e4/*.json`, `d0e4/d.html`, `d0e4/n/`, `d0e4/s/` | Новости и сервисы |
| `about.json` | О zStore |
| GitHub **Releases** | IPA (пока не переносите) |

## Порядок включения

1. DNS: `cdn.zstoreplus.ru` → IP VDS.
2. Nginx: `deploy/nginx-catalog.conf` → `/var/www/zstore-catalog`.
3. Локально собрать каталог: `python3 scripts/build_lite.py`.
4. Залить медиа: `ZSTORE_CDN_HOST=root@… ./deploy/sync_cdn.sh`.
5. Проверить в браузере: `https://cdn.zstoreplus.ru/icons/s/…` (любой файл из репо).
6. Включить CDN в сборке:
   ```bash
   export ZSTORE_USE_CDN=1
   export ZSTORE_CDN_BASE=https://cdn.zstoreplus.ru   # по умолчанию уже так
   python3 scripts/build_lite.py
   python3 scripts/rewrite_repo_cdn.py
   ```
7. Закоммитить `repo.json`, `repo-lite.json`, `details/` → push на GitHub.
8. Снова `./deploy/sync_cdn.sh` после каждого изменения иконок/скринов.

## CI (опционально)

В `.github/workflows/build-lite.yml` перед `build_lite.py`:

```yaml
env:
  ZSTORE_USE_CDN: "1"
  ZSTORE_CDN_BASE: https://cdn.zstoreplus.ru
```

Отдельный шаг деплоя — SSH + `deploy/sync_cdn.sh` (секреты в GitHub Actions).

## IPA

Ссылки `downloadURL` на `github.com/.../releases/...` **не трогаем** — клиенты качают IPA как сейчас. Перенос IPA на VDS — отдельный шаг (только смена URL в `repo.json`).
