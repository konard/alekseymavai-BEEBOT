"""Провайдер доставки Почта России.

Интеграция с API Почты России для расчёта тарифов, создания отправлений
и отслеживания посылок.

Текущий статус: фиксированный тариф (реальный API не интегрирован).
Тариф: 250 ₽ базовая + 30 ₽/кг, срок 7–14 дней.
"""

from src.delivery.base import BaseDeliveryProvider, ShippingRate

# Базовый тариф Почты России (фиксированный, без реального API)
_BASE_PRICE = 250.0   # ₽
_PRICE_PER_KG = 30.0  # ₽/кг
_DAYS_MIN = 7
_DAYS_MAX = 14


class PochtaProvider(BaseDeliveryProvider):
    """Провайдер доставки через Почту России.

    Возвращает фиксированный тариф. В будущем заменить на вызов API Почты.
    """

    async def calculate_rate(
        self,
        origin_city: str,
        destination_city: str,
        weight_kg: float,
    ) -> ShippingRate:
        price = round(_BASE_PRICE + _PRICE_PER_KG * max(weight_kg, 0.1), 0)
        return ShippingRate(
            provider="Почта России",
            price=price,
            currency="RUB",
            days_min=_DAYS_MIN,
            days_max=_DAYS_MAX,
        )

    async def create_shipment(self, order: dict) -> str:
        raise NotImplementedError("PochtaProvider.create_shipment не реализован")

    async def track_shipment(self, tracking_number: str) -> dict:
        raise NotImplementedError("PochtaProvider.track_shipment не реализован")
