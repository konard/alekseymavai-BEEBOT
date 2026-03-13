"""Интеграция с UDS (Unified Discount System).

Получение транзакций из UDS и автоматическое создание заказов в Integram CRM.

Поток:
  UDS транзакция → polling → найти/создать клиента (по телефону)
                           → найти/создать товары (по артикулу UDS)
                           → создать заказ (источник "UDS")
                           → уведомить пчеловода

Конфигурация через .env:
  UDS_API_KEY    — API-ключ UDS
  UDS_COMPANY_ID — ID компании в UDS
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from src import config

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_UDS_BASE_URL = "https://api.uds.app/partner/v2"
_POLL_INTERVAL_SECONDS = 60  # опрос каждую минуту
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class UDSError(Exception):
    """Базовое исключение UDS-клиента."""


class UDSAuthError(UDSError):
    """Ошибка аутентификации UDS."""


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------


def _parse_transaction(data: dict) -> dict:
    """Нормализовать транзакцию UDS в общий формат."""
    customer = data.get("customer") or data.get("user") or {}
    goods = data.get("receipt", {}).get("items") or data.get("items") or []
    return {
        "id": str(data.get("id", "")),
        "created_at": data.get("dateCreated") or data.get("created_at") or "",
        "total": float(data.get("totalPurchase") or data.get("total") or 0.0),
        "customer_phone": (
            customer.get("phone")
            or customer.get("mobilePhone")
            or ""
        ),
        "customer_name": (
            customer.get("displayName")
            or customer.get("name")
            or ""
        ),
        "customer_uds_id": str(customer.get("uid") or customer.get("id") or ""),
        "goods": [
            {
                "sku": str(item.get("product", {}).get("externalId") or item.get("sku") or ""),
                "name": item.get("product", {}).get("name") or item.get("name") or "",
                "quantity": int(item.get("count") or item.get("quantity") or 1),
                "unit_price": float(item.get("price") or 0.0),
            }
            for item in goods
        ],
    }


# ---------------------------------------------------------------------------
# UDSClient
# ---------------------------------------------------------------------------


class UDSClient:
    """Клиент для работы с API UDS.

    Использование::

        client = UDSClient()
        transactions = await client.get_transactions()

    Или через polling::

        async with UDSPoller(uds_client, integram_client, bot) as poller:
            await poller.run()
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        company_id: Optional[str] = None,
        base_url: str = _UDS_BASE_URL,
    ) -> None:
        self._api_key = api_key or config.UDS_API_KEY or ""
        self._company_id = company_id or config.UDS_COMPANY_ID or ""
        self._base_url = base_url.rstrip("/")
        self._http: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                headers={
                    "X-Origin-Request-Id": "beebot",
                    "X-API-KEY": self._api_key,
                    "Accept-Language": "ru",
                    "companyId": self._company_id,
                },
                timeout=30.0,
            )
        return self._http

    async def close(self) -> None:
        """Закрыть HTTP-сессию."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def __aenter__(self) -> "UDSClient":
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Retry logic
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict] = None,
        json: Optional[dict] = None,
    ) -> Any:
        """Выполнить HTTP-запрос с retry (3 попытки, exponential backoff)."""
        http = await self._get_http()
        last_exc: Exception = RuntimeError("no attempts made")

        for attempt in range(_MAX_RETRIES):
            try:
                response = await http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                )
                if response.status_code in (401, 403):
                    raise UDSAuthError(
                        f"Ошибка аутентификации UDS (HTTP {response.status_code}). "
                        "Проверьте UDS_API_KEY и UDS_COMPANY_ID."
                    )
                response.raise_for_status()
                return response.json()
            except UDSAuthError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    wait = _RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "UDS: попытка %d/%d не удалась: %s. Повтор через %.1f с.",
                        attempt + 1,
                        _MAX_RETRIES,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)

        raise UDSError(f"UDS: все {_MAX_RETRIES} попытки исчерпаны: {last_exc}") from last_exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_transactions(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Получить список транзакций (продаж) из UDS.

        Args:
            limit: максимальное число транзакций в ответе.
            offset: смещение для пагинации.

        Returns:
            Список нормализованных транзакций.
        """
        data = await self._request(
            "GET",
            "/operations",
            params={"max": limit, "skip": offset},
        )
        rows = data if isinstance(data, list) else data.get("rows", data.get("items", []))
        return [_parse_transaction(row) for row in rows]

    async def get_customer(self, customer_uds_id: str) -> dict:
        """Получить данные клиента по его UID в UDS.

        Args:
            customer_uds_id: UID клиента в UDS.

        Returns:
            Словарь с данными клиента.
        """
        data = await self._request("GET", f"/customers/{customer_uds_id}")
        return data

    async def get_catalog(self) -> list[dict]:
        """Получить каталог товаров из UDS.

        Returns:
            Список товаров UDS с полями id, name, price, externalId.
        """
        data = await self._request("GET", "/goods")
        rows = data if isinstance(data, list) else data.get("rows", data.get("items", []))
        return rows


