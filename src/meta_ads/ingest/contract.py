"""Versioned CRM receipt contract. An HTTP 200 alone is not a delivery receipt."""

from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID


@dataclass(frozen=True)
class CrmResult:
    kind: Literal["project", "agency"]
    crm_lead_id: int | None = None
    agency_inquiry_id: UUID | None = None
    agency_lead_id: UUID | None = None
    match_status: str | None = None


def parse_crm_result(data: Any) -> CrmResult:
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise ValueError("CRM returned no accepted receipt")
    kind = data.get("kind", "project")
    if kind == "project":
        lead_id = data.get("leadId", data.get("lead_id"))
        if type(lead_id) is not int or lead_id <= 0 or data.get("inquiryId") is not None:
            raise ValueError("CRM project receipt has no positive integer lead ID")
        return CrmResult(kind="project", crm_lead_id=lead_id)
    if kind != "agency":
        raise ValueError("CRM receipt kind is unsupported")
    try:
        inquiry_id = UUID(data["inquiryId"])
        lead_id = UUID(data["leadId"]) if data.get("leadId") is not None else None
    except (KeyError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError("CRM agency receipt has invalid UUIDs") from exc
    status = data.get("matchStatus")
    if status not in {"matched", "conflict", "unresolved"} or (status == "matched") != (lead_id is not None):
        raise ValueError("CRM agency receipt has inconsistent contact match")
    return CrmResult("agency", agency_inquiry_id=inquiry_id, agency_lead_id=lead_id, match_status=status)


def connection_key(app_id: str, page_id: str) -> str:
    if not app_id or not page_id:
        raise ValueError("Meta app and page identity are required")
    return f"meta:{app_id}:{page_id}"
