# Bid Intelligence & Relevance Engine Architecture

## Overview
The SecuredApp GeM Bid Intelligence platform implements a multi-layer evaluation pipeline that combines deterministic signal matching, product knowledge vector scoring, pairwise product differentiation, requirement extraction, eligibility assessment, and opportunity rating.

---

## 1. Evaluation Pipeline Flow

```
Approved Procurement Source (GeM / Ingestion File)
        ↓
Ingestion Adapter (CSV / JSON / XLSX)
        ↓
Validation & Normalization (Field aliases, currency/date parsing, clean text)
        ↓
SHA-256 Deduplication & Fuzzy Candidate Detection
        ↓
Product Knowledge Matching Engine (11 Products)
        ↓
Pairwise Product Differentiation Pass
        ↓
Requirement & Evidence Extraction (Structured AI / Deterministic Provider)
        ↓
Eligibility Analysis (CONFIRMED, UNKNOWN, POTENTIAL_CONFLICT, REQUIRES_HUMAN_VERIFICATION)
        ↓
Opportunity Analysis (Relevance + Contract Value + Eligibility + Deadline Feasibility)
        ↓
Dashboard Visualization & Human Review Decision
        ↓
Audit Logging & Event Notifications
```

---

## 2. Canonical Relevance Score & Classification

Every bid-to-product pair produces exactly **one** canonical final relevance score (`final_relevance_score`) in the range **`0.0` to `1.0`**.

### Classification Rules

| Relevance Score Range | Classification | Action / Meaning |
| :--- | :--- | :--- |
| **`>= 0.70`** | **`MATCH`** | Strong alignment with product capability vector |
| **`>= 0.45` and `< 0.70`** | **`POSSIBLE_MATCH`** | Moderate alignment, potential opportunity candidate |
| **`>= 0.25` and `< 0.45`** | **`NEEDS_REVIEW`** | Low-to-moderate alignment, requires human triage |
| **`< 0.25`** | **`NO_MATCH`** | Insufficient alignment; filtered out |

> **Note**: The API, database (`BidScore`, `BidProductMatch`), frontend, audit logs, and explanation strings (`reason`) all consume this same canonical score.

---

## 3. Score Auditability Breakdown

Every match result exposes a transparent score breakdown:

```json
{
  "field_scores": {
    "title": 3.0,
    "scope_of_work": 2.5
  },
  "signal_scores": ["STRONG", "MODERATE"],
  "positive_adjustments": 1.8,
  "negative_exclusion_adjustments": 0.0,
  "raw_score": 5.5,
  "normalized_score": 0.458,
  "final_relevance_score": 0.708,
  "classification": "MATCH",
  "confidence": 0.854,
  "reason": "Matched 2 signal(s) across bid fields. Raw score: 5.5, final relevance: 0.708 (MATCH). Boosted for expert review & validation capability."
}
```

---

## 4. Product Differentiation Rules

Pairwise rules run after single-product scoring to differentiate closely related SecuredApp products:

1. **SolidityShield vs. AuditExpress**:
   - `expert review`, `manual review`, `auditor validation` → Boosts `SolidityShield`, demotes `AuditExpress`.
   - `rapid automated`, `automated assessment only` → Boosts `AuditExpress`.
2. **SecureTrace vs. SecureWatch**:
   - `investigation`, `forensic`, `tracing` → Boosts `SecureTrace`, demotes `SecureWatch`.
   - `continuous monitoring`, `real-time alert`, `abnormal token movement` → Boosts `SecureWatch`, demotes `SecureTrace`.
3. **SecureCMS vs. CookieHub**:
   - `cookie`, `tracking script`, `website script` → Boosts `CookieHub`, demotes `SecureCMS`.
   - `user consent records`, `privacy compliance records` → Boosts `SecureCMS`.
4. **SecureX-DID vs. SecureX-ID**:
   - `verifiable credential`, `did`, `identity wallet` → Boosts `SecureX-DID`.
   - `kyc`, `aml`, `x-id score`, `watchlist` → Boosts `SecureX-ID`.
5. **PQCSuite vs. QuantumVault**:
   - `crypto agility`, `algorithm migration` → Boosts `PQCSuite`.
   - `hsm`, `hardware backed`, `hardware key` → Boosts `QuantumVault`.

---

## 5. Opportunity Score vs. Relevance Score

- **Relevance Score**: Pure measure of product-capability fit (0.0 to 1.0).
- **Opportunity Score**: Weighted evaluation considering relevance (50%), estimated contract value (20%), eligibility confidence (15%), and deadline feasibility (15%).
