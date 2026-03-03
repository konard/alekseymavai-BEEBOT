# BEEBOT — Контекст сессии

> Последнее обновление: 3 марта 2026

## Статус проекта

**Бот развёрнут и работает в production.**

| Компонент | Статус | Детали |
|-----------|--------|--------|
| Telegram-бот | ✅ Работает | @AleksandrDmitrov_BEEBOT |
| База знаний | ✅ 410 чанков | 13 PDF + 26 YouTube видео |
| Groq LLM | ✅ Через прокси | llama-3.3-70b-versatile |
| VPS Docker | ✅ Запущен | 185.233.200.13, container `beebot` |
| Groq Proxy | ✅ systemd | groq-proxy.service на hive |
| SSH Туннель | ✅ systemd | groq-tunnel.service на hive |
| Группы Telegram | ✅ | По упоминанию @bot или reply |

## Архитектура

```
Telegram → aiogram бот (VPS Docker, network_mode: host)
  → FAISS (семантика 70% + стилометрия 30%, 410 чанков)
  → SSH-туннель (VPS:8990 → hive:8990)  ← systemd, auto-restart
  → Groq Proxy (hive, порт 8990)         ← systemd, auto-restart
  → Groq API (llama-3.3-70b-versatile)
  → Ответ в стиле Александра Дмитрова
```

## Доступы и серверы

| Ресурс | Адрес | Пользователь |
|--------|-------|-------------|
| VPS | 185.233.200.13 | ai-agent (SSH-ключ id_ed25519) |
| hive | локальная машина | hive / new (ai-agent@traderagent) |
| GitHub (upstream) | github.com/alekseymavai/BEEBOT | alekseymavai |
| GitHub (fork) | github.com/unidel2035/BEEBOT | unidel2035 |
| Локальный путь | /home/hive/BEEBOT/ | hive |
| Groq Console | console.groq.com | alekseymavai |

**SSH доступ к VPS:**
- Ключ hive: `/home/hive/.ssh/id_ed25519` → `ai-agent@185.233.200.13` ✅
- Ключ new (ai-agent): `/home/new/.ssh/id_ed25519` → `ai-agent@185.233.200.13` ✅
- Алиас в SSH config hive: `ssh beebot-vps`

**Важно:** аккаунт `unidel2035` не имеет push-доступа к `alekseymavai/BEEBOT`. Все изменения — через fork + PR.

## Ключевые файлы

```
/home/hive/BEEBOT/
├── src/
│   ├── bot.py              # Telegram-бот: /start с кнопками, /products по категориям
│   ├── config.py           # Конфигурация из .env
│   ├── knowledge_base.py   # FAISS + стилометрия, умный чанкинг по типу источника
│   ├── llm_client.py       # Groq API (с поддержкой GROQ_BASE_URL прокси)
│   ├── pdf_loader.py       # Извлечение текста из PDF
│   ├── youtube_loader.py   # Загрузка субтитров YouTube (26 видео)
│   └── build_kb.py         # Сборка базы знаний
├── data/
│   ├── subtitles/          # 26 файлов .txt (238 KB)
│   ├── texts/              # 16 файлов из PDF (107 KB)
│   └── processed/
│       ├── index.faiss     # FAISS-индекс
│       └── chunks.json     # Метаданные чанков (410 чанков)
├── systemd/                # ← НОВОЕ
│   ├── groq-proxy.service  # Автозапуск прокси на hive
│   ├── groq-tunnel.service # Автозапуск SSH-туннеля на hive
│   └── install-hive-services.sh
├── groq_proxy.py           # Reverse proxy для Groq API (порт 8990)
├── Dockerfile
├── docker-compose.yml      # network_mode: host
├── deploy.sh               # Скрипт деплоя на VPS
├── beebot.service          # systemd unit (VPS)
├── .env                    # Секреты (НЕ в git)
└── .env.example
```

## Фоновые процессы на hive — АВТОМАТИЗИРОВАНЫ через systemd

```bash
# Статус
systemctl status groq-proxy
systemctl status groq-tunnel

# Логи
journalctl -u groq-proxy -f
journalctl -u groq-tunnel -f

# Перезапуск (если нужно вручную)
systemctl restart groq-proxy groq-tunnel
```

**Сервисы установлены, включены (enabled) и работают.** При перезагрузке hive — поднимаются автоматически. `groq-tunnel` зависит от `groq-proxy` (стартует после него).

