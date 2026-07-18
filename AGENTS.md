# AGENTS.md — контекст TaskTracker для ИИ / другой машины

Читай этот файл первым, если открываешь репозиторий на новом ПК или в новом чате.

## Суть продукта

**TaskTracker** — лёгкий self-hosted трекер задач/багов для маленьких команд (1–10 человек).

- Позиционирование: ясность как у Linear, «вес» как у Kanboard — **не** клон Jira/Plane.
- Один процесс, SQLite, Jinja2+HTMX, минимум зависимостей, низкая нагрузка на VPS.
- UI **полностью на русском**.
- Репозиторий: https://github.com/SjPn/TT (`main`)
- Локальный путь (автор): `D:\MyPyPro\TaskTracker`

## Стек

| Слой | Технология |
|------|------------|
| API/UI | FastAPI + Jinja2 templates + HTMX |
| БД | SQLAlchemy 2 + SQLite (WAL) |
| Auth | Cookie-сессии (`itsdangerous` + bcrypt) |
| Статика | `/static`, загрузки `/uploads` |
| Деплой | Docker → Coolify на Hetzner VPS |

Ключевые пути:

- `app/main.py` — приложение, middleware, mounts
- `app/models.py` — User, Project, Issue, Comment, Attachment, Notification, Activity
- `app/services.py` — бизнес-логика, workflow, uploads, mentions, activity
- `app/routers/` — `auth`, `projects`, `issues`, `notifications`
- `app/templates/` — UI
- `app/static/style.css`, `app/static/app.js`
- `app/config.py` — env-настройки
- `tests/test_smoke.py` — смоук-тесты
- `Dockerfile`, `docker-compose.yml`

## Доменная модель (кратко)

- **User** — имя, email (логин), пароль
- **Project** — имя, описание, `key` (авто из имени, в UI не показывают), владелец, участники
- **Issue** — задача: title, description, priority P1–P4, status, assignee, author, фото
- **Comment** + фото; **Activity** — единая лента (создание, assign, статус, комментарии)
- **Notification** — in-app (+ опционально email/Telegram)

Статусы:

`open` → `in_progress` → `pending_confirm` → `resolved` (архив)

Workflow:

1. Автор создаёт, назначает исполнителя.
2. Исполнитель: «В работу» / «Отметить выполненной».
3. Если исполнитель ≠ автор → статус `pending_confirm`, автор подтверждает → архив.
4. Если автор = исполнитель → «Отметить выполненной» сразу в `resolved` (без самоподтверждения).

Фильтр **«Мои»** = назначенные **мне** (`assignee_id`), не созданные мной.

## Что уже реализовано (актуально)

### Auth / профиль
- Регистрация, вход, выход
- Secure cookie только на HTTPS (на HTTP sslip.io — без Secure)
- `/profile` — смена имени, email (логин), пароля с подтверждением; клик по имени в шапке

### Проекты
- Создание (только название + описание; key авто)
- Участники по email (уже зарегистрированные)
- Владелец: изменить / удалить проект (меню ⋯)
- Поиск проектов на главной при >3 проектах или активном `q`

### Задачи
- Быстрое создание: title + Enter; детали в `<details>`
- Список / доска / архив
- Удаление задачи (автор); с диска чистятся файлы `uploads/`
- Фото: загрузка + **Ctrl+V** из буфера (комментарии и создание)
- Лента activity + комментарии
- `@Имя` / `@email` → уведомление + подсветка
- Панель «ваш ход» + цвет статуса (open / in_progress / pending_confirm / resolved)
- Хоткеи: `C`/`N` новая задача, `/` поиск, `Esc` закрыть диалог
- Метки и issue-key (`PROJ-N`) в UI **убраны** (в БД key проекта/номер могут остаться)

### Уведомления
- Назначение, приглашение в проект, mention
- Колокольчик в topbar + `/notifications`
- Опционально SMTP / Telegram (env; иначе no-op, в фоне)

### Не делаем (осознанно)
- Спринты, Gantt, time tracking, сложные роли, SSO, мобильное приложение
- HTTPS пока отложен пользователем (на проде может быть HTTP sslip.io)

## Запуск локально

```bash
cd D:\MyPyPro\TaskTracker   # или клон репо
python -m venv .venv
.\.venv\Scripts\activate    # Windows
pip install -r requirements.txt
python seed.py              # опционально демо
python run.py               # обычно http://127.0.0.1:8010
```

Тесты:

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_smoke.py -q
```

## Деплой (Coolify)

- Dockerfile в корне, порт `8000` / `$PORT`
- **Обязателен** volume: `/app/data` → `tracker.db` + `uploads/`
- Env минимум: `SECRET_KEY`, `DATA_DIR=/app/data`
- Сейчас часто: `HTTPS_ONLY=false` на HTTP sslip.io  
  Пример домена: `http://tasktrack.<VPS-IP>.sslip.io`
- Push: `git -c credential.helper=wincred push` (`gh` может быть не установлен)
- **Не коммитить:** `.env`, секреты, `data/`
- Документация `*.md` в `.gitignore`, кроме исключений ниже

Опциональные env: `PUBLIC_BASE_URL`, `SMTP_*`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

## Правила работы агента (важное)

1. Код лёгкий, без тяжёлых зависимостей и раздувания.
2. UI на русском; не возвращать EN-лейблы в шаблоны.
3. Не пушить `.env`, `data/`, секреты.
4. Коммиты/push — только если пользователь просит (или явно «задеплой/запушь»).
5. PowerShell: не использовать `$pid` как переменную цикла.
6. При удалении issue/project — удалять файлы из `uploads/` (уже в `services.py`).
7. UX-приоритет: понятные действия без лишних полей (метки, ручной project key, кнопка «Фильтр» — уже вычищены).

## Типичные следующие задачи (бэклог идей)

Не обязательства — ориентир, если спросят «что улучшить»:

- [ ] HTTPS / нормальный домен
- [ ] Отдельный фильтр «созданные мной» vs «назначенные мне»
- [ ] Цитирование комментариев / ответ на конкретный
- [ ] Сжатие/лимит превью больших скринов
- [ ] Email/Telegram настроить на проде при необходимости

## История решений (коротко)

- Отказ от Plane/Jira-сложности → FastAPI monolith + SQLite.
- Cookie Secure ломал логин на HTTP → Secure только при `https`.
- Issue keys и project keys убраны из UI как шум.
- Self-assign: без шага «подтверди сам себе».
- Дизайн: teal, цветовые статусы, action-panel, Plus Jakarta Sans.

---

**Для ИИ на другом ПК:** клонируй `https://github.com/SjPn/TT`, прочитай этот файл, затем смотри `app/` и `tests/`. Локальные `README.md` / `DEPLOY.md` могут быть полнее, если лежат рядом (часто только локально из‑за gitignore).
