"""Pydantic-модели данных для Integram CRM.

Используются в IntegramClient для сериализации/десериализации ответов API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Product(BaseModel):
    """Товар в каталоге Integram CRM."""

    id: int
    name: str = Field(alias="Название")
    category: Optional[str] = Field(default=None, alias="Категория")
    price: Optional[float] = Field(default=None, alias="Цена")
    weight: Optional[float] = Field(default=None, alias="Вес")
    description: Optional[str] = Field(default=None, alias="Описание")
    in_stock: Optional[bool] = Field(default=True, alias="В наличии")
    sku_uds: Optional[str] = Field(default=None, alias="Артикул UDS")

    model_config = {"populate_by_name": True}


class Client(BaseModel):
    """Клиент в Integram CRM."""

    id: int
    full_name: str = Field(alias="ФИО")
    phone: Optional[str] = Field(default=None, alias="Телефон")
    telegram_id: Optional[int] = Field(default=None, alias="Telegram ID")
    telegram_username: Optional[str] = Field(default=None, alias="Telegram Username")
    address: Optional[str] = Field(default=None, alias="Адрес")
    city: Optional[str] = Field(default=None, alias="Город")
    source: Optional[str] = Field(default=None, alias="Источник")

    model_config = {"populate_by_name": True}


class OrderItem(BaseModel):
    """Позиция заказа в Integram CRM."""

    id: int
    order_id: int
    product_id: int
    product_name: Optional[str] = None
    quantity: int = Field(alias="Количество")
    unit_price: float = Field(alias="Цена за шт.")
    total: float = Field(alias="Сумма")

    model_config = {"populate_by_name": True}


class Order(BaseModel):
    """Заказ в Integram CRM."""

    id: int
    number: str = Field(alias="Номер")
    client_id: int
    client_name: Optional[str] = None
    date: datetime = Field(alias="Дата")
    status: str = Field(alias="Статус")
    delivery_method: Optional[str] = Field(default=None, alias="Способ доставки")
    delivery_address: Optional[str] = Field(default=None, alias="Адрес доставки")
    delivery_cost: Optional[float] = Field(default=None, alias="Стоимость доставки")
    items_total: Optional[float] = Field(default=None, alias="Сумма товаров")
    total: Optional[float] = Field(default=None, alias="Итого")
    tracking_number: Optional[str] = Field(default=None, alias="Трек-номер")
    source: Optional[str] = Field(default=None, alias="Источник")
    items: list[OrderItem] = Field(default_factory=list)

    model_config = {"populate_by_name": True}
