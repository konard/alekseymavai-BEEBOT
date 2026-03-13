"""Тесты для модели данных CRM (src/crm_schema.py).

Проверяют:
  - корректность определений всех 8 таблиц
  - наличие обязательных полей
  - целостность ссылок (REF-поля ссылаются на существующие таблицы)
  - полноту справочных данных
  - полноту каталога товаров (14 позиций)
  - подчинённость «Позиции заказа» → «Заказы»
"""

import pytest

from src.crm_schema import (
    ALL_TABLES,
    INITIAL_PRODUCTS,
    PRODUCT_CATEGORIES,
    CLIENT_SOURCES,
    ORDER_STATUSES,
    DELIVERY_METHODS,
    REFERENCE_DATA,
    TABLE_CLIENTS,
    TABLE_DELIVERY_METHODS,
    TABLE_ORDER_ITEMS,
    TABLE_ORDER_STATUSES,
    TABLE_ORDERS,
    TABLE_PRODUCT_CATEGORIES,
    TABLE_PRODUCTS,
    TABLE_CLIENT_SOURCES,
    FieldType,
)


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _table_names() -> set[str]:
    return {t.name for t in ALL_TABLES}


def _fields_by_name(table):
    return {f.name: f for f in table.fields}


# ---------------------------------------------------------------------------
# Тесты: структура ALL_TABLES
# ---------------------------------------------------------------------------

def test_all_tables_count():
    """Должно быть ровно 8 таблиц."""
    assert len(ALL_TABLES) == 8


def test_all_tables_names():
    """Все 8 таблиц присутствуют с ожидаемыми именами."""
    expected = {
        "Категории товаров",
        "Товары",
        "Источники",
        "Клиенты",
        "Статусы заказов",
        "Способы доставки",
        "Заказы",
        "Позиции заказа",
    }
    assert _table_names() == expected


def test_tables_order_reference_tables_first():
    """Справочные таблицы должны идти раньше зависимых.

    «Категории товаров» перед «Товары»,
    «Источники» перед «Клиенты» и «Заказы».
    """
    names = [t.name for t in ALL_TABLES]
    assert names.index("Категории товаров") < names.index("Товары")
    assert names.index("Источники") < names.index("Клиенты")
    assert names.index("Источники") < names.index("Заказы")
    assert names.index("Заказы") < names.index("Позиции заказа")


# ---------------------------------------------------------------------------
# Тесты: таблица «Товары»
# ---------------------------------------------------------------------------

def test_products_table_has_required_fields():
    fields = _fields_by_name(TABLE_PRODUCTS)
    assert "Название" in fields
    assert fields["Название"].required is True
    assert fields["Название"].field_type == FieldType.SHORT

    assert "Категория" in fields
    assert fields["Категория"].field_type == FieldType.REF
    assert fields["Категория"].ref_table == "Категории товаров"

    assert "Цена" in fields
    assert fields["Цена"].field_type == FieldType.NUMBER

    assert "Вес" in fields
    assert fields["Вес"].field_type == FieldType.NUMBER

    assert "Описание" in fields
    assert fields["Описание"].field_type == FieldType.LONG

    assert "В наличии" in fields
    assert fields["В наличии"].field_type == FieldType.BOOL

    assert "Артикул UDS" in fields
    assert fields["Артикул UDS"].field_type == FieldType.SHORT


# ---------------------------------------------------------------------------
# Тесты: таблица «Клиенты»
# ---------------------------------------------------------------------------

def test_clients_table_has_required_fields():
    fields = _fields_by_name(TABLE_CLIENTS)
    assert "ФИО" in fields
    assert fields["ФИО"].required is True
    assert fields["ФИО"].field_type == FieldType.SHORT

    assert "Телефон" in fields
    assert fields["Телефон"].field_type == FieldType.SHORT

    assert "Telegram ID" in fields
    assert fields["Telegram ID"].field_type == FieldType.NUMBER

    assert "Telegram Username" in fields
    assert fields["Telegram Username"].field_type == FieldType.SHORT

    assert "Адрес" in fields
    assert fields["Адрес"].field_type == FieldType.LONG

    assert "Город" in fields
    assert fields["Город"].field_type == FieldType.SHORT

    assert "Источник" in fields
    assert fields["Источник"].field_type == FieldType.REF
    assert fields["Источник"].ref_table == "Источники"


# ---------------------------------------------------------------------------
# Тесты: таблица «Заказы»
# ---------------------------------------------------------------------------

def test_orders_table_has_required_fields():
    fields = _fields_by_name(TABLE_ORDERS)
    assert "Номер" in fields
    assert fields["Номер"].required is True
    assert fields["Номер"].field_type == FieldType.SHORT

    assert "Клиент" in fields
    assert fields["Клиент"].field_type == FieldType.REF
    assert fields["Клиент"].ref_table == "Клиенты"

    assert "Дата" in fields
    assert fields["Дата"].field_type == FieldType.DATETIME

    assert "Статус" in fields
    assert fields["Статус"].field_type == FieldType.REF
    assert fields["Статус"].ref_table == "Статусы заказов"

    assert "Способ доставки" in fields
    assert fields["Способ доставки"].field_type == FieldType.REF
    assert fields["Способ доставки"].ref_table == "Способы доставки"

    assert "Адрес доставки" in fields
    assert fields["Адрес доставки"].field_type == FieldType.LONG

    assert "Стоимость доставки" in fields
    assert fields["Стоимость доставки"].field_type == FieldType.NUMBER

    assert "Сумма товаров" in fields
    assert fields["Сумма товаров"].field_type == FieldType.NUMBER

    assert "Итого" in fields
    assert fields["Итого"].field_type == FieldType.NUMBER

    assert "Трек-номер" in fields
    assert fields["Трек-номер"].field_type == FieldType.SHORT

    assert "Источник" in fields
    assert fields["Источник"].field_type == FieldType.REF
    assert fields["Источник"].ref_table == "Источники"


