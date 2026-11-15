# SecuredApp Product Validation Report

**Task**: Validate the 11 SecuredApp product descriptions in
`backend/app/db/seed_knowledge.py` (`PRODUCTS_KNOWLEDGE`) against authoritative
sources.
**Date**: 2026-10-13
**Status**: Read-only audit. **No** engine, seed, database, product row, or
notification was modified.
**Companion file**: `docs/SECUREDAPP_PRODUCT_CAPABILITY_MATRIX.md` (per-product
evidence tables).

---

## 1. Executive Summary

- All **11** catalogue products were located on the official SecureDApp site
  (`https://securedapp.io`), so **none is Unverified**.
- **9 of 11** seed descriptions are **Verified** (purpose and every listed
  capability supported by an official source).
- **2 of 11** are **Partially verified**: **SecureTrace** and **AuditExpress**
  — their purpose holds, but a few seed capabilities are not explicitly named on
  the official page.
- **No seed description contradicts an official source at the level of core
  purpose.** However, **three exclusion signals are contradicted or over-stated**
  by official marketing (PQCSuite/QuantumVault HSM overlap; SecureTrace's own
  "real-time monitoring"; AuditExpress's "manual reviews").
- The most important **catalogue-level finding**: the official product
  navigation lists a **12th product, "Secure e-Sign"**, which is **absent from
  the internal 11-product catalogue** — a product-coverage gap, not a matching
  bug.
- Naming discrepancy: the official brand is **SecureDApp** (legal entity
  *Vettedcode Technologies India Pvt. Ltd.*); the internal catalogue is called
  "SecuredApp". This does **not** affect matching (names are not bid keywords)
  but should be reconciled in user-facing copy.
- **Recommended first corrections are listed in §7 but have NOT been applied.**
  Several require company confirmation before changing product knowledge.

---

## 2. Method

1. Extracted all 11 descriptions, capabilities, keywords, exclusions,
   technologies, and categories from `seed_knowledge.py` (the single source of
   truth per `docs/product-knowledge.md`).
2. Harvested authoritative content from official SecureDApp properties (product
   pages, support/navigation, privacy/terms pages, and the product subdomains
   `cookie-app.securedapp.io`, `securewatch.securedapp.io`,
   `quantumvault.tech`). Where a claim could not be found on an official
   property it was recorded as **Not documented**, never inferred as true.
3. Compared each seed description capability-by-capability against the evidence
   and assigned a verdict + confidence (see matrix).
4. Analysed the boundaries between the closely-related product pairs, testing
   the seed's exclusion signals against the sources.
5. Reviewed 4 real GeM bids read-only (structured metadata only) to sanity-check
   how the current descriptions behave in practice.
6. Recorded proposed corrections and open questions. **Nothing was changed.**

**Limitations**
- Only public marketing/documentation was available; no product datasheets,
  contracts, or internal specs.
- `securexdid.com` returns only a title (client-rendered), so SecureX-DID
  evidence relies on `securedapp.io/self-sovereign-identity`.
- GeM bid records in the corpus are **listing metadata only** (title/scope
  duplicated, almost all other fields null — established in the prior audit),
  so bid-level examples can only exercise title matching.
- "120+ companies", "99.9% accuracy", "150+ vulnerability types" are vendor
  claims; they are reported as claims, not independently verified facts.

---

## 3. Authoritative Sources

| Source | Used for |
| --- | --- |
| `https://securedapp.io/support` | Official product navigation (12 products), entity footer |
| `/blockchain-security/smart-contract-security-audit` | SolidityShield |
| `/dpdp-compliance-platform` | SecureCMS |
| `/ai-blockchain-investigation-platform` | SecureTrace |
| `/cookie-hub` | CookieHub |
| `/post-quantum-cryptography-platform` | PQCSuite |
| `/self-sovereign-identity` | SecureX-DID |
| `/real-time-blockchain-threat-monitoring` | SecureWatch |
| `/audit-express` | AuditExpress |
| `/tokenization-platform` | SecurePad |
| `/web3-identity-and-aml-compliance-platform` | SecureX-ID |
| `/enterprise-hsm-key-management-platform` | QuantumVault |
| `https://securexdid.com/` | SecureX-DID secondary (title only) |

---

## 4. Per-Product Verdicts

| # | Product | Verdict | Confidence | Key evidence source |
| --- | --- | --- | --- | --- |
| 1 | SolidityShield | Verified | High | Smart Contract Security Audit page |
| 2 | SecureCMS | Verified | High | DPDP Consent Management page |
| 3 | SecureTrace | **Partially verified** | Medium-High | AI Blockchain Investigation page |
| 4 | CookieHub | Verified | High | Cookie & Script Governance page |
| 5 | PQCSuite | Verified | High | PQC Suite page |
| 6 | SecureX-DID | Verified | High | Self-Sovereign Identity page |
| 7 | SecureWatch | Verified | High | Real-Time Threat Monitoring page |
| 8 | AuditExpress | **Partially verified** | Medium-High | Audit Express page |
| 9 | SecurePad | Verified | High | Tokenization Platform page |
| 10 | SecureX-ID | Verified | High | Web3 Identity & AML page |
| 11 | QuantumVault | Verified | High | Enterprise HSM Key Management page |

Detail, per-capability mapping and "not documented in seed" lists are in the
capability matrix.

### 4.1 Why SecureTrace is "Partially verified"
The seed lists **wallet tracing**, **fund-flow analysis**, and **transaction
relationships**. The official page describes "post-transaction analysis",
"forensic thread tracing", Auto-Trace, and uncovering "hidden connections
related to fraudulent schemes". These strongly imply the seed capabilities but
do not name them. No contradiction; not fully citable.

### 4.2 Why AuditExpress is "Partially verified"
The seed lists **logic issue detection**. The official page speaks of
"vulnerabilities and bugs" and "common and complex vulnerabilities" but does not
state "logic issues". Security score, gas analysis and ERC/GitHub integration
exist on the source but are **missing from the seed** (additive gaps).

---

## 5. Catalogue & Naming Findings

### 5.1 Missing 12th product — Secure e-Sign
Official navigation lists **"Secure e-Sign"** (`/digital-signature-platform`),
alongside a **"Secure e-Sign" service** and "Digital Signature". It is **not**
in `PRODUCTS_KNOWLEDGE` / `OFFICIAL_SECUREDAPP_PRODUCTS`. Consequence: any GeM
tender for digital-signature / e-sign services cannot match a product and will be
classified `NO_MATCH` — a **product-coverage gap**. (This is distinct from the
earlier VAPT coverage gap.)

### 5.2 Brand/entity spelling
- Official brand: **SecureDApp**; legal entity: **Vettedcode Technologies India
  Pvt. Ltd.**
- Internal catalogue: "SecuredApp".
- Impact on matching: **none** — product *names* ("SolidityShield", etc.) are
  unchanged, and the brand string is not used as a bid keyword. This is a
  copy/wording issue only, but should be reconciled in docs and UI.

### 5.3 Product display names
Official pages render **"SecurePAD"**, **"Quantum Vault"**, **"Secure CMS"**,
**"Secure Trace"**, **"Secure Watch"** with spacing/casing variants. The seed
uses single-word `SecurePad`, `QuantumVault`, `SecureCMS`, `SecureTrace`,
`SecureWatch`. Functionally irrelevant to matching; note only.

---

## 6. Boundary & Overlap Analysis

The seed intentionally separates five closely-related pairs using **exclusion**
signals. Testing those exclusions against the authoritative sources reveals
**three over-strict / contradicted exclusions** and two overlaps that remain
genuinely ambiguous.

| Pair | Seed separation | Source finding | Risk |
| --- | --- | --- | --- |
| SolidityShield vs AuditExpress | AuditExpress excludes `expert security review`, `manual audit review` | Official AuditExpress page says it "**combines automated tools with manual reviews**" | **Contradicted** — exclusion too strict; a bid describing manual review could wrongly demote AuditExpress |
| SecureTrace vs SecureWatch | SecureTrace excludes `continuous monitoring`, `real-time alerts` | Official SecureTrace page claims "**real-time monitoring** and forensic capabilities" | **Contradicted** — SecureTrace's own marketing uses SecureWatch vocabulary |
| PQCSuite vs QuantumVault | PQCSuite excludes `hardware security module`, `hsm key storage` | Official PQC Suite advertises an "**IoT & HSM**" capability and KMS/HSM integration | **Contradicted** — HSM mentions in a PQC bid would wrongly demote PQCSuite |
| SecureCMS vs CookieHub | SecureCMS excludes `tracking script`, `cookie consent`; CookieHub excludes `privacy compliance records` | CookieHub's own compliance matrix is branded "**SecureCMS Enterprise Solution**", and SecureCMS ToS references "cookie categorization, dynamic script blocking" | **Ambiguous** — the two are co-branded and share vocabulary; exclusion line is blurry |
| SecureX-DID vs SecureX-ID | SecureX-DID excludes `kyc aml verification`, `x id score`; SecureX-ID excludes `verifiable credentials`, `decentralized identity did` | SecureX-ID describes "**decentralised identity verification**" on blockchain | **Low-Severity ambiguity** — "decentralized identity verification" could be read as either product |

Additional low-severity overlaps:
- **SecurePad ↔ SecureX-ID**: SecurePad advertises integrated **KYC**.
- **SecureTrace ↔ SecureX-ID/SecureWatch**: all three discuss transaction
  monitoring/analysis from different angles.

**Interpretation**: exclusion signals are a reasonable mechanism, but for these
pairs they encode a *sharper* separation than the company's own marketing
supports. The first two "contradicted" exclusions (AuditExpress manual review,
SecureTrace real-time monitoring) are the highest-leverage because they can
actively *suppress* a legitimately matching product.

---

## 7. Recommended Corrections (proposed — not applied)

Ordered by leverage. Items marked **[needs company confirmation]** must not be
changed without sign-off, because they alter matching behaviour.

### P0 — Exclusion signals contradicted by official sources
1. **AuditExpress**: remove or soften the `expert security review` (−0.8) and
   `manual audit review` (−1.0) exclusions, since the official page states
   AuditExpress combines automated tools **with manual reviews**. **[needs
   company confirmation]**
2. **SecureTrace**: reconsider the `continuous monitoring` (−1.0) and
   `real-time alerts` (−0.5) exclusions, since the official SecureTrace page
   itself claims real-time monitoring. **[needs company confirmation]**
3. **PQCSuite**: remove or reduce the `hardware security module` (−0.5) and
   `hsm key storage` (−0.8) exclusions, since PQC Suite advertises HSM/KMS
   integration. **[needs company confirmation]**

### P1 — Missing documented capabilities (additive keywords / capabilities)
4. **SolidityShield**: add AI/ML analysis, "150+ vulnerability types", attack
   simulation, symbolic execution, fuzzing, ERC-standard compatibility,
   GitHub/CI-CD integration.
5. **SecureCMS**: add DPDP Act 2023 (India) positioning, immutable/tamper-proof
   audit logs, user-rights (access/correction/erasure) workflows, multi-language
   consent, consent receipts.
6. **CookieHub**: add script-quarantine / `type="text/plain"` tag control,
   RS256 JWT + JWKS cross-device sync, offline-first, headless mobile REST APIs,
   policy versioning.
7. **PQCSuite**: add managed PQC API gateway, unified SDKs, shipping apps
   (VPN/Chat/File-Sharing/PKI/IoT), NIST algorithm names (Kyber, Dilithium,
   Falcon, SPHINCS+), hybrid KEM/TLS, KMS/HSM integration, BYOK.
8. **SecureWatch**: add named chains (Ethereum, BNB Chain, Polygon, Arbitrum,
   Optimism), behavioural baselines, automated mitigation, SIEM/Slack/Webhook
   integrations.
9. **AuditExpress**: add security-score output, gas-usage analysis, ERC-standard
   compatibility, GitHub integration, instant notifications.
10. **SecurePad**: add zero-fee/tokenization framing, no-code, cross-chain, IDO
    launch, token locker, integrated KYC/audit.
11. **SecureX-DID**: add explicit Holder/Verifier/Issuer VC roles and DID-wallet
    framing.
12. **SecureX-ID**: add decentralised/non-custodial framing and cross-platform
    APIs.
13. **QuantumVault**: add FIPS 140-2, BYOK, multi-cloud, KMIP/PKCS#11, and PQC
    algorithm names.

### P2 — Catalogue & wording
14. Decide whether **Secure e-Sign** should become a 12th product
    **[needs company confirmation]**.
15. Reconcile the **SecureDApp / SecuredApp** spelling in docs/UI (no engine
    impact).
16. Revisit `docs/relevance-engine.md` §Product Differentiation Rules so the
    documented rules match whatever exclusion decisions are approved.

> **None of the above was implemented.** Applying P0/P1 would change matching
> scores and requires (a) company confirmation and (b) a full re-analysis +
> regression run, following the same backup-first procedure used for the P0 gate
> work.

---

## 8. Example Bid Review (read-only)

Four real GeM bids most relevant to the products were inspected read-only. Note
the corpus stores **listing metadata only** (`scope_of_work` == title; all
technical/eligibility fields null), so this tests title matching only.

| GeM bid | Title | Product it triggered | Current engine result | Assessment |
| --- | --- | --- | --- | --- |
| `GEM/2026/B/8124731` | "PROVISION OF ARBORICULTURE FOR DEFI SINGLE OFFRS ACCN…" | SecurePad (via "defi") | relevance 0.4, NEEDS_REVIEW, 0 matches | **False positive** — "DEFI" is a military abbreviation, not DeFi |
| `GEM/2026/B/8018975` | "Diesel, Engine oil, …, **Cookies**, …" (canteen supplies) | CookieHub (via "cookies") | relevance 0.4, NEEDS_REVIEW, 0 matches | **False positive** — food "Cookies" |
| `GEM/2026/B/8084573` | "ORV SPHERICAL BEARING AND **STAKING** TOOL" | SecurePad (via "staking") | relevance 0.4, NEEDS_REVIEW, 0 matches | **False positive** — mechanical "staking" tool |
| `GEM/2026/B/8021448` | "KEY MANAGEMENT SYSTEM" | QuantumVault (not detected) | relevance 0.0, NO_MATCH, 0 matches | **Potential false negative** — with only a title and no scope text, QuantumVault's multi-token vocabulary cannot fire |

**Conclusions**
- The three false positives are already **contained** by the hardened contextual
  gate (capped to `0.3999`, still `NEEDS_REVIEW`, and — after the orphan-cleanup
  findings — no live `bid_product_matches` row). They are consistent with the
  single-token ambiguity flagged in the capability matrix (SecurePad/`defi`,
  `staking`; CookieHub/`cookies`).
- The **false negative** `GEM/2026/B/8021448` is a *data* limitation (no scope
  text), not a description defect: QuantumVault's seed keywords are multi-word
  ("cryptographic key management", "hardware backed protection"), and the title
  "KEY MANAGEMENT SYSTEM" is not among them. A curated synonym such as
  "key management system" would be needed — **[needs company confirmation]**
  and would be a keyword addition, not a description change.

---

## 9. Open Questions for Company Confirmation

1. Is **Secure e-Sign** an active, sellable product? Should it be the 12th
   catalogue product?
2. Approve/deny the three **exclusion-signal corrections** (AuditExpress manual
   review, SecureTrace real-time monitoring, PQCSuite HSM) — these change
   matching behaviour.
3. What is the **intended boundary** between SecureCMS and CookieHub, and between
   SecureX-DID and SecureX-ID? The official pages overlap.
4. May the **additive capabilities** in P1 be written into the seed, or are some
   still pre-GA / not to be advertised?
5. Is the official brand to be written **"SecureDApp"** everywhere going forward?
6. Should QuantumVault gain a curated **"key management system"** synonym to
   reduce the false negative in §8?

---

## 10. Confidence & Caveats

- **High confidence** for 9 products whose pages state the seed capabilities
  explicitly.
- **Medium-High** for SecureTrace and AuditExpress, where the source implies but
  does not name two seed capabilities.
- All vendor metrics ("120+ companies", "99.9% accuracy", "150+ vulnerability
  types", "Government of India Patent #574710", "FIPS 140-2") are recorded as
  **vendor claims**.
- This report is an audit only. No product knowledge, engine, database, or
  notification state was changed; the recommendations in §7 are proposals.

---

## Appendix A — GeM bid IDs reviewed

`GEM/2026/B/8124731`, `GEM/2026/B/8018975`, `GEM/2026/B/8084573`,
`GEM/2026/B/8021448`.

## Appendix B — Files inspected (read-only)

- `backend/app/db/seed_knowledge.py` (11-product source of truth)
- `backend/app/seed.py` (`OFFICIAL_SECUREDAPP_PRODUCTS`)
- `docs/product-knowledge.md`, `docs/relevance-engine.md`
- `backend/dev.db` (read-only: the 4 example bids, their scores/matches)
