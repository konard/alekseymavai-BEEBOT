"""Тесты для src/integrations/uds.py.

Покрывает:
- _parse_transaction: нормализация данных UDS
- UDSClient: HTTP-запросы, retry-логика, авторизационные ошибки
- TransactionDeduplicator: дедупликация по ID и дате
- sync_uds_transaction: полный поток (клиент → позиции → заказ → уведомление)
- UDSPoller: polling-цикл, остановка, обработка ошибок
- sync_uds_catalog: маппинг UDS ↔ Integram
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call

import httpx
import pytest

from src.integrations.uds import (
    UDSClient,
    UDSError,
    UDSAuthError,
    TransactionDeduplicator,
    UDSPoller,
    _parse_transaction,
    sync_uds_transaction,
    sync_uds_catalog,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_raw_transaction(
    tid: str = "tx-1",
    phone: str = "+79001234567",
    name: str = "Иван Иванов",
    total: float = 500.0,
    uds_id: str = "uid-1",
    items: list | None = None,
    created_at: str = "2026-03-13T10:00:00Z",
) -> dict:
    if items is None:
        items = [
            {
                "product": {"externalId": "SKU-001", "name": "Перга"},
                "count": 2,
                "price": 250.0,
            }
        ]
    return {
        "id": tid,
        "dateCreated": created_at,
        "totalPurchase": total,
        "customer": {"phone": phone, "displayName": name, "uid": uds_id},
        "receipt": {"items": items},
    }


def _make_integram_mock(
    client_id: int = 42,
    order_id: int = 100,
    product_id: int = 7,
) -> MagicMock:
    """Вернуть мок IntegramClient с настроенными async-методами."""
    mock = MagicMock()

    client_obj = MagicMock()
    client_obj.id = client_id
    client_obj.full_name = "Иван Иванов"
    client_obj.phone = "+79001234567"

    order_obj = MagicMock()
    order_obj.id = order_id
    order_obj.number = f"UDS-tx-1"

    product_obj = MagicMock()
    product_obj.id = product_id
    product_obj.price = 250.0
    product_obj.sku_uds = "SKU-001"

    mock._request = AsyncMock(return_value=[])
    mock.get_or_create_client = AsyncMock(return_value=client_obj)
    mock.create_order = AsyncMock(return_value=order_obj)
    mock.get_product_by_name = AsyncMock(return_value=product_obj)
    mock.get_products = AsyncMock(return_value=[product_obj])

    return mock


# ---------------------------------------------------------------------------
# _parse_transaction
# ---------------------------------------------------------------------------

class TestParseTransaction:

    def test_standard_format(self):
        raw = _make_raw_transaction()
        tx = _parse_transaction(raw)
        assert tx["id"] == "tx-1"
        assert tx["customer_phone"] == "+79001234567"
        assert tx["customer_name"] == "Иван Иванов"
        assert tx["customer_uds_id"] == "uid-1"
        assert tx["total"] == 500.0
        assert len(tx["goods"]) == 1
        assert tx["goods"][0]["sku"] == "SKU-001"
        assert tx["goods"][0]["name"] == "Перга"
        assert tx["goods"][0]["quantity"] == 2
        assert tx["goods"][0]["unit_price"] == 250.0

    def test_missing_customer_fields(self):
        raw = {"id": "tx-2", "totalPurchase": 100.0}
        tx = _parse_transaction(raw)
        assert tx["customer_phone"] == ""
        assert tx["customer_name"] == ""
        assert tx["customer_uds_id"] == ""
        assert tx["goods"] == []

    def test_alternative_field_names(self):
        """Поддержка альтернативных полей (mobilePhone, name, etc.)."""
        raw = {
            "id": "tx-3",
            "total": 300.0,
            "user": {"mobilePhone": "+79999999999", "name": "Пётр"},
            "items": [{"sku": "S1", "name": "Мёд", "quantity": 1, "price": 300.0}],
        }
        tx = _parse_transaction(raw)
        assert tx["customer_phone"] == "+79999999999"
        assert tx["customer_name"] == "Пётр"
        assert tx["goods"][0]["sku"] == "S1"


# ---------------------------------------------------------------------------
# UDSClient
# ---------------------------------------------------------------------------

class TestUDSClient:

    @pytest.mark.asyncio
    async def test_get_transactions_returns_normalized_list(self):
        raw = _make_raw_transaction()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"rows": [raw]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            client = UDSClient(api_key="key", company_id="cid")
            transactions = await client.get_transactions()

        assert len(transactions) == 1
        assert transactions[0]["id"] == "tx-1"

    @pytest.mark.asyncio
    async def test_get_transactions_list_response(self):
        """API вернул список напрямую (без обёртки rows)."""
        raw = _make_raw_transaction(tid="tx-direct")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [raw]
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            client = UDSClient(api_key="key", company_id="cid")
            transactions = await client.get_transactions()

        assert transactions[0]["id"] == "tx-direct"

    @pytest.mark.asyncio
    async def test_auth_error_raises_uds_auth_error(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            client = UDSClient(api_key="bad", company_id="cid")
            with pytest.raises(UDSAuthError):
                await client.get_transactions()

    @pytest.mark.asyncio
    async def test_retry_on_network_error(self):
        """Клиент делает 3 попытки при сетевой ошибке."""
        with patch(
            "httpx.AsyncClient.request",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                client = UDSClient(api_key="key", company_id="cid")
                with pytest.raises(UDSError, match="3 попытки"):
                    await client.get_transactions()

    @pytest.mark.asyncio
    async def test_get_catalog(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"rows": [{"id": 1, "name": "Перга", "externalId": "SKU-1"}]}
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.request", new_callable=AsyncMock, return_value=mock_resp):
            client = UDSClient(api_key="key", company_id="cid")
            catalog = await client.get_catalog()

        assert len(catalog) == 1
        assert catalog[0]["name"] == "Перга"

    @pytest.mark.asyncio
    async def test_close_releases_http(self):
        client = UDSClient(api_key="key", company_id="cid")
        await client._get_http()  # создаёт httpx.AsyncClient
        assert client._http is not None
        await client.close()
        assert client._http.is_closed

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with UDSClient(api_key="key", company_id="cid") as client:
            assert isinstance(client, UDSClient)


# ---------------------------------------------------------------------------
# TransactionDeduplicator
# ---------------------------------------------------------------------------

class TestTransactionDeduplicator:

    def test_new_transaction_passes(self):
        dedup = TransactionDeduplicator(since=datetime(2026, 1, 1, tzinfo=timezone.utc))
        tx = {"id": "tx-1", "created_at": "2026-03-13T10:00:00Z"}
        assert dedup.is_new(tx) is True

    def test_seen_transaction_rejected(self):
        dedup = TransactionDeduplicator(since=datetime(2026, 1, 1, tzinfo=timezone.utc))
        tx = {"id": "tx-1", "created_at": "2026-03-13T10:00:00Z"}
        dedup.mark_seen("tx-1")
        assert dedup.is_new(tx) is False

    def test_old_transaction_rejected(self):
        """Транзакция до since должна быть отфильтрована."""
        since = datetime(2026, 3, 13, 12, 0, 0, tzinfo=timezone.utc)
        dedup = TransactionDeduplicator(since=since)
        tx = {"id": "tx-old", "created_at": "2026-03-13T10:00:00Z"}
        assert dedup.is_new(tx) is False

    def test_transaction_without_date_passes(self):
        """Транзакция без даты — обрабатываем (не отфильтровываем)."""
        dedup = TransactionDeduplicator()
        tx = {"id": "tx-nodate", "created_at": ""}
        assert dedup.is_new(tx) is True

    def test_transaction_with_invalid_date_passes(self):
        dedup = TransactionDeduplicator(since=datetime(2026, 1, 1, tzinfo=timezone.utc))
        tx = {"id": "tx-bad", "created_at": "not-a-date"}
        assert dedup.is_new(tx) is True


# ---------------------------------------------------------------------------
# sync_uds_transaction
# ---------------------------------------------------------------------------

class TestSyncUdsTransaction:

    @pytest.mark.asyncio
    async def test_creates_client_and_order(self):
        tx = _parse_transaction(_make_raw_transaction())
        integram = _make_integram_mock(client_id=42, order_id=100)

        await sync_uds_transaction(tx, integram)

        integram.create_order.assert_called_once()
        call_kwargs = integram.create_order.call_args
        assert call_kwargs.kwargs.get("source") == "UDS"
        assert "UDS-tx-1" in call_kwargs.kwargs.get("number", "")

    @pytest.mark.asyncio
    async def test_notifies_beekeeper(self):
        tx = _parse_transaction(_make_raw_transaction())
        integram = _make_integram_mock()
        bot = MagicMock()
        bot.send_message = AsyncMock()

        await sync_uds_transaction(tx, integram, notify_chat_id=999, bot=bot)

        bot.send_message.assert_called_once()
        args = bot.send_message.call_args
        assert args[0][0] == 999  # chat_id
        assert "UDS" in args[0][1]

    @pytest.mark.asyncio
    async def test_no_notification_without_bot(self):
        tx = _parse_transaction(_make_raw_transaction())
        integram = _make_integram_mock()
        # bot=None — уведомление не отправляется, исключений нет
        await sync_uds_transaction(tx, integram, notify_chat_id=999, bot=None)
        integram.create_order.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_goods_creates_fallback_item(self):
        raw = _make_raw_transaction(items=[])
        tx = _parse_transaction(raw)
        integram = _make_integram_mock()

        await sync_uds_transaction(tx, integram)

        items_arg = integram.create_order.call_args[0][1]
        assert len(items_arg) == 1
        assert items_arg[0]["unit_price"] == 500.0  # fallback total

    @pytest.mark.asyncio
    async def test_product_lookup_used_for_sku(self):
        """Если у товара есть SKU, мы ищем его в каталоге Integram."""
        tx = _parse_transaction(_make_raw_transaction())
        integram = _make_integram_mock(product_id=7)

        await sync_uds_transaction(tx, integram)

        integram.get_product_by_name.assert_called_once_with("Перга")
        items_arg = integram.create_order.call_args[0][1]
        assert items_arg[0]["product_id"] == 7


# ---------------------------------------------------------------------------
# UDSPoller
# ---------------------------------------------------------------------------

class TestUDSPoller:

    @pytest.mark.asyncio
    async def test_polls_and_processes_new_transactions(self):
        raw = _make_raw_transaction(created_at="2099-01-01T00:00:00Z")  # будущая дата
        uds_client = MagicMock()
        uds_client.get_transactions = AsyncMock(return_value=[_parse_transaction(raw)])

        integram = _make_integram_mock()

        poller = UDSPoller(
            uds_client=uds_client,
            integram_client=integram,
            poll_interval=0,
        )
        # Установим since в прошлое, чтобы транзакция прошла дедупликацию
        poller._dedup._since = datetime(2026, 1, 1, tzinfo=timezone.utc)

        await poller._poll_once()

        integram.create_order.assert_called_once()
        assert "tx-1" in poller._dedup._seen

    @pytest.mark.asyncio
    async def test_skips_already_seen_transactions(self):
        tx = _parse_transaction(_make_raw_transaction(created_at="2099-01-01T00:00:00Z"))
        uds_client = MagicMock()
        uds_client.get_transactions = AsyncMock(return_value=[tx])

        integram = _make_integram_mock()
        poller = UDSPoller(uds_client=uds_client, integram_client=integram, poll_interval=0)
        poller._dedup._since = datetime(2026, 1, 1, tzinfo=timezone.utc)
        poller._dedup.mark_seen("tx-1")  # уже обработана

        await poller._poll_once()

        integram.create_order.assert_not_called()

    @pytest.mark.asyncio
    async def test_stops_polling_loop(self):
        uds_client = MagicMock()
        uds_client.get_transactions = AsyncMock(return_value=[])
        integram = _make_integram_mock()

        poller = UDSPoller(uds_client=uds_client, integram_client=integram, poll_interval=0)

        call_count = 0

        async def mock_poll_once():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                poller.stop()

        poller._poll_once = mock_poll_once

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await poller.run()

        assert call_count == 2
        assert not poller._running

    @pytest.mark.asyncio
    async def test_error_in_poll_does_not_crash_loop(self):
        """Ошибка в одном цикле не останавливает polling."""
        uds_client = MagicMock()
        uds_client.get_transactions = AsyncMock(side_effect=Exception("network error"))
        integram = _make_integram_mock()

        poller = UDSPoller(uds_client=uds_client, integram_client=integram, poll_interval=0)

        iteration = 0

        original_poll = poller._poll_once

        async def _poll_and_stop():
            nonlocal iteration
            iteration += 1
            if iteration >= 2:
                poller.stop()
            await original_poll()

        poller._poll_once = _poll_and_stop

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await poller.run()

        assert iteration >= 2

    @pytest.mark.asyncio
    async def test_context_manager_stops_poller(self):
        uds_client = MagicMock()
        integram = _make_integram_mock()
        async with UDSPoller(uds_client=uds_client, integram_client=integram) as poller:
            poller._running = True

        assert not poller._running


# ---------------------------------------------------------------------------
# sync_uds_catalog
# ---------------------------------------------------------------------------

class TestSyncUdsCatalog:

    @pytest.mark.asyncio
    async def test_maps_matching_skus(self):
        uds_client = MagicMock()
        uds_client.get_catalog = AsyncMock(return_value=[
            {"externalId": "SKU-001", "name": "Перга"},
            {"externalId": "SKU-002", "name": "Прополис"},
        ])

        product1 = MagicMock()
        product1.id = 10
        product1.sku_uds = "SKU-001"

        product2 = MagicMock()
        product2.id = 11
        product2.sku_uds = "SKU-002"

        integram = MagicMock()
        integram.get_products = AsyncMock(return_value=[product1, product2])

        mapping = await sync_uds_catalog(uds_client, integram)

        assert mapping == {"SKU-001": 10, "SKU-002": 11}

    @pytest.mark.asyncio
    async def test_logs_missing_items(self):
        uds_client = MagicMock()
        uds_client.get_catalog = AsyncMock(return_value=[
            {"externalId": "SKU-999", "name": "Неизвестный товар"},
        ])

        integram = MagicMock()
        integram.get_products = AsyncMock(return_value=[])

        mapping = await sync_uds_catalog(uds_client, integram)

        assert "SKU-999" not in mapping

    @pytest.mark.asyncio
    async def test_empty_catalog(self):
        uds_client = MagicMock()
        uds_client.get_catalog = AsyncMock(return_value=[])
        integram = MagicMock()
        integram.get_products = AsyncMock(return_value=[])

        mapping = await sync_uds_catalog(uds_client, integram)

        assert mapping == {}
