from typing import Protocol

import httpx


class MessengerGateway(Protocol):
    def send(self, chat_id: str, text: str) -> None: ...


class TelegramGateway:
    def __init__(self, bot_token: str, timeout: float = 10):
        self.url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        self.timeout = timeout

    def send(self, chat_id: str, text: str) -> None:
        response = httpx.post(
            self.url, json={"chat_id": chat_id, "text": text}, timeout=self.timeout
        )
        response.raise_for_status()
