"""Агент «Аналитик» — статистика продаж и рекомендации по фасовке.

Анализирует историю заказов из Integram CRM, формирует отчёты:
- Заказы за период (неделя / месяц / произвольный)
- Топ продуктов по количеству и выручке
- Рекомендации по фасовке (что готовить в первую очередь)

Доступен только пользователям с ADMIN_CHAT_ID.
LLM парсит свободный текст в структурированный запрос.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Системный промпт для LLM-парсинга запроса
# ---------------------------------------------------------------------------

_PARSE_SYSTEM = (
    "Ты классификатор аналитических запросов. "
    "По тексту пользователя верни одну строку в формате:\n"
    "  period=<week|month|all>  — период анализа\n"
    "  report=<orders|top|packaging|summary>  — тип отчёта\n\n"
    "Правила:\n"
    "  week  — 'неделю', 'за 7 дней', 'на этой неделе'\n"
    "  month — 'месяц', 'март', 'за 30 дней', 'в этом месяце'\n"
    "  all   — 'всё время', 'за всё', без явного периода\n"
    "  orders    — сколько заказов, количество\n"
    "  top       — топ товаров, что продаётся лучше\n"
    "  packaging — что фасовать, что готовить\n"
    "  summary   — общая статистика или любой другой запрос\n\n"
    "Ответь ТОЛЬКО двумя параметрами через пробел, например: period=week report=top"
)


def _parse_analyst_query(groq_client, model: str, query: str) -> tuple[str, str]:
    """Распознать период и тип отчёта из свободного текста через LLM.

    Returns:
        (period, report_type) — период ('week'/'month'/'all') и тип отчёта.
    """
    try:
        resp = groq_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _PARSE_SYSTEM},
                {"role": "user", "content": query},
            ],
            max_tokens=20,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip()
        period = "all"
        report = "summary"
        for part in raw.split():
            if part.startswith("period="):
                val = part.split("=", 1)[1]
                if val in ("week", "month", "all"):
                    period = val
            elif part.startswith("report="):
                val = part.split("=", 1)[1]
                if val in ("orders", "top", "packaging", "summary"):
                    report = val
        return period, report
    except Exception as e:
        logger.warning("LLM-парсинг аналитического запроса не удался: %s", e)
        return "all", "summary"


# ---------------------------------------------------------------------------
# Форматирование отчётов (Telegram Markdown)
# ---------------------------------------------------------------------------


def _period_label(period: str) -> str:
    labels = {"week": "за неделю", "month": "за месяц", "all": "за всё время"}
    return labels.get(period, period)


def format_orders_report(orders: list, period: str) -> str:
    """Отчёт: количество заказов и общая выручка за период."""
    label = _period_label(period)
    if not orders:
        return f"📊 *Заказы {label}:* нет данных."

    total_revenue = sum((o.total or 0.0) for o in orders)
    statuses: Counter = Counter(o.status for o in orders)
    status_lines = "\n".join(f"  • {s}: {c}" for s, c in statuses.most_common())

    lines = [
        f"📊 *Заказы {label}:*\n",
        f"Всего заказов: *{len(orders)}*",
        f"Выручка: *{total_revenue:.0f} ₽*\n",
        "*По статусам:*",
        status_lines,
    ]
    return "\n".join(lines)


def format_top_products_report(orders: list, period: str, top_n: int = 5) -> str:
    """Отчёт: топ товаров по количеству проданных единиц и выручке."""
    label = _period_label(period)
    if not orders:
        return f"🏆 *Топ товаров {label}:* нет данных."

    qty_counter: Counter = Counter()
    revenue_counter: defaultdict[str, float] = defaultdict(float)

    for order in orders:
        for item in order.items:
            name = item.product_name or f"Товар #{item.product_id}"
            qty_counter[name] += item.quantity
            revenue_counter[name] += item.total

    if not qty_counter:
        return f"🏆 *Топ товаров {label}:* нет позиций в заказах."

    lines = [f"🏆 *Топ товаров {label}:*\n"]
    for i, (name, qty) in enumerate(qty_counter.most_common(top_n), start=1):
        rev = revenue_counter[name]
        lines.append(f"{i}. {name} — {qty} шт. / {rev:.0f} ₽")

    return "\n".join(lines)


def format_packaging_report(orders: list, period: str, top_n: int = 5) -> str:
    """Отчёт: рекомендации по фасовке — что готовить в первую очередь."""
    label = _period_label(period)
    if not orders:
        return f"📦 *Рекомендации по фасовке {label}:* нет данных."

    qty_counter: Counter = Counter()
    for order in orders:
        for item in order.items:
            name = item.product_name or f"Товар #{item.product_id}"
            qty_counter[name] += item.quantity

    if not qty_counter:
        return f"📦 *Рекомендации по фасовке {label}:* нет позиций."

    lines = [
        f"📦 *Рекомендации по фасовке {label}:*\n",
        "Фасовать в первую очередь (по спросу):\n",
    ]
    for i, (name, qty) in enumerate(qty_counter.most_common(top_n), start=1):
        lines.append(f"{i}. {name} — спрос: {qty} шт.")

    return "\n".join(lines)


def format_summary_report(orders: list, period: str) -> str:
    """Сводный отчёт: заказы + топ 3 товара."""
    orders_part = format_orders_report(orders, period)
    top_part = format_top_products_report(orders, period, top_n=3)
    return orders_part + "\n\n" + top_part


# ---------------------------------------------------------------------------
# Главный класс агента
# ---------------------------------------------------------------------------


class AnalystAgent:
    """Агент для аналитики продаж и рекомендаций по фасовке.

    Доступен только администратору (ADMIN_CHAT_ID).
    LLM (Groq) парсит свободный текст в структурированный запрос.
    """

    def __init__(self, integram_client=None, groq_client=None, groq_model: str = ""):
        """
        Args:
            integram_client: IntegramClient или None (без CRM).
            groq_client:     groq.Groq-клиент для LLM-парсинга запросов.
            groq_model:      Название модели Groq.
        """
        self._crm = integram_client
        self._groq = groq_client
        self._model = groq_model

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    async def handle_query(self, query: str) -> str:
        """Обработать свободный текстовый запрос от администратора.

        Шаги:
          1. LLM парсит запрос → period + report_type.
          2. Загрузить заказы из Integram за период.
          3. Сформировать отчёт в Telegram Markdown.

        Returns:
            Текст отчёта для отправки в Telegram.
        """
        period, report_type = self._classify_query(query)
        orders = await self._fetch_orders(period)
        return self._build_report(orders, period, report_type)

    async def get_sales_summary(self, period: str = "all") -> dict:
        """Получить сводку продаж за период.

        Args:
            period: 'week', 'month' или 'all'.

        Returns:
            dict с ключами: total_orders, total_revenue, top_products.
        """
        orders = await self._fetch_orders(period)
        total_revenue = sum((o.total or 0.0) for o in orders)
        qty_counter: Counter = Counter()
        for order in orders:
            for item in order.items:
                name = item.product_name or f"Товар #{item.product_id}"
                qty_counter[name] += item.quantity

        return {
            "total_orders": len(orders),
            "total_revenue": total_revenue,
            "top_products": qty_counter.most_common(5),
            "period": period,
        }

    async def get_packaging_recommendations(self, period: str = "month") -> list[dict]:
        """Получить рекомендации по фасовке на основе истории заказов.

        Args:
            period: 'week', 'month' или 'all'.

        Returns:
            Список dict: {name, quantity} — отсортированный по убыванию спроса.
        """
        orders = await self._fetch_orders(period)
        qty_counter: Counter = Counter()
        for order in orders:
            for item in order.items:
                name = item.product_name or f"Товар #{item.product_id}"
                qty_counter[name] += item.quantity

        return [
            {"name": name, "quantity": qty}
            for name, qty in qty_counter.most_common()
        ]

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _classify_query(self, query: str) -> tuple[str, str]:
        """Распознать период и тип отчёта.

        Если LLM недоступен — простой keyword-парсинг как fallback.
        """
        if self._groq and self._model:
            return _parse_analyst_query(self._groq, self._model, query)
        return _keyword_classify(query)

    async def _fetch_orders(self, period: str) -> list:
        """Загрузить заказы из CRM с фильтрацией по дате."""
        if not self._crm:
            logger.info("CRM недоступна — аналитика без данных.")
            return []

        try:
            all_orders = await self._crm.get_orders()
        except Exception as e:
            logger.error("Не удалось загрузить заказы: %s", e)
            return []

        return _filter_by_period(all_orders, period)

    def _build_report(self, orders: list, period: str, report_type: str) -> str:
        """Сформировать текстовый отчёт нужного типа."""
        if report_type == "orders":
            return format_orders_report(orders, period)
        elif report_type == "top":
            return format_top_products_report(orders, period)
        elif report_type == "packaging":
            return format_packaging_report(orders, period)
        else:
            return format_summary_report(orders, period)


# ---------------------------------------------------------------------------
# Вспомогательные функции (вне класса, для тестируемости)
# ---------------------------------------------------------------------------


def _keyword_classify(query: str) -> tuple[str, str]:
    """Keyword-классификатор как fallback когда LLM недоступен."""
    q = query.lower()

    # Период
    if any(w in q for w in ("неделю", "неделя", "7 дней", "на этой неделе")):
        period = "week"
    elif any(w in q for w in ("месяц", "30 дней", "в этом месяце",
                               "январ", "феврал", "март", "апрел", "май", "июн",
                               "июл", "август", "сентябр", "октябр", "ноябр", "декабр")):
        period = "month"
    else:
        period = "all"

    # Тип отчёта
    if any(w in q for w in ("фасов", "готовить", "упаковат", "запас")):
        report = "packaging"
    elif any(w in q for w in ("топ", "лучш", "популярн", "продаётся", "продается")):
        report = "top"
    elif any(w in q for w in ("сколько заказов", "количество заказов", "заказов за")):
        report = "orders"
    else:
        report = "summary"

    return period, report


def _filter_by_period(orders: list, period: str) -> list:
    """Отфильтровать заказы по периоду (week / month / all)."""
    if period == "all":
        return orders

    now = datetime.now()
    if period == "week":
        cutoff = now - timedelta(days=7)
    else:  # month
        cutoff = now - timedelta(days=30)

    filtered = []
    for order in orders:
        try:
            order_date = order.date if isinstance(order.date, datetime) else datetime.fromisoformat(str(order.date))
            if order_date >= cutoff:
                filtered.append(order)
        except Exception:
            filtered.append(order)  # при ошибке парсинга — включаем

    return filtered
