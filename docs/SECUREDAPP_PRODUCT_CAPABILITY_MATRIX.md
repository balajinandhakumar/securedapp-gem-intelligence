# SecuredApp Product Capability Matrix

**Purpose**: Map each of the 11 products defined in `backend/app/db/seed_knowledge.py`
(`PRODUCTS_KNOWLEDGE`) to authoritative SecureDApp sources, and record what the
public product documentation does and does not support.

**Retrieved**: 2026-10-13
**Authoritative source of record**: `https://securedapp.io` (official product site).
**Legal entity on site**: Vettedcode Technologies India Pvt. Ltd.
**Brand spelling on site**: **SecureDApp** (the internal catalogue spells it "SecuredApp").

> **Rule applied**: a capability is marked **Verified** only when it is stated or
> clearly implied on an official SecureDApp property. Anything not found on an
> official source is marked **Not documented** — never invented. This file is
> read-only analysis: no engine, seed, database, or product row was modified.

---

## 1. Source Index

| # | Official name | Official page (product) | Other official properties |
| --- | --- | --- | --- |
| 1 | SolidityShield | `/blockchain-security/smart-contract-security-audit` | `/solidity-shield-scan/pricing`, `/solidity-shield-scan/auth` |
| 2 | SecureCMS | `/dpdp-compliance-platform` | `/securecms/privacy-policy`, `/securecms/terms-of-service` |
| 3 | SecureTrace | `/ai-blockchain-investigation-platform` | service page `/blockchain-intelligence-and-forensic-platform` |
| 4 | CookieHub | `/cookie-hub` | `https://cookie-app.securedapp.io/` |
| 5 | PQCSuite | `/post-quantum-cryptography-platform` | — |
| 6 | SecureX-DID | `/self-sovereign-identity` | `https://securexdid.com/` (JS-rendered, title only) |
| 7 | SecureWatch | `/real-time-blockchain-threat-monitoring` | `https://securewatch.securedapp.io/` |
| 8 | AuditExpress | `/audit-express` | — |
| 9 | SecurePad | `/tokenization-platform` | — |
| 10 | SecureX-ID | `/web3-identity-and-aml-compliance-platform` | — |
| 11 | QuantumVault | `/enterprise-hsm-key-management-platform` | `https://quantumvault.tech/`, `https://app.quantumvault.tech/` |

The site's own navigation also lists a **12th product, "Secure e-Sign"**
(`/digital-signature-platform`), which is **not** in the internal 11-product
catalogue. See the validation report, §Catalogue gap.

---

## 2. Summary Matrix

| Product | Seed verdict | Confidence | Biggest documentation gap in seed | Boundary risk |
| --- | --- | --- | --- | --- |
| SolidityShield | Verified | High | AI/ML, 150+ vuln classes, attack simulation, fuzzing, ERC/GitHub | vs AuditExpress |
| SecureCMS | Verified | High | DPDP-2023 positioning, immutable audit logs, user-rights workflows | vs CookieHub |
| SecureTrace | Partially verified | Medium-High | "wallet tracing"/"fund-flow" not named; page itself claims real-time monitoring | vs SecureWatch |
| CookieHub | Verified | High | Script-quarantine mechanism, JWT/JWKS sync, offline/mobile SDKs | vs SecureCMS |
| PQCSuite | Verified | High | Managed API, SDKs, apps (VPN/Chat/PKI/IoT), NIST algorithms, HSM/KMS | vs QuantumVault |
| SecureX-DID | Verified | High | DID wallets, VC holder/verifier/issuer roles, industry applications | vs SecureX-ID |
| SecureWatch | Verified | High | Multi-chain names, behavioural baselines, automated mitigation, integrations | vs SecureTrace |
| AuditExpress | Partially verified | Medium-High | Security score, gas analysis, ERC/GitHub integration | vs SolidityShield |
| SecurePad | Verified | High | Zero-fee/no-code/cross-chain, IDO, token locker, KYC | vs SecureX-ID |
| SecureX-ID | Verified | High | Non-custodial/decentralised framing, cross-platform APIs | vs SecureX-DID |
| QuantumVault | Verified | High | FIPS 140-2, BYOK, multi-cloud, KMIP/PKCS#11, PQC algorithms | vs PQCSuite |

