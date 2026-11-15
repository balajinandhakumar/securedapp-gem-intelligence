# PHASE 7 — SUPPLIER DEMONSTRATION GUIDE

**SecuredApp GeM Bid Intelligence Platform**
**Version:** 1.0 — Phase 7 (Supplier Demonstration Readiness)
**Status:** Ready for local supplier demonstration

---

## 1. Overview

The SecuredApp GeM Bid Intelligence Platform helps suppliers discover, track, and evaluate government procurement opportunities published on the GeM (Government e-Marketplace) portal and state/UT procurement portals.

This guide provides a complete, repeatable supplier demonstration workflow (5–10 minutes) using **real database records** — no fabricated bids, no artificial opportunities, no mocked data.

### What the platform does

- Collects GeM public bid listings automatically (no credentials required).
- Matches each bid against the supplier's product catalogue using keywords.
- Scores relevance so suppliers see the most relevant opportunities first.
- Shows state-wise and All-India views of procurement coverage.
- Tracks scraper/source health so you know which portals are collecting.

### What the platform does NOT do

- Does not bypass GeM login walls, CAPTCHA, or anti-bot measures.
- Does not fabricate bids or procurement opportunities.
- Does not claim nationwide complete coverage — only sources with verified collection are shown as active.
- Does not store or transmit your credentials in plain text.

---

## 2. Prerequisites

### Services (must be running)

| Service | URL | Port |
|---------|-----|------|
| Backend API | `http://127.0.0.1:8002` | 8002 |
| Frontend (Vite dev server) | `http://localhost:3004` | 3004 |

### Start services (Windows)

```powershell
# From the repository root
.\start_services.ps1
```

The script checks whether each service is already running before starting, avoids duplicate processes, and logs to `logs/startup.log`.

Verify before demo:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8002/api/v1/health" -UseBasicParsing
Invoke-WebRequest -Uri "http://localhost:3004/" -UseBasicParsing
```

Both should return HTTP 200.

### Demo account

A demo user exists in the development database:

- **Email:** `demo@securedapp.io` (or `admin@securedapp.io`)
- **Role:** admin
- **Source:** real database user, not hardcoded in source code

The demo password is **not** in source code. The platform owner sets it locally in `frontend/.env` (`VITE_DEMO_PASSWORD`). Do not ask the supplier for the password; the demonstrator enters it.

Demo Login authenticates through the **real backend** (`POST /api/v1/auth/login`) — no fake session, no JWT bypass, no mocked token.

---

## 3. Demonstration Script (5–10 minutes)

| # | Step | What to show | What to say |
|---|------|-------------|-------------|
| 1 | **Open the application** | Browser at `http://localhost:3004` | "This is the SecuredApp GeM Bid Intelligence Platform — a supplier-facing tool for discovering government procurement opportunities." |
| 2 | **Login** | Click Demo Login, enter demo credentials | "We log in with a real demo account. Authentication goes through the real backend — no bypass, no mocked session." |
| 3 | **Dashboard** | Show totals: bids, open, closed, relevant matches | "The dashboard shows genuine database-backed counts — total bids collected, open vs. closed, product-relevant matches, and closing-soon items." |
| 4 | **GeM bid collection** | Ingestion/Data Source tab | "GeM public bids are collected automatically every 20 minutes. No GeM credentials are used — only the public portal." |
| 5 | **State/UT coverage** | Scraper & Source Monitoring tab | "We show exactly which state/UT portals are collecting, which have no new records, and which are blocked. No false claims of nationwide coverage." |
| 6 | **Bid intelligence** | Bids tab, search for a product | "Search for a relevant procurement opportunity — e.g. 'laptop', 'server', 'cybersecurity'. Results come from real collected bids." |
| 7 | **Open a bid** | Click a bid → Bid Detail Drawer | "Open any bid to see its full details: buyer, value, closing date, original source link, and product relevance score." |
| 8 | **Original source portal** | "View Original Bid" link | "Each bid links back to its genuine original source portal. We never fabricate source URLs." |
| 9 | **PDF download** | Download original bid PDF where available | "Where the source portal publishes a PDF, it can be downloaded directly. We do not host or reproduce procurement documents." |
| 10 | **Product relevance score** | Match score and matched keywords | "Each bid is matched against your product catalogue using keywords. The score shows how relevant this bid is to your products." |
| 11 | **Matched SecuredApp product** | Products tab → open a product | "Open the matched product to see its description and configured keywords." |
| 12 | **Add/remove a keyword** | Keyword management on a product | "Demonstrate adding and removing a keyword (authorized access required). Explain how product matching uses these keywords." |
| 13 | **State-wise and All-India views** | State-wise Bids / All-India tabs | "See procurement broken down by state/UT, or view all India product-relevant bids." |
| 14 | **Source monitoring** | Scraper & Source Monitoring tab | "Show collection status, latest timestamps, and which sources are active vs. blocked." |
| 15 | **Notifications** | Notifications tab/drawer | "New relevant bids trigger notifications so suppliers don't miss opportunities." |
| 16 | **Business value** | Summary | "Find relevant government bids faster, understand product matching, and track procurement across states — all from real data." |

---

## 4. Example Real Bid Records

Use actual records from the development database (43,987 bids collected). Example fields shown on a bid detail:

| Field | Example (real) |
|-------|----------------|
| Bid reference | From GeM listing (e.g., GEM/2024/B/...) |
| Title | Real published bid title |
| Buyer | Government department/ministry |
| Value | Published bid value |
| Closing date | Real published closing date |
| Source URL | `https://bidplus.gem.gov.in/...` |
| Relevance score | 0.0–1.0 computed from keyword matching |
| Matched keywords | List of product keywords that matched |

**Do not fabricate** bid numbers, values, or URLs. If a field is empty in the database, show it as empty.

---

## 5. How to Explain Product Matching

1. Each SecuredApp product has a set of keywords (e.g., "cybersecurity", "encryption", "identity verification").
2. Each collected GeM bid is scanned for those keywords in its title and scope.
3. A relevance score (0.0–1.0) is computed based on keyword matches.
4. Bids above the relevance threshold appear in "All India – Product Relevant Bids".
5. Suppliers can add/remove keywords on any product they own to refine matching.

**Demo tip:** Add a test keyword to a product, then search the bids feed to see how results change. Clearly label this as demonstration-only test data.

---

## 6. How to Explain Scraper Coverage

Distinguish four categories (never claim complete nationwide coverage):

| Category | Meaning | Example |
|----------|---------|---------|
| Collecting successfully | Source is actively collecting new bids | GeM direct public portal |
| No new records | Source configured but returned no new bids in last run | Some state portals |
| Blocked/unavailable | Source is blocked by CAPTCHA, login wall, or anti-bot | Andhra Pradesh, Bihar, Gujarat, Karnataka, Telangana (restricted portals) |
| Requires configuration | Source needs additional setup before collection | Sources without saved configuration |

**Never** describe restricted portals as working. **Never** bypass CAPTCHA, login walls, DNS restrictions, or anti-bot mechanisms.

---

## 7. How to Demonstrate Original Bid Links and PDF Downloads

1. Open a bid detail from the bids feed.
2. Click "View Original Bid" — opens the genuine source portal URL in a new tab (`target="_blank"`, `rel="noopener noreferrer"`).
3. Where the source portal offers a PDF, download it directly from the source portal.
4. The platform does **not** host, reproduce, or re-serve procurement documents.

---

## 8. How to Demonstrate Keyword Management

1. Go to the Products tab.
2. Click a product to open its keyword manager.
3. Add a keyword (e.g., "vulnerability assessment") with type `keyword` and weight `1.0`.
4. Remove a keyword using the delete button.
5. Explain: adding/removing keywords changes which bids match this product.

**Requires Operator or Admin role.** The demo account has admin role.

---

## 9. Common Supplier Questions and Answers

| Question | Answer |
|----------|--------|
| "Do I need a GeM account to use this?" | No. The platform collects from the **public** GeM portal. No GeM credentials are used or stored. |
| "Are these real bids?" | Yes. All data comes from actual GeM and state/UT portal collection — no fabricated records. |
| "Which states are covered?" | Only sources with verified collection are shown as active. Some portals (e.g., Andhra Pradesh, Bihar, Gujarat, Karnataka, Telangana) are blocked/restricted and are not described as working. |
| "Can I download bid documents?" | Yes, where the source portal publishes a PDF — download directly from the source. The platform does not host documents. |
| "How is relevance calculated?" | Keyword matching against your product catalogue, scored 0.0–1.0. |
| "Can I add my own products/keywords?" | Yes, with Operator or Admin role. |
| "Is my data secure?" | Authentication via JWT, password hashing, rate limiting, account lockout, and security headers. Demo Login is development-only and can be disabled in production. |

---

## 10. Known Limitations

- Five state/UT portals (Andhra Pradesh, Bihar, Gujarat, Karnataka, Telangana) are blocked or unavailable and cannot be collected without bypassing restrictions — which we do not do.
- Dashboard loads real data from 43,987 bids; first load may take a few seconds as APIs warm up.
- Demo Login is a development convenience; it is controlled by environment configuration and can be disabled for production.
- Rate limiting is active — rapid repeated requests may be throttled.

---

## 11. Troubleshooting

| Issue | Resolution |
|-------|------------|
| Frontend won't load | Verify `http://localhost:3004/` returns HTTP 200. Run `.\start_services.ps1`. |
| Backend won't load | Verify `http://127.0.0.1:8002/api/v1/health` returns HTTP 200. Check `logs/backend-uvicorn.log`. |
| Login fails | Verify backend is running. Confirm demo user exists in `backend/dev.db`. Check `logs/backend-uvicorn-err.log`. |
| Bids feed empty | GeM collection may be between runs. Check Scraper & Source Monitoring for latest collection timestamp. |
| Dashboard slow | Real data from 43,987 bids. Wait for API responses (~2–5s warm). |

---

## 12. Shutdown

```powershell
.\stop_services.ps1
```

Stops only the backend uvicorn and frontend vite processes started by `start_services.ps1`. Never terminates unrelated processes.

---

## 13. Service URLs and Process IDs

| Service | URL | Status |
|---------|-----|--------|
| Backend API | `http://127.0.0.1:8002` | Running |
| Frontend | `http://localhost:3004` | Running |
| Health check | `http://127.0.0.1:8002/api/v1/health` | HTTP 200 |
| GeM collector | `http://127.0.0.1:8002/api/v1/ingestion/gem-direct/status` | READY |

Check running processes:

```powershell
Get-Process | Where-Object { $_.ProcessName -like "*python*" -or $_.ProcessName -like "*node*" }
```

---

*End of Supplier Demonstration Guide*
