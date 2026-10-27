"""
Field-name alias map.

Different CSV/XLSX/JSON sources may label the same concept with different
column headers. This module provides a deterministic mapping from common
variants to the canonical RawBidRecord field names.
"""
from __future__ import annotations

import re
from typing import Dict

# Canonical field name -> list of known source aliases (lowercase).
FIELD_ALIASES: Dict[str, list[str]] = {
    "gem_bid_id": [
        "gem_bid_id", "gem bid id", "gem_id", "gem id", "gembidid", "bid_id_gem",
        "gem_bid_no", "gem bid no", "gem bid no.", "bid_no", "bid no", "bid no.",
        "bid_id", "bid id", "tender_id", "tender id", "bid / tender no", "bid/tender no",
    ],
    "bid_number": [
        "bid_number", "bid number", "bid_no", "bid no", "bid no.", "bidnumber",
        "tender_number", "tender number", "tender_no", "tender no", "tender no.", "tendernumber",
        "tender_ref_no", "tender ref no", "tender_ref_number", "tender ref number",
        "tender_ref", "tender ref", "tender_reference", "tender reference",
    ],
    "title": [
        "title", "bid_title", "bid title", "tender_title", "tender title",
        "subject", "description_title", "item_description", "item description",
        "work_title", "work title", "name_of_work", "name of work", "tender_name", "tender name",
    ],
    "organisation": [
        "organisation", "organization", "org", "buyer", "buyer_name", "buyer name",
        "org_name", "organisation_name", "organization_name", "procuring_entity",
        "procuring entity", "authority", "department_organisation", "department organisation",
        "buyer name / organisation", "buyer name / organization", "buyer name organisation",
        "buyer name organization", "buyer / organisation", "buyer / organization",
        "buyer organisation", "buyer organization", "buyer department", "buyer / department",
    ],
    "department": [
        "department", "dept", "department_name", "dept_name", "dept.", "sub_department",
    ],
    "ministry": [
        "ministry", "ministry_name", "ministry / state", "ministry/state",
    ],
    "category": [
        "category", "bid_category", "tender_category", "product_category",
        "service_category", "item_category", "major_category",
    ],
    "bid_type": [
        "bid_type", "bid type", "tender_type", "tender type", "type",
    ],
    "published_date": [
        "published_date", "published date", "publish_date", "publish date",
        "start_date", "start date", "bid_start_date", "bid start date", "bid_publish_date",
        "bid publish date", "issue_date", "issue date", "posting_date", "posting date",
    ],
    "closing_date": [
        "closing_date", "closing date", "close_date", "close date",
        "end_date", "end date", "bid_end_date", "bid end date", "due_date", "due date",
        "submission_end_date", "submission end date", "last_date", "last date",
        "bid_submission_closing_date", "bid submission closing date",
    ],
    "location": [
        "location", "city", "state", "delivery_location", "delivery location",
        "place", "place_of_delivery", "place of delivery", "work_location", "work location",
    ],
    "estimated_value": [
        "estimated_value", "estimated value", "value", "amount",
        "estimated_amount", "estimated amount", "bid_value", "bid value",
        "tender_value", "tender value", "contract_value", "contract value",
        "total_value", "total value", "budget", "estimated_cost", "estimated cost", "cost",
        "estimated value (inr)", "estimated value inr", "estimated value (rs)", "estimated value rs",
        "bid value (inr)", "bid value inr", "tender value (inr)", "tender value inr",
    ],
    "currency": [
        "currency", "currency_code",
    ],
    "scope_of_work": [
        "scope_of_work", "scope of work", "scope", "work_description", "work description",
        "description", "brief", "brief_description", "brief description", "work_scope",
        "work scope", "detailed_description", "detailed description", "specifications",
        "specification", "technical_scope", "technical scope", "description / scope",
        "description scope", "scope / description", "scope description",
    ],
    "technical_requirements": [
        "technical_requirements", "technical requirements", "tech_requirements", "tech requirements",
        "technical_specifications", "technical specifications",
    ],
    "eligibility_criteria": [
        "eligibility_criteria", "eligibility criteria", "eligibility", "eligibility_requirements",
        "eligibility requirements",
    ],
    "qualification_requirements": [
        "qualification_requirements", "qualification requirements", "qualifications",
        "qualification", "qualification_criteria", "qualification criteria",
    ],
    "experience_requirements": [
        "experience_requirements", "experience requirements", "experience",
        "experience_criteria", "experience criteria", "prior_experience", "prior experience",
    ],
    "certification_requirements": [
        "certification_requirements", "certification requirements", "certifications",
        "certification", "required_certifications", "required certifications",
        "certifications_required", "certifications required",
    ],
    "emd_information": [
        "emd_information", "emd information", "emd", "earnest_money", "earnest money",
        "earnest_money_deposit", "earnest money deposit", "emd_amount", "emd amount",
    ],
    "tender_fee_information": [
        "tender_fee_information", "tender fee information", "tender_fee", "tender fee",
        "fee", "bid_fee", "bid fee", "tender_cost", "tender cost", "document_fee", "document fee",
    ],
    "contact_information": [
        "contact_information", "contact information", "contact", "contact_details", "contact details",
    ],
    "source_url": [
        "source_url", "source url", "url", "link", "bid_url", "bid url", "tender_url", "tender url",
        "detail_url", "detail url", "tender_detail_url", "tender detail url",
    ],
    "source_name": [
        "source_name", "source name", "source",
    ],
}

# Reverse lookup: alias (lowercase) -> canonical field name
_ALIAS_TO_CANONICAL: Dict[str, str] | None = None


def _build_reverse_map() -> Dict[str, str]:
    global _ALIAS_TO_CANONICAL
    if _ALIAS_TO_CANONICAL is None:
        _ALIAS_TO_CANONICAL = {}
        for canonical, aliases in FIELD_ALIASES.items():
            for alias in aliases:
                # normalize alias for standard lookup
                norm = alias.strip().lower().replace("-", "_").replace(".", "").replace(":", "")
                norm = re.sub(r"\s+", " ", norm).strip()
                _ALIAS_TO_CANONICAL[norm] = canonical
                _ALIAS_TO_CANONICAL[norm.replace(" ", "_")] = canonical
    return _ALIAS_TO_CANONICAL


def resolve_field_name(raw_name: str) -> str | None:
    """Return the canonical field name for *raw_name*, or None if unknown."""
    if not raw_name:
        return None
    lookup = _build_reverse_map()
    
    # 1. Direct normalized lookup
    clean = str(raw_name).strip().lower().replace("-", " ").replace("_", " ").replace(".", "").replace(":", "").replace("/", " ")
    clean = re.sub(r"\s+", " ", clean).strip()
    
    if clean in lookup:
        return lookup[clean]
    
    under = clean.replace(" ", "_")
    if under in lookup:
        return lookup[under]
        
    return None
