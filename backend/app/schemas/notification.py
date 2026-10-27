from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    """
    A persisted notification row plus an explicit delivery status.

    ``status`` and ``sent_at`` are the raw stored fields (kept for existing
    consumers). ``delivery_state`` (``QUEUED`` / ``DELIVERED`` / ``FAILED``),
    ``delivery_configured`` and ``delivery_note`` are derived: the row is only
    ever DELIVERED when the configured provider confirmed the send, and a
    deployment without SMTP credentials reports ``delivery_configured: false``
    with queued alerts. SMTP settings themselves are never part of this model.
    """

    id: UUID
    bid_id: UUID
    channel: str
    recipient: str
    notification_type: str
    deduplication_key: Optional[str] = None
    status: str
    sent_at: Optional[datetime] = None
    delivery_state: str
    delivery_configured: bool
    delivery_note: str

    model_config = ConfigDict(from_attributes=True)
