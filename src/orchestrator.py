"""Оркестратор BEEBOT — маршрутизация между агентами через LangGraph.

Принимает сообщения от Telegram, классифицирует intent через Groq (~100 токенов),
направляет нужному агенту. Хранит состояние диалога по user_id с TTL 30 минут.

Intents:
    consult  → BeebotAgent  — вопросы о продуктах пчеловодства
    order    → LogistAgent  — купить / заказать
    delivery → LogistAgent  — доставка / трек-номер
    stats    → AnalystAgent — статистика (только для пчеловода)
"""

import logging
import time
from typing import Literal

from groq import Groq
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from src.config import GROQ_API_KEY, GROQ_BASE_URL, GROQ_MODEL
from src.agents.beebot import BeebotAgent
from src.agents.logist import LogistAgent
from src.agents.analyst import AnalystAgent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intent type
# ---------------------------------------------------------------------------

Intent = Literal["consult", "order", "delivery", "stats"]

# ---------------------------------------------------------------------------
# Dialog state (per user)
# ---------------------------------------------------------------------------

_DIALOG_TTL_SECONDS = 30 * 60  # 30 minutes


class DialogState(TypedDict):
    """Состояние одного диалога."""
    user_id: int
    query: str
    intent: Intent
    response: str
    chunks: list[dict]
    updated_at: float


# ---------------------------------------------------------------------------
# LangGraph state for a single routing run
# ---------------------------------------------------------------------------

class OrchestratorState(TypedDict):
    user_id: int
    query: str
    intent: str          # classified intent
    response: str        # final response text
    chunks: list[dict]   # knowledge base chunks (from BEEBOT)


# ---------------------------------------------------------------------------
# Intent classification prompt (short, ~100 tokens)
# ---------------------------------------------------------------------------

_INTENT_SYSTEM = (
    "Ты классификатор намерений. Определи intent одним словом из списка:\n"
    "consult — вопрос о продуктах пчеловодства, здоровье, рецептах\n"
    "order   — хочет купить, заказать, оформить заказ\n"
    "delivery — вопрос о доставке, трек-номере, сроках\n"
    "stats   — запрос статистики продаж или аналитики\n"
    "Ответь ТОЛЬКО одним словом: consult, order, delivery или stats."
)


def _classify_intent(client: Groq, model: str, query: str) -> Intent:
    """Классифицировать intent запроса через Groq (~100 токенов)."""
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": _INTENT_SYSTEM},
                {"role": "user", "content": query},
            ],
            max_tokens=5,
            temperature=0.0,
        )
        raw = resp.choices[0].message.content.strip().lower()
        if raw in ("consult", "order", "delivery", "stats"):
            return raw  # type: ignore[return-value]
        logger.warning("Unexpected intent value '%s', falling back to consult", raw)
    except Exception as e:
        logger.error("Intent classification failed: %s — falling back to consult", e)
    return "consult"


# ---------------------------------------------------------------------------
# Orchestrator class
# ---------------------------------------------------------------------------

