# PHASE 8 — STATE ATTRIBUTION REPORT (8A)

**SecuredApp GeM Bid Intelligence Platform**
**Version:** 1.0 — Phase 8 (State/UT Scraper Pipeline)
**Date:** 2026-11-10
**Scope:** Authoritative `Bid.source_id` attribution to `data_sources.id`

---

## 1. Executive Summary

Phase 8A fixes state/UT bid attribution. Previously, state-wise views joined
`Bid.source_name == DataSource.name` as a string, which split states whose
portal display name has variants (e.g. "Jammu & Kashmir e-Procurement" vs
"Jammu and Kashmir e-Procurement"; "Sikkim Government Tender Portal" vs
"Sikkim e-Procurement"). A new authoritative `Bid.source_id` foreign key to
`data_sources.id` (set at collection time) replaces the fragile string join.

All changes are uncommitted on `main`. No database deletion/truncation, no
fabricated bids, no existing functionality removed.

---

## 2. What changed

### 2.1 Bid model (`backend/app/models/bid.py`)
Added a nullable `source_id` column:
- Type: `GUID()`
- Foreign key: `data_sources.id`, `ondelete="SET NULL"`
- Nullable: yes (historical bids keep `source_name` text if a source row is removed)
- Indexed: yes

### 2.2 Alembic migration
`backend/alembic/versions/0011_bid_source_id.py` (down_revision `0010_bid_original_bid_url`)
- Uses SQLite batch mode (inline FK constraints are not supported by SQLite
  `ADD COLUMN`)
- `upgrade()`: adds `source_id` column + `fk_bids_source_id_data_sources` FK
- `downgrade()`: drops FK then column
- Applied to `backend/dev.db`; `alembic head = 0011_bid_source_id`

### 2.3 Backfill script
`backend/scripts/backfill_source_id.py` (already run)
- Exact `Bid.source_name` → `DataSource.name` match: 2,136 bids
- Variant mapping → canonical `source_id`:
  - "Jammu & Kashmir e-Procurement" / "Jammu and Kashmir e-Procurement" → `jammu_kashmir`
  - "Sikkim Government Tender Portal" / "Sikkim e-Procurement" → `sikkim`
- 115 variant bids re-attributed
- Total state bids backfilled: 2,251 (2,136 exact + 115 variant); 1 bid already
  had `source_id` set (unchanged)
- 41,811 GeM bids keep `source_id = NULL` (correctly excluded from state views)

### 2.4 Runner (`backend/app/services/sources/runner.py`)
Newly persisted bids now set `bid_data["source_id"] = source.id`, so every
future state collection is authoritatively attributed.

---

## 3. Attribution verification (via `source_id` join)

Jammu & Kashmir unified from two name variants into one state:
- "Jammu & Kashmir e-Procurement": 114 bids
- "Jammu and Kashmir e-Procurement": 16 bids
- **J&K total: 130 bids** (previously split across two rows)

Sikkim unified from two name variants into one state:
- "Sikkim Government Tender Portal": 1 bid
- "Sikkim e-Procurement": 12 bids
- **Sikkim total: 13 bids**

State | Source name | Status | Collected (via source_id)
------|-------------|--------|--------------------------
Andhra Pradesh | Andhra Pradesh e-Procurement | CONFIG_ERROR | 0
Arunachal Pradesh | Arunachal Pradesh e-Procurement | SUCCESS | 10
Assam | Assam e-Procurement | SUCCESS | 78
Bihar | Bihar e-Procurement | CONFIG_ERROR | 0
Chandigarh | Chandigarh e-Procurement | SUCCESS | 55
Chhattisgarh | Chhattisgarh e-Procurement | NO_RECORDS | 0
Delhi | Delhi e-Procurement | SUCCESS | 126
Goa | Goa e-Procurement | BLOCKED | 0
Gujarat | Gujarat e-Procurement | CONFIG_ERROR | 0
Haryana | Haryana e-Procurement | SUCCESS | 179
Himachal Pradesh | Himachal Pradesh e-Procurement | SUCCESS | 87
Jammu & Kashmir | Jammu and Kashmir e-Procurement | SUCCESS | 130
Jharkhand | Jharkhand e-Procurement | SUCCESS | 91
Karnataka | Karnataka e-Procurement | CONFIG_ERROR | 0
Kerala | Kerala e-Procurement | SUCCESS | 186
Madhya Pradesh | Madhya Pradesh e-Procurement | SUCCESS | 169
Maharashtra | Maharashtra e-Procurement | SUCCESS | 233
Manipur | Manipur e-Procurement | NO_RECORDS | 10
Meghalaya | Meghalaya e-Procurement | SUCCESS | 10
Mizoram | Mizoram e-Procurement | SUCCESS | 2
Nagaland | Nagaland e-Procurement | SUCCESS | 5
Odisha | Odisha e-Procurement | SUCCESS | 101
Punjab | Punjab e-Procurement | SUCCESS | 101
Rajasthan | Rajasthan e-Procurement | SUCCESS | 106
Sikkim | Sikkim e-Procurement | SUCCESS | 13
Tamil Nadu | Tamil Nadu e-Procurement | SUCCESS | 211
Telangana | Telangana e-Procurement | CONFIG_ERROR | 0
Tripura | Tripura e-Procurement | SUCCESS | 48
Uttar Pradesh | Uttar Pradesh e-Procurement | SUCCESS | 118
Uttarakhand | Uttarakhand e-Procurement | SUCCESS | 74
West Bengal | West Bengal e-Procurement | SUCCESS | 109
**Total** | | | **2,252**

Source counts: 31 total (23 SUCCESS, 5 CONFIG_ERROR, 2 NO_RECORDS, 1 BLOCKED).

---

## 4. Evidence

| File | Description |
|------|-------------|
| `PHASE_8_EVIDENCE/db/reconciliation.json` | Full DB reconciliation (per-state counts, FK, variant mapping) |
| `PHASE_8_EVIDENCE/db/reconciliation.txt` | Human-readable per-state reconciliation |
| `backend/alembic/versions/0011_bid_source_id.py` | Migration |
| `backend/scripts/backfill_source_id.py` | Backfill script |
| `backend/app/models/bid.py` | Bid model (with `source_id`) |
| `backend/app/services/sources/runner.py` | Runner sets `source_id` on new bids |

---

## 5. Preservation statement

- No `git reset --hard`, `git clean`, or discard of uncommitted changes
- No database deletion, truncation, or recreation
- No historical bid records modified (only `source_id` populated where NULL)
- No working features removed
- No commits or pushes made

---

*End of Phase 8 State Attribution Report*
