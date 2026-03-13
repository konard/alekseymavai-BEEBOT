"""Telegram bot for BEEBOT — AI assistant for a beekeeper blog."""

import asyncio
import logging
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.enums import ChatType
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
)

from src.config import TELEGRAM_BOT_TOKEN, BASE_DIR, PDFS_DIR, BEEKEEPER_CHAT_ID
from src.agents.beebot import (
    INSTRUCTIONS,
    CATEGORY_LABELS as _CATEGORY_LABELS,
    is_products_query,
    get_top_instruction,
)
from src.agents.logist import (
    LogistAgent,
    OrderFSM,
    ORDER_TIMEOUT_SECONDS,
    format_order_summary,
)
from src.orchestrator import Orchestrator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

orchestrator = Orchestrator()
logist = LogistAgent(beekeeper_chat_id=BEEKEEPER_CHAT_ID)

# Хранилище задач таймаута (user_id → asyncio.Task)
_timeout_tasks: dict[int, asyncio.Task] = {}

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

BOT_USERNAME = "AleksandrDmitrov_BEEBOT"


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
        if not (PDFS_DIR / fname).exists():
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
    result = get_top_instruction(chunks)
    if result is None:
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📦 Все продукты", callback_data="show_products"),
        ]])

    idx, name, filename = result
    if not (PDFS_DIR / filename).exists():
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


