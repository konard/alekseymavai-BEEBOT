"""Модуль уведомлений BEEBOT.

Отправляет Telegram-уведомления пчеловоду (BEEKEEPER_CHAT_ID) и,
при наличии Telegram ID клиента, самому клиенту.

Основные события:
  - новый заказ (с кнопками «Подтвердить» / «Отклонить»)
  - заказ подтверждён
  - заказ отправлен с трек-номером
  - новый заказ из UDS

Использование:
    from src.notifications import Notifier
    notifier = Notifier(bot)
    await notifier.new_order(order_id=42, client_name="Иван И.", total=2500, delivery="СДЭК")
"""

from __future__ import annotations

import logging
from typing import Optional

from aiogram import Bot
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from src.config import BEEKEEPER_CHAT_ID

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Вспомогательные функции для построения клавиатур
# ---------------------------------------------------------------------------


def _order_action_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Клавиатура «Подтвердить» / «Отклонить» для нового заказа."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="✅ Подтвердить",
            callback_data=f"order_confirm:{order_id}",
        ),
        InlineKeyboardButton(
            text="❌ Отклонить",
            callback_data=f"order_reject:{order_id}",
        ),
    ]])


# ---------------------------------------------------------------------------
# Главный класс
# ---------------------------------------------------------------------------


class Notifier:
    """Отправляет уведомления пчеловоду и клиентам через бота."""

    def __init__(self, bot: Bot, beekeeper_chat_id: Optional[int] = None):
        """
        Args:
            bot: экземпляр aiogram Bot.
            beekeeper_chat_id: Telegram ID пчеловода.
                Если не передан — берётся из конфига BEEKEEPER_CHAT_ID.
        """
        self._bot = bot
        self._beekeeper_chat_id = beekeeper_chat_id or BEEKEEPER_CHAT_ID

    # ------------------------------------------------------------------
    # Публичные методы — события жизненного цикла заказа
    # ------------------------------------------------------------------

    async def new_order(
        self,
        order_id: int,
        client_name: str,
        total: float,
        delivery: str,
        client_telegram_id: Optional[int] = None,
    ) -> None:
        """Уведомить пчеловода о новом заказе.

        Отправляет сообщение с кнопками «Подтвердить» / «Отклонить».
        Если передан client_telegram_id — дополнительно уведомляет клиента.

        Args:
            order_id: идентификатор заказа.
            client_name: имя клиента (ФИО или сокращение).
            total: итоговая сумма заказа в рублях.
            delivery: способ доставки (СДЭК, Почта России, Самовывоз).
            client_telegram_id: Telegram ID клиента (если доступен).
        """
        beekeeper_text = (
            f"🍯 *Новый заказ #{order_id}*\n\n"
            f"👤 {client_name}\n"
            f"💰 {total:.0f} ₽\n"
            f"🚚 {delivery}"
        )
        await self._send_to_beekeeper(
            beekeeper_text,
            reply_markup=_order_action_keyboard(order_id),
        )

        if client_telegram_id:
            client_text = (
                f"✅ Заявка на заказ #{order_id} принята!\n"
                f"Александр свяжется с вами для подтверждения."
            )
            await self._send_to_client(client_telegram_id, client_text)

    async def order_confirmed(
        self,
        order_id: int,
        client_telegram_id: Optional[int] = None,
    ) -> None:
        """Уведомить о подтверждении заказа.

        Args:
            order_id: идентификатор заказа.
            client_telegram_id: Telegram ID клиента (если доступен).
        """
        beekeeper_text = f"✅ Заказ #{order_id} подтверждён."
        await self._send_to_beekeeper(beekeeper_text)

        if client_telegram_id:
            client_text = (
                f"✅ Ваш заказ #{order_id} подтверждён!\n"
                f"Александр готовит посылку."
            )
            await self._send_to_client(client_telegram_id, client_text)

    async def order_shipped(
        self,
        order_id: int,
        tracking_number: str,
        client_telegram_id: Optional[int] = None,
    ) -> None:
        """Уведомить об отправке заказа с трек-номером.

        Args:
            order_id: идентификатор заказа.
            tracking_number: трек-номер (например EE123456789RU).
            client_telegram_id: Telegram ID клиента (если доступен).
        """
        beekeeper_text = (
            f"📦 Заказ #{order_id} отправлен.\n"
            f"Трек: `{tracking_number}`"
        )
        await self._send_to_beekeeper(beekeeper_text)

        if client_telegram_id:
            client_text = (
                f"📦 Ваш заказ #{order_id} отправлен!\n"
                f"Трек-номер для отслеживания: `{tracking_number}`"
            )
            await self._send_to_client(client_telegram_id, client_text)

    async def uds_order(
        self,
        client_name: str,
        total: float,
        order_id: Optional[int] = None,
    ) -> None:
        """Уведомить пчеловода о новом заказе из UDS.

        Args:
            client_name: имя клиента из UDS.
            total: сумма заказа в рублях.
            order_id: идентификатор заказа в Integram (если уже создан).
        """
        order_ref = f" #{order_id}" if order_id else ""
        text = (
            f"🐝 *Заказ из UDS{order_ref}*\n\n"
            f"👤 {client_name}\n"
            f"💰 {total:.0f} ₽"
        )
        keyboard = _order_action_keyboard(order_id) if order_id else None
        await self._send_to_beekeeper(text, reply_markup=keyboard)

    # ------------------------------------------------------------------
    # Внутренние методы отправки
    # ------------------------------------------------------------------

    async def _send_to_beekeeper(
        self,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
    ) -> None:
        """Отправить сообщение пчеловоду."""
        if not self._beekeeper_chat_id:
            logger.info("BEEKEEPER_CHAT_ID не задан — уведомление пропущено: %s", text[:50])
            return
        try:
            await self._bot.send_message(
                self._beekeeper_chat_id,
                text,
                parse_mode="Markdown",
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error("Не удалось отправить уведомление пчеловоду: %s", e)

    async def _send_to_client(self, telegram_id: int, text: str) -> None:
        """Отправить уведомление клиенту (если есть Telegram ID)."""
        try:
            await self._bot.send_message(
                telegram_id,
                text,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.warning("Не удалось отправить уведомление клиенту %d: %s", telegram_id, e)
