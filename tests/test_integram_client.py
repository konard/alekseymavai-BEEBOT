"""Тесты для IntegramClient (src/integram_client.py).

Используют моки httpx.AsyncClient — реальных запросов к Integram не делают.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.integram_client import (
    IntegramAuthError,
    IntegramClient,
    IntegramError,
    IntegramNotFoundError,
)
from src.models import Client, Order, OrderItem, Product


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _make_client(**kwargs) -> IntegramClient:
    return IntegramClient(
        base_url="https://test.integram.example",
        login="user",
        password="pass",
        db="test_db",
        **kwargs,
    )


def _mock_response(json_data, status_code: int = 200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_data
    response.raise_for_status = MagicMock()
    return response


# ---------------------------------------------------------------------------
# Тесты: authenticate
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_authenticate_success():
    client = _make_client()
    mock_resp = _mock_response({"token": "abc123"})

    with patch.object(client, "_get_http") as mock_get_http:
        http = AsyncMock()
        http.request = AsyncMock(return_value=mock_resp)
        mock_get_http.return_value = http

        await client.authenticate()

    assert client._token == "abc123"


@pytest.mark.asyncio
async def test_authenticate_success_access_token_key():
    """Поддержка ключа access_token в ответе."""
    client = _make_client()
    mock_resp = _mock_response({"access_token": "xyz789"})

    with patch.object(client, "_get_http") as mock_get_http:
        http = AsyncMock()
        http.request = AsyncMock(return_value=mock_resp)
        mock_get_http.return_value = http

        await client.authenticate()

    assert client._token == "xyz789"


@pytest.mark.asyncio
async def test_authenticate_raises_on_missing_token():
    client = _make_client()
    mock_resp = _mock_response({"error": "invalid credentials"})

    with patch.object(client, "_get_http") as mock_get_http:
        http = AsyncMock()
        http.request = AsyncMock(return_value=mock_resp)
        mock_get_http.return_value = http

        with pytest.raises(IntegramAuthError):
            await client.authenticate()


@pytest.mark.asyncio
async def test_authenticate_raises_on_401():
    client = _make_client()
    mock_resp = _mock_response({}, status_code=401)

    with patch.object(client, "_get_http") as mock_get_http:
        http = AsyncMock()
        http.request = AsyncMock(return_value=mock_resp)
        mock_get_http.return_value = http

        with pytest.raises(IntegramAuthError):
            await client.authenticate()


# ---------------------------------------------------------------------------
# Тесты: retry-логика
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_request_retries_on_network_error():
    """Клиент повторяет запрос до 3 раз при сетевой ошибке."""
    client = _make_client()
    client._token = "tok"

    call_count = 0

    async def failing_request(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise ConnectionError("network error")

    with patch.object(client, "_get_http") as mock_get_http:
        http = AsyncMock()
        http.request = AsyncMock(side_effect=failing_request)
        mock_get_http.return_value = http

        with patch("src.integram_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(IntegramError, match="Все 3 попытки исчерпаны"):
                await client._request("GET", "/api/test")

    assert call_count == 3


@pytest.mark.asyncio
async def test_request_succeeds_on_second_attempt():
    """Клиент успешно возвращает данные после первой неудачной попытки."""
    client = _make_client()
    client._token = "tok"

    attempt = 0

    async def flaky_request(*args, **kwargs):
        nonlocal attempt
        attempt += 1
        if attempt == 1:
            raise ConnectionError("timeout")
        return _mock_response({"ok": True})

    with patch.object(client, "_get_http") as mock_get_http:
        http = AsyncMock()
        http.request = AsyncMock(side_effect=flaky_request)
        mock_get_http.return_value = http

        with patch("src.integram_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client._request("GET", "/api/test")

    assert result == {"ok": True}
    assert attempt == 2


# ---------------------------------------------------------------------------
# Тесты: get_products
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_products_returns_list():
    client = _make_client()
    client._token = "tok"

    raw = [
        {
            "id": 1,
            "Название": "Перга",
            "Категория": "Продукты пчеловодства",
            "Цена": 500.0,
            "В наличии": True,
        },
        {
            "id": 2,
            "Название": "Прополис (сухой + настойка)",
            "Категория": "Настойки",
            "Цена": 300.0,
            "В наличии": True,
        },
    ]

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = raw
        products = await client.get_products()

    assert len(products) == 2
    assert all(isinstance(p, Product) for p in products)
    assert products[0].name == "Перга"
    assert products[1].name == "Прополис (сухой + настойка)"


@pytest.mark.asyncio
async def test_get_products_wrapped_in_items_key():
    """API может вернуть {'items': [...]}."""
    client = _make_client()
    client._token = "tok"

    raw = {"items": [{"id": 1, "Название": "Перга", "В наличии": True}]}

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = raw
        products = await client.get_products()

    assert len(products) == 1
    assert products[0].name == "Перга"


@pytest.mark.asyncio
async def test_get_product_by_name_found():
    client = _make_client()
    raw_products = [
        {"id": 1, "Название": "Перга", "В наличии": True},
        {"id": 2, "Название": "Прополис", "В наличии": False},
    ]

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = raw_products
        product = await client.get_product_by_name("перга")

    assert product is not None
    assert product.id == 1
    assert product.name == "Перга"


@pytest.mark.asyncio
async def test_get_product_by_name_not_found():
    client = _make_client()

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = [{"id": 1, "Название": "Перга", "В наличии": True}]
        product = await client.get_product_by_name("Несуществующий товар")

    assert product is None


# ---------------------------------------------------------------------------
# Тесты: get_or_create_client
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_or_create_client_existing():
    """Клиент уже существует — возвращаем найденного."""
    client = _make_client()
    client._token = "tok"

    existing = {
        "id": 42,
        "ФИО": "Иванов Иван",
        "Telegram ID": 123456,
    }

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = existing
        result = await client.get_or_create_client(123456)

    assert result.id == 42
    assert result.full_name == "Иванов Иван"
    assert result.telegram_id == 123456
    mock_req.assert_called_once_with("GET", "/api/clients/telegram/123456")


@pytest.mark.asyncio
async def test_get_or_create_client_creates_new():
    """Клиент не найден — создаём нового."""
    client = _make_client()
    client._token = "tok"

    new_client = {
        "id": 99,
        "ФИО": "Telegram 777",
        "Telegram ID": 777,
    }

    call_count = 0

    async def side_effect(method, path, **kwargs):
        nonlocal call_count
        call_count += 1
        if method == "GET":
            raise IntegramNotFoundError("not found")
        return new_client

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = side_effect
        result = await client.get_or_create_client(777)

    assert result.id == 99
    assert result.telegram_id == 777
    assert call_count == 2


@pytest.mark.asyncio
async def test_update_client():
    client = _make_client()
    client._token = "tok"

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {}
        await client.update_client(42, full_name="Новое Имя", city="Москва")

    mock_req.assert_called_once_with(
        "PATCH",
        "/api/clients/42",
        json={"ФИО": "Новое Имя", "Город": "Москва"},
    )


# ---------------------------------------------------------------------------
# Тесты: create_order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_order():
    client = _make_client()
    client._token = "tok"

    order_resp = {
        "id": 10,
        "Номер": "ORD-001",
        "Клиент": 42,
        "Дата": "2026-03-13T10:00:00",
        "Статус": "Новый",
        "items": [],
    }

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = order_resp
        order = await client.create_order(
            client_id=42,
            items=[{"product_id": 1, "quantity": 2, "unit_price": 500.0}],
            delivery_method="СДЭК",
        )

    assert isinstance(order, Order)
    assert order.id == 10
    assert order.number == "ORD-001"
    assert order.status == "Новый"

    call_args = mock_req.call_args
    payload = call_args.kwargs["json"]
    assert payload["Клиент"] == 42
    assert payload["Статус"] == "Новый"
    assert payload["Способ доставки"] == "СДЭК"
    assert len(payload["items"]) == 1
    assert payload["items"][0]["Количество"] == 2
    assert payload["items"][0]["Цена за шт."] == 500.0
    assert payload["items"][0]["Сумма"] == 1000.0


# ---------------------------------------------------------------------------
# Тесты: update_order_status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_update_order_status():
    client = _make_client()
    client._token = "tok"

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {}
        await client.update_order_status(10, "Подтверждён")

    mock_req.assert_called_once_with(
        "PATCH",
        "/api/orders/10",
        json={"Статус": "Подтверждён"},
    )


# ---------------------------------------------------------------------------
# Тесты: get_orders
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_orders_all():
    client = _make_client()
    client._token = "tok"

    raw = [
        {
            "id": 1,
            "Номер": "ORD-001",
            "Клиент": 42,
            "Дата": "2026-03-13T10:00:00",
            "Статус": "Новый",
        }
    ]

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = raw
        orders = await client.get_orders()

    assert len(orders) == 1
    assert orders[0].number == "ORD-001"


@pytest.mark.asyncio
async def test_get_orders_filter_by_client():
    client = _make_client()
    client._token = "tok"

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = []
        await client.get_orders(client_id=42, status="Новый")

    mock_req.assert_called_once_with(
        "GET",
        "/api/orders",
        params={"client_id": 42, "status": "Новый"},
    )


# ---------------------------------------------------------------------------
# Тесты: get_order
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_order_found():
    client = _make_client()
    client._token = "tok"

    raw = {
        "id": 5,
        "Номер": "ORD-005",
        "Клиент": 7,
        "Дата": "2026-03-12T08:30:00",
        "Статус": "Отправлен",
        "Трек-номер": "ABC123",
        "items": [
            {
                "id": 1,
                "Товар": 2,
                "Количество": 1,
                "Цена за шт.": 300.0,
                "Сумма": 300.0,
            }
        ],
    }

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = raw
        order = await client.get_order(5)

    assert order.id == 5
    assert order.tracking_number == "ABC123"
    assert len(order.items) == 1
    assert order.items[0].quantity == 1


@pytest.mark.asyncio
async def test_get_order_not_found():
    client = _make_client()
    client._token = "tok"

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = IntegramNotFoundError("Order not found")
        with pytest.raises(IntegramNotFoundError):
            await client.get_order(999)


# ---------------------------------------------------------------------------
# Тесты: add_order_item
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_order_item():
    client = _make_client()
    client._token = "tok"

    with patch.object(client, "_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {}
        await client.add_order_item(order_id=10, product_id=3, qty=2)

    mock_req.assert_called_once_with(
        "POST",
        "/api/orders/10/items",
        json={"Товар": 3, "Количество": 2},
    )


# ---------------------------------------------------------------------------
# Тесты: context manager
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_manager():
    client = _make_client()

    with patch.object(client, "authenticate", new_callable=AsyncMock) as mock_auth, \
         patch.object(client, "close", new_callable=AsyncMock) as mock_close:
        async with client as c:
            assert c is client

    mock_auth.assert_called_once()
    mock_close.assert_called_once()


# ---------------------------------------------------------------------------
# Тесты: Pydantic модели
# ---------------------------------------------------------------------------

def test_product_model():
    product = Product(
        id=1,
        **{"Название": "Перга", "Цена": 500.0, "В наличии": True}
    )
    assert product.name == "Перга"
    assert product.price == 500.0
    assert product.in_stock is True


def test_client_model():
    client = Client(
        id=42,
        **{"ФИО": "Иванов Иван", "Telegram ID": 123456}
    )
    assert client.full_name == "Иванов Иван"
    assert client.telegram_id == 123456


def test_order_model():
    order = Order(
        id=1,
        client_id=42,
        **{
            "Номер": "ORD-001",
            "Дата": datetime(2026, 3, 13),
            "Статус": "Новый",
        }
    )
    assert order.number == "ORD-001"
    assert order.status == "Новый"
    assert order.items == []


def test_order_item_model():
    item = OrderItem(
        id=1,
        order_id=10,
        product_id=2,
        **{"Количество": 3, "Цена за шт.": 200.0, "Сумма": 600.0}
    )
    assert item.quantity == 3
    assert item.unit_price == 200.0
    assert item.total == 600.0
