"""Python-клиент для Integram CRM (ai2o.ru).

Обёртка над REST API Integram для runtime-кода бота.
Поддерживает async, retry-логику (3 попытки с backoff).

Конфигурация через .env:
  INTEGRAM_URL      — базовый URL API (например, https://app.ai2o.ru)
  INTEGRAM_LOGIN    — логин пользователя
  INTEGRAM_PASSWORD — пароль пользователя
  INTEGRAM_DB       — имя базы данных (рабочего пространства)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional

import httpx

from src import config
from src.models import Client, Order, OrderItem, Product

logger = logging.getLogger(__name__)

# Константы retry-логики
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # секунды


class IntegramError(Exception):
    """Базовое исключение клиента Integram."""


class IntegramAuthError(IntegramError):
    """Ошибка аутентификации."""


class IntegramNotFoundError(IntegramError):
    """Запись не найдена."""


class IntegramClient:
    """Async-клиент для работы с Integram CRM.

    Использование::

        client = IntegramClient()
        await client.authenticate()
        products = await client.get_products()
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        login: Optional[str] = None,
        password: Optional[str] = None,
        db: Optional[str] = None,
    ) -> None:
        self._base_url = (base_url or config.INTEGRAM_URL or "").rstrip("/")
        self._login = login or config.INTEGRAM_LOGIN or ""
        self._password = password or config.INTEGRAM_PASSWORD or ""
        self._db = db or config.INTEGRAM_DB or ""
        self._token: Optional[str] = None
        self._http: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Управление сессией
    # ------------------------------------------------------------------

    async def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=30.0,
            )
        return self._http

    async def close(self) -> None:
        """Закрыть HTTP-сессию."""
        if self._http and not self._http.is_closed:
            await self._http.aclose()

    async def __aenter__(self) -> "IntegramClient":
        await self.authenticate()
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Retry-логика
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
        auth_required: bool = True,
    ) -> Any:
        """Выполнить HTTP-запрос с retry (3 попытки, exponential backoff)."""
        http = await self._get_http()
        headers: dict[str, str] = {}
        if auth_required and self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        last_exc: Exception = RuntimeError("no attempts made")
        for attempt in range(_MAX_RETRIES):
            try:
                response = await http.request(
                    method,
                    path,
                    json=json,
                    params=params,
                    headers=headers,
                )
                if response.status_code == 401:
                    raise IntegramAuthError("Не авторизован (401). Вызовите authenticate().")
                if response.status_code == 404:
                    raise IntegramNotFoundError(f"Не найдено: {path}")
                response.raise_for_status()
                return response.json()
            except (IntegramAuthError, IntegramNotFoundError):
                raise
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES - 1:
                    wait = _RETRY_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "Попытка %d/%d не удалась: %s. Повтор через %.1f с.",
                        attempt + 1,
                        _MAX_RETRIES,
                        exc,
                        wait,
                    )
                    await asyncio.sleep(wait)
        raise IntegramError(f"Все {_MAX_RETRIES} попытки исчерпаны: {last_exc}") from last_exc

    # ------------------------------------------------------------------
    # Аутентификация
    # ------------------------------------------------------------------

    async def authenticate(self) -> None:
        """Получить JWT-токен по логину и паролю."""
        data = await self._request(
            "POST",
            "/api/auth/login",
            json={
                "login": self._login,
                "password": self._password,
                "db": self._db,
            },
            auth_required=False,
        )
        token = data.get("token") or data.get("access_token")
        if not token:
            raise IntegramAuthError(f"Токен не получен. Ответ: {data}")
        self._token = token
        logger.info("Аутентификация в Integram прошла успешно.")

    # ------------------------------------------------------------------
    # Товары
    # ------------------------------------------------------------------

    async def get_products(self, in_stock_only: bool = True) -> list[Product]:
        """Получить список товаров.

        Args:
            in_stock_only: если True — только товары в наличии.
        """
        params: dict[str, Any] = {}
        if in_stock_only:
            params["in_stock"] = True
        data = await self._request("GET", "/api/products", params=params)
        items = data if isinstance(data, list) else data.get("items", data.get("data", []))
        return [self._parse_product(item) for item in items]

    async def get_product_by_name(self, name: str) -> Optional[Product]:
        """Найти товар по названию (регистронезависимо).

        Returns:
            Product или None, если не найден.
        """
        products = await self.get_products(in_stock_only=False)
        name_lower = name.lower()
        for product in products:
            if product.name.lower() == name_lower:
                return product
        return None

    @staticmethod
    def _parse_product(data: dict) -> Product:
        product_data = {
            "id": data.get("id", 0),
            "Название": data.get("Название") or data.get("name", ""),
            "Категория": data.get("Категория") or data.get("category"),
            "Цена": data.get("Цена") or data.get("price"),
            "Вес": data.get("Вес") or data.get("weight"),
            "Описание": data.get("Описание") or data.get("description"),
            "В наличии": data.get("В наличии") if "В наличии" in data else data.get("in_stock", True),
            "Артикул UDS": data.get("Артикул UDS") or data.get("sku_uds"),
        }
        return Product.model_validate(product_data)

    # ------------------------------------------------------------------
    # Клиенты
    # ------------------------------------------------------------------

    async def get_or_create_client(
        self,
        telegram_id: int,
        **kwargs: Any,
    ) -> Client:
        """Получить клиента по Telegram ID или создать нового.

        Args:
            telegram_id: Telegram chat_id пользователя.
            **kwargs: Дополнительные поля (full_name, phone, telegram_username, и др.)
        """
        try:
            data = await self._request("GET", f"/api/clients/telegram/{telegram_id}")
            return self._parse_client(data)
        except IntegramNotFoundError:
            pass

        full_name = kwargs.get("full_name") or kwargs.get("ФИО") or f"Telegram {telegram_id}"
        create_data: dict[str, Any] = {
            "ФИО": full_name,
            "Telegram ID": telegram_id,
        }
        if "telegram_username" in kwargs:
            create_data["Telegram Username"] = kwargs["telegram_username"]
        if "phone" in kwargs:
            create_data["Телефон"] = kwargs["phone"]
        if "address" in kwargs:
            create_data["Адрес"] = kwargs["address"]
        if "city" in kwargs:
            create_data["Город"] = kwargs["city"]

        data = await self._request("POST", "/api/clients", json=create_data)
        return self._parse_client(data)

    async def update_client(self, client_id: int, **kwargs: Any) -> None:
        """Обновить данные клиента.

        Args:
            client_id: ID клиента в Integram.
            **kwargs: Поля для обновления (full_name, phone, address, city, и др.)
        """
        update_data: dict[str, Any] = {}
        field_map = {
            "full_name": "ФИО",
            "phone": "Телефон",
            "telegram_username": "Telegram Username",
            "address": "Адрес",
            "city": "Город",
            "source": "Источник",
        }
        for py_key, api_key in field_map.items():
            if py_key in kwargs:
                update_data[api_key] = kwargs[py_key]
        # Разрешаем передавать русские ключи напрямую
        for key, val in kwargs.items():
            if key not in field_map:
                update_data[key] = val

        await self._request("PATCH", f"/api/clients/{client_id}", json=update_data)

    @staticmethod
    def _parse_client(data: dict) -> Client:
        client_data = {
            "id": data.get("id", 0),
            "ФИО": data.get("ФИО") or data.get("full_name", ""),
            "Телефон": data.get("Телефон") or data.get("phone"),
            "Telegram ID": data.get("Telegram ID") or data.get("telegram_id"),
            "Telegram Username": data.get("Telegram Username") or data.get("telegram_username"),
            "Адрес": data.get("Адрес") or data.get("address"),
            "Город": data.get("Город") or data.get("city"),
            "Источник": data.get("Источник") or data.get("source"),
        }
        return Client.model_validate(client_data)

    # ------------------------------------------------------------------
    # Заказы
    # ------------------------------------------------------------------

    async def create_order(
        self,
        client_id: int,
        items: list[dict],
        **kwargs: Any,
    ) -> Order:
        """Создать новый заказ.

        Args:
            client_id: ID клиента.
            items: Список позиций — каждая dict с ключами product_id, quantity, unit_price.
            **kwargs: Доп. поля (delivery_method, delivery_address, source, и др.)
        """
        order_data: dict[str, Any] = {
            "Клиент": client_id,
            "Дата": datetime.now().isoformat(),
            "Статус": kwargs.get("status", "Новый"),
        }
        field_map = {
            "delivery_method": "Способ доставки",
            "delivery_address": "Адрес доставки",
            "delivery_cost": "Стоимость доставки",
            "items_total": "Сумма товаров",
            "total": "Итого",
            "tracking_number": "Трек-номер",
            "source": "Источник",
            "number": "Номер",
        }
        for py_key, api_key in field_map.items():
            if py_key in kwargs:
                order_data[api_key] = kwargs[py_key]

        order_data["items"] = [
            {
                "Товар": item["product_id"],
                "Количество": item["quantity"],
                "Цена за шт.": item["unit_price"],
                "Сумма": item["quantity"] * item["unit_price"],
            }
            for item in items
        ]

        data = await self._request("POST", "/api/orders", json=order_data)
        return self._parse_order(data)

    async def update_order_status(self, order_id: int, status: str) -> None:
        """Обновить статус заказа.

        Args:
            order_id: ID заказа.
            status: Новый статус (из справочника ORDER_STATUSES).
        """
        await self._request(
            "PATCH",
            f"/api/orders/{order_id}",
            json={"Статус": status},
        )

    async def get_orders(
        self,
        client_id: Optional[int] = None,
        status: Optional[str] = None,
    ) -> list[Order]:
        """Получить список заказов с фильтрацией.

        Args:
            client_id: Фильтр по клиенту.
            status: Фильтр по статусу.
        """
        params: dict[str, Any] = {}
        if client_id is not None:
            params["client_id"] = client_id
        if status is not None:
            params["status"] = status
        data = await self._request("GET", "/api/orders", params=params)
        items = data if isinstance(data, list) else data.get("items", data.get("data", []))
        return [self._parse_order(item) for item in items]

    async def get_order(self, order_id: int) -> Order:
        """Получить заказ по ID.

        Args:
            order_id: ID заказа.

        Raises:
            IntegramNotFoundError: если заказ не найден.
        """
        data = await self._request("GET", f"/api/orders/{order_id}")
        return self._parse_order(data)

    async def add_order_item(
        self,
        order_id: int,
        product_id: int,
        qty: int,
    ) -> None:
        """Добавить позицию к существующему заказу.

        Args:
            order_id: ID заказа.
            product_id: ID товара.
            qty: Количество штук.
        """
        await self._request(
            "POST",
            f"/api/orders/{order_id}/items",
            json={
                "Товар": product_id,
                "Количество": qty,
            },
        )

    @staticmethod
    def _parse_order(data: dict) -> Order:
        date_raw = data.get("Дата") or data.get("date") or datetime.now().isoformat()
        if isinstance(date_raw, str):
            try:
                date = datetime.fromisoformat(date_raw)
            except ValueError:
                date = datetime.now()
        else:
            date = date_raw

        raw_items = data.get("items", [])
        order_id = data.get("id", 0)
        parsed_items = [
            OrderItem(
                id=item.get("id", 0),
                order_id=order_id,
                product_id=item.get("Товар") or item.get("product_id", 0),
                product_name=item.get("product_name"),
                **{
                    "Количество": item.get("Количество") or item.get("quantity", 0),
                    "Цена за шт.": item.get("Цена за шт.") or item.get("unit_price", 0.0),
                    "Сумма": item.get("Сумма") or item.get("total", 0.0),
                },
            )
            for item in raw_items
        ]

        order_data = {
            "id": order_id,
            "Номер": data.get("Номер") or data.get("number", str(order_id)),
            "client_id": data.get("Клиент") or data.get("client_id", 0),
            "client_name": data.get("client_name"),
            "Дата": date,
            "Статус": data.get("Статус") or data.get("status", "Новый"),
            "Способ доставки": data.get("Способ доставки") or data.get("delivery_method"),
            "Адрес доставки": data.get("Адрес доставки") or data.get("delivery_address"),
            "Стоимость доставки": data.get("Стоимость доставки") or data.get("delivery_cost"),
            "Сумма товаров": data.get("Сумма товаров") or data.get("items_total"),
            "Итого": data.get("Итого") or data.get("total"),
            "Трек-номер": data.get("Трек-номер") or data.get("tracking_number"),
            "Источник": data.get("Источник") or data.get("source"),
            "items": parsed_items,
        }
        return Order.model_validate(order_data)
