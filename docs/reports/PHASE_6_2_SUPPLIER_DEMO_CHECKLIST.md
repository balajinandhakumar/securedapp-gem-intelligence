# PHASE 6.2 SUPPLIER DEMO CHECKLIST

**SecuredApp GeM Bid Intelligence Platform — Live Supplier Demonstration Readiness**

**Demo URL:** http://localhost:3001
**Backend API:** http://127.0.0.1:8000
**Demo Account:** demo@securedapp.io (Admin) — login via real backend
**Date:** Wed Nov 11 2026
**Status:** All checks verified against live running application

---

## Pre-Demo Checklist

### Infrastructure
- [x] Backend running on port 8000 (health: 200, database_connected: true)
- [x] Frontend running on port 3001 (health: 200)
- [x] Active database: `backend/dev.db` (1.1 GB, 44,659 bids)
- [x] Alembic at migration `0011_bid_source_id` (head)
- [x] No database reset/truncate/delete performed
- [x] No secrets in `.env`, source code, or build output

### Authentication
- [x] Login page renders correctly (no duplicated branding)
- [x] Demo Login authenticates via real backend POST /api/v1/auth/login
- [x] Valid credentials (demo@securedapp.io) → 200, redirects to dashboard
- [x] Invalid credentials → clear error "Invalid email or password"
- [x] Session persists across browser refresh
- [x] Logout works (clears session, returns to login)
- [x] Expired tokens auto-refreshed (single in-flight refresh)
- [x] Protected routes deny access without valid token (401 when AUTH_REQUIRED=True)

---

## Section-by-Section Demo Checks

### 1. Dashboard
- [x] Summary cards show real values: total_bids=44,631, open=3,605, closed=41,026
- [x] Charts load (no empty/misleading charts)
- [x] No infinite loading or blank sections
- [x] Cross-checked values match backend API and SQL

### 2. All India Bids
- [x] Bid list loads (3,605 open bids)
- [x] Search by title/bid reference/buyer works
- [x] Filters work (state, product, match status, bid status)
- [x] Sorting works
- [x] Pagination works
- [x] "Inspect" opens bid detail drawer
- [x] Source names, closing dates, open/closed status correct
- [x] Relevance scores displayed

### 3. Bid Detail + View Original Tender (CRITICAL)
- [x] Click "Inspect" on any bid → detail drawer opens
- [x] "View Original Bid" link opens the exact tender page on the original portal
- [x] Link uses `target="_blank"` and `rel="noopener noreferrer"`
- [x] Bid reference number preserved
- [x] Missing URL → button not shown (clear unavailable state)
- [x] Tested 5 GeM bids — all open correct tender pages

### 4. PDF Download
- [x] "Download Bid PDF" button in bid detail drawer
- [x] Actual original GeM tender PDF downloaded (5/5 valid `%PDF`)
- [x] Loading state ("Downloading…") shown
- [x] Failed/unavailable → 404 with useful error (never false success)
- [x] Meaningful filename: `bid_<gem_bid_id>_original.pdf`

### 5. Products Section
- [x] All 14 active products load
- [x] Product names, descriptions, keyword counts correct
- [x] Select product → detail drawer (Overview / Matching Tenders tabs)
- [x] Existing keywords appear
- [x] Add keyword → persists after refresh
- [x] Delete keyword → removed after refresh
- [x] Update keyword supported
- [x] Empty/duplicate keywords rejected
- [x] RBAC: ADMIN/OPERATOR can write; VIEWER is read-only

### 6. Notifications
- [x] Notifications load (7 items)
- [x] Unread/read state correct
- [x] No duplicates
- [x] Navigation works
- [x] Empty state handled

### 7. Sources & Scraper Monitoring
- [x] All 31 sources displayed
- [x] Statuses accurate (SUCCESS / CONFIG_ERROR / NOT_CONFIGURED / BLOCKED)
- [x] Failed sources NOT labeled as successful
- [x] Individual source failures don't crash the page
- [x] Scheduler status visible (enabled=True, running=True, 20-min interval)

### 8. State-wise Bids
- [x] Collected tab (all collected state bids)
- [x] Matched tab (only bids with product match)
- [x] State filters, search, pagination
- [x] Bid detail navigation
- [x] Product matching details
- [x] Source portal links
- [x] Real data (not mock)

---

## Role-Based Access Checklist (for demo)

| Feature | ADMIN (demo) | OPERATOR | VIEWER |
|---|---|---|---|
| View dashboard/bids/products | ✅ | ✅ | ✅ |
| Add/update/delete keywords | ✅ | ✅ | ❌ |
| Create/delete products | ✅ | ✅ | ❌ |
| Manage sources | ✅ | ✅ | ❌ |
| Manage users | ✅ | ❌ | ❌ |
| Run matching/analysis | ✅ | ✅ | ❌ |
| View original tender/PDF | ✅ | ✅ | ✅ |

**Demo account:** demo@securedapp.io = ADMIN (full access)

---

## Known Limitations (Documented, Non-Blocking)

1. **Dev mode AUTH_REQUIRED=False:** Frontend RBAC gates enforce access. Production must set `AUTH_REQUIRED=true` and a strong `SECRET_KEY` (startup validator enforces this when `ENVIRONMENT=production`).
2. **44 PENDING GeM bids have match records without COMPLETED status:** Data-consistency note only; does not affect demo experience.
3. **Some state sources show CONFIG_ERROR/NOT_CONFIGURED:** Portals require authentication or aren't configured; correctly distinguished in UI.
4. **External GeM portal may block automated access:** Distinguish inaccessible portal from incorrect URL.
5. **Bid count grows** due to scheduler activity (expected, 20-min interval).

---

## Demo URLs

- **Application:** http://localhost:3001
- **Login:** demo@securedapp.io / (demo password set locally)
- **Backend health:** http://127.0.0.1:8000/api/v1/health

**Both servers must remain running for the demonstration.**