@dp.message(StateFilter(None))
async def handle_question(message: types.Message, state: FSMContext):
    """Handle user questions: search KB → generate response via Groq."""
    if message.text and message.text.startswith("/"):
        return

    if not _should_respond(message):
        return

    query = (message.text or "").replace(f"@{BOT_USERNAME}", "").strip()
    if len(query) < 3:
        await message.reply("Напиши вопрос подлиннее, чтобы я мог помочь.")
        return

    if is_products_query(query):
        await message.reply(PRODUCTS_MESSAGE, reply_markup=_build_products_keyboard())
        return

    logger.info(f"Question from {message.from_user.id} in {message.chat.type}: {query}")
    await bot.send_chat_action(message.chat.id, "typing")

    try:
        response, chunks = await orchestrator.route(message.from_user.id, query)
        logger.info(f"Found {len(chunks)} relevant chunks")

        # Если оркестратор определил intent «order» или «delivery» — запустить FSM
        intent = orchestrator.get_intent(message.from_user.id)
        if intent in ("order", "delivery"):
            await cmd_order(message, state)
            return

        keyboard = _get_instruction_keyboard(chunks)
        await message.reply(response, reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error handling question: {e}")
        await message.reply(
            "Извини, что-то пошло не так. Попробуй спросить ещё раз чуть позже."
        )


# ===========================================================================
# Helpers: таймаут диалога заказа
# ===========================================================================


def _cancel_timeout(user_id: int) -> None:
    """Отменить задачу таймаута для пользователя."""
    task = _timeout_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()


async def _timeout_dialog(user_id: int, chat_id: int, state: FSMContext) -> None:
    """Завершить диалог заказа по таймауту."""
    await asyncio.sleep(ORDER_TIMEOUT_SECONDS)
    current = await state.get_state()
    if current is not None:
        await state.clear()
        _timeout_tasks.pop(user_id, None)
        try:
            await bot.send_message(
                chat_id,
                "⏰ Диалог оформления заказа завершён по таймауту (15 минут).\n"
                "Напишите /order чтобы начать заново.",
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception as e:
            logger.warning("Не удалось отправить сообщение о таймауте: %s", e)


def _reset_timeout(user_id: int, chat_id: int, state: FSMContext) -> None:
    """Сбросить таймаут — отменить старый и запустить новый."""
    _cancel_timeout(user_id)
    task = asyncio.create_task(_timeout_dialog(user_id, chat_id, state))
    _timeout_tasks[user_id] = task


# ===========================================================================
# Вспомогательные клавиатуры для FSM-диалога
# ===========================================================================


def _delivery_keyboard(options: list[dict]) -> ReplyKeyboardMarkup:
    """Клавиатура с вариантами доставки."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=opt["label"])] for opt in options],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def _confirm_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да, подтвердить")],
            [KeyboardButton(text="❌ Нет, отменить")],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ===========================================================================
# /order — начало диалога оформления заказа
# ===========================================================================


@dp.message(Command("order"))
async def cmd_order(message: types.Message, state: FSMContext) -> None:
    """Начать диалог оформления заказа."""
    user_id = message.from_user.id
    chat_id = message.chat.id

    # Показать каталог
    catalog_text, products = await logist.start_order(user_id)

    # Сохранить каталог в FSM-контекст
    products_data = [
        {
            "id": p.id,
            "name": p.name,
            "price": p.price,
            "weight": p.weight,
        }
        for p in products
    ]
    await state.update_data(products=products_data, cart=[])
    await state.set_state(OrderFSM.choosing_product)

    _reset_timeout(user_id, chat_id, state)
    await message.answer(catalog_text, parse_mode="Markdown")


# ===========================================================================
# /cancel — отмена диалога на любом шаге
# ===========================================================================


@dp.message(Command("cancel"), StateFilter(OrderFSM))
async def cmd_cancel_order(message: types.Message, state: FSMContext) -> None:
    """Отменить диалог оформления заказа."""
    _cancel_timeout(message.from_user.id)
    await state.clear()
    await message.answer(
        "Заказ отменён. Напишите /order чтобы начать заново.",
        reply_markup=ReplyKeyboardRemove(),
    )


# ===========================================================================
# Шаг 1: Выбор товаров
# ===========================================================================


@dp.message(OrderFSM.choosing_product)
async def fsm_choose_product(message: types.Message, state: FSMContext) -> None:
    """Обработать выбор товаров из каталога."""
    user_id = message.from_user.id
    data = await state.get_data()
    products = data.get("products", [])

    cart, error = logist.parse_product_selection(message.text or "", products)
    if error:
        await message.answer(error)
        return

    # Загрузить данные постоянного клиента
    existing_client = await logist.get_existing_client(user_id)

    await state.update_data(cart=cart)

    prefill = ""
    if existing_client and existing_client.full_name:
        prefill = f"\nПодсказка: в прошлый раз вы представились как *{existing_client.full_name}*.\nПросто отправьте его или введите другое."
        await state.update_data(prefill_name=existing_client.full_name)

    await state.set_state(OrderFSM.entering_name)
    _reset_timeout(user_id, message.chat.id, state)
    await message.answer(
        f"Отлично! Введите ваше *ФИО* (Фамилия Имя Отчество).{prefill}",
        parse_mode="Markdown",
    )


# ===========================================================================
# Шаг 2: Ввод ФИО
# ===========================================================================


@dp.message(OrderFSM.entering_name)
async def fsm_enter_name(message: types.Message, state: FSMContext) -> None:
    """Обработать ввод ФИО."""
    name = (message.text or "").strip()
    if len(name) < 3:
        await message.answer("Пожалуйста, введите полное ФИО (минимум 3 символа).")
        return

    data = await state.get_data()
    # Если пользователь нажал «Enter» без текста — использовать предзаполненное
    if name.lower() in ("да", "+", "ok", "ок") and data.get("prefill_name"):
        name = data["prefill_name"]

    await state.update_data(full_name=name)
    await state.set_state(OrderFSM.entering_phone)
    _reset_timeout(message.from_user.id, message.chat.id, state)
    await message.answer("📞 Введите ваш *номер телефона*:", parse_mode="Markdown")


# ===========================================================================
# Шаг 3: Ввод телефона
# ===========================================================================


@dp.message(OrderFSM.entering_phone)
async def fsm_enter_phone(message: types.Message, state: FSMContext) -> None:
    """Обработать ввод номера телефона."""
    phone = (message.text or "").strip()
    # Простая валидация: минимум 7 цифр
    digits = "".join(c for c in phone if c.isdigit())
    if len(digits) < 7:
        await message.answer("Введите корректный номер телефона (минимум 7 цифр).")
        return

    data = await state.get_data()
    existing_client = None
    if data.get("prefill_address") is None:
        existing_client = await logist.get_existing_client(message.from_user.id)

    await state.update_data(phone=phone)

    prefill = ""
    if existing_client and existing_client.address:
        prefill = (
            f"\nПодсказка: ваш прошлый адрес — *{existing_client.address}*.\n"
            "Отправьте его или введите новый."
        )
        await state.update_data(prefill_address=existing_client.address)

    await state.set_state(OrderFSM.entering_address)
    _reset_timeout(message.from_user.id, message.chat.id, state)
    await message.answer(
        f"🏠 Введите *адрес доставки* (город, улица, дом, квартира).{prefill}",
        parse_mode="Markdown",
    )


# ===========================================================================
# Шаг 4: Ввод адреса
# ===========================================================================


@dp.message(OrderFSM.entering_address)
async def fsm_enter_address(message: types.Message, state: FSMContext) -> None:
    """Обработать ввод адреса доставки."""
    address = (message.text or "").strip()
    if len(address) < 5:
        await message.answer("Введите полный адрес (минимум 5 символов).")
        return

    data = await state.get_data()
    # Если ввели подтверждение — использовать предзаполненный адрес
    if address.lower() in ("да", "+", "ok", "ок") and data.get("prefill_address"):
        address = data["prefill_address"]

    cart = data.get("cart", [])
    options = await logist.get_delivery_options(cart)

    await state.update_data(address=address, delivery_options=options)
    await state.set_state(OrderFSM.choosing_delivery)
    _reset_timeout(message.from_user.id, message.chat.id, state)

    keyboard = _delivery_keyboard(options)
    options_text = "\n".join(f"  {opt['label']}" for opt in options)
    await message.answer(
        f"🚚 Выберите *способ доставки*:\n\n{options_text}",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


# ===========================================================================
# Шаг 5: Выбор способа доставки
# ===========================================================================


@dp.message(OrderFSM.choosing_delivery)
async def fsm_choose_delivery(message: types.Message, state: FSMContext) -> None:
    """Обработать выбор способа доставки."""
    user_input = (message.text or "").strip()
    data = await state.get_data()
    options = data.get("delivery_options", [])

    # Сопоставить ввод пользователя с вариантами
    chosen = None
    chosen_cost = 0.0
    for opt in options:
        if opt["method"].lower() in user_input.lower() or opt["label"] in user_input:
            chosen = opt["method"]
            chosen_cost = opt["cost"]
            break

    if not chosen:
        labels = "\n".join(f"  • {opt['label']}" for opt in options)
        await message.answer(
            f"Пожалуйста, выберите один из вариантов:\n{labels}",
            reply_markup=_delivery_keyboard(options),
        )
        return

    cart = data.get("cart", [])
    full_name = data.get("full_name", "")
    phone = data.get("phone", "")
    address = data.get("address", "")

    summary = format_order_summary(
        cart=cart,
        full_name=full_name,
        phone=phone,
        address=address,
        delivery=chosen,
        delivery_cost=chosen_cost,
    )

    await state.update_data(delivery=chosen, delivery_cost=chosen_cost)
    await state.set_state(OrderFSM.confirming_order)
    _reset_timeout(message.from_user.id, message.chat.id, state)

    await message.answer(
        summary,
        parse_mode="Markdown",
        reply_markup=_confirm_keyboard(),
    )


# ===========================================================================
# Шаг 6: Подтверждение заказа
# ===========================================================================


@dp.message(OrderFSM.confirming_order)
async def fsm_confirm_order(message: types.Message, state: FSMContext) -> None:
    """Обработать подтверждение или отмену заказа."""
    answer = (message.text or "").strip().lower()

    if answer in ("да", "✅ да, подтвердить", "yes", "подтвердить", "+"):
        await state.set_state(OrderFSM.creating_order)
        await _do_create_order(message, state)
    elif answer in ("нет", "❌ нет, отменить", "no", "отменить", "-"):
        _cancel_timeout(message.from_user.id)
        await state.clear()
        await message.answer(
            "Заказ отменён. Напишите /order чтобы начать заново.",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await message.answer(
            "Пожалуйста, отправьте *да* для подтверждения или *нет* для отмены.",
            parse_mode="Markdown",
            reply_markup=_confirm_keyboard(),
        )


# ===========================================================================
# Шаг 7: Создание заказа
# ===========================================================================


async def _do_create_order(message: types.Message, state: FSMContext) -> None:
    """Создать заказ в Integram и уведомить пчеловода."""
    _cancel_timeout(message.from_user.id)
    data = await state.get_data()
    await state.clear()

    await bot.send_chat_action(message.chat.id, "typing")

    success, response_text = await logist.create_order(
        telegram_id=message.from_user.id,
        full_name=data.get("full_name", ""),
        phone=data.get("phone", ""),
        address=data.get("address", ""),
        delivery=data.get("delivery", ""),
        delivery_cost=data.get("delivery_cost", 0.0),
        cart=data.get("cart", []),
        telegram_username=message.from_user.username,
    )

    await message.answer(
        response_text,
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )

    if success:
        # Уведомить пчеловода
        cart = data.get("cart", [])
        delivery_cost = data.get("delivery_cost", 0.0)
        items_total = sum(i["qty"] * i["unit_price"] for i in cart)
        total = items_total + delivery_cost
        items_str = "\n".join(f"  • {i['name']} × {i['qty']}" for i in cart)
        beekeeper_msg = (
            f"👤 {data.get('full_name', '')}\n"
            f"📞 {data.get('phone', '')}\n"
            f"🏠 {data.get('address', '')}\n"
            f"🚚 {data.get('delivery', '')} — {delivery_cost:.0f} ₽\n\n"
            f"*Товары:*\n{items_str}\n\n"
            f"💰 Итого: {total:.0f} ₽"
        )
        await logist.notify_beekeeper(bot, beekeeper_msg)


@dp.callback_query(F.data.startswith("doc:"))
async def send_instruction_pdf(callback: types.CallbackQuery):
    """Send the instruction PDF when user taps the button."""
    try:
        idx = int(callback.data.split(":")[1])
        _, name, filename, _cat = INSTRUCTIONS[idx]
    except (ValueError, IndexError):
        await callback.answer("Инструкция не найдена.", show_alert=True)
        return

    pdf_path = PDFS_DIR / filename
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
        orchestrator.load_kb()
        logger.info(f"Knowledge base loaded: {len(orchestrator._beebot.kb.chunks)} chunks")
    except FileNotFoundError:
        logger.error("Knowledge base not found! Run `python -m src.build_kb` first.")
        return

    logger.info("Bot is running!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
