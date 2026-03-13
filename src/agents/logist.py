"""Агент «Логист» — диалог оформления заказа (FSM).

Ведёт пошаговый диалог с клиентом для оформления заказа:
  1. Выбор товаров — каталог из Integram с ценами и наличием
  2. ФИО        — предзаполнение для постоянных клиентов
  3. Телефон
  4. Адрес      — предложить последний известный адрес
  5. Доставка   — СДЭК / Почта России / Самовывоз + расчёт стоимости
  6. Подтверждение — карточка-резюме заказа (подтвердить / изменить / отменить)
  7. Создание   — создать заказ в Integram + уведомить пчеловода

Таймаут диалога: 15 минут.
Команда /cancel: прерывает диалог на любом шаге.
"""

from __future__ import annotations

import logging
from typing import Optional

from aiogram.fsm.state import State, StatesGroup

from src.crm_schema import DELIVERY_METHODS
from src.models import Client, Product

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Таймаут диалога
# ---------------------------------------------------------------------------

ORDER_TIMEOUT_SECONDS = 15 * 60  # 15 минут

# ---------------------------------------------------------------------------
# FSM: состояния диалога оформления заказа
# ---------------------------------------------------------------------------


class OrderFSM(StatesGroup):
    """7 состояний диалога оформления заказа."""
    choosing_product = State()    # 1. Выбор товара из каталога
    entering_name = State()       # 2. Ввод ФИО
    entering_phone = State()      # 3. Ввод номера телефона
    entering_address = State()    # 4. Ввод адреса доставки
    choosing_delivery = State()   # 5. Выбор способа доставки
    confirming_order = State()    # 6. Подтверждение заказа
    creating_order = State()      # 7. Создание заказа (финальный шаг)


# ---------------------------------------------------------------------------
# Вспомогательные форматтеры
# ---------------------------------------------------------------------------


def format_product_catalog(products: list[Product]) -> str:
    """Форматировать каталог товаров для отображения."""
    if not products:
        return "Каталог товаров временно недоступен."

    lines = ["📦 *Каталог товаров:*\n"]
    for i, p in enumerate(products, start=1):
        price_str = f"{p.price:.0f} ₽" if p.price else "цена по запросу"
        weight_str = f" · {p.weight} г" if p.weight else ""
        lines.append(f"{i}. {p.name}{weight_str} — {price_str}")

    lines.append("\nНапишите *номер* товара или несколько через запятую (напр: 1,3).")
    lines.append("Или /cancel для отмены.")
    return "\n".join(lines)