# ---------------------------------------------------------------------------
# Deduplication helper
# ---------------------------------------------------------------------------


class TransactionDeduplicator:
    """Хранит ID уже обработанных транзакций UDS (в памяти).

    При рестарте процесса история сбрасывается, поэтому при первом
    запуске обрабатываются только транзакции, созданные после ``since``.
    """

    def __init__(self, since: Optional[datetime] = None) -> None:
        self._seen: set[str] = set()
        # Если since не указан — принять текущий момент, чтобы не дублировать старые.
        self._since: datetime = since or datetime.now(tz=timezone.utc)

    def is_new(self, transaction: dict) -> bool:
        """Вернуть True, если транзакция новая и ещё не обрабатывалась."""
        tid = transaction.get("id", "")
        if tid in self._seen:
            return False

        # Фильтр по дате: пропустить транзакции, созданные до запуска.
        created_raw = transaction.get("created_at", "")
        if created_raw:
            try:
                created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                if created < self._since:
                    return False
            except ValueError:
                pass  # Нераспознанный формат — всё равно обрабатываем

        return True

    def mark_seen(self, transaction_id: str) -> None:
        """Пометить транзакцию как обработанную."""
        self._seen.add(transaction_id)


# ---------------------------------------------------------------------------
# UDS → Integram sync logic
# ---------------------------------------------------------------------------


async def sync_uds_transaction(
    transaction: dict,
    integram_client: Any,
    notify_chat_id: Optional[int] = None,
    bot: Optional[Any] = None,
) -> None:
    """Синхронизировать одну UDS-транзакцию с Integram CRM.

    Args:
        transaction:      Нормализованная транзакция из UDSClient.
        integram_client:  Экземпляр IntegramClient.
        notify_chat_id:   Telegram chat_id для уведомления пчеловода.
        bot:              Экземпляр aiogram Bot (нужен для отправки уведомления).
    """
    tid = transaction["id"]
    phone = transaction["customer_phone"]
    name = transaction["customer_name"] or f"UDS-клиент {transaction['customer_uds_id']}"
    total = transaction["total"]

    logger.info("UDS: обрабатываем транзакцию %s (клиент: %s, сумма: %.2f)", tid, name, total)

    # 1. Найти или создать клиента по телефону
    client = await _get_or_create_client_by_phone(integram_client, phone, name)

    # 2. Собрать позиции заказа из UDS-транзакции
    items = await _build_order_items(integram_client, transaction["goods"], total)

    # 3. Создать заказ
    items_total = sum(i["quantity"] * i["unit_price"] for i in items)
    order = await integram_client.create_order(
        client.id,
        items,
        source="UDS",
        number=f"UDS-{tid}",
        items_total=items_total,
        total=total,
        status="Новый",
    )
    logger.info("UDS: создан заказ #%s (Integram ID=%d)", order.number, order.id)

    # 4. Уведомить пчеловода
    if bot and notify_chat_id:
        await _notify_beekeeper(bot, notify_chat_id, order, client, transaction)


async def _get_or_create_client_by_phone(
    integram_client: Any,
    phone: str,
    name: str,
) -> Any:
    """Найти клиента в Integram по телефону или создать нового."""
    from src.integram_client import IntegramNotFoundError

    if phone:
        try:
            # Попробовать найти клиента по телефону через поиск
            data = await integram_client._request(
                "GET",
                "/api/clients",
                params={"phone": phone},
            )
            clients_raw = data if isinstance(data, list) else data.get("items", data.get("data", []))
            if clients_raw:
                from src.integram_client import IntegramClient
                return IntegramClient._parse_client(clients_raw[0])
        except IntegramNotFoundError:
            pass
        except Exception as e:
            logger.warning("UDS: поиск клиента по телефону %s не удался: %s", phone, e)

    # Создать нового клиента
    return await integram_client.get_or_create_client(
        telegram_id=0,  # UDS-клиент без Telegram
        full_name=name,
        phone=phone,
        source="UDS",
    )


async def _build_order_items(
    integram_client: Any,
    goods: list[dict],
    fallback_total: float,
) -> list[dict]:
    """Сопоставить товары UDS с каталогом Integram и вернуть позиции заказа.

    Если товар не найден — создаём позицию с нулевым product_id и именем из UDS.
    """
    items = []

    for good in goods:
        sku = good.get("sku", "")
        product_id = 0
        unit_price = good.get("unit_price", 0.0)

        if sku:
            try:
                product = await integram_client.get_product_by_name(good["name"])
                if product:
                    product_id = product.id
                    if not unit_price and product.price:
                        unit_price = product.price
            except Exception as e:
                logger.warning("UDS: не удалось найти товар '%s' (SKU=%s): %s", good["name"], sku, e)

        items.append(
            {
                "product_id": product_id,
                "quantity": good["quantity"],
                "unit_price": unit_price,
            }
        )

    # Если нет позиций — добавить одну сводную строку на всю сумму
    if not items:
        items.append(
            {
                "product_id": 0,
                "quantity": 1,
                "unit_price": fallback_total,
            }
        )

    return items