class Orchestrator:
    """Оркестратор: классифицирует intent и маршрутизирует к нужному агенту."""

    def __init__(self):
        kwargs: dict = {"api_key": GROQ_API_KEY}
        if GROQ_BASE_URL:
            kwargs["base_url"] = GROQ_BASE_URL
        self._groq = Groq(**kwargs)
        self._model = GROQ_MODEL

        self._beebot = BeebotAgent()
        self._logist = LogistAgent()
        self._analyst = AnalystAgent(groq_client=self._groq, groq_model=self._model)

        # In-memory dialog state per user_id
        self._dialog_states: dict[int, DialogState] = {}

        self._graph = self._build_graph()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_kb(self):
        """Загрузить базу знаний BEEBOT (вызывается при старте бота)."""
        self._beebot.kb.load()

    async def route(self, user_id: int, query: str) -> tuple[str, list[dict]]:
        """Маршрутизировать запрос к нужному агенту.

        Returns:
            (response_text, chunks) — chunks пустой если агент не BEEBOT.
        """
        self._evict_stale_states()

        initial_state: OrchestratorState = {
            "user_id": user_id,
            "query": query,
            "intent": "",
            "response": "",
            "chunks": [],
        }

        result = await self._graph.ainvoke(initial_state)

        # Persist dialog state
        self._dialog_states[user_id] = DialogState(
            user_id=user_id,
            query=query,
            intent=result["intent"],
            response=result["response"],
            chunks=result["chunks"],
            updated_at=time.monotonic(),
        )

        return result["response"], result["chunks"]

    def get_intent(self, user_id: int) -> Intent | None:
        """Вернуть последний intent для пользователя (если не устарел)."""
        state = self._dialog_states.get(user_id)
        if state and self._is_fresh(state):
            return state["intent"]  # type: ignore[return-value]
        return None

    # ------------------------------------------------------------------
    # LangGraph graph definition
    # ------------------------------------------------------------------

    def _build_graph(self) -> StateGraph:
        graph = StateGraph(OrchestratorState)

        graph.add_node("classify", self._node_classify)
        graph.add_node("beebot", self._node_beebot)
        graph.add_node("logist", self._node_logist)
        graph.add_node("analyst", self._node_analyst)

        graph.set_entry_point("classify")
        graph.add_conditional_edges(
            "classify",
            self._route_by_intent,
            {
                "consult": "beebot",
                "order": "logist",
                "delivery": "logist",
                "stats": "analyst",
            },
        )
        graph.add_edge("beebot", END)
        graph.add_edge("logist", END)
        graph.add_edge("analyst", END)

        return graph.compile()

    # ------------------------------------------------------------------
    # Graph nodes
    # ------------------------------------------------------------------

    def _node_classify(self, state: OrchestratorState) -> OrchestratorState:
        """Классифицировать intent запроса."""
        intent = _classify_intent(self._groq, self._model, state["query"])
        logger.info(
            "Intent classified for user %d: '%s' → %s",
            state["user_id"], state["query"][:60], intent,
        )
        return {**state, "intent": intent}

    def _node_beebot(self, state: OrchestratorState) -> OrchestratorState:
        """Маршрут: consult → BEEBOT-консультант."""
        response, chunks = self._beebot.answer(state["query"])
        return {**state, "response": response, "chunks": chunks}

    async def _node_logist(self, state: OrchestratorState) -> OrchestratorState:
        """Маршрут: order/delivery → Логист (заглушка)."""
        try:
            await self._logist.collect_shipping_info(state["user_id"])
        except NotImplementedError:
            pass
        response = (
            "Спасибо за интерес! Сейчас приём заказов ведётся вручную — "
            "напишите Александру напрямую или оставьте заявку в чате."
        )
        return {**state, "response": response, "chunks": []}

    async def _node_analyst(self, state: OrchestratorState) -> OrchestratorState:
        """Маршрут: stats → Аналитик."""
        try:
            response = await self._analyst.handle_query(state["query"])
        except Exception as e:
            logger.error("AnalystAgent ошибка: %s", e)
            response = "Не удалось получить статистику. Попробуйте позже."
        return {**state, "response": response, "chunks": []}

    # ------------------------------------------------------------------
    # Routing & state helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _route_by_intent(state: OrchestratorState) -> str:
        return state["intent"] if state["intent"] in ("consult", "order", "delivery", "stats") else "consult"

    def _is_fresh(self, state: DialogState) -> bool:
        return (time.monotonic() - state["updated_at"]) < _DIALOG_TTL_SECONDS

    def _evict_stale_states(self):
        """Удалить устаревшие состояния диалога (TTL 30 мин)."""
        stale = [uid for uid, s in self._dialog_states.items() if not self._is_fresh(s)]
        for uid in stale:
            del self._dialog_states[uid]