Verdict legend:
- **Verified** — the seed description's purpose and every listed capability is supported by an official source; only additive details are missing.
- **Partially verified** — the purpose is supported, but at least one seed capability is not explicitly documented on an official source.

No product is **Unverified** (all 11 have an official page) and none is
**Contradicted** at the level of its core purpose.

---

## 3. Per-Product Detail

### 3.1 SolidityShield — `Verified` (High)

**Seed description**: "Smart contract security platform for Solidity-based smart
contracts. It supports automated security scanning, vulnerability detection,
findings validation, expert security review, remediation validation, and
pre-deployment security assessment."

**Official evidence**: AI-powered smart-contract security solution; automated
scanning combined with manual, expert-driven review; detects 150+ vulnerability
types (reentrancy, unchecked transfers, access control, oracle manipulation,
flash-loan paths, business-logic flaws, arithmetic errors); end-to-end process
(intake/scope, automated detection, manual line-by-line review, attack
simulation, reporting/remediation, revalidation); methodology includes static
analysis, symbolic execution (SMTChecker, taint analysis), property-based/fuzz
testing; GitHub & file upload, CI/CD integration; ERC-standard compatibility;
pre-deployment focus; "150+ vulnerability types", "99.9% detection accuracy".

| Seed capability | Status on official source |
| --- | --- |
| Smart contract security / Solidity security | Supported ("Ethereum-based contracts", Solidity) |
| Automated security scanning | Supported |
| Vulnerability detection | Supported (150+ types) |
| Findings validation | Supported (reporting & remediation, revalidation) |
| Expert security review | Supported (manual line-by-line review) |
| Remediation validation | Supported ("Revalidation & Final Approval") |
| Pre-deployment assessment | Supported |

**Not documented in seed (additive)**: AI/ML-driven analysis, 150+ vulnerability
class count, flash-loan/oracle/business-logic categories, attack simulation,
symbolic execution & fuzzing, ERC-standard compatibility, GitHub/CI-CD
integration, published accuracy metric.

**Boundary note**: overlaps heavily with AuditExpress (see report §Overlap).

---

### 3.2 SecureCMS — `Verified` (High)

**Seed description**: "User consent and privacy compliance management platform.
It supports consent management, consent records and tracking, consent
withdrawal, privacy compliance workflows, and compliance/audit records."

