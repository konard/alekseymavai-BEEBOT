"""Скрипт создания таблиц CRM в Integram через MCP.

Создаёт 8 таблиц модели данных «Усадьба Дмитровых»:
  - Категории товаров, Товары
  - Источники, Клиенты
  - Статусы заказов, Способы доставки
  - Заказы, Позиции заказа

Также заполняет справочники начальными значениями
и добавляет 14 продуктов из каталога бота.

Использование:
  python -m tools.setup_integram_crm

Требования к окружению:
  INTEGRAM_MCP_URL  — базовый URL Integram MCP (например, http://localhost:3000)
  INTEGRAM_API_KEY  — ключ доступа к Integram API (если требуется)

Примечание: скрипт идемпотентен — повторный запуск пропускает уже
созданные таблицы и записи (проверяет по имени).
"""

import asyncio
import logging
import os
import sys

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from src.crm_schema import (
    ALL_TABLES,
    INITIAL_PRODUCTS,
    REFERENCE_DATA,
    FieldType,
    TableDef,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

INTEGRAM_MCP_URL = os.getenv("INTEGRAM_MCP_URL", "http://localhost:3000")
INTEGRAM_API_KEY = os.getenv("INTEGRAM_API_KEY", "")


def _build_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if INTEGRAM_API_KEY:
        headers["Authorization"] = f"Bearer {INTEGRAM_API_KEY}"
    return headers


def _table_to_mcp_payload(table: TableDef) -> dict:
    """Преобразует TableDef в payload для MCP create_table."""
    fields_payload = []
    for f in table.fields:
        field_entry: dict = {
            "name": f.name,
            "type": f.field_type.value,
            "required": f.required,
        }
        if f.field_type == FieldType.REF and f.ref_table:
            field_entry["ref_table"] = f.ref_table
        fields_payload.append(field_entry)

    payload: dict = {
        "name": table.name,
        "fields": fields_payload,
    }
    if table.is_subordinate_of:
        payload["subordinate_of"] = table.is_subordinate_of

    return payload


async def get_existing_tables(client: httpx.AsyncClient) -> set[str]:
    """Получает список уже существующих таблиц в Integram."""
    try:
        resp = await client.get(
            f"{INTEGRAM_MCP_URL}/api/tables",
            headers=_build_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return {t["name"] for t in data.get("tables", [])}
    except httpx.HTTPError as exc:
        logger.warning("Не удалось получить список таблиц: %s", exc)
        return set()


async def create_table(client: httpx.AsyncClient, table: TableDef) -> bool:
    """Создаёт таблицу в Integram. Возвращает True при успехе."""
    payload = _table_to_mcp_payload(table)
    try:
        resp = await client.post(
            f"{INTEGRAM_MCP_URL}/api/tables",
            json=payload,
            headers=_build_headers(),
        )
        resp.raise_for_status()
        logger.info("Таблица создана: %s", table.name)
        return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Ошибка создания таблицы %s: HTTP %s — %s",
            table.name,
            exc.response.status_code,
            exc.response.text,
        )
        return False
    except httpx.HTTPError as exc:
        logger.error("Ошибка соединения при создании таблицы %s: %s", table.name, exc)
        return False


async def get_existing_records(
    client: httpx.AsyncClient, table_name: str
) -> set[str]:
    """Получает набор имён уже существующих записей в справочнике."""
    try:
        resp = await client.get(
            f"{INTEGRAM_MCP_URL}/api/tables/{table_name}/records",
            headers=_build_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        return {r.get("Название", "") for r in data.get("records", [])}
    except httpx.HTTPError as exc:
        logger.warning(
            "Не удалось получить записи таблицы %s: %s", table_name, exc
        )
        return set()


async def insert_record(
    client: httpx.AsyncClient, table_name: str, record: dict
) -> bool:
    """Вставляет одну запись в таблицу Integram."""
    try:
        resp = await client.post(
            f"{INTEGRAM_MCP_URL}/api/tables/{table_name}/records",
            json=record,
            headers=_build_headers(),
        )
        resp.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Ошибка вставки записи в %s: HTTP %s — %s",
            table_name,
            exc.response.status_code,
            exc.response.text,
        )
        return False
    except httpx.HTTPError as exc:
        logger.error("Ошибка соединения при вставке в %s: %s", table_name, exc)
        return False


async def populate_reference_table(
    client: httpx.AsyncClient, table_name: str, values: list[str]
) -> int:
    """Заполняет справочную таблицу значениями. Возвращает количество добавленных записей."""
    existing = await get_existing_records(client, table_name)
    added = 0
    for value in values:
        if value in existing:
            logger.debug("Запись «%s» уже есть в %s — пропускаем", value, table_name)
            continue
        if await insert_record(client, table_name, {"Название": value}):
            logger.info("Добавлено в %s: %s", table_name, value)
            added += 1
    return added


async def populate_products(client: httpx.AsyncClient) -> int:
    """Добавляет 14 продуктов из каталога бота в таблицу Товары."""
    table_name = "Товары"
    try:
        resp = await client.get(
            f"{INTEGRAM_MCP_URL}/api/tables/{table_name}/records",
            headers=_build_headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        existing_names = {r.get("Название", "") for r in data.get("records", [])}
    except httpx.HTTPError as exc:
        logger.warning("Не удалось получить список товаров: %s", exc)
        existing_names = set()

    added = 0
    for product in INITIAL_PRODUCTS:
        if product.name in existing_names:
            logger.debug("Товар «%s» уже существует — пропускаем", product.name)
            continue
        record = {
            "Название":    product.name,
            "Категория":   product.category,
            "Описание":    product.description,
            "В наличии":   product.in_stock,
            "Артикул UDS": product.sku_uds,
        }
        if await insert_record(client, table_name, record):
            logger.info("Добавлен товар: %s", product.name)
            added += 1
    return added


async def main() -> None:
    logger.info("Начинаем настройку CRM Integram...")
    logger.info("MCP URL: %s", INTEGRAM_MCP_URL)

    async with httpx.AsyncClient(timeout=30.0) as client:
        # 1. Создаём таблицы
        logger.info("--- Шаг 1: Создание таблиц ---")
        existing_tables = await get_existing_tables(client)
        created = 0
        skipped = 0
        for table in ALL_TABLES:
            if table.name in existing_tables:
                logger.info("Таблица «%s» уже существует — пропускаем", table.name)
                skipped += 1
                continue
            if await create_table(client, table):
                created += 1
        logger.info("Таблиц создано: %d, пропущено (уже есть): %d", created, skipped)

        # 2. Заполняем справочники
        logger.info("--- Шаг 2: Заполнение справочников ---")
        for table_name, values in REFERENCE_DATA.items():
            added = await populate_reference_table(client, table_name, values)
            logger.info("Справочник «%s»: добавлено %d значений", table_name, added)

        # 3. Добавляем каталог товаров
        logger.info("--- Шаг 3: Добавление каталога товаров ---")
        products_added = await populate_products(client)
        logger.info("Товаров добавлено: %d из %d", products_added, len(INITIAL_PRODUCTS))

    logger.info("Настройка CRM завершена.")
    logger.info(
        "Проверьте таблицы в Integram: %s/tables", INTEGRAM_MCP_URL
    )


if __name__ == "__main__":
    asyncio.run(main())
