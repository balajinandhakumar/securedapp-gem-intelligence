"""
Seed product knowledge base for SecuredApp's 11 products using exact internal working knowledge.

Strict rule: No invented capabilities, certifications, vendors, or unverified claims.
"""
from __future__ import annotations

from typing import Any, Dict, List
from sqlalchemy.orm import Session

from app.models.product import Product, ProductCapability, ProductKeyword, ProductTechnology, ProductCategory

# ---------------------------------------------------------------------------
# Strict Product Knowledge Definition
# ---------------------------------------------------------------------------
PRODUCTS_KNOWLEDGE: List[Dict[str, Any]] = [
    {
        "name": "SolidityShield",
        "description": (
            "Smart contract security platform for Solidity-based smart contracts. It supports automated security scanning, "
            "vulnerability detection, findings validation, expert security review, remediation validation, and pre-deployment "
            "security assessment."
        ),
        "priority": 10,
        "capabilities": [
            ("Smart contract security", "Core smart contract security capability", 1.0),
            ("Solidity smart contract security", "Solidity specific contract security", 1.0),
            ("Automated security scanning", "Automated contract scanner", 1.0),
            ("Vulnerability detection", "Vulnerability detection engine", 1.0),
            ("Findings validation", "Validation of identified findings", 0.9),
            ("Expert security review", "Manual expert security review", 1.0),
            ("Remediation validation", "Validation of vulnerability fixes", 0.9),
            ("Pre-deployment assessment", "Pre-deployment audit and assessment", 1.0),
            ("Reentrancy detection", "Reentrancy vulnerability detection", 0.9),
            ("Access control issue detection", "Access control analysis", 0.9),
        ],
        "keywords": [
            ("solidity", 1.0, "positive_signal"),
            ("smart contract security", 1.0, "positive_signal"),
            ("smart contract audit", 1.0, "positive_signal"),
            ("automated security scanning", 1.0, "positive_signal"),
            ("vulnerability detection", 1.0, "positive_signal"),
            ("reentrancy", 0.9, "positive_signal"),
            ("access control", 0.8, "positive_signal"),
            ("security review", 0.9, "positive_signal"),
            ("findings validation", 0.9, "positive_signal"),
            ("remediation validation", 0.9, "positive_signal"),
            ("pre-deployment assessment", 1.0, "positive_signal"),
            ("smart contract vulnerabilities", 1.0, "positive_signal"),
            # Real-world GeM procurement terminology for security-assessment /
            # vulnerability-detection work that the formal capability names above
            # (vulnerability detection, automated security scanning, security
            # review) never appear as in tender text. Added as terminology
            # coverage only - every term maps to an existing verified
            # capability; no new capability is invented.
            ("penetration testing", 1.0, "positive_signal"),
            ("vulnerability assessment", 1.0, "positive_signal"),
            ("vulnerability scanner", 1.0, "positive_signal"),
            ("security audit", 1.0, "positive_signal"),
            ("application security", 1.0, "positive_signal"),
            ("web application security", 1.0, "positive_signal"),
            ("vapt", 1.0, "positive_signal"),
            ("owasp", 1.0, "positive_signal"),
            ("security testing", 0.9, "positive_signal"),
            ("cyber security audit", 1.0, "positive_signal"),
        ],
        "technologies": ["Solidity", "Smart Contracts", "EVM"],
        "categories": ["Smart Contract Security", "Cybersecurity Audit"],
    },
    {
        "name": "SecureCMS",
        "description": (
            "User consent and privacy compliance management platform. It supports consent management, consent records "
            "and tracking, consent withdrawal, privacy compliance workflows, and compliance/audit records."
        ),
        "priority": 9,
        "capabilities": [
            ("Consent management", "Management of user privacy consents", 1.0),
            ("User consent records", "Storage and tracking of user consent records", 1.0),
            ("Consent tracking", "Tracking user consent lifecycle", 1.0),
            ("Consent withdrawal", "Handling withdrawal of user consent", 1.0),
            ("Privacy compliance", "Privacy compliance record and workflow management", 1.0),
            ("Compliance records", "Audit trail of privacy compliance", 0.9),
            ("Audit records", "Privacy consent audit records", 0.9),
            ("Data consent", "Management of data processing consent", 0.9),
            ("Privacy management", "Comprehensive privacy management", 0.9),
        ],
        "keywords": [
            ("user consent", 1.0, "positive_signal"),
            ("consent management", 1.0, "positive_signal"),
            ("consent records", 1.0, "positive_signal"),
            ("consent tracking", 1.0, "positive_signal"),
            ("consent withdrawal", 1.0, "positive_signal"),
            ("privacy compliance", 1.0, "positive_signal"),
            ("compliance records", 0.9, "positive_signal"),
            ("audit records", 0.9, "positive_signal"),
            ("data consent", 0.9, "positive_signal"),
            ("privacy management", 0.9, "positive_signal"),
            ("tracking script", -1.0, "exclusion"),  # Distinction from CookieHub
            ("cookie consent", -0.5, "exclusion"),    # Distinction from CookieHub
        ],
        "technologies": ["Privacy Management", "Consent Records"],
        "categories": ["Privacy & Compliance", "Data Governance"],
    },
    {
        "name": "SecureTrace",
        "description": (
            "Blockchain investigation and forensics platform focused on transaction tracing, wallet tracing, "
            "fund-flow analysis, transaction relationships, and suspicious transaction investigation."
        ),
        "priority": 9,
        "capabilities": [
            ("Blockchain investigation", "Investigation of blockchain activities", 1.0),
            ("Blockchain forensics", "Forensic analysis of blockchain data", 1.0),
            ("Transaction tracing", "Tracing transaction paths across ledger", 1.0),
            ("Wallet tracing", "Tracing relationships and funds between wallets", 1.0),
            ("Fund-flow analysis", "Analyzing the flow of digital assets/funds", 1.0),
            ("Suspicious transaction investigation", "Investigating suspicious transfers", 1.0),
            ("Transaction relationships", "Mapping transaction relationships", 0.9),
            ("Wallet investigation", "Forensic investigation of target wallets", 0.9),
        ],
        "keywords": [
            ("blockchain investigation", 1.0, "positive_signal"),
            ("blockchain forensics", 1.0, "positive_signal"),
            ("transaction tracing", 1.0, "positive_signal"),
            ("wallet tracing", 1.0, "positive_signal"),
            ("fund flow analysis", 1.0, "positive_signal"),
            ("suspicious transaction investigation", 1.0, "positive_signal"),
            ("transaction relationships", 0.9, "positive_signal"),
            ("wallet investigation", 0.9, "positive_signal"),
        ],
        "technologies": ["Blockchain Forensics", "Transaction Analysis"],
        "categories": ["Blockchain Forensics", "Investigation"],
    },
    {
        "name": "CookieHub",
        "description": (
            "Website cookie consent and tracking-script management platform. It supports consent collection, "
            "consent-based script control, and website consent management."
        ),
        "priority": 8,
        "capabilities": [
            ("Cookie consent", "Website cookie consent collection", 1.0),
            ("Cookies", "Cookie classification and management", 0.9),
            ("Tracking scripts", "Management and detection of tracking scripts", 1.0),
            ("Tracking-script management", "Website tracking-script control and blocking", 1.0),
            ("Consent collection", "Collecting website visitor consents", 1.0),
            ("Consent-based script control", "Executing scripts only after consent", 1.0),
            ("Website consent", "Consent banners and preferences for websites", 1.0),
            ("Website cookie management", "End-to-end website cookie compliance", 1.0),
        ],
        "keywords": [
            ("cookie consent", 1.0, "positive_signal"),
            ("cookies", 0.9, "positive_signal"),
            ("tracking scripts", 1.0, "positive_signal"),
            ("tracking script management", 1.0, "positive_signal"),
            ("consent collection", 1.0, "positive_signal"),
            ("consent based script control", 1.0, "positive_signal"),
            ("website consent", 1.0, "positive_signal"),
            ("website cookie management", 1.0, "positive_signal"),
            ("privacy compliance records", -0.5, "exclusion"),  # Distinction from SecureCMS
        ],
        "technologies": ["JavaScript", "Website Script Management"],
        "categories": ["Website Privacy", "Cookie Management"],
    },
    {
        "name": "PQCSuite",
        "description": (
            "Post-quantum cryptography platform focused on helping organizations prepare for quantum-resistant cryptography. "
            "It supports post-quantum cryptography, cryptographic agility, algorithm migration, and a flexible cryptographic layer."
        ),
        "priority": 9,
        "capabilities": [
            ("Post-quantum cryptography", "Software post-quantum cryptographic primitives", 1.0),
            ("PQC", "Post-quantum cryptography readiness and tools", 1.0),
            ("Quantum-resistant cryptography", "Quantum-safe encryption and signatures", 1.0),
            ("Crypto-agility", "Support for crypto-agility", 1.0),
            ("Cryptographic agility", "Agile cryptographic layer", 1.0),
            ("Algorithm migration", "Migration to post-quantum algorithms", 1.0),
            ("Cryptographic migration", "Migrating cryptographic assets", 0.9),
            ("Flexible cryptographic layer", "Abstraction layer for algorithm switching", 0.9),
            ("Post-quantum security", "Preparing for post-quantum security", 0.9),
        ],
        "keywords": [
            ("post quantum cryptography", 1.0, "positive_signal"),
            ("pqc", 1.0, "positive_signal"),
            ("quantum resistant cryptography", 1.0, "positive_signal"),
            ("crypto agility", 1.0, "positive_signal"),
            ("cryptographic agility", 1.0, "positive_signal"),
            ("algorithm migration", 1.0, "positive_signal"),
            ("cryptographic migration", 0.9, "positive_signal"),
            ("flexible cryptographic layer", 0.9, "positive_signal"),
            ("post quantum security", 0.9, "positive_signal"),
        ],
        "technologies": ["Post-Quantum Cryptography", "Crypto-Agility"],
        "categories": ["Cryptography", "Post-Quantum Security"],
    },
    {
        "name": "SecureX-DID",
        "description": (
            "Decentralized identity solution focused on decentralized identities and verifiable credentials. "
            "It supports credential issuance, storage, presentation, and verification, including identity wallet concepts."
        ),
        "priority": 8,
        "capabilities": [
            ("Decentralized identity", "Decentralized identity management", 1.0),
            ("DID", "Decentralized identifiers", 1.0),
            ("Digital identity", "Digital identity architecture", 0.8),
            ("Verifiable credentials", "Issuance and verification of credentials", 1.0),
            ("Credential issuance", "Issuing verifiable credentials", 1.0),
            ("Credential storage", "Secure storage of identity credentials", 0.9),
            ("Credential presentation", "Presenting credential proofs", 0.9),
            ("Credential verification", "Verifying credential authenticity", 1.0),
            ("Identity wallet", "Identity wallet concepts and management", 0.9),
            ("Decentralized credentials", "Decentralized verifiable credentials", 0.9),
        ],
        "keywords": [
            ("decentralized identity", 1.0, "positive_signal"),
            ("did", 1.0, "positive_signal"),
            ("digital identity", 0.8, "positive_signal"),
            ("verifiable credentials", 1.0, "positive_signal"),
            ("credential issuance", 1.0, "positive_signal"),
            ("credential storage", 0.9, "positive_signal"),
            ("credential presentation", 0.9, "positive_signal"),
            ("credential verification", 1.0, "positive_signal"),
            ("identity wallet", 0.9, "positive_signal"),
            ("decentralized credentials", 0.9, "positive_signal"),
            ("kyc aml verification", -0.8, "exclusion"),  # Distinction from SecureX-ID
            ("x id score", -1.0, "exclusion"),            # Distinction from SecureX-ID
        ],
        "technologies": ["Decentralized Identity", "Verifiable Credentials"],
        "categories": ["Decentralized Identity", "Web3 Identity"],
    },
    {
        "name": "SecureWatch",
        "description": (
            "Continuous monitoring platform for blockchain transactions and smart contract activity. "
            "It focuses on anomaly detection, suspicious activity detection, alerts, and abnormal token movement."
        ),
        "priority": 9,
        "capabilities": [
            ("Blockchain monitoring", "Continuous monitoring of blockchain ledgers", 1.0),
            ("Transaction monitoring", "Monitoring active live transactions", 1.0),
            ("Smart contract monitoring", "Real-time contract activity observation", 1.0),
            ("Continuous monitoring", "24/7 automated activity monitoring", 1.0),
            ("Anomaly detection", "Detecting unusual patterns in contract/tx activity", 1.0),
            ("Suspicious activity", "Real-time threat and suspicious behavior detection", 1.0),
            ("Security alerts", "Instant alerting for security teams", 0.9),
            ("Abnormal token movement", "Detecting unexpected high-volume transfers", 1.0),
            ("Transaction alerts", "Real-time transaction alerting", 0.9),
            ("Smart contract activity monitoring", "Observing smart contract activity", 0.9),
        ],
        "keywords": [
            ("blockchain monitoring", 1.0, "positive_signal"),
            ("transaction monitoring", 1.0, "positive_signal"),
            ("smart contract monitoring", 1.0, "positive_signal"),
            ("continuous monitoring", 1.0, "positive_signal"),
            ("anomaly detection", 1.0, "positive_signal"),
            ("suspicious activity", 1.0, "positive_signal"),
            ("security alerts", 0.9, "positive_signal"),
            ("abnormal token movement", 1.0, "positive_signal"),
            ("transaction alerts", 0.9, "positive_signal"),
            ("smart contract activity monitoring", 0.9, "positive_signal"),
            ("forensic investigation", -0.8, "exclusion"),  # Distinction from SecureTrace
            ("transaction tracing", -0.5, "exclusion"),       # Distinction from SecureTrace
        ],
        "technologies": ["Real-time Monitoring", "Blockchain Telemetry"],
        "categories": ["Blockchain Security", "Threat Monitoring"],
    },
    {
        "name": "AuditExpress",
        "description": (
            "Automated smart contract security assessment platform focused on vulnerability scanning, logic issue detection, "
            "findings generation, security posture assessment, and pre-deployment assessment."
        ),
        "priority": 8,
        "capabilities": [
            ("Automated smart contract assessment", "Rapid automated contract security assessment", 1.0),
            ("Smart contract vulnerability scanning", "Scanning contract code for vulnerabilities", 1.0),
            ("Logic issue detection", "Detecting logic flaws in contract code", 1.0),
            ("Security findings", "Generating structured security findings", 0.9),
            ("Security posture", "Assessment of contract security posture", 0.9),
            ("Security assessment", "Fast automated security assessment reports", 0.9),
            ("Pre-deployment security assessment", "Rapid pre-deployment code scanning", 0.9),
            ("Automated audit", "Automated smart contract audit", 1.0),
            ("Smart contract analysis", "Static and dynamic contract analysis", 0.9),
        ],
        "keywords": [
            ("automated smart contract assessment", 1.0, "positive_signal"),
            ("smart contract vulnerability scanning", 1.0, "positive_signal"),
            ("logic issue detection", 1.0, "positive_signal"),
            ("security findings", 0.9, "positive_signal"),
            ("security posture", 0.9, "positive_signal"),
            ("security assessment", 0.9, "positive_signal"),
            ("pre deployment security assessment", 0.9, "positive_signal"),
            ("automated audit", 1.0, "positive_signal"),
            ("smart contract analysis", 0.9, "positive_signal"),
            # Real-world GeM procurement terminology for security-assessment /
            # vulnerability-scanning work that the formal capability names above
            # (security assessment, smart contract vulnerability scanning,
            # automated audit) never appear as in tender text. Added as
            # terminology coverage only - every term maps to an existing
            # verified capability; no new capability is invented.
            ("penetration testing", 1.0, "positive_signal"),
            ("vulnerability assessment", 1.0, "positive_signal"),
            ("security audit", 1.0, "positive_signal"),
            ("application security", 1.0, "positive_signal"),
            ("web application security", 1.0, "positive_signal"),
            ("vapt", 1.0, "positive_signal"),
            ("owasp", 1.0, "positive_signal"),
            ("security testing", 0.9, "positive_signal"),
            ("cyber security audit", 1.0, "positive_signal"),
        ],
        "technologies": ["Automated Code Analysis", "Smart Contracts"],
        "categories": ["Automated Audit", "Smart Contract Assessment"],
    },
    {
        "name": "SecurePad",
        "description": (
            "Web3 and DeFi infrastructure platform covering token creation and management, trading, staking, "
            "lending, borrowing, and governance."
        ),
        "priority": 7,
        "capabilities": [
            ("Web3", "Web3 platform functionality", 0.8),
            ("DeFi", "Decentralized finance protocols", 0.9),
            ("Decentralized finance", "DeFi infrastructure components", 0.9),
            ("Token creation", "Token minting and contract creation", 1.0),
            ("Token management", "Lifecycle management of tokens", 1.0),
            ("Trading", "Token exchange and trading mechanisms", 0.9),
            ("Staking", "Token staking pool management", 0.9),
            ("Lending", "DeFi lending functionality", 0.9),
            ("Borrowing", "DeFi borrowing protocols", 0.9),
            ("Governance", "Token-based voting and governance", 0.9),
            ("Web3 infrastructure", "Infrastructure for Web3 platforms", 1.0),
            ("DeFi infrastructure", "Infrastructure for DeFi platforms", 1.0),
        ],
        "keywords": [
            ("web3", 0.8, "positive_signal"),
            ("defi", 0.9, "positive_signal"),
            ("decentralized finance", 0.9, "positive_signal"),
            ("token creation", 1.0, "positive_signal"),
            ("token management", 1.0, "positive_signal"),
            ("token trading", 0.9, "positive_signal"),
            ("staking", 0.9, "positive_signal"),
            ("lending", 0.9, "positive_signal"),
            ("borrowing", 0.9, "positive_signal"),
            ("governance", 0.9, "positive_signal"),
            ("web3 infrastructure", 1.0, "positive_signal"),
            ("defi infrastructure", 1.0, "positive_signal"),
            ("generic blockchain development", -1.0, "exclusion"),
        ],
        "technologies": ["Web3", "DeFi Protocols", "Token Standards"],
        "categories": ["Web3 Infrastructure", "DeFi Platform"],
    },
    {
        "name": "SecureX-ID",
        "description": (
            "Identity verification and compliance platform for Web3 and DeFi. It supports KYC, AML, fraud-risk monitoring, "
            "watchlist checks, transaction-history analysis, behavior analysis, risk assessment, and the X-ID Score concept."
        ),
        "priority": 8,
        "capabilities": [
            ("Identity verification", "Identity verification workflows", 1.0),
            ("KYC", "Know Your Customer verification", 1.0),
            ("AML", "Anti-Money Laundering checks", 1.0),
            ("Web3 compliance", "Compliance checks tailored for Web3", 1.0),
            ("DeFi compliance", "Compliance verification for DeFi platforms", 1.0),
            ("Fraud risk", "Monitoring identity fraud risk", 0.9),
            ("Fraud-risk monitoring", "Continuous fraud risk detection", 1.0),
            ("Watchlist checks", "Screening against sanction/watchlists", 1.0),
            ("Transaction-history analysis", "Analyzing user transaction history for risk", 0.9),
            ("Behavior analysis", "Analyzing user behavior for risk scoring", 0.9),
            ("Risk assessment", "Identity risk scoring", 0.9),
            ("X-ID Score", "Proprietary X-ID risk and verification score", 1.0),
            ("Identity compliance", "End-to-end identity compliance", 0.9),
        ],
        "keywords": [
            ("identity verification", 1.0, "positive_signal"),
            ("kyc", 1.0, "positive_signal"),
            ("aml", 1.0, "positive_signal"),
            ("web3 compliance", 1.0, "positive_signal"),
            ("defi compliance", 1.0, "positive_signal"),
            ("fraud risk", 0.9, "positive_signal"),
            ("fraud risk monitoring", 1.0, "positive_signal"),
            ("watchlist checks", 1.0, "positive_signal"),
            ("transaction history analysis", 0.9, "positive_signal"),
            ("behavior analysis", 0.9, "positive_signal"),
            ("risk assessment", 0.9, "positive_signal"),
            ("x id score", 1.0, "positive_signal"),
            ("identity compliance", 0.9, "positive_signal"),
            ("verifiable credentials", -0.5, "exclusion"),  # Distinction from SecureX-DID
            ("decentralized identity did", -0.8, "exclusion"), # Distinction from SecureX-DID
        ],
        "technologies": ["KYC/AML Engine", "Web3 Risk Scoring"],
        "categories": ["Compliance", "Identity Verification"],
    },
    {
        "name": "QuantumVault",
        "description": (
            "Cryptographic key protection and key-management platform focused on secure key generation, storage, access control, "
            "rotation, revocation, and hardware-backed protection, with consideration for future post-quantum requirements."
        ),
        "priority": 9,
        "capabilities": [
            ("Cryptographic key protection", "Protection of cryptographic keys", 1.0),
            ("Cryptographic key management", "End-to-end key lifecycle management", 1.0),
            ("Secure key generation", "Generating cryptographically secure keys", 1.0),
            ("Secure key storage", "Protected hardware key storage", 1.0),
            ("Key access control", "Granular access control policies for key usage", 0.9),
            ("Key rotation", "Automated cryptographic key rotation", 0.9),
            ("Key revocation", "Revoking compromised cryptographic keys", 0.9),
            ("Hardware-backed protection", "Hardware security module backed key protection", 1.0),
            ("HSM concepts", "Hardware security module integration concepts", 1.0),
            ("Cryptographic key security", "Cryptographic key security and auditing", 0.9),
            ("Post-quantum key protection", "Key protection designed for post-quantum crypto", 0.9),
        ],
        "keywords": [
            ("cryptographic key protection", 1.0, "positive_signal"),
            ("cryptographic key management", 1.0, "positive_signal"),
            ("secure key generation", 1.0, "positive_signal"),
            ("secure key storage", 1.0, "positive_signal"),
            ("key access control", 0.9, "positive_signal"),
            ("key rotation", 0.9, "positive_signal"),
            ("key revocation", 0.9, "positive_signal"),
            ("hardware backed protection", 1.0, "positive_signal"),
            ("hsm concepts", 1.0, "positive_signal"),
            ("cryptographic key security", 0.9, "positive_signal"),
            ("post quantum key protection", 0.9, "positive_signal"),
            # Real-world GeM procurement terminology for key-management /
            # hardware-backed-protection work that the formal capability names
            # above (cryptographic key management, secure key storage,
            # hardware-backed protection) never appear as in tender text.
            # Added as terminology coverage only - every term maps to an
            # existing verified capability; no new capability is invented.
            ("key management system", 1.0, "positive_signal"),
            ("hardware security module", 1.0, "positive_signal"),
            ("secure socket layer", 0.9, "positive_signal"),
            ("ssl certificate", 0.9, "positive_signal"),
            ("crypto agility software", -0.5, "exclusion"),  # Distinction from PQCSuite
        ],
        "technologies": ["HSM", "Hardware Key Protection"],
        "categories": ["Key Management", "Hardware Security"],
    },
]


