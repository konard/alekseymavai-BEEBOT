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

# Initialize knowledge base and LLM client
kb = KnowledgeBase()
llm = LLMClient()

WELCOME_MESSAGE = """Привет! Я бот-помощник Александра Дмитрова — пчеловода и автора блога о продуктах пчеловодства.

Задай мне любой вопрос о:
- Продуктах пчеловодства (мёд, перга, прополис, пыльца)
- Рецептах и дозировках
- Пчеловодстве и здоровье

Просто напиши свой вопрос!"""

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
/help — эта справка
/products — список продуктов с инструкциями"""

PRODUCTS_MESSAGE = "Вот все продукты, по которым есть инструкции — нажми на любой, чтобы получить PDF:"

# Keywords that trigger the /products list
_PRODUCTS_TRIGGERS = {
    "какие продукты", "список продуктов", "что есть", "что у тебя есть",
    "какие настойки", "какие товары", "что продаёшь", "что продаешь",
    "ассортимент", "что можно купить", "какие препараты",
}

BOT_USERNAME = "AleksandrDmitrov_BEEBOT"

# (kb_source_stem, display_name, pdf_filename)
# Index in this list is used as callback_data to stay within 64-byte limit
INSTRUCTIONS = [
    ("«УНИВЕРСАЛЬНАЯ_ПРОГРАММА_ОЗДОРОВЛЕНИЯ»", "Универсальная программа оздоровления",  "«УНИВЕРСАЛЬНАЯ_ПРОГРАММА_ОЗДОРОВЛЕНИЯ».pdf"),
    ("Антивирус",                               "Настойка Антивирус",                    "Антивирус.pdf"),
    ("Иммунитет ребенка",                       "Иммунитет ребёнка",                     "Иммунитет ребенка.pdf"),
    ("Инструкция ТГ",                           "Инструкция ТГ",                         "Инструкция ТГ.pdf"),
    ("Настойка «Успокоин» (Травяная)",          "Успокоин (травяная настойка)",          "Настойка «Успокоин» (Травяная).pdf"),
    ("Настойка ПЖВМ",                           "Настойка ПЖВМ (огнёвка)",               "Настойка ПЖВМ.pdf"),
    ("Настойка Подмора пчелиного (на самогоне 40°)", "Настойка подмора пчелиного",       "Настойка Подмора пчелиного (на самогоне 40°).pdf"),
    ("Перга",                                   "Перга (пчелиный хлеб)",                 "Перга.pdf"),
    ("Приложение к УПО (1)",                    "Приложение к УПО",                      "Приложение к УПО (1).pdf"),
    ("Прополис_ сухой + настойка",              "Прополис (сухой + настойка)",           "Прополис_ сухой + настойка.pdf"),
    ("Пчелиная обножка",                        "Пчелиная обножка (цветочная пыльца)",   "Пчелиная обножка.pdf"),
    ("Трутнёвый гомогенат",                     "Трутнёвый гомогенат",                   "Трутнёвый гомогенат.pdf"),
    ("ФитоЭнергия",                             "Настойка ФитоЭнергия",                  "ФитоЭнергия.pdf"),
]

# Lookup: stem → (index, display_name, filename)
_STEM_TO_INSTRUCTION = {
    stem: (i, name, fname)
    for i, (stem, name, fname) in enumerate(INSTRUCTIONS)
}


def _build_products_keyboard() -> InlineKeyboardMarkup:
    """Build a keyboard with all available instruction PDFs (2 buttons per row)."""
    buttons = [
        InlineKeyboardButton(text=f"📄 {name}", callback_data=f"doc:{i}")
        for i, (stem, name, fname) in enumerate(INSTRUCTIONS)
        if (BASE_DIR / fname).exists()
    ]
    # 2 per row
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _get_instruction_keyboard(chunks: list[dict]) -> InlineKeyboardMarkup | None:
    """Find the most relevant instruction PDF and return an inline keyboard button."""
    stems = [
        chunk["source"][4:]  # strip "pdf:" prefix
        for chunk in chunks
        if chunk.get("source", "").startswith("pdf:")
        and chunk["source"][4:] in _STEM_TO_INSTRUCTION
    ]
    if not stems:
        return None

    top_stem = Counter(stems).most_common(1)[0][0]
    idx, name, filename = _STEM_TO_INSTRUCTION[top_stem]

    if not (BASE_DIR / filename).exists():
        return None

    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"📄 Инструкция: {name}", callback_data=f"doc:{idx}")
    ]])


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(WELCOME_MESSAGE)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_MESSAGE)


@dp.message(Command("products"))
async def cmd_products(message: types.Message):
    await message.answer(PRODUCTS_MESSAGE, reply_markup=_build_products_keyboard())


def _should_respond(message: types.Message) -> bool:
    """Check if bot should respond to this message."""
    # Always respond in private chats
    if message.chat.type == ChatType.PRIVATE:
        return True

    # In groups: respond if mentioned or replied to
    text = message.text or ""
    if f"@{BOT_USERNAME}" in text:
        return True
    if message.reply_to_message and message.reply_to_message.from_user:
        if message.reply_to_message.from_user.id == bot.id:
            return True

    return False


@dp.message()
async def handle_question(message: types.Message):
    """Handle user questions: search KB → generate response via Groq."""
    if not _should_respond(message):
        return

    query = (message.text or "").replace(f"@{BOT_USERNAME}", "").strip()
    if len(query) < 3:
        await message.reply("Напиши вопрос подлиннее, чтобы я мог помочь.")
        return

    # Detect "what products do you have" type queries
    query_lower = query.lower()
    if any(trigger in query_lower for trigger in _PRODUCTS_TRIGGERS):
        await message.reply(PRODUCTS_MESSAGE, reply_markup=_build_products_keyboard())
        return

    logger.info(f"Question from {message.from_user.id} in {message.chat.type}: {query}")

    # Show typing indicator
    await bot.send_chat_action(message.chat.id, "typing")

    try:
        # Search knowledge base
        chunks = kb.search(query)
        logger.info(f"Found {len(chunks)} relevant chunks")

        # Generate response
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
        _, name, filename = INSTRUCTIONS[idx]
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
    )


async def main():
    logger.info("Starting BEEBOT...")

    # Load knowledge base
    try:
        kb.load()
        logger.info(f"Knowledge base loaded: {len(kb.chunks)} chunks")
    except FileNotFoundError:
        logger.error("Knowledge base not found! Run `python -m src.build_kb` first.")
        return

    # Start polling
    logger.info("Bot is running!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