## UI бота (актуально)

- `/start` — приветствие + кнопки `📦 Все продукты` / `❓ Как пользоваться`
- `/products` — список продуктов сгруппирован по категориям:
  - 🍯 Продукты пчеловодства (Перга, Обножка, Гомогенат)
  - 🌿 Настойки (Прополис, ПЖВМ, Подмор, Успокоин, Антивирус, ФитоЭнергия)
  - 📋 Программы здоровья (УПО, Приложение к УПО, Иммунитет ребёнка, Инструкция ТГ)
- После каждого ответа — кнопки `📄 [конкретный PDF]` + `📦 Все продукты`

## Чанкинг базы знаний (актуально)

| Источник | chunk_size | overlap | Доп. обработка |
|---|---|---|---|
| PDF (`pdf:*`) | 900 | 150 | — |
| YouTube (`youtube:*`) | 1200 | 250 | Очистка повторов и timestamps |
| Default | 900 | 150 | — |

**Индекс нужно пересобрать на VPS** после последних изменений:
```bash
ssh ai-agent@185.233.200.13 "cd /home/ai-agent/BEEBOT && docker exec beebot python -m src.build_kb"
```

## Секреты (.env на VPS)

```
TELEGRAM_BOT_TOKEN=8762491951:AAGvmx8YCJcGaq6HEf8xMGV3NOPehr38H84
GROQ_API_KEY=gsk_...ounD (последние 4: ounD)
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_BASE_URL=http://localhost:8990
```

## Известные проблемы и ограничения

1. **Groq блокирует IP VPS** — решено: SSH-туннель + прокси на hive (systemd)
2. **YouTube блокирует IP hive** — субтитры скачаны заранее и хранятся в `data/subtitles/`
3. **YouTube блокирует IP VPS** — нельзя использовать VPS для скрапинга YouTube (риск блокировки порушит туннель Groq)
4. **llama-3.3-70b-versatile** иногда вставляет иноязычные слова — частично решено промптом
5. **unidel2035 нет push-доступа** к alekseymavai/BEEBOT — только fork + PR

## Расширение базы знаний — план

**Следующий приоритет:** добавить обучающих данных.

Лучшие источники (по убыванию ценности):
1. **YouTube Data API v3** — скачать комментарии к видео Дмитрова. Комментарии = реальные Q&A от подписчиков + ответы автора в его стиле. Нужен API-ключ Google Cloud. **Не блокирует IP** — лимиты по ключу.
2. **Новые видео с канала** — проверить `@a.dmitrov` на новые видео, добавить ID в `youtube_loader.py`
3. **FAQ-файл вручную** — `data/texts/faq.txt` с частыми вопросами и ответами

**Почему не yt-dlp на VPS:** VPS — дата-центровый IP, YouTube его заблокирует так же как hive. Это разрушит туннель Groq.

## Git-история (последние)

```
8ad0bc2 feat: systemd services, UI categories, smart chunking
cd10e16 fix: skip command messages in handle_question
2584be0 feat: /products команда + защита от галлюцинаций
9657866 fix: keyword-буст поиска + очистка OCR-текстов
852f099 feat: кнопка «Показать инструкцию» под ответом бота
```

## Команды для быстрого старта сессии

```bash
# Перейти в проект
cd /home/hive/BEEBOT

# Статус сервисов на hive
systemctl status groq-proxy groq-tunnel

# Проверить туннель (порт 8990 на VPS)
ssh ai-agent@185.233.200.13 "ss -tlnp | grep 8990"

# Проверить бота на VPS
ssh ai-agent@185.233.200.13 "docker logs --tail 10 beebot"

# Перезапустить бота на VPS
ssh ai-agent@185.233.200.13 "docker restart beebot"

# Пересобрать базу знаний на VPS
ssh ai-agent@185.233.200.13 "cd /home/ai-agent/BEEBOT && docker exec beebot python -m src.build_kb"

# Обновить код на VPS (без пересборки Docker)
scp src/bot.py ai-agent@185.233.200.13:/home/ai-agent/BEEBOT/src/bot.py
ssh ai-agent@185.233.200.13 "docker restart beebot"

# Полный редеплой (с пересборкой образа)
ssh ai-agent@185.233.200.13 "cd /home/ai-agent/BEEBOT && git pull && docker compose up -d --build"
```
