"""Модель данных CRM Integram для «Усадьба Дмитровых».

Определяет структуру 8 таблиц:
  1. Категории товаров
  2. Товары
  3. Источники
  4. Клиенты
  5. Статусы заказов
  6. Способы доставки
  7. Заказы
  8. Позиции заказа (подчинённая к Заказам)

Используется как единственный источник истины (Single Source of Truth)
при создании таблиц в Integram через MCP.
"""

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Типы полей Integram
# ---------------------------------------------------------------------------

class FieldType(str, Enum):
    SHORT = "SHORT"        # Короткий текст
    LONG = "LONG"          # Длинный текст
    NUMBER = "NUMBER"      # Числовое значение
    BOOL = "BOOL"          # Логическое (да/нет)
    DATETIME = "DATETIME"  # Дата и время
    REF = "REF"            # Ссылка на другую таблицу


# ---------------------------------------------------------------------------
# Вспомогательные структуры
# ---------------------------------------------------------------------------

@dataclass
class FieldDef:
    """Определение поля таблицы Integram."""
    name: str
    field_type: FieldType
    required: bool = False
    ref_table: str | None = None  # Для типа REF — имя таблицы-справочника


@dataclass
class TableDef:
    """Определение таблицы Integram."""
    name: str
    fields: list[FieldDef]
    is_subordinate_of: str | None = None  # Для подчинённых таблиц


# ---------------------------------------------------------------------------
# Справочные значения
# ---------------------------------------------------------------------------

PRODUCT_CATEGORIES: list[str] = [
    "Продукты пчеловодства",
    "Настойки",
    "Программы здоровья",
]

CLIENT_SOURCES: list[str] = [
    "Telegram",
    "UDS",
    "WhatsApp",
    "Ручной ввод",
]

ORDER_STATUSES: list[str] = [
    "Новый",
    "Подтверждён",
    "В сборке",
    "Отправлен",
    "Доставлен",
    "Отменён",
]

DELIVERY_METHODS: list[str] = [
    "СДЭК",
    "Почта России",
    "Самовывоз",
]


# ---------------------------------------------------------------------------
# Начальный каталог продуктов (14 позиций из бота)
# ---------------------------------------------------------------------------

@dataclass
class ProductSeed:
    """Начальные данные для таблицы Товары."""
    name: str
    category: str
    in_stock: bool = True
    sku_uds: str = ""
    description: str = ""


INITIAL_PRODUCTS: list[ProductSeed] = [
    # Продукты пчеловодства
    ProductSeed(
        name="Перга",
        category="Продукты пчеловодства",
        in_stock=True,
        description="Пчелиный хлеб — богатый источник белков, витаминов и минералов.",
    ),
    ProductSeed(
        name="Пчелиная обножка",
        category="Продукты пчеловодства",
        in_stock=True,
        description="Свежесобранная пыльца — природный витаминный комплекс.",
    ),
    ProductSeed(
        name="Трутнёвый гомогенат",
        category="Продукты пчеловодства",
        in_stock=True,
        description="Гомогенат трутнёвого расплода — источник гормональных предшественников.",
    ),
    # Настойки
    ProductSeed(
        name="Прополис (сухой + настойка)",
        category="Настойки",
        in_stock=True,
        description="Природный антибиотик. Укрепляет иммунитет, борется с вирусами.",
    ),
    ProductSeed(
        name="Настойка ПЖВМ",
        category="Настойки",
        in_stock=True,
        description="Настойка подмора живых восковых молей (огнёвки).",
    ),
    ProductSeed(
        name="Настойка подмора пчелиного",
        category="Настойки",
        in_stock=True,
        description="Настойка подмора пчелиного на самогоне 40°.",
    ),
    ProductSeed(
        name="Успокоин",
        category="Настойки",
        in_stock=True,
        description="Травяная настойка для успокоения нервной системы.",
    ),
    ProductSeed(
        name="Антивирус",
        category="Настойки",
        in_stock=True,
        description="Противовирусная настойка на основе продуктов пчеловодства.",
    ),
    ProductSeed(
        name="ФитоЭнергия",
        category="Настойки",
        in_stock=True,
        description="Тонизирующая настойка для повышения энергии и работоспособности.",
    ),
    ProductSeed(
        name="Настойка для ЖКТ",
        category="Настойки",
        in_stock=True,
        description="Настойка для нормализации работы желудочно-кишечного тракта.",
    ),
    # Программы здоровья
    ProductSeed(
        name="Универсальная программа оздоровления (УПО)",
        category="Программы здоровья",
        in_stock=True,
        description="Комплексная программа оздоровления организма с продуктами пчеловодства.",
    ),
    ProductSeed(
        name="Приложение к УПО",
        category="Программы здоровья",
        in_stock=True,
        description="Дополнение к универсальной программе оздоровления.",
    ),
    ProductSeed(
        name="Иммунитет ребёнка",
        category="Программы здоровья",
        in_stock=True,
        description="Программа укрепления иммунитета для детей.",
    ),
    ProductSeed(
        name="Инструкция ТГ",
        category="Программы здоровья",
        in_stock=True,
        description="Инструкция по использованию продуктов пчеловодства для Telegram-канала.",
    ),
]


