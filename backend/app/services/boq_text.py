"""Pure helpers for turning stored BoQ evidence into matchable text.

This module deliberately has **no** imports from the ingestion or intelligence
packages: the matching engine imports it, and the ingestion package imports the
matching engine (via the batch processor), so anything the engine pulls in must
be a leaf module to avoid an import cycle.
"""
from __future__ import annotations

from typing import Any, Iterable, List


def boq_item_lines(boq_items: Any) -> List[str]:
    """Return the distinct title/description lines from stored BoQ evidence.

    Accepts the stored evidence envelope (``{"items": [...]}``) or a bare list of
    item dicts. Blank values are skipped and duplicate lines are collapsed so a
    CSV whose title and description are identical contributes one line.
    """
    if isinstance(boq_items, dict):
        items: Iterable[Any] = boq_items.get("items") or []
    elif isinstance(boq_items, (list, tuple)):
        items = boq_items
    else:
        return []

    seen: set = set()
    lines: List[str] = []
    for item in items:
        if isinstance(item, dict):
            values = (item.get("title"), item.get("description"))
        elif isinstance(item, str):
            values = (item,)
        else:
            continue
        for value in values:
            text = (value or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            lines.append(text)
    return lines


def boq_evidence_text(boq_items: Any) -> str:
    """Lower-cased, comma-joined BoQ line text for matching ("" when absent).

    The BoQ line items are the tender's actual scope of work, so the matching
    engine folds this text into the existing ``scope_of_work`` evidence channel.
    No weights, thresholds or knowledge are involved here.
    """
    return ", ".join(boq_item_lines(boq_items)).lower()


def boq_item_count(boq_items: Any) -> int:
    """Number of line items in a stored BoQ evidence envelope."""
    if isinstance(boq_items, dict):
        count = boq_items.get("item_count")
        if isinstance(count, int):
            return count
        items = boq_items.get("items")
        return len(items) if isinstance(items, list) else 0
    if isinstance(boq_items, (list, tuple)):
        return len(boq_items)
    return 0
