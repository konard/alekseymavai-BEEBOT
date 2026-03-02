# BEEBOT

AI-бот помощник для автора блога о продуктах пчеловодства. Отвечает на вопросы подписчиков в стиле автора, используя базу знаний из видео и инструкций.

## Архитектура

```
Telegram → aiogram бот → База знаний (FAISS) → Groq (llama3-70b-8192) → Ответ
```

**Компоненты:**
- **База знаний** — гибридный поиск: семантические эмбеддинги (sentence-transformers) + стилометрия
- **LLM** — Groq API с моделью llama3-70b-8192
- **Бот** — Telegram бот на aiogram 3
- **Данные** — PDF-инструкции по продуктам + субтитры YouTube

## Быстрый старт

### 1. Клонировать и настроить

```bash
git clone https://github.com/alekseymavai/BEEBOT.git
cd BEEBOT
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

### 2. Настроить переменные окружения

```bash
cp .env.example .env
# Отредактировать .env:
#   TELEGRAM_BOT_TOKEN=ваш_токен
#   GROQ_API_KEY=ваш_ключ
```

### 3. Собрать базу знаний

```bash
python -m src.build_kb
```

### 4. Запустить бота

```bash
python -m src.bot
```

## Деплой на VPS

### Docker (рекомендуется)

```bash
docker-compose up -d
```

### systemd

```bash
sudo bash deploy.sh
```

Подробнее: `beebot.service`, `deploy.sh`

## Структура проекта

```
BEEBOT/
├── src/
│   ├── bot.py              # Telegram бот
│   ├── config.py           # Конфигурация
│   ├── knowledge_base.py   # FAISS + стилометрия
│   ├── llm_client.py       # Groq API клиент
│   ├── pdf_loader.py       # Извлечение текста из PDF
│   ├── youtube_loader.py   # Загрузка субтитров YouTube
│   └── build_kb.py         # Сборка базы знаний
├── data/
│   ├── subtitles/          # Субтитры YouTube
│   ├── texts/              # Извлечённые тексты PDF
│   └── processed/          # FAISS индекс + чанки
├── Dockerfile
├── docker-compose.yml
├── deploy.sh
├── beebot.service
├── requirements.txt
└── .env.example
```

## Источники данных

- **YouTube**: [Усадьба Дмитровых](https://www.youtube.com/@a.dmitrov) — 27 видео
- **PDF инструкции**: 10 документов (прополис, перга, обножка, ПЖВМ и др.)

## Технологии

| Компонент | Технология |
|-----------|------------|
| Бот | aiogram 3 |
| LLM | Groq (llama3-70b-8192) |
| Эмбеддинги | sentence-transformers (paraphrase-multilingual-MiniLM-L12-v2) |
| Векторный поиск | FAISS |
| Чанкинг | langchain-text-splitters |
