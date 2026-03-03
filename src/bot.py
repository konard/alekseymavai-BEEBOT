"""Telegram bot for BEEBOT — AI assistant for a beekeeper blog."""

import asyncio
import logging
from collections import Counter

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile

from src.config import TELEGRAM_BOT_TOKEN, BASE_DIR
from src.knowledge_base import KnowledgeBase
from src.llm_client import LLMClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher()

kb = KnowledgeBase()
llm = LLMClient()

WELCOME_MESSAGE = """Привет! Я бот-помощник Александра Дмитрова — пчеловода и автора блога о продуктах пчеловодства.

Задай мне любой вопрос о:
- Продуктах пчеловодства (мёд, перга, прополис, пыльца)
- Рецептах и дозировках
- Пчеловодстве и здоровье

Просто напиши свой вопрос или выбери раздел ниже 👇"""

HELP_MESSAGE = """Как пользоваться ботом:

В личных сообщениях — просто напиши вопрос.

В группе — обратись ко мне по имени или ответь на моё сообщение:
• @AleksandrDmitrov_BEEBOT чем полезна перга?
• Или reply на моё сообщение с вопросом

Примеры вопросов:
- Как принимать настойку прополиса?
- Чем полезна перга?
- Как укрепить иммунитет ребёнка?

/start — начать
/ask — задать вопрос
/help — эта справка
/products — список продуктов с инструкциями"""

ASK_MESSAGE = "Напишите свой вопрос — я отвечу на основе знаний о продуктах пчеловодства 🐝"

PRODUCTS_MESSAGE = "Выбери продукт, чтобы получить PDF с инструкцией:"

VOICE_MESSAGE = "Голосовые сообщения пока не поддерживаю — напиши вопрос текстом, отвечу сразу 🙂"

_PRODUCTS_TRIGGERS = {
    "какие продукты", "список продуктов", "что есть", "что у тебя есть",
    "какие настойки", "какие товары", "что продаёшь", "что продаешь",
    "ассортимент", "что можно купить", "какие препараты",
}

BOT_USERNAME = "AleksandrDmitrov_BEEBOT"

# (kb_source_stem, display_name, pdf_filename, category)
INSTRUCTIONS = [
    # Продукты пчеловодства
    ("Перга",                                        "Перга",                        "Перга.pdf",                                        "bee"),
    ("Пчелиная обножка",                             "Обножка (пыльца)",             "Пчелиная обножка.pdf",                             "bee"),
    ("Трутнёвый гомогенат",                          "Трутнёвый гомогенат",          "Трутнёвый гомогенат.pdf",                          "bee"),
    # Настойки
    ("Прополис_ сухой + настойка",                   "Прополис",                     "Прополис_ сухой + настойка.pdf",                   "tincture"),
    ("Настойка ПЖВМ",                                "ПЖВМ (огнёвка)",               "Настойка ПЖВМ.pdf",                                "tincture"),
    ("Настойка Подмора пчелиного (на самогоне 40°)", "Подмор пчелиный",              "Настойка Подмора пчелиного (на самогоне 40°).pdf", "tincture"),
    ("Настойка «Успокоин» (Травяная)",               "Успокоин",                     "Настойка «Успокоин» (Травяная).pdf",               "tincture"),
    ("Антивирус",                                    "Антивирус",                    "Антивирус.pdf",                                    "tincture"),
    ("ФитоЭнергия",                                  "ФитоЭнергия",                  "ФитоЭнергия.pdf",                                  "tincture"),
    ("Настойка для ЖКТ",                             "Настойка для ЖКТ",             "Настойка для ЖКТ.pdf",                             "tincture"),
    # Программы здоровья
    ("«УНИВЕРСАЛЬНАЯ_ПРОГРАММА_ОЗДОРОВЛЕНИЯ»",       "Программа оздоровления (УПО)", "«УНИВЕРСАЛЬНАЯ_ПРОГРАММА_ОЗДОРОВЛЕНИЯ».pdf",       "program"),
    ("Приложение к УПО (1)",                         "Приложение к УПО",             "Приложение к УПО (1).pdf",                         "program"),
    ("Иммунитет ребенка",                            "Иммунитет ребёнка",            "Иммунитет ребенка.pdf",                            "program"),
    ("Инструкция ТГ",                                "Инструкция ТГ",                "Инструкция ТГ.pdf",                                "program"),
]

_STEM_TO_INSTRUCTION = {
    stem: (i, name, fname)
    for i, (stem, name, fname, _cat) in enumerate(INSTRUCTIONS)
}

_CATEGORY_LABELS = {
    "bee":      "🍯 Продукты пчеловодства",
    "tincture": "🌿 Настойки",
    "program":  "📋 Программы здоровья",
}


def _build_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📦 Все продукты", callback_data="show_products"),
        InlineKeyboardButton(text="❓ Как пользоваться", callback_data="show_help"),
    ]])


def _build_back_to_products_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📦 Все продукты", callback_data="show_products"),
    ]])


