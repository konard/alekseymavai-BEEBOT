"""Unit tests for src/agents/analyst.py — AnalystAgent."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.agents.analyst import (
    AnalystAgent,
    _filter_by_period,
    _keyword_classify,
    format_orders_report,
    format_packaging_report,
    format_summary_report,
    format_top_products_report,
)
from src.models import Order, OrderItem


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_order_item(
    product_id: int = 1,
    product_name: str = "Перга",
    quantity: int = 2,
    unit_price: float = 500.0,
) -> OrderItem:
    return OrderItem(
        id=1,
        order_id=1,
        product_id=product_id,
        product_name=product_name,
        **{
            "Количество": quantity,
            "Цена за шт.": unit_price,
            "Сумма": quantity * unit_price,
        },
    )


def _make_order(
    order_id: int = 1,
    status: str = "Выполнен",
    total: float = 1000.0,
    days_ago: int = 0,
    items: list[OrderItem] | None = None,
) -> Order:
    date = datetime.now() - timedelta(days=days_ago)
    return Order(
        id=order_id,
        **{
            "Номер": str(order_id),
            "Дата": date,
            "Статус": status,
        },
        client_id=1,
        total=total,
        items=items or [_make_order_item()],
    )


# ---------------------------------------------------------------------------
# _keyword_classify
# ---------------------------------------------------------------------------


class TestKeywordClassify:
    def test_week_period(self):
        period, _ = _keyword_classify("Сколько заказов за неделю?")
        assert period == "week"

    def test_month_period(self):
        period, _ = _keyword_classify("Статистика за месяц")
        assert period == "month"

    def test_month_period_named(self):
        period, _ = _keyword_classify("Статистика за март")
        assert period == "month"

    def test_all_period_default(self):
        period, _ = _keyword_classify("Общая статистика")
        assert period == "all"

    def test_packaging_report(self):
        _, report = _keyword_classify("Что нужно фасовать?")
        assert report == "packaging"

    def test_top_report(self):
        _, report = _keyword_classify("Какой товар продаётся лучше всего?")
        assert report == "top"

    def test_orders_report(self):
        _, report = _keyword_classify("Сколько заказов за неделю")
        assert report == "orders"

    def test_summary_default(self):
        _, report = _keyword_classify("Покажи что-нибудь интересное")
        assert report == "summary"


# ---------------------------------------------------------------------------
# _filter_by_period
# ---------------------------------------------------------------------------


class TestFilterByPeriod:
    def test_all_returns_everything(self):
        orders = [_make_order(days_ago=100), _make_order(days_ago=5)]
        result = _filter_by_period(orders, "all")
        assert len(result) == 2

    def test_week_filters_old(self):
        recent = _make_order(1, days_ago=3)
        old = _make_order(2, days_ago=10)
        result = _filter_by_period([recent, old], "week")
        assert recent in result
        assert old not in result

    def test_month_filters_old(self):
        recent = _make_order(1, days_ago=15)
        old = _make_order(2, days_ago=45)
        result = _filter_by_period([recent, old], "month")
        assert recent in result
        assert old not in result

    def test_empty_list(self):
        assert _filter_by_period([], "week") == []

    def test_week_includes_today(self):
        today = _make_order(1, days_ago=0)
        result = _filter_by_period([today], "week")
        assert today in result


# ---------------------------------------------------------------------------
# format_orders_report
# ---------------------------------------------------------------------------


class TestFormatOrdersReport:
    def test_empty_orders(self):
        result = format_orders_report([], "week")
        assert "нет данных" in result

    def test_shows_count(self):
        orders = [_make_order(1, total=500.0), _make_order(2, total=300.0)]
        result = format_orders_report(orders, "week")
        assert "2" in result

    def test_shows_revenue(self):
        orders = [_make_order(1, total=500.0), _make_order(2, total=300.0)]
        result = format_orders_report(orders, "week")
        assert "800" in result

    def test_shows_status(self):
        orders = [_make_order(1, status="Выполнен"), _make_order(2, status="Новый")]
        result = format_orders_report(orders, "all")
        assert "Выполнен" in result
        assert "Новый" in result

    def test_period_label_week(self):
        result = format_orders_report([], "week")
        assert "неделю" in result

    def test_period_label_month(self):
        result = format_orders_report([], "month")
        assert "месяц" in result

    def test_markdown_bold_total(self):
        orders = [_make_order(1, total=1000.0)]
        result = format_orders_report(orders, "all")
        assert "*" in result


# ---------------------------------------------------------------------------
# format_top_products_report
# ---------------------------------------------------------------------------


class TestFormatTopProductsReport:
    def test_empty_orders(self):
        result = format_top_products_report([], "all")
        assert "нет данных" in result

    def test_shows_product_names(self):
        item = _make_order_item(product_name="Прополис", quantity=3)
        orders = [_make_order(items=[item])]
        result = format_top_products_report(orders, "all")
        assert "Прополис" in result

    def test_shows_quantity(self):
        item = _make_order_item(product_name="Перга", quantity=5)
        orders = [_make_order(items=[item])]
        result = format_top_products_report(orders, "all")
        assert "5" in result

    def test_sorted_by_quantity(self):
        item1 = _make_order_item(product_id=1, product_name="Мёд", quantity=1)
        item2 = _make_order_item(product_id=2, product_name="Перга", quantity=10)
        orders = [_make_order(items=[item1, item2])]
        result = format_top_products_report(orders, "all")
        # Перга (10 шт.) должна быть выше Мёда (1 шт.)
        assert result.index("Перга") < result.index("Мёд")

    def test_top_n_limit(self):
        items = [
            _make_order_item(product_id=i, product_name=f"Товар{i}", quantity=i)
            for i in range(1, 8)
        ]
        orders = [_make_order(items=items)]
        result = format_top_products_report(orders, "all", top_n=3)
        # Только 3 позиции должны быть в топе (плюс заголовок)
        lines = [l for l in result.split("\n") if l.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7."))]
        assert len(lines) <= 3

    def test_no_items_in_orders(self):
        order = Order(
            id=1,
            **{"Номер": "1", "Дата": datetime.now(), "Статус": "Новый"},
            client_id=1,
            items=[],
        )
        result = format_top_products_report([order], "all")
        assert "нет позиций" in result


# ---------------------------------------------------------------------------
# format_packaging_report
# ---------------------------------------------------------------------------


class TestFormatPackagingReport:
    def test_empty_orders(self):
        result = format_packaging_report([], "month")
        assert "нет данных" in result

    def test_shows_product_name(self):
        item = _make_order_item(product_name="Пыльца", quantity=4)
        orders = [_make_order(items=[item])]
        result = format_packaging_report(orders, "month")
        assert "Пыльца" in result

    def test_sorted_by_demand(self):
        item1 = _make_order_item(product_id=1, product_name="Мёд", quantity=1)
        item2 = _make_order_item(product_id=2, product_name="Перга", quantity=10)
        orders = [_make_order(items=[item1, item2])]
        result = format_packaging_report(orders, "month")
        assert result.index("Перга") < result.index("Мёд")


# ---------------------------------------------------------------------------
# format_summary_report
# ---------------------------------------------------------------------------


class TestFormatSummaryReport:
    def test_contains_orders_section(self):
        orders = [_make_order(1, total=500.0)]
        result = format_summary_report(orders, "all")
        assert "Заказы" in result

    def test_contains_top_section(self):
        orders = [_make_order(1, total=500.0)]
        result = format_summary_report(orders, "all")
        assert "Топ товаров" in result


# ---------------------------------------------------------------------------
# AnalystAgent — unit tests with mocked CRM
# ---------------------------------------------------------------------------


class TestAnalystAgentInit:
    def test_no_crm_no_groq(self):
        agent = AnalystAgent()
        assert agent._crm is None
        assert agent._groq is None

    def test_with_crm(self):
        mock_crm = MagicMock()
        agent = AnalystAgent(integram_client=mock_crm)
        assert agent._crm is mock_crm


class TestAnalystAgentGetSalesSummary:
    @pytest.mark.asyncio
    async def test_no_crm_returns_empty(self):
        agent = AnalystAgent()
        summary = await agent.get_sales_summary()
        assert summary["total_orders"] == 0
        assert summary["total_revenue"] == 0.0
        assert summary["top_products"] == []

    @pytest.mark.asyncio
    async def test_with_orders(self):
        mock_crm = MagicMock()
        item = _make_order_item(product_name="Перга", quantity=3)
        orders = [_make_order(1, total=1500.0, items=[item])]
        mock_crm.get_orders = AsyncMock(return_value=orders)

        agent = AnalystAgent(integram_client=mock_crm)
        summary = await agent.get_sales_summary("all")

        assert summary["total_orders"] == 1
        assert summary["total_revenue"] == 1500.0
        assert summary["top_products"][0][0] == "Перга"
        assert summary["top_products"][0][1] == 3

    @pytest.mark.asyncio
    async def test_crm_error_returns_empty(self):
        mock_crm = MagicMock()
        mock_crm.get_orders = AsyncMock(side_effect=Exception("CRM недоступна"))

        agent = AnalystAgent(integram_client=mock_crm)
        summary = await agent.get_sales_summary()
        assert summary["total_orders"] == 0

    @pytest.mark.asyncio
    async def test_period_week(self):
        mock_crm = MagicMock()
        recent = _make_order(1, total=500.0, days_ago=3)
        old = _make_order(2, total=700.0, days_ago=15)
        mock_crm.get_orders = AsyncMock(return_value=[recent, old])

        agent = AnalystAgent(integram_client=mock_crm)
        summary = await agent.get_sales_summary("week")
        assert summary["total_orders"] == 1
        assert summary["total_revenue"] == 500.0


class TestAnalystAgentGetPackagingRecommendations:
    @pytest.mark.asyncio
    async def test_no_crm_returns_empty(self):
        agent = AnalystAgent()
        recs = await agent.get_packaging_recommendations()
        assert recs == []

    @pytest.mark.asyncio
    async def test_sorted_by_quantity(self):
        mock_crm = MagicMock()
        item1 = _make_order_item(product_id=1, product_name="Мёд", quantity=2)
        item2 = _make_order_item(product_id=2, product_name="Перга", quantity=7)
        orders = [_make_order(items=[item1, item2])]
        mock_crm.get_orders = AsyncMock(return_value=orders)

        agent = AnalystAgent(integram_client=mock_crm)
        recs = await agent.get_packaging_recommendations()

        assert recs[0]["name"] == "Перга"
        assert recs[0]["quantity"] == 7
        assert recs[1]["name"] == "Мёд"
        assert recs[1]["quantity"] == 2


class TestAnalystAgentHandleQuery:
    @pytest.mark.asyncio
    async def test_no_crm_returns_report(self):
        agent = AnalystAgent()
        result = await agent.handle_query("Общая статистика")
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.asyncio
    async def test_uses_llm_when_available(self):
        mock_groq = MagicMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "period=week report=top"
        mock_groq.chat.completions.create.return_value = MagicMock(
            choices=[mock_choice]
        )

        mock_crm = MagicMock()
        item = _make_order_item(product_name="Прополис", quantity=5)
        mock_crm.get_orders = AsyncMock(return_value=[_make_order(items=[item])])

        agent = AnalystAgent(
            integram_client=mock_crm,
            groq_client=mock_groq,
            groq_model="test-model",
        )
        result = await agent.handle_query("Топ товаров за неделю")
        assert "Прополис" in result
        mock_groq.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_when_llm_fails(self):
        mock_groq = MagicMock()
        mock_groq.chat.completions.create.side_effect = Exception("LLM недоступен")

        mock_crm = MagicMock()
        mock_crm.get_orders = AsyncMock(return_value=[])

        agent = AnalystAgent(
            integram_client=mock_crm,
            groq_client=mock_groq,
            groq_model="test-model",
        )
        # Should not raise — falls back to keyword classify
        result = await agent.handle_query("Что фасовать?")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_packaging_query(self):
        mock_crm = MagicMock()
        item = _make_order_item(product_name="Пыльца", quantity=10)
        mock_crm.get_orders = AsyncMock(return_value=[_make_order(items=[item])])

        agent = AnalystAgent(integram_client=mock_crm)
        result = await agent.handle_query("Что нужно фасовать?")
        assert "Пыльца" in result

    @pytest.mark.asyncio
    async def test_orders_query(self):
        mock_crm = MagicMock()
        orders = [_make_order(1, status="Выполнен", total=300.0)]
        mock_crm.get_orders = AsyncMock(return_value=orders)

        agent = AnalystAgent(integram_client=mock_crm)
        result = await agent.handle_query("Сколько заказов за неделю?")
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_empty_crm_returns_no_data_message(self):
        mock_crm = MagicMock()
        mock_crm.get_orders = AsyncMock(return_value=[])

        agent = AnalystAgent(integram_client=mock_crm)
        result = await agent.handle_query("Топ товаров")
        assert "нет данных" in result or "нет позиций" in result
