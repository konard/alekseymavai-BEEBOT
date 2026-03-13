"""Unit tests for src/bot.py — Telegram bot handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from src.bot import _should_respond, handle_question, cmd_start, cmd_help
from src.bot import WELCOME_MESSAGE, HELP_MESSAGE, BOT_USERNAME


# ---------------------------------------------------------------------------
# _should_respond tests
# ---------------------------------------------------------------------------

class TestShouldRespond:
    """Tests for the _should_respond helper function."""

    def _make_message(
        self,
        chat_type: str = "private",
        text: str = "",
        reply_to_from_id: int | None = None,
        bot_id: int = 12345,
    ):
        """Create a mock aiogram Message."""
        from aiogram.enums import ChatType

        message = MagicMock()
        message.chat.type = chat_type
        message.text = text

        if reply_to_from_id is not None:
            message.reply_to_message = MagicMock()
            message.reply_to_message.from_user = MagicMock()
            message.reply_to_message.from_user.id = reply_to_from_id
        else:
            message.reply_to_message = None

        return message

    def test_always_responds_in_private_chat(self):
        """Bot should always respond in private chats."""
        msg = self._make_message(chat_type="private")
        assert _should_respond(msg) is True

    def test_responds_when_mentioned_in_group(self):
        """Bot should respond in groups when @username is in message."""
        msg = self._make_message(
            chat_type="group",
            text=f"@{BOT_USERNAME} чем полезна перга?",
        )
        assert _should_respond(msg) is True

    def test_does_not_respond_to_other_group_messages(self):
        """Bot should NOT respond to group messages not addressed to it."""
        msg = self._make_message(
            chat_type="group",
            text="Просто разговор в группе",
        )
        assert _should_respond(msg) is False

    def test_responds_when_reply_to_bot_message(self):
        """Bot should respond when message is a reply to its own message."""
        from src.bot import bot

        with patch("src.bot.bot") as mock_bot:
            mock_bot.id = 99999
            msg = self._make_message(
                chat_type="group",
                text="Спасибо!",
                reply_to_from_id=99999,
            )
            # Patch bot.id in the module
            with patch("src.bot.bot") as patched_bot:
                patched_bot.id = 99999
                result = _should_respond(msg)

        assert result is True

    def test_supergroup_treated_like_group(self):
        """Bot should follow group rules in supergroups."""
        msg = self._make_message(
            chat_type="supergroup",
            text="обычное сообщение",
        )
        assert _should_respond(msg) is False

    def test_responds_in_supergroup_when_mentioned(self):
        """Bot should respond in supergroups when mentioned."""
        msg = self._make_message(
            chat_type="supergroup",
            text=f"@{BOT_USERNAME} как зимуют пчёлы?",
        )
        assert _should_respond(msg) is True


# ---------------------------------------------------------------------------
# Message handler tests (async)
# ---------------------------------------------------------------------------

class TestHandleQuestion:
    """Tests for the handle_question async handler."""

    def _make_message(
        self,
        text: str = "Как принимать прополис?",
        chat_type: str = "private",
        user_id: int = 1001,
    ):
        message = AsyncMock()
        message.text = text
        message.chat.type = chat_type
        message.chat.id = 42
        message.from_user = MagicMock()
        message.from_user.id = user_id
        message.reply_to_message = None
        message.reply = AsyncMock()
        return message

    def _make_state(self):
        """Create a mock FSMContext (state) for handle_question."""
        state = AsyncMock()
        state.get_state = AsyncMock(return_value=None)
        state.set_state = AsyncMock()
        state.get_data = AsyncMock(return_value={})
        state.update_data = AsyncMock()
        state.clear = AsyncMock()
        return state

    @pytest.mark.asyncio
    async def test_ignores_non_addressable_group_message(self):
        """Handler must not reply to group messages not aimed at bot."""
        msg = self._make_message(chat_type="group", text="обычный разговор")
        state = self._make_state()

        with patch("src.bot._should_respond", return_value=False):
            await handle_question(msg, state)

        msg.reply.assert_not_called()

    @pytest.mark.asyncio
    async def test_replies_to_short_query_with_prompt(self):
        """Handler should ask user for a longer question when query < 3 chars."""
        msg = self._make_message(text="?")
        state = self._make_state()

        with patch("src.bot._should_respond", return_value=True):
            await handle_question(msg, state)

        msg.reply.assert_called_once()
        call_text = msg.reply.call_args[0][0]
        assert "вопрос" in call_text.lower()

    @pytest.mark.asyncio
    async def test_calls_kb_search(self):
        """Handler should call orchestrator.route with the user's query."""
        msg = self._make_message(text="Как принимать прополис?")
        state = self._make_state()

        mock_orchestrator = MagicMock()
        mock_orchestrator.route = AsyncMock(return_value=(
            "Принимайте по 20 капель.",
            [{"text": "...", "source": "pdf:X", "score": 0.9}],
        ))
        mock_orchestrator.get_intent = MagicMock(return_value="consult")

        with (
            patch("src.bot._should_respond", return_value=True),
            patch("src.bot.orchestrator", mock_orchestrator),
            patch("src.bot.bot") as mock_bot,
        ):
            mock_bot.send_chat_action = AsyncMock()
            await handle_question(msg, state)

        mock_orchestrator.route.assert_called_once_with(msg.from_user.id, "Как принимать прополис?")

    @pytest.mark.asyncio
    async def test_calls_llm_generate_with_chunks(self):
        """Handler should call orchestrator.route and send the response."""
        chunks = [{"text": "Прополис...", "source": "pdf:X", "score": 0.9}]
        msg = self._make_message(text="Вопрос о прополисе")
        state = self._make_state()

        mock_orchestrator = MagicMock()
        mock_orchestrator.route = AsyncMock(return_value=("ответ", chunks))
        mock_orchestrator.get_intent = MagicMock(return_value="consult")

        with (
            patch("src.bot._should_respond", return_value=True),
            patch("src.bot.orchestrator", mock_orchestrator),
            patch("src.bot.bot") as mock_bot,
        ):
            mock_bot.send_chat_action = AsyncMock()
            await handle_question(msg, state)

        mock_orchestrator.route.assert_called_once_with(msg.from_user.id, "Вопрос о прополисе")

    @pytest.mark.asyncio
    async def test_replies_with_llm_response(self):
        """Handler should send orchestrator response back to user."""
        expected_reply = "Настойку прополиса принимают по 30 капель."
        msg = self._make_message(text="Как принимать прополис?")
        state = self._make_state()

        mock_orchestrator = MagicMock()
        mock_orchestrator.route = AsyncMock(return_value=(expected_reply, []))
        mock_orchestrator.get_intent = MagicMock(return_value="consult")

        with (
            patch("src.bot._should_respond", return_value=True),
            patch("src.bot.orchestrator", mock_orchestrator),
            patch("src.bot.bot") as mock_bot,
        ):
            mock_bot.send_chat_action = AsyncMock()
            await handle_question(msg, state)

        msg.reply.assert_called_once()
        assert msg.reply.call_args[0][0] == expected_reply

    @pytest.mark.asyncio
    async def test_strips_bot_username_from_query(self):
        """Handler should strip @BotUsername from query before processing."""
        msg = self._make_message(
            text=f"@{BOT_USERNAME} чем полезна перга?",
            chat_type="group",
        )
        msg.reply_to_message = None
        state = self._make_state()

        mock_orchestrator = MagicMock()
        mock_orchestrator.route = AsyncMock(return_value=("ответ", []))
        mock_orchestrator.get_intent = MagicMock(return_value="consult")

        with (
            patch("src.bot._should_respond", return_value=True),
            patch("src.bot.orchestrator", mock_orchestrator),
            patch("src.bot.bot") as mock_bot,
        ):
            mock_bot.send_chat_action = AsyncMock()
            await handle_question(msg, state)

        route_call_query = mock_orchestrator.route.call_args[0][1]
        assert BOT_USERNAME not in route_call_query
        assert "@" not in route_call_query

    @pytest.mark.asyncio
    async def test_error_handling_returns_fallback_message(self):
        """Handler should reply with a fallback message on unexpected errors."""
        msg = self._make_message(text="Вопрос")
        state = self._make_state()

        mock_orchestrator = MagicMock()
        mock_orchestrator.route = AsyncMock(side_effect=RuntimeError("Database error"))

        with (
            patch("src.bot._should_respond", return_value=True),
            patch("src.bot.orchestrator", mock_orchestrator),
            patch("src.bot.bot") as mock_bot,
        ):
            mock_bot.send_chat_action = AsyncMock()
            await handle_question(msg, state)

        msg.reply.assert_called_once()
        reply_text = msg.reply.call_args[0][0]
        # Fallback message should be in Russian
        russian_chars = "абвгдеёжзийклмнопрстуфхцчшщъыьэюя"
        assert any(c in russian_chars for c in reply_text.lower())