def _build_products_keyboard() -> InlineKeyboardMarkup:
    rows = []
    current_cat = None
    cat_buttons = []

    for i, (stem, name, fname, cat) in enumerate(INSTRUCTIONS):
        if not (BASE_DIR / fname).exists():
            continue
        if cat != current_cat:
            if cat_buttons:
                rows += [cat_buttons[j:j+2] for j in range(0, len(cat_buttons), 2)]
            rows.append([InlineKeyboardButton(
                text=_CATEGORY_LABELS.get(cat, cat),
                callback_data="noop",
            )])
            cat_buttons = []
            current_cat = cat
        cat_buttons.append(InlineKeyboardButton(text=name, callback_data=f"doc:{i}"))

    if cat_buttons:
        rows += [cat_buttons[j:j+2] for j in range(0, len(cat_buttons), 2)]

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _get_instruction_keyboard(chunks: list[dict]) -> InlineKeyboardMarkup:
    stems = [
        chunk["source"][4:]
        for chunk in chunks
        if chunk.get("source", "").startswith("pdf:")
        and chunk["source"][4:] in _STEM_TO_INSTRUCTION
    ]
    if not stems:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📦 Все продукты", callback_data="show_products"),
        ]])

    top_stem = Counter(stems).most_common(1)[0][0]
    idx, name, filename = _STEM_TO_INSTRUCTION[top_stem]

    if not (BASE_DIR / filename).exists():
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📦 Все продукты", callback_data="show_products"),
        ]])

    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"📄 {name}", callback_data=f"doc:{idx}"),
        InlineKeyboardButton(text="📦 Все продукты", callback_data="show_products"),
    ]])


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(WELCOME_MESSAGE, reply_markup=_build_start_keyboard())


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_MESSAGE, reply_markup=_build_back_to_products_keyboard())


@dp.message(Command("ask"))
async def cmd_ask(message: types.Message):
    await message.answer(ASK_MESSAGE)


@dp.message(Command("products"))
async def cmd_products(message: types.Message):
    await message.answer(PRODUCTS_MESSAGE, reply_markup=_build_products_keyboard())


@dp.callback_query(F.data == "show_products")
async def cb_show_products(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(PRODUCTS_MESSAGE, reply_markup=_build_products_keyboard())


@dp.callback_query(F.data == "show_help")
async def cb_show_help(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.answer(HELP_MESSAGE, reply_markup=_build_back_to_products_keyboard())


@dp.callback_query(F.data == "noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


@dp.callback_query(F.data.startswith("ask:"))
async def cb_ask_about_product(callback: types.CallbackQuery):
    """Prompt user to ask a question about a specific product."""
    try:
        idx = int(callback.data.split(":")[1])
        _, name, _fname, _cat = INSTRUCTIONS[idx]
    except (ValueError, IndexError):
        await callback.answer()
        await callback.message.answer(ASK_MESSAGE)
        return

    await callback.answer()
    await callback.message.answer(
        f"Напишите свой вопрос о продукте «{name}» — я отвечу 🐝"
    )


def _should_respond(message: types.Message) -> bool:
    if message.chat.type == ChatType.PRIVATE:
        return True
    text = message.text or ""
    if f"@{BOT_USERNAME}" in text:
        return True
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == bot.id:
            return True
    return False


@dp.message(F.voice)
async def handle_voice(message: types.Message):
    """Respond to voice messages with a text prompt."""
    if not _should_respond(message):
        return
    await message.reply(VOICE_MESSAGE)


@dp.message()
async def handle_question(message: types.Message):
    """Handle user questions: search KB → generate response via Groq."""
    if message.text and message.text.startswith("/"):
        return

    if not _should_respond(message):
        return

    query = (message.text or "").replace(f"@{BOT_USERNAME}", "").strip()
    if len(query) < 3:
        await message.reply("Напиши вопрос подлиннее, чтобы я мог помочь.")
        return

    query_lower = query.lower()
    if any(trigger in query_lower for trigger in _PRODUCTS_TRIGGERS):
        await message.reply(PRODUCTS_MESSAGE, reply_markup=_build_products_keyboard())
        return

    logger.info(f"Question from {message.from_user.id} in {message.chat.type}: {query}")
    await bot.send_chat_action(message.chat.id, "typing")

    try:
        chunks = kb.search(query)
        logger.info(f"Found {len(chunks)} relevant chunks")
        response = llm.generate(query, chunks)
        keyboard = _get_instruction_keyboard(chunks)
        await message.reply(response, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error handling question: {e}")
        await message.reply(
            "Извини, что-то пошло не так. Попробуй спросить ещё раз чуть позже."
        )


@dp.callback_query(F.data.startswith("doc:"))
async def send_instruction_pdf(callback: types.CallbackQuery):
    """Send the instruction PDF when user taps the button."""
    try:
        idx = int(callback.data.split(":")[1])
        _, name, filename, _cat = INSTRUCTIONS[idx]
    except (ValueError, IndexError):
        await callback.answer("Инструкция не найдена.", show_alert=True)
        return

    pdf_path = BASE_DIR / filename
    if not pdf_path.exists():
        await callback.answer("Файл не найден на сервере.", show_alert=True)
        return

    await callback.answer()
    await callback.message.answer_document(
        document=FSInputFile(str(pdf_path), filename=filename),
        caption=f"📄 {name}",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"❓ Задать вопрос о {name}", callback_data=f"ask:{idx}"),
        ], [
            InlineKeyboardButton(text="📦 Все продукты", callback_data="show_products"),
        ]]),
    )


async def main():
    logger.info("Starting BEEBOT...")
    try:
        kb.load()
        logger.info(f"Knowledge base loaded: {len(kb.chunks)} chunks")
    except FileNotFoundError:
        logger.error("Knowledge base not found! Run `python -m src.build_kb` first.")
        return

    logger.info("Bot is running!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
