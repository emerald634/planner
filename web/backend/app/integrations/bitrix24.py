from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from app.core.crm_policy import workspace_runtime


class Bitrix24Error(RuntimeError):
    pass


@dataclass
class BitrixObject:
    lead_id: str


class CRMGateway(Protocol):
    def create_lead(
        self,
        *,
        phone: str,
        name: str | None,
        comment: str | None,
        responsible_id: str,
        source_id: str,
    ) -> BitrixObject: ...


class Bitrix24Gateway:
    def __init__(self, webhook_url: str, timeout: float = 20):
        self.webhook_url = webhook_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, params: dict[str, Any] | None = None) -> Any:
        if workspace_runtime() and method not in {
            "crm.status.list", "crm.lead.get", "crm.deal.list", "crm.deal.get",
            "crm.stagehistory.list", "crm.settings.mode.get",
        }:
            raise Bitrix24Error("CRM write is disabled in workspace runtime")
        try:
            response = httpx.post(
                f"{self.webhook_url}/{method}.json", json=params or {}, timeout=self.timeout
            )
        except httpx.RequestError as exc:
            raise Bitrix24Error(f"Сетевая ошибка Bitrix24: {type(exc).__name__}") from exc
        if response.is_error:
            raise Bitrix24Error(f"Bitrix24 вернул HTTP {response.status_code}")
        payload = response.json()
        if error := payload.get("error"):
            raise Bitrix24Error(payload.get("error_description") or error)
        return payload.get("result")

    def create_lead(
        self,
        *,
        phone: str,
        name: str | None,
        comment: str | None,
        responsible_id: str,
        source_id: str,
    ) -> BitrixObject:
        fields = {
            "TITLE": name or phone,
            "NAME": name or "",
            "PHONE": [{"VALUE": phone, "VALUE_TYPE": "WORK"}],
            "COMMENTS": comment or "",
            "ASSIGNED_BY_ID": responsible_id,
            "SOURCE_ID": source_id,
        }
        return BitrixObject(lead_id=str(self._call("crm.lead.add", {"fields": fields})))

    def list_sources(self) -> list[dict[str, Any]]:
        return self._call(
            "crm.status.list", {"order": {"SORT": "ASC"}, "filter": {"ENTITY_ID": "SOURCE"}}
        )

    def list_statuses(self, entity_id: str) -> list[dict[str, Any]]:
        return self._call(
            "crm.status.list",
            {"order": {"SORT": "ASC"}, "filter": {"ENTITY_ID": entity_id}},
        )

    def get_lead(self, lead_id: str) -> dict[str, Any]:
        return self._call("crm.lead.get", {"id": lead_id})

    def find_deal_by_lead(self, lead_id: str) -> dict[str, Any] | None:
        result = self._call(
            "crm.deal.list",
            {"filter": {"LEAD_ID": lead_id}, "select": ["ID"], "order": {"ID": "DESC"}},
        )
        return result[0] if result else None

    def get_deal(self, deal_id: str) -> dict[str, Any]:
        return self._call("crm.deal.get", {"id": deal_id})

    def list_stage_history(self, entity_type_id: int, owner_id: str) -> list[dict[str, Any]]:
        stage_fields = (
            ["STATUS_ID", "STATUS_SEMANTIC_ID"]
            if entity_type_id == 1
            else ["CATEGORY_ID", "STAGE_ID", "STAGE_SEMANTIC_ID"]
        )
        result = self._call(
            "crm.stagehistory.list",
            {
                "entityTypeId": entity_type_id,
                "order": {"ID": "ASC"},
                "filter": {"OWNER_ID": owner_id},
                "select": ["ID", "OWNER_ID", "CREATED_TIME", *stage_fields],
            },
        )
        return list(result.get("items", []))

    def get_crm_mode(self) -> int:
        return int(self._call("crm.settings.mode.get"))