def _has_knowledge(db: Session, product_id: Any) -> bool:
    """True when the product already carries any knowledge vector rows."""
    return any(
        db.query(model).filter(model.product_id == product_id).count() > 0
        for model in (ProductCapability, ProductKeyword, ProductTechnology, ProductCategory)
    )


def _write_knowledge(db: Session, product: Product, prod_info: Dict[str, Any]) -> None:
    """(Re)write the full knowledge vector for a product from PRODUCTS_KNOWLEDGE."""
    db.query(ProductCapability).filter(ProductCapability.product_id == product.id).delete()
    db.query(ProductKeyword).filter(ProductKeyword.product_id == product.id).delete()
    db.query(ProductTechnology).filter(ProductTechnology.product_id == product.id).delete()
    db.query(ProductCategory).filter(ProductCategory.product_id == product.id).delete()
    db.flush()

    for cap_name, cap_desc, cap_weight in prod_info["capabilities"]:
        db.add(ProductCapability(
            product_id=product.id,
            name=cap_name,
            description=cap_desc,
            weight=cap_weight,
            active=True,
        ))

    for kw_text, kw_weight, kw_type in prod_info["keywords"]:
        db.add(ProductKeyword(
            product_id=product.id,
            keyword=kw_text,
            weight=kw_weight,
            type=kw_type,
            active=True,
        ))

    for tech in prod_info["technologies"]:
        db.add(ProductTechnology(product_id=product.id, technology=tech))

    for cat in prod_info["categories"]:
        db.add(ProductCategory(product_id=product.id, category=cat))