**Official evidence** (page title: *"Secure CMS: Consent Management for DPDP Act
Compliance"*): collect/manage/audit user consent; immutable, cryptographically
signed, tamper-proof audit logs; consent receipts; user-rights management
(access, correction, erasure / right to be forgotten); real-time consent
tracking with hooks; multi-language (Indian regional languages); API/webhook
integrations; web & mobile consent widgets; DPDP Act 2023 (India) alignment;
privacy policy documents defining Data Processor vs Data Fiduciary, cryptographic
hashing and consent-receipt records.

| Seed capability | Status on official source |
| --- | --- |
| Consent management | Supported |
| Consent records & tracking | Supported |
| Consent withdrawal | Supported (user preference portal) |
| Privacy compliance workflows | Supported (DPDP workflows) |
| Compliance / audit records | Supported (immutable audit logs) |

**Not documented in seed (additive)**: DPDP Act 2023 (India) positioning,
immutable/tamper-proof audit logs, user-rights (access/correction/erasure)
portals, multi-language notices, industry playbooks (fintech, health, etc.).

**Boundary note**: the SecureCMS Terms of Service reference "cookie
categorization, dynamic script blocking" — capability that also belongs to
CookieHub. Overlap risk (see report §Overlap).

---

### 3.3 SecureTrace — `Partially verified` (Medium-High)

**Seed description**: "Blockchain investigation and forensics platform focused on
transaction tracing, wallet tracing, fund-flow analysis, transaction
relationships, and suspicious transaction investigation."

**Official evidence**: AI/ML blockchain forensic tool; post-transaction analysis;
"forensic thread tracing"; signature **Auto-Trace** feature that automates
transaction tracing; historical-data reports; anomaly/unusual-pattern detection;
use cases: reclaim lost/compromised assets, detect fraud, respond to breaches,
analyze smart-contract interactions; regulatory compliance.

| Seed capability | Status on official source |
| --- | --- |
| Blockchain investigation | Supported |
| Blockchain forensics | Supported |
| Transaction tracing | Supported (Auto-Trace, forensic thread tracing) |
| Wallet tracing | **Not named** (implied by "hidden connections") |
| Fund-flow analysis | **Not named** (implied by "hidden connections"/asset recovery) |
| Suspicious transaction investigation | Supported |
| Transaction relationships | **Not named** (implied by "hidden connections") |

**Boundary note / contradiction**: the SecureTrace page states *"SecureTrace's
real-time monitoring and forensic capabilities"* and "monitoring and analyzing
transaction patterns", yet the seed lists `continuous monitoring` and
`real-time alerts` as **exclusion** signals for SecureTrace (to separate it from
SecureWatch). The seed exclusion is stricter than the official marketing.

---

### 3.4 CookieHub — `Verified` (High)

**Seed description**: "Website cookie consent and tracking-script management
platform. It supports consent collection, consent-based script control, and
website consent management."

**Official evidence**: "Enterprise Cookie Consent & Script Governance"; true
zero-data-leak script governance by converting scripts to `type="text/plain"`
with purpose tags until consent; granular category consent; cross-device
preference sync via **RS256 JWT + JWKS**; offline-first localStorage queue;
headless REST APIs for iOS/Android/React Native/Flutter/server; immutable audit
trails with `consent_id`, timestamp, tenant/app id, `policy_version`; policy
versioning with renewal prompts; DPDP 2023 & GDPR; "<15KB" bundle.

| Seed capability | Status on official source |
| --- | --- |
| Cookie consent | Supported |
| Cookies management | Supported |
| Tracking scripts / tracking-script management | Supported (tag quarantine) |
| Consent collection | Supported |
| Consent-based script control | Supported (activate on consent) |
| Website consent | Supported |

**Not documented in seed (additive)**: RS256/JWKS cross-device sync,
offline-first resilience, mobile/headless REST APIs, policy versioning, tag
quarantine mechanism, bundle size, regulatory references (DPDP/GDPR).

**Boundary note**: official CookieHub page is co-branded with "SecureCMS" in its
compliance matrix and states "SecureCMS verifies signatures dynamically"; the
two products share consent/privacy vocabulary.

---

### 3.5 PQCSuite — `Verified` (High)

**Seed description**: "Post-quantum cryptography platform focused on helping
organizations prepare for quantum-resistant cryptography. It supports
post-quantum cryptography, cryptographic agility, algorithm migration, and a
flexible cryptographic layer."

**Official evidence** (page title: *"PQC Suite: Quantum-Safe Security Products"*):
modular end-to-end PQC adoption platform; managed **PQC API Service** (policy
guardrails, SIEM telemetry); unified **SDKs**; ready-to-use **applications**
(File Sharing, Chat, VPN, Sign/PKI, IoT Device Manager, HSM/KMS); NIST-track
algorithms (**Kyber, Dilithium, Falcon, SPHINCS+**); hybrid KEM/TLS and classical
compatibility; **crypto-agility** and pluggable backends; staged migration;
KMS/HSM integrations and BYOK patterns; SOC 2 / FIPS / GDPR evidence support.

| Seed capability | Status on official source |
| --- | --- |
| Post-quantum cryptography / PQC | Supported |
| Quantum-resistant cryptography | Supported |
| Crypto-agility / cryptographic agility | Supported |
| Algorithm migration / cryptographic migration | Supported (staged migration) |
| Flexible cryptographic layer | Supported (pluggable backends) |
| Post-quantum security | Supported |

**Not documented in seed (additive)**: managed API gateway, unified SDKs,
shipping apps (VPN/Chat/File-Sharing/PKI/IoT), NIST algorithm names, hybrid
KEM/TLS, KMS/HSM integration, BYOK.

**Boundary note / contradiction**: the seed marks `hardware security module`
and `hsm key storage` as **exclusion** signals for PQCSuite (to separate it from
QuantumVault), but the official PQC Suite page explicitly advertises an
"IoT & HSM" capability and enterprise KMS/HSM integrations. The exclusion is
contradicted by the source.

---

### 3.6 SecureX-DID — `Verified` (High)

**Seed description**: "Decentralized identity solution focused on decentralized
identities and verifiable credentials. It supports credential issuance, storage,
presentation, and verification, including identity wallet concepts."

**Official evidence**: Decentralized Identity (DID) / self-sovereign identity;
**decentralized identity wallets**; **Decentralized Identifiers**; blockchain
identity; **verifiable credentials** with Holder / Verifier / Issuer roles;
applications across supply chain, government/voting, education, healthcare,
digital identity verification, decentralised social media; distinct from
SecureX-ID. Secondary property `securexdid.com` exists.

| Seed capability | Status on official source |
| --- | --- |
| Decentralized identity / DID | Supported |
| Digital identity | Supported |
| Verifiable credentials | Supported |
| Credential issuance | Supported (Issuer) |
| Credential storage | Supported (wallet) |
| Credential presentation | Supported (Holder presents) |
| Credential verification | Supported (Verifier) |
| Identity wallet | Supported (DID wallets) |

**Not documented in seed (additive)**: explicit Holder/Verifier/Issuer model,
DID-wallet portability/tamper-proof framing, industry application list.

---

### 3.7 SecureWatch — `Verified` (High)

**Seed description**: "Continuous monitoring platform for blockchain transactions
and smart contract activity. It focuses on anomaly detection, suspicious activity
detection, alerts, and abnormal token movement."

**Official evidence**: AI-powered real-time blockchain threat monitoring,
post-deployment; continuous 24/7 monitoring; **multi-chain** coverage (Ethereum,
BNB Chain, Polygon, Arbitrum, Optimism); behavioural-baseline analysis;
transaction/wallet/smart-contract-call analysis; anomaly detection of exploit
patterns, abnormal token transfers, governance anomalies; alerts via Slack,
Webhooks, SIEM; custom monitoring policies; automated mitigation workflows;
**Government of India Patent #574710**; tiered plans (Guardian/Sentinel/Fortress);
property `securewatch.securedapp.io`.

| Seed capability | Status on official source |
| --- | --- |
| Blockchain monitoring | Supported |
| Transaction monitoring | Supported |
| Smart contract monitoring | Supported |
| Continuous monitoring | Supported (24/7) |
| Anomaly detection | Supported |
| Suspicious activity | Supported |
| Security alerts | Supported |
| Abnormal token movement | Supported |
| Transaction alerts | Supported |

**Not documented in seed (additive)**: named chains, behavioural baselines,
automated mitigation, SIEM/Slack/Webhook integrations, patent, plan tiers.

---

### 3.8 AuditExpress — `Partially verified` (Medium-High)

**Seed description**: "Automated smart contract security assessment platform
focused on vulnerability scanning, logic issue detection, findings generation,
security posture assessment, and pre-deployment assessment."

**Official evidence** (page title: *"SecureDApp Audit Express — Automated Smart
Contract Scanning"*): quick smart-contract auditing tool; GitHub / upload /
blockchain select → report; produces a **security score**; gas-usage analysis;
ERC-standard compatibility; detailed visual reports; actionable findings and
secure-coding recommendations; instant in-IDE vulnerability notifications;
**combines automated tools with manual reviews**.

| Seed capability | Status on official source |
| --- | --- |
| Automated smart contract assessment | Supported |
| Vulnerability scanning | Supported |
| Logic issue detection | **Not named** (implied by "bugs"/"vulnerabilities") |
| Findings / security findings | Supported (detailed vulnerability reports) |
| Security posture assessment | Supported (security score) |
| Pre-deployment security assessment | Supported (pre-deployment focus) |
| Automated audit | Supported |
| Smart contract analysis | Supported (static/dynamic implied) |

**Boundary note**: the official page states AuditExpress "combines automated
tools with manual reviews", while the seed uses `expert security review` and
`manual audit review` as **exclusion** signals to separate AuditExpress from
SolidityShield. The distinction is weaker on the official sources than in the
seed.

---

### 3.9 SecurePad — `Verified` (High)

**Seed description**: "Web3 and DeFi infrastructure platform covering token
creation and management, trading, staking, lending, borrowing, and governance."

**Official evidence** (product name **SecurePAD**, page title *"SecurePad:
Zero-Fee Tokenization..."*): zero-fee tokenization platform; no-code; cross-chain
token deployment; create/trade/manage tokens across full lifecycle; Initial DEX
Offerings (IDOs); integrated **KYC** verification and smart-contract audits;
decentralised exchange; lending & borrowing; staking; token locker; governance.

| Seed capability | Status on official source |
| --- | --- |
| Web3 | Supported |
| DeFi / Decentralized finance | Supported |
| Token creation / management | Supported |
| Trading | Supported (DEX, trade) |
| Staking | Supported |
| Lending / Borrowing | Supported |
| Governance | Supported |
| Web3/DeFi infrastructure | Supported |

**Not documented in seed (additive)**: zero-fee model, no-code, cross-chain,
IDO launch, token locker, integrated KYC/audit.

**Boundary note**: SecurePad's page advertises integrated KYC — vocabulary that
also maps to SecureX-ID. Low-severity overlap.

---

### 3.10 SecureX-ID — `Verified` (High)

**Seed description**: "Identity verification and compliance platform for Web3 and
DeFi. It supports KYC, AML, fraud-risk monitoring, watchlist checks,
transaction-history analysis, behavior analysis, risk assessment, and the X-ID
Score concept."

**Official evidence** (page title: *"Blockchain Identity Verification for Secure
KYC & Compliance"*): decentralised KYC/AML platform for Web3/DeFi/DApps;
decentralised identity verification on blockchain; **AML transaction
monitoring** (real-time); regulatory-compliance tools & APIs; non-custodial data
management; cross-platform/DApp integration; **X-ID Score** methodology
(identity-verification level, transaction history, data consistency, sanctions &
watchlist screening, behavioural analysis).

| Seed capability | Status on official source |
| --- | --- |
| Identity verification | Supported |
| KYC | Supported |
| AML | Supported |
| Web3/DeFi compliance | Supported |
| Fraud risk / fraud-risk monitoring | Supported (reduced fraud/AML monitoring) |
| Watchlist checks | Supported (sanctions/watchlist screening) |
| Transaction-history analysis | Supported |
| Behavior analysis | Supported |
| Risk assessment | Supported (X-ID Score) |
| X-ID Score | Supported |

**Not documented in seed (additive)**: decentralised/non-custodial framing,
cross-platform API, X-ID Score input factors.

---

### 3.11 QuantumVault — `Verified` (High)

**Seed description**: "Cryptographic key protection and key-management platform
focused on secure key generation, storage, access control, rotation, revocation,
and hardware-backed protection, with consideration for future post-quantum
requirements."

**Official evidence** (product name **Quantum Vault**): Enterprise HSM Key
Management platform; **FIPS 140-2** certified, hardware-backed; keys generated
in HSM with TRNG, non-extractable, tamper-resistant; full lifecycle
(generate/rotate/revoke); RBAC + m-of-n multi-party approval; **BYOK**;
multi-cloud (AWS KMS, Azure HSM, GCP, on-prem); **KMIP / PKCS#11** / REST;
**crypto-agility** with ML-KEM (FIPS 203) & ML-DSA (FIPS 204); PQC readiness;
blockchain/Web3 wallet & validator key custody; SIEM/IAM integration;
properties `quantumvault.tech`, `app.quantumvault.tech`.

| Seed capability | Status on official source |
| --- | --- |
| Cryptographic key protection / management | Supported |
| Secure key generation / storage | Supported |
| Key access control | Supported (RBAC, m-of-n) |
| Key rotation / revocation | Supported |
| Hardware-backed protection / HSM | Supported |
| Cryptographic key security | Supported |
| Post-quantum key protection | Supported |

**Not documented in seed (additive)**: FIPS 140-2 certification, BYOK,
multi-cloud, KMIP/PKCS#11, specific PQC algorithms, wallet/validator custody.

---

## 4. Cross-Cutting Facts

| Fact | Value | Source |
| --- | --- | --- |
| Official brand spelling | **SecureDApp** | site logo/域名 `securedapp.io` |
| Legal entity | Vettedcode Technologies India Pvt. Ltd. | site footer |
| Products on official navigation | **12** (11 catalogue + **Secure e-Sign**) | `/support` |
| Claimed scale | "120+ companies" | most product pages |
| SecureWatch patent | Government of India Patent #574710 | SecureWatch page |
| QuantumVault certification | FIPS 140-2 | QuantumVault page |
| SolidityShield claim | 150+ vulnerability types, 99.9% detection accuracy | SolidityShield page |
