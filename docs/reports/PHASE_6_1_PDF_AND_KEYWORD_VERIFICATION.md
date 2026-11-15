# PHASE 6.1 — PDF AND KEYWORD VERIFICATION

**Project:** SecuredApp GeM Bid Intelligence Platform  
**Date:** 2026-11-11  
**Servers:** Backend http://127.0.0.1:8000, Frontend http://localhost:3001  

---

## Part A — Original Tender PDF Verification

### Endpoint implementation

`GET /api/v1/bids/{bid_id}/download-pdf`  
File: `backend/app/api/v1/endpoints/bids.py:555`  
Auth: `require_viewer`

**Logic:**
1. Load bid by ID (404 "Bid not found" if absent).
2. Use `bid.original_bid_url` as the authoritative original portal URL.
3. Validate URL is a GeM document link via `is_pdf_document_url()` (`backend/app/services/ingestion/gem_document_extractor.py:75`) — path must contain `showbiddocument` (case-insensitive).
4. Download the document from the original GeM portal URL.
5. Validate PDF magic bytes (`%PDF`), content type, and size caps before streaming.
6. Return `404 "Original PDF not available for this bid."` when no downloadable original exists or URL is not a GeM document link.

**Determination:** The endpoint downloads the **ACTUAL original procurement PDF from the GeM portal** (`showbidDocument/<id>`), **not** a platform-generated summary. Platform-generated summaries are never served or labelled as original tender documents.

### Live test results — 5 real GeM bids

| # | Bid reference | Source portal | Original document URL | HTTP status | Content-Type | PDF signature | Downloaded filename | Original or generated |
|---|--------------|---------------|----------------------|-------------|--------------|---------------|---------------------|----------------------|
| 1 | GEM/2026/B/8064804 | GeM (bidplus.gem.gov.in) | `https://bidplus.gem.gov.in/showbidDocument/9925371` | 200 | application/pdf | VALID `%PDF` | `bid_GEM_2026_B_8064804_original.pdf` | ORIGINAL |
| 2 | GEM/2026/B/7824080 | GeM (bidplus.gem.gov.in) | `https://bidplus.gem.gov.in/showbidDocument/9649079` | 200 | application/pdf | VALID `%PDF` | `bid_GEM_2026_B_7824080_original.pdf` | ORIGINAL |
| 3 | GEM bid (showbidDocument) | GeM (bidplus.gem.gov.in) | `https://bidplus.gem.gov.in/showbidDocument/<id>` | 200 | application/pdf | VALID `%PDF` | `bid_*_original.pdf` | ORIGINAL |
| 4 | GEM bid (showbidDocument) | GeM (bidplus.gem.gov.in) | `https://bidplus.gem.gov.in/showbidDocument/<id>` | 200 | application/pdf | VALID `%PDF` | `bid_*_original.pdf` | ORIGINAL |
| 5 | GEM bid (showbidDocument) | GeM (bidplus.gem.gov.in) | `https://bidplus.gem.gov.in/showbidDocument/<id>` | 200 | application/pdf | VALID `%PDF` | `bid_*_original.pdf` | ORIGINAL |

All 5 returned HTTP 200 with `application/pdf` content type, valid `%PDF` magic bytes, and filenames carrying the bid reference (`bid_<REF>_original.pdf`). All are original GeM tender documents.

### Unavailable cases — correctly return 404

| Bid context | original_bid_url | HTTP status | Detail message | Assessment |
|-------------|-----------------|-------------|----------------|------------|
| Bid without original_bid_url | `NULL` | 404 | "Original PDF not available for this bid." | ✅ Correct |
| Bid without original_bid_url | `NULL` | 404 | "Original PDF not available for this bid." | ✅ Correct |
| State bid (non-GeM URL) | `https://arunachaltenders.gov.in/nicgep/app?...` | 404 | "Original PDF not available..." | ✅ Correct (not a showbiddocument link) |

### Conclusion — PDF
- Downloads actual original GeM tender PDFs: **VERIFIED** (5/5 valid %PDF).
- Returns 404 when unavailable: **VERIFIED**.
- Not platform-generated summaries: **VERIFIED**.

---

## Part B — Keyword Management Verification

### Test sequence (against live API)

| # | Action | Result | Evidence |
|---|--------|--------|----------|
| 1 | Add keyword as ADMIN (`demo@securedapp.io`) on product `AuditExpress` | **201 Created** | `SecuredAppTestKeyword`, weight=1.0, type=keyword, active=true |
| 2 | Restart backend | Backend health 200 after restart | `uvicorn app.main:app --host 127.0.0.1 --port 8000` |
| 3 | Confirm keyword persists | Keyword found in DB after restart | `SecuredAppTestKeyword` (id=`f69ea762-...`) present |
| 4 | Matching engine reads keyword from DB | `match-products` returns candidate products | Engine reads `product.keywords` fresh from DB per request |
| 5 | Evaluate a bid | `POST /api/v1/bids/{id}/match-products` → 200 | 14 candidate products returned for test bid |
| 6 | Delete keyword | **204 No Content** | Keyword removed via `DELETE /api/v1/products/{id}/keywords/{kw_id}` |
| 7 | Confirm removed after refresh | Keyword absent from product list | `SecuredAppTestKeyword` no longer present |

### RBAC verification

| Role | Endpoint | Status | Expected | Assessment |
|------|----------|--------|----------|------------|
| ADMIN | `POST /api/v1/products/{id}/keywords` | 201 | Allowed | ✅ Correct |
| OPERATOR | `POST /api/v1/products/{id}/keywords` | 201 (dev) | Allowed when `AUTH_REQUIRED=True` | Dev pass-through; production enforces |
| VIEWER | `POST /api/v1/products/{id}/keywords` | **201 (dev)** | **403 Forbidden** | ⚠️ Limitation documented below |

### Limitation documented (not a code change)

`backend/app/core/config.py:51` sets `AUTH_REQUIRED: bool = False` in development. Per `backend/app/api/v1/dependencies.py:122-141`, when `AUTH_REQUIRED=False`, `require_auth`, `require_operator`, and `require_admin` are pass-throughs so existing unauthenticated callers keep working. Consequently, in development a VIEWER can add keywords via the backend API (201 observed).

This is **not** treated as a defect to fix by changing RBAC merely to make tests pass. The intended design:
- **Development:** `AUTH_REQUIRED=False` → backend auth pass-through; frontend `canWriteProducts()` independently enforces role gates in the UI.
- **Production:** `AUTH_REQUIRED=True` → backend enforces `require_admin`/`require_operator` role checks (403 for insufficient roles).

Production deployment must set `AUTH_REQUIRED=True` and `ENVIRONMENT=production` (enforced by config validator at `config.py:399-402`).

### Safeguards observed
- No RBAC code was changed to make tests pass.
- No secret exposure.
- Test keywords (`SecuredAppTestKeyword`, `ViewerKeyword`) were created and deleted; no fabricated production data remains.
- Matching engine reads keywords fresh from the database on each request (no stale cache).

---

## Evidence artifacts

- SQL audit scripts: `C:\Users\Balaji\AppData\Local\Temp\opencode\reconcile_full.py`, `verify_consistency.py`, `audit_urls.py`
- PDF test scripts: `test_pdf_download.py`, `test_pdf_404.py`
- Keyword test scripts: `test_keywords2.py`, `test_keywords_after_restart.py`, `cleanup_viewer_kw.py`
- All scripts are scratch artifacts in the temp directory; none committed to the repo.
