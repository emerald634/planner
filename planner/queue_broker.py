"""Internal UDS queue client for the EXISTING polling process. No second bot."""

import httpx

from .distribution_queue import validate


class BrokerError(OSError):
    pass


class BrokerQueue:
    def __init__(self, socket_path, key, actor_id, client=None):
        self.actor_id = actor_id
        self.client = client or httpx.Client(
            transport=httpx.HTTPTransport(uds=str(socket_path)),
            base_url="http://writer",
            trust_env=False,
            timeout=12,
        )
        self.key = key

    def call(self, path, body):
        try:
            r = self.client.post(
                path,
                json={"actor_id": self.actor_id, **body},
                headers={"Authorization": "Bearer " + self.key},
            )
            if r.status_code == 409:
                raise ValueError("На день уже подтверждён другой вариант.")
            if r.status_code == 403:
                raise PermissionError("Нет права подтверждения.")
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            if isinstance(e, ValueError) and not isinstance(e, httpx.HTTPError):
                raise
            raise BrokerError("Сервис подтверждений временно недоступен.") from None

    def initialize(self):
        self.call("/bot/check", {})

    def find(self, identifier):
        return self.call("/bot/find", {"identifier": identifier})

    def publish(self, snapshot, authorized_ids):
        validate(snapshot)
        if (
            snapshot["confirmed_by"] != self.actor_id
            or self.actor_id not in authorized_ids
        ):
            raise PermissionError("Нет права подтверждения.")
        return self.call("/bot/publish", {"snapshot": snapshot})

    def close(self):
        self.client.close()