# ---------------------------------------------------------------------------
# Определения таблиц CRM
# ---------------------------------------------------------------------------

TABLE_PRODUCT_CATEGORIES = TableDef(
    name="Категории товаров",
    fields=[
        FieldDef(name="Название", field_type=FieldType.SHORT, required=True),
    ],
)

TABLE_PRODUCTS = TableDef(
    name="Товары",
    fields=[
        FieldDef(name="Название",     field_type=FieldType.SHORT,  required=True),
        FieldDef(name="Категория",    field_type=FieldType.REF,    required=True, ref_table="Категории товаров"),
        FieldDef(name="Цена",         field_type=FieldType.NUMBER, required=False),
        FieldDef(name="Вес",          field_type=FieldType.NUMBER, required=False),
        FieldDef(name="Описание",     field_type=FieldType.LONG,   required=False),
        FieldDef(name="В наличии",    field_type=FieldType.BOOL,   required=False),
        FieldDef(name="Артикул UDS",  field_type=FieldType.SHORT,  required=False),
    ],
)

TABLE_CLIENT_SOURCES = TableDef(
    name="Источники",
    fields=[
        FieldDef(name="Название", field_type=FieldType.SHORT, required=True),
    ],
)

TABLE_CLIENTS = TableDef(
    name="Клиенты",
    fields=[
        FieldDef(name="ФИО",               field_type=FieldType.SHORT,  required=True),
        FieldDef(name="Телефон",           field_type=FieldType.SHORT,  required=False),
        FieldDef(name="Telegram ID",       field_type=FieldType.NUMBER, required=False),
        FieldDef(name="Telegram Username", field_type=FieldType.SHORT,  required=False),
        FieldDef(name="Адрес",             field_type=FieldType.LONG,   required=False),
        FieldDef(name="Город",             field_type=FieldType.SHORT,  required=False),
        FieldDef(name="Источник",          field_type=FieldType.REF,    required=False, ref_table="Источники"),
    ],
)

TABLE_ORDER_STATUSES = TableDef(
    name="Статусы заказов",
    fields=[
        FieldDef(name="Название", field_type=FieldType.SHORT, required=True),
    ],
)

TABLE_DELIVERY_METHODS = TableDef(
    name="Способы доставки",
    fields=[
        FieldDef(name="Название", field_type=FieldType.SHORT, required=True),
    ],
)

TABLE_ORDERS = TableDef(
    name="Заказы",
    fields=[
        FieldDef(name="Номер",              field_type=FieldType.SHORT,    required=True),
        FieldDef(name="Клиент",             field_type=FieldType.REF,      required=True, ref_table="Клиенты"),
        FieldDef(name="Дата",               field_type=FieldType.DATETIME, required=True),
        FieldDef(name="Статус",             field_type=FieldType.REF,      required=True, ref_table="Статусы заказов"),
        FieldDef(name="Способ доставки",    field_type=FieldType.REF,      required=False, ref_table="Способы доставки"),
        FieldDef(name="Адрес доставки",     field_type=FieldType.LONG,     required=False),
        FieldDef(name="Стоимость доставки", field_type=FieldType.NUMBER,   required=False),
        FieldDef(name="Сумма товаров",      field_type=FieldType.NUMBER,   required=False),
        FieldDef(name="Итого",              field_type=FieldType.NUMBER,   required=False),
        FieldDef(name="Трек-номер",         field_type=FieldType.SHORT,    required=False),
        FieldDef(name="Источник",           field_type=FieldType.REF,      required=False, ref_table="Источники"),
    ],
)

TABLE_ORDER_ITEMS = TableDef(
    name="Позиции заказа",
    is_subordinate_of="Заказы",
    fields=[
        FieldDef(name="Товар",         field_type=FieldType.REF,    required=True, ref_table="Товары"),
        FieldDef(name="Количество",    field_type=FieldType.NUMBER, required=True),
        FieldDef(name="Цена за шт.",   field_type=FieldType.NUMBER, required=True),
        FieldDef(name="Сумма",         field_type=FieldType.NUMBER, required=True),
    ],
)

# Все таблицы в порядке создания (справочники сначала, зависимые — потом)
ALL_TABLES: list[TableDef] = [
    TABLE_PRODUCT_CATEGORIES,
    TABLE_PRODUCTS,
    TABLE_CLIENT_SOURCES,
    TABLE_CLIENTS,
    TABLE_ORDER_STATUSES,
    TABLE_DELIVERY_METHODS,
    TABLE_ORDERS,
    TABLE_ORDER_ITEMS,
]

# Справочные данные для заполнения при инициализации
REFERENCE_DATA: dict[str, list[str]] = {
    "Категории товаров": PRODUCT_CATEGORIES,
    "Источники":         CLIENT_SOURCES,
    "Статусы заказов":   ORDER_STATUSES,
    "Способы доставки":  DELIVERY_METHODS,
}