async def _notify_beekeeper(
    bot: Any,
    chat_id: int,
    order: Any,
    client: Any,
    transaction: dict,
) -> None:
    """Отправить уведомление пчеловоду о новом заказе из UDS."""
    goods_lines = "\n".join(
        f"  • {g['name']} × {g['quantity']}"
        for g in transaction["goods"]
    ) or "  • (позиции не указаны)"

    text = (
        f"🛒 *Новый заказ из UDS*\n\n"
        f"Заказ: *{order.number}*\n"
        f"Клиент: {client.full_name}"
        + (f" ({client.phone})" if client.phone else "")
        + f"\nСумма: *{transaction['total']:.0f} ₽*\n\n"
        f"Состав:\n{goods_lines}"
    )
    try:
        await bot.send_message(chat_id, text, parse_mode="Markdown")
    except Exception as e:
        logger.error("UDS: не удалось отправить уведомление пчеловоду: %s", e)


# ---------------------------------------------------------------------------
# UDS Poller
# ---------------------------------------------------------------------------


class UDSPoller:
    """Polling-сервис: периодически опрашивает UDS и синхронизирует заказы.

    Запускается как фоновая asyncio-задача::

        poller = UDSPoller(uds_client, integram_client, bot)
        asyncio.create_task(poller.run())

    Или через async context manager::

        async with UDSPoller(uds_client, integram_client, bot) as poller:
            await poller.run()
    """

    def __init__(
        self,
        uds_client: UDSClient,
        integram_client: Any,
        bot: Optional[Any] = None,
        notify_chat_id: Optional[int] = None,
        poll_interval: float = _POLL_INTERVAL_SECONDS,
    ) -> None:
        self._uds = uds_client
        self._integram = integram_client
        self._bot = bot
        self._notify_chat_id = notify_chat_id or config.BEEKEEPER_CHAT_ID
        self._poll_interval = poll_interval
        self._dedup = TransactionDeduplicator()
        self._running = False

    async def __aenter__(self) -> "UDSPoller":
        return self

    async def __aexit__(self, *_: Any) -> None:
        self.stop()

    def stop(self) -> None:
        """Остановить polling-цикл."""
        self._running = False

    async def run(self) -> None:
        """Запустить бесконечный polling-цикл (до вызова stop())."""
        self._running = True
        logger.info("UDS Poller: запущен (интервал опроса %ds).", self._poll_interval)

        while self._running:
            try:
                await self._poll_once()
            except Exception as e:
                logger.error("UDS Poller: ошибка при опросе: %s", e)

            await asyncio.sleep(self._poll_interval)

        logger.info("UDS Poller: остановлен.")

    async def _poll_once(self) -> None:
        """Один цикл опроса: получить транзакции и обработать новые."""
        transactions = await self._uds.get_transactions(limit=50)
        new_count = 0

        for tx in transactions:
            if not self._dedup.is_new(tx):
                continue

            try:
                await sync_uds_transaction(
                    tx,
                    self._integram,
                    notify_chat_id=self._notify_chat_id,
                    bot=self._bot,
                )
                self._dedup.mark_seen(tx["id"])
                new_count += 1
            except Exception as e:
                logger.error(
                    "UDS Poller: не удалось обработать транзакцию %s: %s",
                    tx.get("id"),
                    e,
                )

        if new_count:
            logger.info("UDS Poller: обработано %d новых транзакций.", new_count)


# ---------------------------------------------------------------------------
# Catalog sync: UDS ↔ Integram
# ---------------------------------------------------------------------------


async def sync_uds_catalog(
    uds_client: UDSClient,
    integram_client: Any,
) -> dict[str, int]:
    """Синхронизировать каталог UDS с Integram CRM.

    Для каждого товара UDS проверяет, есть ли соответствующий товар в Integram
    (по полю «Артикул UDS»). Возвращает маппинг externalId → Integram product ID.

    Args:
        uds_client:      Экземпляр UDSClient.
        integram_client: Экземпляр IntegramClient.

    Returns:
        Словарь {uds_external_id: integram_product_id}.
    """
    uds_goods = await uds_client.get_catalog()
    integram_products = await integram_client.get_products(in_stock_only=False)

    # Индекс Integram-товаров по артикулу UDS
    sku_to_integram: dict[str, int] = {
        p.sku_uds: p.id
        for p in integram_products
        if p.sku_uds
    }

    mapping: dict[str, int] = {}
    synced = 0
    missing = 0

    for good in uds_goods:
        ext_id = str(good.get("externalId") or good.get("id") or "")
        if not ext_id:
            continue

        if ext_id in sku_to_integram:
            mapping[ext_id] = sku_to_integram[ext_id]
            synced += 1
        else:
            logger.debug(
                "UDS: товар '%s' (externalId=%s) не найден в Integram.",
                good.get("name"),
                ext_id,
            )
            missing += 1

    logger.info(
        "UDS каталог: синхронизировано %d товаров, не найдено %d.",
        synced,
        missing,
    )
    return mapping
