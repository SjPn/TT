# TaskTracker

Лёгкий self-hosted трекер задач для небольших команд (1–10 человек).  
Один процесс, SQLite, русский UI. Не Jira.

Репозиторий: https://github.com/SjPn/TT

> Для ИИ / передачи контекста на другой ПК см. **[AGENTS.md](AGENTS.md)**.

## Быстрый старт

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate

pip install -r requirements.txt
python seed.py          # опционально
python run.py
```

Открой http://127.0.0.1:8010 (порт можно задать через `PORT`).

Демо из `seed.py`:

- `alice@example.com` / `password`
- `bob@example.com` / `password`

Тесты:

```bash
python -m pytest tests/test_smoke.py -q
```

## Возможности

- Регистрация / вход / профиль (имя, email-логин, пароль)
- Проекты: создание, участники по email, владелец правит/удаляет
- Задачи: приоритет, исполнитель, фото (файл или Ctrl+V)
- Виды: список, доска, архив; фильтр «Мои» = назначенные мне
- Workflow: в работу → выполнено → подтверждение автора → архив  
  (если автор = исполнитель — сразу в архив)
- Лента событий + комментарии + @упоминания
- Уведомления в шапке; опционально email/Telegram через env
- Хоткеи: `C`/`N` — новая задача, `/` — поиск, `Esc` — закрыть

## Стек

FastAPI · SQLAlchemy · SQLite (WAL) · Jinja2 · HTMX · bcrypt

Данные: `data/tracker.db` + `data/uploads/` (бэкап = копия папки `data/`).

## Деплой

См. [DEPLOY.md](DEPLOY.md) (Coolify + volume `/app/data`).

Минимум env:

```env
SECRET_KEY=<длинная-случайная-строка>
DATA_DIR=/app/data
HTTPS_ONLY=false
```

На HTTP (sslip.io) держи `HTTPS_ONLY=false`, иначе cookie-сессии могут не работать.

## Команда в проекте

1. Человек регистрируется на `/register`.
2. Владелец: проект → ⋯ → Участники → email → Добавить.
3. После этого проект виден у участника; его можно назначать исполнителем.
