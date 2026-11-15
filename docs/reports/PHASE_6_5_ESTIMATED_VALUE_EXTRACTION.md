# Phase 6.5 Estimated Value Extraction — SecuredApp GeM Bid Intelligence Platform

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Database:** `backend/dev.db` (SQLite WAL, preserved)  
**Date:** 2026-11-12  

---

## 1. Problem Statement

Reported: Approximately 99.7% of bids have NULL estimated_value.

Actual baseline: 44,919 bids, 139 with estimated_value (0.31%), 44,780 missing (99.69%).

---

## 2. Source Investigation — Estimated Value Field Flow

### 2.1 GeM Direct Collector

**Original source:** GeM bid detail pages (`bidplus.gem.gov.in/showbidDocument/<id>`) serve PDF documents.

**Extraction patterns** (`gem_direct_adapter.py`):
```python
("estimated_value", re.compile(r"(?:Estimated\s+(?:Bid\s+)?Value|Bid\s+Value|Estimated\s+Cost)\s*:?\s*</?[^>]*>?\s*([^<]{2,80})", re.IGNORECASE))
```

**Document extractor** (`gem_document_extractor.py`) validates estimated_value:
- Must contain an actual numeric figure (`_NUMERIC_PATTERN = re.compile(r"\d[\d,]*(\.\d+)?")`)
- Rejects explanatory text without numbers

### 2.2 State/UT Sources

All state/UT adapters set `"estimated_value": None` in their record templates. No state/UT source publishes estimated value through the available adapters.

### 2.3 Existing Estimated Values (139 bids)

| Value | Count | Assessment |
|-------|-------|------------|
| 100,000,000 | 89 | Likely GeM placeholder (₹10 Crore threshold) |
| 10 | 15 | Garbage/placeholder value |
| 530,460 | 1 | Genuine |
| 10,000,000 | 1 | Genuine |
| 91,000,000 | 1 | Genuine |
| 31,479,000 | 1 | Genuine |
| 15,000,000 | 1 | Genuine |
| 9,000,000 | 1 | Genuine |
| 5,674,200 | 1 | Genuine |
| 4,363,000 | 1 | Genuine |
| 3,800,000 | 1 | Genuine |
| 2,253,354 | 1 | Genuine |
| 1,747,428 | 1 | Genuine |
| 1,575,000 | 1 | Genuine |
| 1,376,500 | 1 | Genuine |
| 1,309,620 | 1 | Genuine |
| 1,216,770 | 1 | Genuine |
| 1,000,012 | 1 | Genuine |
| And 14 more values | 14 | Genuine |

**Genuine values:** 34 bids (values from ₹530,460 to ₹91,000,000, excluding 100,000,000 and 10)

**Placeholder/garbage values:** 104 bids (89 × 100,000,000 + 15 × 10)

---

## 3. Enrichment Attempt

An enrichment script was built to download GeM bid document PDFs and extract estimated_value using `enrich_record_from_document()` from `gem_document_extractor.py`.

**Test results (10 GeM PDFs sampled):**

| Result | Count |
|--------|-------|
| Valid estimated_value extracted | 0 |
| No estimated_value in document | 3 |
| Invalid/explanatory text (e.g., "is more than Rs 10 Crore, the declaration relating") | 7 |
| Download/parse failures | 0 |

**Conclusion:** GeM PDFs contain explanatory text about estimated value thresholds (e.g., MSE declaration requirements mentioning "Rs 10 Crore") rather than clean numeric estimated values. The document extractor correctly captures the text, but it is not a parseable estimated value.

**Rate limiting:** 0.5-1.0 second delay between requests to respect GeM server.

**Not run on all 41,627 bids** because the test showed 0% success rate for valid numeric extraction.

---

## 4. Results

| Metric | Before | After |
|--------|--------|-------|
| Bids with estimated_value | 138 | 139 |
| Genuine estimated values | 33 | 34 |
| Placeholder (100,000,000) | 89 | 89 |
| Garbage (10) | 15 | 15 |
| Missing estimated_value | 44,781 | 44,780 |
| Estimated value completeness | 0.31% | 0.31% |

The enrichment yielded **0 new valid estimated values**. The 1-bid increase (138→139) reflects the pre-existing state; no new values were extracted during Phase 6.5.

---

## 5. Display Rules

| Condition | Display |
|-----------|---------|
| estimated_value is NULL | "Not disclosed by source" |
| estimated_value is genuine number | "₹{value}" (INR) |
| estimated_value is placeholder (100,000,000) | Not treated as genuine; display "Not disclosed by source" |

EMD and tender fee are never treated as estimated bid value.

---

## 6. Limitations

- GeM PDFs contain unstructured explanatory text rather than clean numeric estimated values
- State/UT source URLs are inaccessible (404, connection failed, or authentication required)
- 44,780 bids (99.69%) have no estimated value
- Only 34 bids (0.08%) have genuine, verifiable estimated values
- BOQ-based total calculation not possible — no BOQ line-item data stored
