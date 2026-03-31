import logging
from typing import Optional

from aiogram import Bot
from aiogram.enums import ParseMode

from ....core.agent.trace import TraceAction, TraceCategory, TraceEvent, TraceHandler
from .utils import markdown_to_tg_html

logger = logging.getLogger(__name__)


class TelegramTraceHandler(TraceHandler):
    def __init__(
        self, task_id: int, bot: Bot, chat_id: int, message_id: Optional[int] = None
    ):
        self.task_id = task_id
        self.bot = bot
        self.chat_id = chat_id
        self.message_id = message_id
        self.current_text = ""

    async def handle_event(self, event: TraceEvent) -> None:
        try:
            # We only care about message events and tool events for Telegram
            if (
                event.event_type.category == TraceCategory.MESSAGE
                and event.event_type.action == TraceAction.UPDATE
            ):
                data = event.data or {}
                role = data.get("role")
                content = data.get("content", "")

                if role == "assistant" and content:
                    await self._update_message(content)

            elif (
                event.event_type.category == TraceCategory.MESSAGE
                and event.event_type.action == TraceAction.END
            ):
                data = event.data or {}
                role = data.get("role")
                content = data.get("content", "")

                if role == "assistant" and content:
                    await self._update_message(content, final=True)

        except Exception as e:
            logger.warning(f"TelegramTraceHandler error for task {self.task_id}: {e}")

    async def _update_message(self, text: str, final: bool = False) -> None:
        if not text:
            return

        # Add a typing indicator for non-final messages
        display_text = text if final else text + " ✍️"

        # Avoid updating if text hasn't changed much (to prevent rate limits)
        if self.current_text == display_text:
            return

        self.current_text = display_text

        try:
            html_text = markdown_to_tg_html(display_text[:4000])
            if self.message_id is None:
                try:
                    msg = await self.bot.send_message(
                        chat_id=self.chat_id, text=html_text, parse_mode=ParseMode.HTML
                    )
                except Exception:
                    # Fallback if HTML parsing fails
                    msg = await self.bot.send_message(
                        chat_id=self.chat_id, text=display_text[:4000]
                    )
                self.message_id = msg.message_id
            else:
                try:
                    await self.bot.edit_message_text(
                        chat_id=self.chat_id,
                        message_id=self.message_id,
                        text=html_text,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception as e:
                    if "message is not modified" not in str(e).lower():
                        # Fallback if HTML parsing fails
                        await self.bot.edit_message_text(
                            chat_id=self.chat_id,
                            message_id=self.message_id,
                            text=display_text[:4000],
                        )
        except Exception as e:
            if "message is not modified" not in str(e).lower():
                logger.error(f"Error updating Telegram message: {e}")
