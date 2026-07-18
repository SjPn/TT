# Деплой: Hetzner + Coolify

Один контейнер, SQLite + uploads на persistent volume.

## Coolify

1. Репозиторий: https://github.com/SjPn/TT (`main`), build: **Dockerfile**.
2. Port: `8000` (или Coolify `PORT` — образ читает его).
3. Domain: свой домен или `http://<имя>.<VPS-IP>.sslip.io` (без IP в имени sslip не попадёт на VPS).
4. **Persistent storage (обязательно):**

| Путь в контейнере | Назначение |
|---|---|
| `/app/data` | `tracker.db` + `uploads/` |

5. Environment:

```env
SECRET_KEY=<long-random-string>
DATA_DIR=/app/data
HTTPS_ONLY=false
```

На HTTPS-домене можно `HTTPS_ONLY=true`. На голом HTTP sslip.io — **только `false`**, иначе логин ломается (Secure cookie).

Секрет:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

6. Deploy. Health: `GET /health`.
7. Первый пользователь: открыть сайт → Регистрация.

Опционально внутри контейнера: `python seed.py`.

### Опциональные уведомления

```env
PUBLIC_BASE_URL=https://your.domain
SMTP_HOST=...
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
SMTP_FROM=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

Пустые = выключено (нулевая нагрузка).

## Локальный Docker

```bash
# PowerShell
$env:SECRET_KEY="local-dev-secret"
docker compose up --build
```

http://127.0.0.1:8000

## Бэкап

Периодически копировать volume:

- `data/tracker.db` (+ `-wal` / `-shm` если есть)
- `data/uploads/`

## Важно

- Одна реплика (SQLite).
- Не стирать `/app/data` при redeploy.
- Traefik/Coolify: `ProxyHeadersMiddleware` уже в приложении.