def format_order_summary(
    cart: list[dict],
    full_name: str,
    phone: str,
    address: str,
    delivery: str,
    delivery_cost: float,
) -> str:
    """Форматировать карточку-резюме заказа перед подтверждением."""
    items_total = sum(item["qty"] * item["unit_price"] for item in cart)
    total = items_total + delivery_cost

    lines = ["📋 *Ваш заказ:*\n"]
    lines.append("*Товары:*")
    for item in cart:
        price = item["qty"] * item["unit_price"]
        lines.append(f"  • {item['name']} × {item['qty']} = {price:.0f} ₽")

    lines.append(f"\n👤 ФИО: {full_name}")
    lines.append(f"📞 Телефон: {phone}")
    lines.append(f"🏠 Адрес: {address}")
    lines.append(f"🚚 Доставка: {delivery} — {delivery_cost:.0f} ₽")
    lines.append(f"\n💰 Сумма товаров: {items_total:.0f} ₽")
    lines.append(f"💰 *Итого: {total:.0f} ₽*")
    lines.append("\nОтправьте *да* для подтверждения, *нет* — для отмены.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Расчёт стоимости доставки
# ---------------------------------------------------------------------------


async def calculate_delivery_cost(
    delivery_method: str,
    address: str,
    cart: list[dict],
) -> float:
    """Рассчитать стоимость доставки.

    Реальные API СДЭК и Почты России не интегрированы — используются
    фиксированные тарифы. В будущем заменить на CDEKProvider / PochtaProvider.
    """
    # Расчёт суммарного веса (в граммах, конвертируем в кг)
    total_weight_g = sum(
        item.get("weight", 500) * item["qty"] for item in cart
    )
    weight_kg = max(total_weight_g / 1000, 0.1)

    if delivery_method == "Самовывоз":
        return 0.0
    elif delivery_method == "СДЭК":
        # Базовый тариф СДЭК: 350 ₽ + 50 ₽/кг
        return round(350 + 50 * weight_kg, 0)
    elif delivery_method == "Почта России":
        # Базовый тариф Почты России: 250 ₽ + 30 ₽/кг
        return round(250 + 30 * weight_kg, 0)
    else:
        return 0.0


# ---------------------------------------------------------------------------
# Главный класс агента
# ---------------------------------------------------------------------------


class LogistAgent:
    """Агент для ведения диалога оформления заказа.

    Управляет FSM-переходами и бизнес-логикой. Хэндлеры Telegram
    регистрируются отдельно в src/bot.py и вызывают методы этого класса.
    """

    def __init__(self, integram_client=None, beekeeper_chat_id: Optional[int] = None):
        """
        Args:
            integram_client: IntegramClient или None (бот работает без CRM).
            beekeeper_chat_id: Telegram ID пчеловода для уведомлений.
        """
        self._crm = integram_client
        self._beekeeper_chat_id = beekeeper_chat_id

    # ------------------------------------------------------------------
    # Шаг 1: Старт диалога — показать каталог
    # ------------------------------------------------------------------

    async def start_order(self, user_id: int) -> tuple[str, list[Product]]:
        """Начать диалог оформления заказа.

        Returns:
            (сообщение для пользователя, список товаров).
            Устанавливает состояние choosing_product снаружи (в хэндлере).
        """
        products: list[Product] = []
        if self._crm:
            try:
                products = await self._crm.get_products(in_stock_only=True)
            except Exception as e:
                logger.error("Не удалось загрузить каталог: %s", e)

        if not products:
            # Статичный каталог как fallback
            from src.crm_schema import INITIAL_PRODUCTS
            products = [
                Product(
                    id=i + 1,
                    **{
                        "Название": p.name,
                        "Категория": p.category,
                        "Цена": None,
                        "Вес": None,
                        "Описание": p.description,
                        "В наличии": p.in_stock,
                        "Артикул UDS": p.sku_uds or None,
                    },
                )
                for i, p in enumerate(INITIAL_PRODUCTS)
            ]

        text = format_product_catalog(products)
        return text, products

    # ------------------------------------------------------------------
    # Шаг 1→2: Обработка выбора товаров
    # ------------------------------------------------------------------

    def parse_product_selection(
        self,
        user_input: str,
        products: list[dict],
    ) -> tuple[list[dict], str]:
        """Разобрать ввод пользователя с выбором товаров.

        Args:
            user_input: строка от пользователя (например "1,3" или "2")
            products: список товаров из каталога (dicts с id/name/price/weight)

        Returns:
            (cart, error_msg) — если error_msg не пустой, ввод некорректен.
        """
        cart = []
        errors = []

        parts = [p.strip() for p in user_input.replace("；", ",").split(",")]
        for part in parts:
            if not part:
                continue
            # Поддержка формата "2x3" или просто "2"
            qty = 1
            idx_str = part
            if "x" in part.lower():
                pieces = part.lower().split("x", 1)
                idx_str, qty_str = pieces[0].strip(), pieces[1].strip()
                try:
                    qty = int(qty_str)
                except ValueError:
                    qty = 1

            try:
                idx = int(idx_str) - 1  # пользователь видит нумерацию с 1
            except ValueError:
                errors.append(f"«{part}» — не число")
                continue

            if idx < 0 or idx >= len(products):
                errors.append(f"Товар №{idx + 1} не найден в каталоге")
                continue

            product = products[idx]
            existing = next((c for c in cart if c["product_id"] == product["id"]), None)
            if existing:
                existing["qty"] += qty
            else:
                cart.append({
                    "product_id": product["id"],
                    "name": product["name"],
                    "qty": qty,
                    "unit_price": product.get("price") or 0.0,
                    "weight": product.get("weight") or 500,
                })

        if errors:
            return [], "Не понял выбор: " + "; ".join(errors) + ".\nПопробуйте ещё раз."
        if not cart:
            return [], "Выберите хотя бы один товар."
        return cart, ""

    # ------------------------------------------------------------------
    # Шаг 2: Загрузить данные существующего клиента (для предзаполнения)
    # ------------------------------------------------------------------

    async def get_existing_client(self, telegram_id: int) -> Optional[Client]:
        """Найти клиента по Telegram ID (для предзаполнения ФИО/адреса)."""
        if not self._crm:
            return None
        try:
            return await self._crm.get_or_create_client(telegram_id)
        except Exception as e:
            logger.warning("Не удалось найти клиента %d: %s", telegram_id, e)
            return None

    # ------------------------------------------------------------------
    # Шаг 5: Расчёт стоимости доставки
    # ------------------------------------------------------------------

    async def get_delivery_options(self, cart: list[dict]) -> list[dict]:
        """Получить список способов доставки с расчётом стоимости.

        Returns:
            Список dict: {method, cost, label}
        """
        options = []
        for method in DELIVERY_METHODS:
            cost = await calculate_delivery_cost(method, "", cart)
            if method == "Самовывоз":
                label = "🏪 Самовывоз — бесплатно"
            else:
                label = f"🚚 {method} — {cost:.0f} ₽"
            options.append({"method": method, "cost": cost, "label": label})
        return options

    # ------------------------------------------------------------------
    # Шаг 7: Создание заказа в Integram + уведомление пчеловода
    # ------------------------------------------------------------------

    async def create_order(
        self,
        telegram_id: int,
        full_name: str,
        phone: str,
        address: str,
        delivery: str,
        delivery_cost: float,
        cart: list[dict],
        telegram_username: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Создать заказ в Integram CRM и уведомить пчеловода.

        Returns:
            (success, message) — сообщение для пользователя.
        """
        if not self._crm:
            # Нет CRM — вернуть подтверждение с данными заказа
            logger.info(
                "CRM недоступна. Заказ для %s: %s, %s, %s",
                full_name, phone, address, delivery,
            )
            return True, self._format_no_crm_confirmation(
                full_name, phone, address, delivery, delivery_cost, cart
            )

        try:
            # Получить или создать клиента
            client = await self._crm.get_or_create_client(
                telegram_id,
                full_name=full_name,
                phone=phone,
                address=address,
                telegram_username=telegram_username,
            )
            # Обновить данные клиента (адрес мог измениться)
            await self._crm.update_client(
                client.id,
                full_name=full_name,
                phone=phone,
                address=address,
            )

            # Рассчитать итоговые суммы
            items_total = sum(i["qty"] * i["unit_price"] for i in cart)
            total = items_total + delivery_cost

            order = await self._crm.create_order(
                client_id=client.id,
                items=[
                    {
                        "product_id": item["product_id"],
                        "quantity": item["qty"],
                        "unit_price": item["unit_price"],
                    }
                    for item in cart
                ],
                delivery_method=delivery,
                delivery_address=address,
                delivery_cost=delivery_cost,
                items_total=items_total,
                total=total,
                source="Telegram",
            )

            logger.info("Создан заказ #%s для клиента %s", order.number, full_name)
            return True, (
                f"✅ Заказ *#{order.number}* оформлен!\n\n"
                f"Александр свяжется с вами для подтверждения.\n"
                f"Ваш адрес: {address}\n"
                f"Доставка: {delivery}"
            )

        except Exception as e:
            logger.error("Ошибка создания заказа: %s", e)
            return False, (
                "Не удалось оформить заказ автоматически. "
                "Пожалуйста, напишите Александру напрямую — он поможет!"
            )

    @staticmethod
    def _format_no_crm_confirmation(
        full_name: str,
        phone: str,
        address: str,
        delivery: str,
        delivery_cost: float,
        cart: list[dict],
    ) -> str:
        """Сообщение об успехе когда CRM недоступна."""
        items_total = sum(i["qty"] * i["unit_price"] for i in cart)
        total = items_total + delivery_cost
        items_str = "\n".join(
            f"  • {i['name']} × {i['qty']}" for i in cart
        )
        return (
            f"✅ Заявка принята!\n\n"
            f"*Товары:*\n{items_str}\n\n"
            f"👤 {full_name}\n"
            f"📞 {phone}\n"
            f"🏠 {address}\n"
            f"🚚 {delivery} — {delivery_cost:.0f} ₽\n"
            f"💰 Итого: {total:.0f} ₽\n\n"
            f"Александр свяжется с вами для подтверждения!"
        )

    # ------------------------------------------------------------------
    # Уведомление пчеловода
    # ------------------------------------------------------------------

    async def notify_beekeeper(self, bot, order_summary: str) -> None:
        """Отправить пчеловоду уведомление о новом заказе."""
        if not self._beekeeper_chat_id:
            logger.info("BEEKEEPER_CHAT_ID не задан — уведомление пропущено.")
            return
        try:
            await bot.send_message(
                self._beekeeper_chat_id,
                f"🍯 *Новый заказ!*\n\n{order_summary}",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Не удалось уведомить пчеловода: %s", e)

    # ------------------------------------------------------------------
    # Совместимость со старым интерфейсом оркестратора
    # ------------------------------------------------------------------

    async def collect_shipping_info(self, chat_id: int) -> dict:
        """Устаревший метод — FSM управляется через хэндлеры в bot.py."""
        raise NotImplementedError(
            "LogistAgent использует FSM через aiogram. "
            "Используйте OrderFSM и хэндлеры в src/bot.py."
        )
