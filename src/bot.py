"""Telegram bot for BEEBOT — AI assistant for a beekeeper blog."""

import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart, Command
from aiogram.enums import ParseMode

from src.config import TELEGRAM_BOT_TOKEN
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

1. Напиши вопрос о продуктах пчеловодства
2. Бот найдёт информацию в базе знаний
3. Ответ будет в стиле Александра Дмитрова

Примеры вопросов:
- Как принимать настойку прополиса?
- Чем полезна перга?
- Как укрепить иммунитет ребёнка?

/start — начать
/help — эта справка"""


@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    await message.answer(WELCOME_MESSAGE)


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(HELP_MESSAGE)


@dp.message()
async def handle_question(message: types.Message):
    """Handle user questions: search KB → generate response via Groq."""
    query = message.text
    if not query or len(query.strip()) < 3:
        await message.answer("Напиши вопрос подлиннее, чтобы я мог помочь.")
        return

    logger.info(f"Question from {message.from_user.id}: {query}")

    # Show typing indicator
    await bot.send_chat_action(message.chat.id, "typing")

    try:
        # Search knowledge base
        chunks = kb.search(query)
        logger.info(f"Found {len(chunks)} relevant chunks")

        # Generate response
        response = llm.generate(query, chunks)
        await message.answer(response)

    except Exception as e:
        logger.error(f"Error handling question: {e}")
        await message.answer(
            "Извини, что-то пошло не так. Попробуй спросить ещё раз чуть позже."
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
