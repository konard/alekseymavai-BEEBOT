"""Провайдер доставки СДЭК.

Интеграция с API СДЭК для расчёта тарифов, создания отправлений
и отслеживания посылок.

Текущий статус: фиксированный тариф (реальный API не интегрирован).
Тариф: 350 ₽ базовая + 50 ₽/кг, срок 3–7 дней.
"""

from src.delivery.base import BaseDeliveryProvider, ShippingRate

# Базовый тариф СДЭК (фиксированный, без реального API)
_BASE_PRICE = 350.0   # ₽
_PRICE_PER_KG = 50.0  # ₽/кг
_DAYS_MIN = 3
_DAYS_MAX = 7


class CDEKProvider(BaseDeliveryProvider):
    """Провайдер доставки через СДЭК.

    Возвращает фиксированный тариф. В будущем заменить на вызов СДЭК API.
    """

    async def calculate_rate(
        self,
        origin_city: str,
        destination_city: str,
        weight_kg: float,
    ) -> ShippingRate:
        price = round(_BASE_PRICE + _PRICE_PER_KG * max(weight_kg, 0.1), 0)
        return ShippingRate(
            provider="СДЭК",
            price=price,
            currency="RUB",
            days_min=_DAYS_MIN,
            days_max=_DAYS_MAX,
        )

    async def create_shipment(self, order: dict) -> str:
        raise NotImplementedError("CDEKProvider.create_shipment не реализован")

    async def track_shipment(self, tracking_number: str) -> dict:
        raise NotImplementedError("CDEKProvider.track_shipment не реализован")
