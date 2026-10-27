from datetime import datetime
from typing import Optional, Any, Dict, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class BidBase(BaseModel):
    gem_bid_id: Optional[str] = None
    bid_number: Optional[str] = None
    title: str = Field(..., description="Title of the bid opportunity")
    organisation: Optional[str] = None
    department: Optional[str] = None
    ministry: Optional[str] = None
    category: Optional[str] = None
    bid_type: Optional[str] = None
    published_date: Optional[datetime] = None
    closing_date: Optional[datetime] = None
    location: Optional[str] = None
    estimated_value: Optional[float] = None
    currency: str = "INR"
    scope_of_work: Optional[str] = None
    technical_requirements: Optional[Dict[str, Any]] = None
    eligibility_criteria: Optional[Dict[str, Any]] = None
    qualification_requirements: Optional[Dict[str, Any]] = None
    experience_requirements: Optional[Dict[str, Any]] = None
    certification_requirements: Optional[Dict[str, Any]] = None
    emd_information: Optional[Dict[str, Any]] = None
    tender_fee_information: Optional[Dict[str, Any]] = None
    contact_information: Optional[Dict[str, Any]] = None
    source_url: Optional[str] = None
    status: str = "NEW"


class BidCreate(BidBase):
    pass


class BidUpdate(BaseModel):
    title: Optional[str] = None
    status: Optional[str] = None
    closing_date: Optional[datetime] = None
    scope_of_work: Optional[str] = None


class BidResponse(BidBase):
    id: UUID
    content_hash: Optional[str] = None
    first_discovered_at: datetime
    last_updated_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BidDetailResponse(BidResponse):
    """
    Single-bid detail projection.

    Adds the persisted Bill-of-Quantities evidence that the list endpoints
    deliberately omit: ``boq_items`` can be large (hundreds of line items), so
    it is only carried on the per-bid detail response. ``boq_items`` is ``None``
    when no BoQ was ever stored; ``boq_checked_at`` records when enrichment last
    *attempted* the bid (present even when GeM published no BoQ CSV), so a client
    can distinguish "never attempted" from "attempted, nothing published".
    """

    boq_items: Optional[Dict[str, Any]] = None
    boq_checked_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