# ---------------------------------------------------------------------------
# Тесты: таблица «Позиции заказа»
# ---------------------------------------------------------------------------

def test_order_items_is_subordinate_to_orders():
    """Позиции заказа должны быть подчинены таблице Заказы."""
    assert TABLE_ORDER_ITEMS.is_subordinate_of == "Заказы"


def test_order_items_has_required_fields():
    fields = _fields_by_name(TABLE_ORDER_ITEMS)
    assert "Товар" in fields
    assert fields["Товар"].field_type == FieldType.REF
    assert fields["Товар"].ref_table == "Товары"

    assert "Количество" in fields
    assert fields["Количество"].field_type == FieldType.NUMBER
    assert fields["Количество"].required is True

    assert "Цена за шт." in fields
    assert fields["Цена за шт."].field_type == FieldType.NUMBER

    assert "Сумма" in fields
    assert fields["Сумма"].field_type == FieldType.NUMBER


# ---------------------------------------------------------------------------
# Тесты: целостность REF-ссылок
# ---------------------------------------------------------------------------

def test_ref_fields_point_to_existing_tables():
    """Все REF-поля должны ссылаться на таблицы, которые присутствуют в ALL_TABLES."""
    table_names = _table_names()
    for table in ALL_TABLES:
        for f in table.fields:
            if f.field_type == FieldType.REF:
                assert f.ref_table is not None, (
                    f"Поле {f.name} в {table.name} имеет тип REF, но ref_table не задан"
                )
                assert f.ref_table in table_names, (
                    f"Поле {f.name} в {table.name} ссылается на несуществующую "
                    f"таблицу «{f.ref_table}»"
                )


# ---------------------------------------------------------------------------
# Тесты: справочные данные
# ---------------------------------------------------------------------------

def test_product_categories_count():
    assert len(PRODUCT_CATEGORIES) == 3


def test_product_categories_values():
    assert "Продукты пчеловодства" in PRODUCT_CATEGORIES
    assert "Настойки" in PRODUCT_CATEGORIES
    assert "Программы здоровья" in PRODUCT_CATEGORIES


def test_client_sources_count():
    assert len(CLIENT_SOURCES) == 4


def test_client_sources_values():
    assert "Telegram" in CLIENT_SOURCES
    assert "UDS" in CLIENT_SOURCES
    assert "WhatsApp" in CLIENT_SOURCES
    assert "Ручной ввод" in CLIENT_SOURCES


def test_order_statuses_count():
    assert len(ORDER_STATUSES) == 6


def test_order_statuses_values():
    for status in ["Новый", "Подтверждён", "В сборке", "Отправлен", "Доставлен", "Отменён"]:
        assert status in ORDER_STATUSES


def test_delivery_methods_count():
    assert len(DELIVERY_METHODS) == 3


def test_delivery_methods_values():
    assert "СДЭК" in DELIVERY_METHODS
    assert "Почта России" in DELIVERY_METHODS
    assert "Самовывоз" in DELIVERY_METHODS


def test_reference_data_keys_match_tables():
    """Ключи REFERENCE_DATA должны соответствовать именам таблиц из ALL_TABLES."""
    table_names = _table_names()
    for key in REFERENCE_DATA:
        assert key in table_names, (
            f"Ключ «{key}» в REFERENCE_DATA не соответствует ни одной таблице"
        )


# ---------------------------------------------------------------------------
# Тесты: начальный каталог товаров
# ---------------------------------------------------------------------------

def test_initial_products_count():
    """Должно быть ровно 14 товаров — по каталогу бота."""
    assert len(INITIAL_PRODUCTS) == 14


def test_initial_products_categories_are_valid():
    """Каждый товар должен принадлежать одной из трёх категорий."""
    valid_categories = set(PRODUCT_CATEGORIES)
    for product in INITIAL_PRODUCTS:
        assert product.category in valid_categories, (
            f"Товар «{product.name}» имеет неизвестную категорию «{product.category}»"
        )


def test_initial_products_names_unique():
    """Имена товаров должны быть уникальны."""
    names = [p.name for p in INITIAL_PRODUCTS]
    assert len(names) == len(set(names)), "Обнаружены дублирующиеся имена товаров"


def test_initial_products_have_names():
    """Все товары должны иметь непустое имя."""
    for product in INITIAL_PRODUCTS:
        assert product.name.strip(), "Обнаружен товар с пустым именем"


def test_initial_products_per_category():
    """Проверяем количество товаров по категориям (3 + 7 + 4 = 14)."""
    from collections import Counter
    counts = Counter(p.category for p in INITIAL_PRODUCTS)
    assert counts["Продукты пчеловодства"] == 3
    assert counts["Настойки"] == 7
    assert counts["Программы здоровья"] == 4
