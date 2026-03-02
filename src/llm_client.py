"""LLM client using Groq API with llama3-70b-8192."""

import logging

from groq import Groq

from src.config import GROQ_API_KEY, GROQ_MODEL, MAX_RESPONSE_LENGTH

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — Александр Дмитров, пчеловод с многолетним опытом, автор блога и YouTube-канала о продуктах пчеловодства и здоровом образе жизни. У тебя своя пасека и усадьба.

Твой стиль общения:
- Дружелюбный и открытый, как будто разговариваешь с другом
- Простой и понятный язык, без лишнего наукообразия
- Уверенный тон эксперта, который делится личным опытом
- Искренняя забота о здоровье собеседника
- Конкретные практические советы с дозировками и рецептами

Правила:
- Отвечай на основе предоставленного контекста из своих видео и инструкций
- Если информации в контексте недостаточно — честно скажи об этом
- Не придумывай дозировки или рецепты, которых нет в контексте
- Отвечай кратко и по делу, но не сухо
- Используй разговорный стиль, как в видеоблоге"""


def build_prompt(query: str, context_chunks: list[dict]) -> str:
    """Build the user prompt with context from knowledge base."""
    context_parts = []
    for chunk in context_chunks:
        source = chunk.get("source", "unknown")
        context_parts.append(f"[Источник: {source}]\n{chunk['text']}")

    context_text = "\n\n---\n\n".join(context_parts)

    return f"""Контекст из моих видео и инструкций:

{context_text}

---

Вопрос подписчика: {query}

Ответь как Александр Дмитров, опираясь на контекст выше."""


class LLMClient:
    """Client for generating responses via Groq."""

    def __init__(self):
        self.client = Groq(api_key=GROQ_API_KEY)
        self.model = GROQ_MODEL

    def generate(self, query: str, context_chunks: list[dict]) -> str:
        """Generate a response for the user's query with context."""
        user_prompt = build_prompt(query, context_chunks)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=MAX_RESPONSE_LENGTH,
                temperature=0.7,
            )
            return response.choices[0].message.content

        except Exception as e:
            logger.error(f"Groq API error: {e}")
            return "Извини, сейчас не могу ответить — техническая проблема. Попробуй чуть позже!"