# ---------------------------------------------------------------------------
# /start and /help command tests (async)
# ---------------------------------------------------------------------------

class TestStartAndHelpCommands:
    """Tests for /start and /help command handlers."""

    @pytest.mark.asyncio
    async def test_start_sends_welcome_message(self):
        """cmd_start should send the WELCOME_MESSAGE."""
        message = AsyncMock()
        message.answer = AsyncMock()

        await cmd_start(message)

        message.answer.assert_called_once()
        assert message.answer.call_args[0][0] == WELCOME_MESSAGE

    @pytest.mark.asyncio
    async def test_help_sends_help_message(self):
        """cmd_help should send the HELP_MESSAGE."""
        message = AsyncMock()
        message.answer = AsyncMock()

        await cmd_help(message)

        message.answer.assert_called_once()
        assert message.answer.call_args[0][0] == HELP_MESSAGE

    def test_welcome_message_mentions_products(self):
        """WELCOME_MESSAGE should mention key bee products."""
        text_lower = WELCOME_MESSAGE.lower()
        assert any(word in text_lower for word in ["мёд", "пчел", "продукт"])

    def test_help_message_mentions_start_command(self):
        """HELP_MESSAGE should mention /start command."""
        assert "/start" in HELP_MESSAGE

    def test_help_message_mentions_help_command(self):
        """HELP_MESSAGE should mention /help command."""
        assert "/help" in HELP_MESSAGE
