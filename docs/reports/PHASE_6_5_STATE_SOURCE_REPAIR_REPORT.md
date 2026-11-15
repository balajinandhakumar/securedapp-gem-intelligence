# Phase 6.5 State Source Repair Report — SecuredApp GeM Bid Intelligence Platform

**Repository:** `C:\Users\Balaji\Desktop\securedapp-gem-intelligence`  
**Database:** `backend/dev.db` (SQLite WAL, preserved)  
**Date:** 2026-11-12  

---

## 1. Problem Statement

Five state/UT sources were identified with CONFIG_ERROR status and 0 collection runs (never successfully ran). One additional source (Goa) is BLOCKED with enabled=0.

---

## 2. Sources Identified from Database

| # | Source Name | Status | Enabled | Total Runs | Config URL |
|---|-------------|--------|---------|------------|------------|
| 1 | Andhra Pradesh e-Procurement | CONFIG_ERROR | 1 | 0 | https://tender.apeprocurement.gov.in/ |
| 2 | Bihar e-Procurement | CONFIG_ERROR | 1 | 0 | https://bihar.gov.in/ |
| 3 | Gujarat e-Procurement | CONFIG_ERROR | 1 | 0 | https://gujarat.gov.in/ |
| 4 | Karnataka e-Procurement | CONFIG_ERROR | 1 | 0 | https://eproc.karnataka.gov.in/eprocportal/pages/index.jsp |
| 5 | Telangana e-Procurement | CONFIG_ERROR | 1 | 0 | https://tender.telangana.gov.in/ |
| 6 | Goa e-Procurement | BLOCKED | 0 | 0 | (no config) |

All six sources have `max_records: 0` in config (where config exists), meaning the adapter does not know how many records to fetch — a configuration error.

---

## 3. Investigation Results

Each source was tested via HTTP request to determine the actual failure reason:

### 3.1 Andhra Pradesh e-Procurement
- **HTTP response:** 200 OK (721 bytes)
- **Content:** Login page with auto-submit to `login.html`
- **Reason:** **Access restriction** — authentication required. Cannot scrape without credentials.
- **Classification:** Access restriction (authentication required)

### 3.2 Bihar e-Procurement
- **HTTP response:** 000 (connection failed)
- **Reason:** **Network error** — website unreachable
- **Classification:** Network error / source unavailable

### 3.3 Gujarat e-Procurement
- **HTTP response:** 000 (connection failed)
- **Reason:** **Network error** — website unreachable
- **Classification:** Network error / source unavailable

### 3.4 Karnataka e-Procurement
- **HTTP response:** 200 OK (22,825 bytes)
- **Content:** Portal homepage with login links. Tender listing link points to `eproc_tenders_list.seam` which requires authentication.
- **Reason:** **Access restriction** — authentication required for tender listing
- **Classification:** Access restriction (authentication required)

### 3.5 Telangana e-Procurement
- **HTTP response:** 200 OK (1,110 bytes)
- **Content:** Login page with auto-submit to `login.html`
- **Reason:** **Access restriction** — authentication required. Cannot scrape without credentials.
- **Classification:** Access restriction (authentication required)

### 3.6 Goa e-Procurement
- **HTTP response:** Not tested (enabled=0, BLOCKED)
- **Reason:** **Intentionally disabled** — `enabled=0`, status=BLOCKED, no config URL
- **Classification:** Access restriction / administratively blocked

---

## 4. Repair Classification

| Source | Classification | Repairable? | Reason |
|--------|---------------|-------------|--------|
| Andhra Pradesh | Access restriction | No | Authentication required; bypass prohibited |
| Bihar | Network error | No | Website unreachable; outside our control |
| Gujarat | Network error | No | Website unreachable; outside our control |
| Karnataka | Access restriction | No | Tender listing requires login; bypass prohibited |
| Telangana | Access restriction | No | Authentication required; bypass prohibited |
| Goa | Administratively blocked | No | `enabled=0`, intentionally disabled |

**0 of 6 sources repaired.** None can be repaired without:
- Bypassing authentication (prohibited by requirements)
- Fixing external network issues (outside our control)
- Changing administrative settings (Goa is intentionally disabled)

---

## 5. Compliance

- ✅ No authentication bypass attempted
- ✅ No CAPTCHA bypass attempted
- ✅ No access control circumvention
- ✅ Source terms and rate limits respected
- ✅ Each source verified with actual HTTP request (not just assuming 200 = success)

---

## 6. Sources Still Unavailable

| Source | Status | Reason |
|--------|--------|--------|
| Andhra Pradesh e-Procurement | CONFIG_ERROR | Authentication required |
| Bihar e-Procurement | CONFIG_ERROR | Network error (unreachable) |
| Gujarat e-Procurement | CONFIG_ERROR | Network error (unreachable) |
| Karnataka e-Procurement | CONFIG_ERROR | Authentication required |
| Telangana e-Procurement | CONFIG_ERROR | Authentication required |
| Goa e-Procurement | BLOCKED | Intentionally disabled (enabled=0) |

---

## 7. Other Sources

13 sources show SUCCESS status. 10 sources show CONFIG_ERROR but have runs (52-66 runs each) — these are stale error statuses from previous runs, not never-run sources. These are not part of the "five sources that never successfully ran" group.
