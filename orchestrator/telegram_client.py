"""
Telegram client — polling only (no webhook server needed).
Sends messages and reads replies by polling getUpdates.
"""
from __future__ import annotations

import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

TIMEOUT = 10


class TelegramClient:
    def __init__(self, bot_token: str, admin_chat_id: int):
        self.token = bot_token
        self.chat_id = admin_chat_id
        self._base = f"https://api.telegram.org/bot{bot_token}"

    def send(self, text: str, reply_markup: Optional[dict] = None) -> Optional[int]:
        """Send a message; return message_id or None on failure."""
        payload: dict = {"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            r = requests.post(f"{self._base}/sendMessage", json=payload, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()["result"]["message_id"]
        except Exception as e:
            logger.error("Telegram send failed: %s", e)
            return None

    def get_updates(self, offset: int) -> tuple[list[dict], int]:
        """
        Poll for new updates since offset.
        Returns (updates, new_offset).
        """
        try:
            r = requests.get(
                f"{self._base}/getUpdates",
                params={"offset": offset, "timeout": 5, "limit": 20},
                timeout=15,
            )
            r.raise_for_status()
            updates = r.json().get("result", [])
            new_offset = updates[-1]["update_id"] + 1 if updates else offset
            return updates, new_offset
        except Exception as e:
            logger.error("Telegram getUpdates failed: %s", e)
            return [], offset

    def answer_callback(self, callback_query_id: str) -> None:
        try:
            requests.post(
                f"{self._base}/answerCallbackQuery",
                json={"callback_query_id": callback_query_id},
                timeout=TIMEOUT,
            )
        except Exception:
            pass

    def approval_keyboard(self, project: str, task_id: int) -> dict:
        return {
            "inline_keyboard": [[
                {"text": "✅ Approve", "callback_data": f"approve:{project}:{task_id}"},
                {"text": "⏭ Skip",    "callback_data": f"skip:{project}:{task_id}"},
                {"text": "📅 Schedule", "callback_data": f"schedule:{project}:{task_id}"},
                {"text": "⏹ Stop all", "callback_data": f"stop:{project}"},
            ]]
        }

    def format_approval_message(
        self, project: str, next_task: dict, queue: list[dict]
    ) -> str:
        lines = [
            f"🤖 *Ready to work — {project}*\n",
            f"▶️ *Next:* {next_task['title']}",
        ]
        if queue:
            lines.append("\n📋 *Queue:*")
            for i, t in enumerate(queue, 2):
                lines.append(f"  {i}. {t['title']}")
        return "\n".join(lines)

    def format_done_message(self, project: str, task: dict) -> str:
        return f"✅ *Done — {project}*\n\n{task['title']}\n\nChanges committed and pushed."

    def format_error_message(self, project: str, task: dict, error: str) -> str:
        return f"❌ *Error — {project}*\n\n{task['title']}\n\n```\n{error[:500]}\n```"

    def format_maintenance_message(self, project: str, stats: str) -> str:
        return f"📊 *Maintenance report — {project}*\n\n{stats}"
