"""Unit tests for src/agents/logist.py — LogistAgent FSM logic."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.agents.logist import (
    LogistAgent,
    OrderFSM,
    calculate_delivery_cost,
    format_product_catalog,
    format_order_summary,
    ORDER_TIMEOUT_SECONDS,
)
from src.models import Product


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_product(
    idx: int = 1,
    name: str = "Перга",
    price: float = 500.0,
    weight: float = 200.0,
) -> Product:
    return Product(
        id=idx,
        **{
            "Название": name,
            "Категория": "Продукты пчеловодства",
            "Цена": price,
            "Вес": weight,
            "Описание": "Тестовый продукт",
            "В наличии": True,
            "Артикул UDS": None,
        },
    )


def _make_cart(qty: int = 1, unit_price: float = 500.0, weight: int = 200) -> list[dict]:
    return [
        {
            "product_id": 1,
            "name": "Перга",
            "qty": qty,
            "unit_price": unit_price,
            "weight": weight,
        }
    ]


# ---------------------------------------------------------------------------
# OrderFSM states
# ---------------------------------------------------------------------------


class TestOrderFSMStates:
    """Verify all 7 FSM states are defined."""

    def test_has_seven_states(self):
        states = [
            OrderFSM.choosing_product,
            OrderFSM.entering_name,
            OrderFSM.entering_phone,
            OrderFSM.entering_address,
            OrderFSM.choosing_delivery,
            OrderFSM.confirming_order,
            OrderFSM.creating_order,
        ]
        assert len(states) == 7

    def test_state_names_are_unique(self):
        states = [
            str(OrderFSM.choosing_product),
            str(OrderFSM.entering_name),
            str(OrderFSM.entering_phone),
            str(OrderFSM.entering_address),
            str(OrderFSM.choosing_delivery),
            str(OrderFSM.confirming_order),
            str(OrderFSM.creating_order),
        ]
        assert len(set(states)) == 7


# ---------------------------------------------------------------------------
# ORDER_TIMEOUT_SECONDS
# ---------------------------------------------------------------------------


class TestTimeout:
    def test_timeout_is_15_minutes(self):
        assert ORDER_TIMEOUT_SECONDS == 15 * 60


# ---------------------------------------------------------------------------
# calculate_delivery_cost
# ---------------------------------------------------------------------------


class TestCalculateDeliveryCost:
    """Tests for the delivery cost calculation function."""

    @pytest.mark.asyncio
    async def test_samovyvoz_is_free(self):
        cart = _make_cart(qty=2, weight=500)
        cost = await calculate_delivery_cost("Самовывоз", "Москва", cart)
        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_cdek_base_rate(self):
        """СДЭК: 350 base + 50/kg. 0.2 kg → max(0.2, 0.1) = 0.2 → 360."""
        cart = _make_cart(qty=1, weight=200)
        cost = await calculate_delivery_cost("СДЭК", "Москва", cart)
        assert cost == 360.0

    @pytest.mark.asyncio
    async def test_pochta_base_rate(self):
        """Почта: 250 base + 30/kg. 0.2 kg → 256."""
        cart = _make_cart(qty=1, weight=200)
        cost = await calculate_delivery_cost("Почта России", "Москва", cart)
        assert cost == 256.0

    @pytest.mark.asyncio
    async def test_cdek_heavier_shipment(self):
        """СДЭК with 2 kg: 350 + 50 * 2 = 450."""
        cart = _make_cart(qty=4, weight=500)  # 4 * 500g = 2000g = 2 kg
        cost = await calculate_delivery_cost("СДЭК", "Москва", cart)
        assert cost == 450.0

    @pytest.mark.asyncio
    async def test_unknown_method_is_free(self):
        cart = _make_cart()
        cost = await calculate_delivery_cost("Неизвестный метод", "Москва", cart)
        assert cost == 0.0

    @pytest.mark.asyncio
    async def test_minimum_weight_floor(self):
        """Empty cart weight treated as 0.1 kg minimum."""
        cost = await calculate_delivery_cost("СДЭК", "Москва", [])
        # 0.1 kg min → 350 + 50 * 0.1 = 355
        assert cost == 355.0


# ---------------------------------------------------------------------------
# format_product_catalog
# ---------------------------------------------------------------------------


class TestFormatProductCatalog:
    def test_empty_catalog_returns_message(self):
        result = format_product_catalog([])
        assert "недоступен" in result.lower()

    def test_contains_product_names(self):
        products = [_make_product(1, "Перга"), _make_product(2, "Прополис")]
        result = format_product_catalog(products)
        assert "Перга" in result
        assert "Прополис" in result

    def test_numbered_list(self):
        products = [_make_product(1, "Перга"), _make_product(2, "Прополис")]
        result = format_product_catalog(products)
        assert "1." in result
        assert "2." in result

    def test_price_shown_when_available(self):
        products = [_make_product(1, "Перга", price=450.0)]
        result = format_product_catalog(products)
        assert "450" in result

    def test_cancel_hint_shown(self):
        products = [_make_product(1, "Перга")]
        result = format_product_catalog(products)
        assert "/cancel" in result


# ---------------------------------------------------------------------------
# format_order_summary
# ---------------------------------------------------------------------------


class TestFormatOrderSummary:
    def test_contains_full_name(self):
        cart = _make_cart()
        result = format_order_summary(cart, "Иванов Иван", "+79991234567", "Москва", "СДЭК", 360.0)
        assert "Иванов Иван" in result

    def test_contains_delivery_method(self):
        cart = _make_cart()
        result = format_order_summary(cart, "Иванов Иван", "+79991234567", "Москва", "Почта России", 256.0)
        assert "Почта России" in result

    def test_total_includes_delivery(self):
        cart = _make_cart(qty=1, unit_price=500.0)
        result = format_order_summary(cart, "Иванов Иван", "+79991234567", "Москва", "СДЭК", 360.0)
        # items_total = 500, delivery = 360, total = 860
        assert "860" in result

    def test_confirm_prompt_present(self):
        cart = _make_cart()
        result = format_order_summary(cart, "Тест", "+7000", "Адрес", "Самовывоз", 0.0)
        assert "да" in result.lower() or "нет" in result.lower()


# ---------------------------------------------------------------------------
# LogistAgent.parse_product_selection
# ---------------------------------------------------------------------------


class TestParseProductSelection:
    def setup_method(self):
        self.agent = LogistAgent()
        self.products = [
            {"id": 1, "name": "Перга", "price": 500.0, "weight": 200},
            {"id": 2, "name": "Прополис", "price": 300.0, "weight": 100},
            {"id": 3, "name": "Гомогенат", "price": 800.0, "weight": 50},
        ]

    def test_single_selection(self):
        cart, err = self.agent.parse_product_selection("1", self.products)
        assert err == ""
        assert len(cart) == 1
        assert cart[0]["product_id"] == 1
        assert cart[0]["qty"] == 1

    def test_multiple_selection(self):
        cart, err = self.agent.parse_product_selection("1,3", self.products)
        assert err == ""
        assert len(cart) == 2

    def test_quantity_with_x(self):
        cart, err = self.agent.parse_product_selection("2x3", self.products)
        assert err == ""
        assert cart[0]["product_id"] == 2
        assert cart[0]["qty"] == 3

    def test_invalid_number_returns_error(self):
        cart, err = self.agent.parse_product_selection("abc", self.products)
        assert cart == []
        assert err != ""

    def test_out_of_range_returns_error(self):
        cart, err = self.agent.parse_product_selection("99", self.products)
        assert cart == []
        assert err != ""

    def test_empty_input_returns_error(self):
        cart, err = self.agent.parse_product_selection("", self.products)
        assert cart == []
        assert err != ""

    def test_duplicate_products_merged(self):
        cart, err = self.agent.parse_product_selection("1,1", self.products)
        assert err == ""
        assert len(cart) == 1
        assert cart[0]["qty"] == 2

    def test_price_copied_to_cart(self):
        cart, err = self.agent.parse_product_selection("2", self.products)
        assert err == ""
        assert cart[0]["unit_price"] == 300.0


# ---------------------------------------------------------------------------
# LogistAgent.start_order
# ---------------------------------------------------------------------------


class TestStartOrder:
    @pytest.mark.asyncio
    async def test_returns_catalog_text_and_products(self):
        agent = LogistAgent()
        text, products = await agent.start_order(user_id=12345)
        assert isinstance(text, str)
        assert len(products) > 0  # fallback catalog

    @pytest.mark.asyncio
    async def test_uses_crm_when_available(self):
        mock_crm = AsyncMock()
        mock_crm.get_products.return_value = [_make_product(1, "Перга", 500.0)]
        agent = LogistAgent(integram_client=mock_crm)

        text, products = await agent.start_order(user_id=12345)
        mock_crm.get_products.assert_called_once_with(in_stock_only=True)
        assert len(products) == 1

    @pytest.mark.asyncio
    async def test_falls_back_to_static_catalog_on_crm_error(self):
        mock_crm = AsyncMock()
        mock_crm.get_products.side_effect = Exception("CRM недоступна")
        agent = LogistAgent(integram_client=mock_crm)

        text, products = await agent.start_order(user_id=12345)
        assert len(products) > 0  # fallback catalog должен работать


# ---------------------------------------------------------------------------
# LogistAgent.get_delivery_options
# ---------------------------------------------------------------------------


class TestGetDeliveryOptions:
    @pytest.mark.asyncio
    async def test_returns_three_options(self):
        agent = LogistAgent()
        cart = _make_cart()
        options = await agent.get_delivery_options(cart)
        assert len(options) == 3

    @pytest.mark.asyncio
    async def test_samovyvoz_is_free(self):
        agent = LogistAgent()
        cart = _make_cart()
        options = await agent.get_delivery_options(cart)
        samovyvoz = next(o for o in options if o["method"] == "Самовывоз")
        assert samovyvoz["cost"] == 0.0

    @pytest.mark.asyncio
    async def test_options_have_labels(self):
        agent = LogistAgent()
        options = await agent.get_delivery_options(_make_cart())
        for opt in options:
            assert "label" in opt
            assert len(opt["label"]) > 0


# ---------------------------------------------------------------------------
# LogistAgent.create_order — без CRM
# ---------------------------------------------------------------------------


class TestCreateOrderNoCRM:
    @pytest.mark.asyncio
    async def test_returns_success_without_crm(self):
        agent = LogistAgent()
        success, msg = await agent.create_order(
            telegram_id=12345,
            full_name="Иванов Иван",
            phone="+79991234567",
            address="Москва, ул. Ленина, 1",
            delivery="СДЭК",
            delivery_cost=360.0,
            cart=_make_cart(),
        )
        assert success is True
        assert "Иванов Иван" in msg or "принят" in msg.lower()

    @pytest.mark.asyncio
    async def test_message_contains_total(self):
        agent = LogistAgent()
        cart = _make_cart(qty=1, unit_price=500.0)
        success, msg = await agent.create_order(
            telegram_id=12345,
            full_name="Тест",
            phone="+7000",
            address="Адрес",
            delivery="Самовывоз",
            delivery_cost=0.0,
            cart=cart,
        )
        assert success is True
        assert "500" in msg  # items total


# ---------------------------------------------------------------------------
# LogistAgent.create_order — с CRM
# ---------------------------------------------------------------------------


class TestCreateOrderWithCRM:
    @pytest.mark.asyncio
    async def test_calls_crm_to_create_order(self):
        mock_crm = AsyncMock()
        mock_client = MagicMock()
        mock_client.id = 42
        mock_crm.get_or_create_client.return_value = mock_client
        mock_crm.update_client.return_value = None
        mock_order = MagicMock()
        mock_order.number = "ORD-001"
        mock_crm.create_order.return_value = mock_order

        agent = LogistAgent(integram_client=mock_crm)
        success, msg = await agent.create_order(
            telegram_id=12345,
            full_name="Иванов Иван",
            phone="+79991234567",
            address="Москва, ул. Пушкина, 1",
            delivery="СДЭК",
            delivery_cost=360.0,
            cart=_make_cart(),
        )
        assert success is True
        mock_crm.create_order.assert_called_once()
        assert "ORD-001" in msg

    @pytest.mark.asyncio
    async def test_returns_failure_on_crm_error(self):
        mock_crm = AsyncMock()
        mock_client = MagicMock()
        mock_client.id = 42
        mock_crm.get_or_create_client.return_value = mock_client
        mock_crm.update_client.return_value = None
        mock_crm.create_order.side_effect = Exception("CRM недоступна")

        agent = LogistAgent(integram_client=mock_crm)
        success, msg = await agent.create_order(
            telegram_id=12345,
            full_name="Иванов Иван",
            phone="+79991234567",
            address="Москва",
            delivery="СДЭК",
            delivery_cost=360.0,
            cart=_make_cart(),
        )
        assert success is False


# ---------------------------------------------------------------------------
# LogistAgent.notify_beekeeper
# ---------------------------------------------------------------------------


class TestNotifyBeekeeper:
    @pytest.mark.asyncio
    async def test_sends_message_when_chat_id_set(self):
        mock_bot = AsyncMock()
        agent = LogistAgent(beekeeper_chat_id=99999)
        await agent.notify_beekeeper(mock_bot, "Новый заказ: Перга × 1")
        mock_bot.send_message.assert_called_once()
        call_args = mock_bot.send_message.call_args
        assert call_args[0][0] == 99999

    @pytest.mark.asyncio
    async def test_skips_when_no_chat_id(self):
        mock_bot = AsyncMock()
        agent = LogistAgent(beekeeper_chat_id=None)
        await agent.notify_beekeeper(mock_bot, "Новый заказ")
        mock_bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_raise_on_send_error(self):
        mock_bot = AsyncMock()
        mock_bot.send_message.side_effect = Exception("Telegram error")
        agent = LogistAgent(beekeeper_chat_id=12345)
        # Should not raise
        await agent.notify_beekeeper(mock_bot, "Новый заказ")


# ---------------------------------------------------------------------------
# LogistAgent.collect_shipping_info — legacy stub
# ---------------------------------------------------------------------------


class TestLegacyCollectShippingInfo:
    @pytest.mark.asyncio
    async def test_raises_not_implemented(self):
        agent = LogistAgent()
        with pytest.raises(NotImplementedError):
            await agent.collect_shipping_info(12345)