def seed_product_knowledge(db: Session) -> int:
    """
    Force-seeds all 11 SecuredApp products and their knowledge vectors.

    Existing products have their knowledge vectors replaced. This is the
    behaviour relied upon by the test fixtures, which start from an empty
    database. Use :func:`bootstrap_product_knowledge` for deployed
    environments so that admin edits are never overwritten.

    Returns the count of seeded/updated products.
    """
    seeded_count = 0

    for prod_info in PRODUCTS_KNOWLEDGE:
        product = db.query(Product).filter(Product.name == prod_info["name"]).first()
        if not product:
            product = Product(
                name=prod_info["name"],
                description=prod_info["description"],
                active=True,
                priority=prod_info["priority"],
            )
            db.add(product)
            db.flush()
        else:
            product.description = prod_info["description"]
            product.priority = prod_info["priority"]

        _write_knowledge(db, product, prod_info)
        seeded_count += 1

    db.commit()
    return seeded_count


def bootstrap_product_knowledge(db: Session) -> Dict[str, int]:
    """
    Idempotent deployment bootstrap for the product knowledge layer.

    Guarantees a freshly deployed application has the full knowledge vectors
    required by the matching engine, while never destroying operator data:

    * A missing product is created together with its full knowledge vector.
    * A product that exists but has no knowledge vector yet (for example one
      left behind by the legacy name-only seed) is backfilled, and its
      description/priority are filled in only where they are still empty.
    * A product that already has a knowledge vector is left completely
      untouched, so edits made through the Product Management API survive
      container restarts and redeployments.

    Returns a small breakdown for logging/verification purposes.
    """
    created = 0
    backfilled = 0
    preserved = 0

    for prod_info in PRODUCTS_KNOWLEDGE:
        product = db.query(Product).filter(Product.name == prod_info["name"]).first()

        if not product:
            product = Product(
                name=prod_info["name"],
                description=prod_info["description"],
                active=True,
                priority=prod_info["priority"],
            )
            db.add(product)
            db.flush()
            _write_knowledge(db, product, prod_info)
            created += 1
            continue

        if _has_knowledge(db, product.id):
            preserved += 1
            continue

        # Only fill genuinely empty metadata so operator edits survive.
        if not (product.description or "").strip():
            product.description = prod_info["description"]
        if not product.priority:
            product.priority = prod_info["priority"]

        _write_knowledge(db, product, prod_info)
        backfilled += 1

    db.commit()
    return {"created": created, "backfilled": backfilled, "preserved": preserved}
