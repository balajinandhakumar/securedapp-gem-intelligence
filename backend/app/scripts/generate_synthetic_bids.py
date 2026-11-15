"""
Deterministic Synthetic GeM-style Bids Generator for Development and Testing.
Strict rule: Clearly labeled as synthetic development data.
Generates exactly 1,000 structured GeM-style bid records covering all test scenarios.
"""
import json
import os
import random
from datetime import datetime, timedelta, timezone

def generate_synthetic_dataset(output_path: str = "data/sample_bids/synthetic_1000_bids.json"):
    random.seed(42)  # Deterministic seed for reproducible testing
    base_date = datetime(2026, 11, 1, 10, 0, 0, tzinfo=timezone.utc)
    
    organisations = [
        ("National Smart Grid Mission", "Department of Energy", "Ministry of Power", "New Delhi"),
        ("National Payments Corporation of India", "Digital Payments Group", "Ministry of Finance", "Mumbai"),
        ("Defence Research and Development Organisation", "Centre for AI & Robotics", "Ministry of Defence", "Bengaluru"),
        ("Indian Space Research Organisation", "Telemetry & Tracking", "Department of Space", "Bengaluru"),
        ("State Bank of India", "Core Banking Division", "Ministry of Finance", "Mumbai"),
        ("Oil and Natural Gas Corporation", "SCADA Security", "Ministry of Petroleum", "Dehradun"),
        ("National Informatics Centre", "E-Governance Services", "Ministry of Electronics & IT", "New Delhi"),
        ("Unique Identification Authority of India", "Authentication Systems", "Ministry of Electronics & IT", "New Delhi"),
        ("Indian Railways", "Centre for Railway Information Systems", "Ministry of Railways", "New Delhi"),
        ("Securities and Exchange Board of India", "Market Surveillance", "Ministry of Finance", "Mumbai"),
        ("Power Grid Corporation of India", "Grid Automation", "Ministry of Power", "Gurugram"),
        ("Central Board of Direct Taxes", "E-Filing Portal", "Ministry of Finance", "New Delhi"),
    ]

    unrelated_orgs = [
        ("Central Public Works Department", "Civil Division", "Ministry of Housing", "New Delhi"),
        ("All India Institute of Medical Sciences", "Hospital Stores", "Ministry of Health", "New Delhi"),
        ("Food Corporation of India", "Procurement Division", "Ministry of Consumer Affairs", "New Delhi"),
        ("Kendriya Vidyalaya Sangathan", "Administration", "Ministry of Education", "New Delhi"),
        ("Indian Council of Agricultural Research", "Agronomy Section", "Ministry of Agriculture", "New Delhi"),
        ("Directorate General of Supplies", "General Stores", "Ministry of Commerce", "New Delhi"),
        ("National Highways Authority of India", "Highway Maintenance", "Ministry of Road Transport", "New Delhi"),
        ("Border Roads Organisation", "Equipment Division", "Ministry of Defence", "Dehradun"),
        ("Port Trust of India", "Marine Engineering", "Ministry of Shipping", "Chennai"),
        ("Inland Waterways Authority", "Navigation Infrastructure", "Ministry of Ports", "Noida"),
    ]

    domains = [
        "Energy Distribution Network", "Interbank Clearing Gateway", "Autonomous Drone Swarm Telemetry",
        "Deep Space Communications Array", "Cross-Border Trade Settlement", "Offshore Oil Rig Monitoring",
        "Citizen Passport Verification", "Aadhaar Biometric Authentication", "Freight Train Scheduling",
        "High-Frequency Derivative Trading", "Substation SCADA Automation", "Direct Tax Assessment Portal",
        "Treasury Management System", "Supply Chain Customs Clearance", "Public Healthcare Database",
        "Land Record Registry", "Digital Identity Gateway", "Vehicle Registration Network",
        "Municipal Water Grid", "Emergency Response Dispatch",
    ]

    bids = []
    bid_counter = 10000

    # -------------------------------------------------------------------------
    # 1. CLEARLY RELEVANT BIDS (220 bids: 20 per each of 11 products)
    # -------------------------------------------------------------------------
    product_templates = {
        "SolidityShield": [
            "Smart contract security audit and Solidity vulnerability assessment for EVM contracts",
            "Pre-deployment security assessment and reentrancy detection for Solidity smart contracts",
            "Smart contract audit with expert security review and security finding validation services",
            "Comprehensive smart contract security audit and remediation validation for digital assets",
        ],
        "SecureCMS": [
            "Enterprise user consent management and privacy compliance records platform",
            "Privacy compliance records and user consent tracking system with consent withdrawal",
            "Digital privacy consent management system and compliance audit trail records",
            "Citizen privacy consent records and consent tracking platform for regulatory compliance",
        ],
        "SecureTrace": [
            "Blockchain investigation and cryptocurrency transaction tracing platform",
            "Cryptocurrency forensic investigation and wallet tracing fund-flow analysis tool",
            "Blockchain forensics and suspicious transaction investigation system for law enforcement",
            "Digital asset fund-flow analysis and wallet tracing investigation platform",
        ],
        "CookieHub": [
            "Website cookie consent banner and tracking script management solution",
            "Web portal cookie consent management and dynamic tracking script control platform",
            "Dynamic tracking script control and website cookie consent collection system",
            "Public web portal cookie consent management and analytics script blocking solution",
        ],
        "PQCSuite": [
            "Post-quantum cryptography implementation and cryptographic agility framework",
            "Quantum-resistant cryptography and flexible cryptographic layer migration suite",
            "Cryptographic algorithm migration and post-quantum cryptography software primitives",
            "Post-quantum cryptography readiness and crypto-agility layer implementation",
        ],
        "SecureX-DID": [
            "Decentralized identity (DID) and W3C verifiable credentials issuance platform",
            "Verifiable credentials presentation and digital identity wallet verification system",
            "Self-sovereign digital identity and verifiable credentials ecosystem infrastructure",
            "Decentralized identifier credential issuance and identity wallet management portal",
        ],
        "SecureWatch": [
            "Real-time blockchain monitoring and smart contract activity observation system",
            "24/7 transaction monitoring and abnormal token movement alert generation platform",
            "Continuous blockchain threat monitoring, anomaly detection, and real-time alerts",
            "Live smart contract activity monitoring and suspicious transaction alert system",
        ],
        "AuditExpress": [
            "Automated smart contract security assessment and rapid vulnerability scanning tool",
            "Rapid vulnerability assessment and automated smart contract code scanning engine",
            "Automated smart contract assessment and logic-related issue detection system",
            "Rapid automated security assessment and security posture evaluation for smart contracts",
        ],
        "SecurePad": [
            "Web3 infrastructure and token management ecosystem platform with governance",
            "DeFi infrastructure platform with token creation, staking, lending, and borrowing",
            "Token ecosystem and Web3 DeFi infrastructure platform with token minting and trading",
            "Decentralized finance infrastructure and token creation lifecycle management system",
        ],
        "SecureX-ID": [
            "KYC/AML identity verification and Web3 risk scoring compliance engine",
            "DeFi identity verification, anti-money laundering screening, and X-ID risk scoring",
            "Web3 compliance and KYC/AML identity verification engine with watchlist checks",
            "Identity risk assessment, AML screening, and fraud-risk monitoring system for Web3",
        ],
        "QuantumVault": [
            "Hardware-backed cryptographic key protection and HSM key management system",
            "Hardware security module key management and cryptographic key protection solution",
            "Cryptographic key lifecycle management, secure key generation, and hardware key storage",
            "Hardware-backed cryptographic key rotation, key revocation, and HSM key protection",
        ],
    }

    for prod_name, tmpls in product_templates.items():
        for i in range(20):
            bid_counter += 1
            tmpl_title = tmpls[i % len(tmpls)]
            domain = domains[(i + len(prod_name)) % len(domains)]
            org = organisations[i % len(organisations)]
            days_closing = 10 + (i % 20)
            val = 2500000.0 + (i * 750000.0)
            
            full_title = f"{tmpl_title} for {domain} [{org[0]} - PRJ-{bid_counter}]"
            
            bids.append({
                "gem_bid_id": f"GEM/2026/B/{bid_counter}",
                "bid_number": f"GEM-{bid_counter}",
                "title": full_title,
                "organisation": org[0],
                "department": org[1],
                "ministry": org[2],
                "category": "Cyber Security & Software Services",
                "published_date": (base_date - timedelta(days=2)).isoformat(),
                "closing_date": (base_date + timedelta(days=days_closing)).isoformat(),
                "location": org[3],
                "estimated_value": val,
                "currency": "INR",
                "scope_of_work": f"Comprehensive delivery of {tmpl_title.lower()} tailored for {domain}. The bidder must deliver all core capabilities and comply with rigorous technical evaluation standards.",
                "technical_requirements": {
                    "certifications_required": ["ISO 27001", "CMMI Level 3"],
                    "minimum_experience_years": 3 + (i % 5),
                    "product_domain": prod_name,
                },
                "eligibility_criteria": {
                    "annual_turnover_inr": val * 2.0,
                    "prior_govt_projects": 2,
                },
                "source_name": "synthetic_gem_dev_dataset",
                "source_url": f"https://gem.gov.in/bids/GEM-{bid_counter}",
            })

    # -------------------------------------------------------------------------
    # 2. POSSIBLY RELEVANT BIDS (150 bids: moderate signals scoring 0.45 - 0.69)
    # -------------------------------------------------------------------------
    possible_templates = [
        "Web Application Security Audit and Source Code Vulnerability Review",
        "Information Security Risk Assessment and Compliance Consulting",
        "Digital Certificate Management and Key Security Consulting",
        "Enterprise API Security Testing and Access Control Assessment",
        "Digital Identity Governance and Access Management Advisory",
        "Database Security Audit and Data Protection Assessment",
        "Secure Code Review and Application Threat Modeling Advisory",
        "Cyber Threat Intelligence and Vulnerability Management Services",
    ]

    for i in range(150):
        bid_counter += 1
        tmpl_title = possible_templates[i % len(possible_templates)]
        domain = domains[i % len(domains)]
        org = organisations[i % len(organisations)]
        days_closing = 7 + (i % 25)
        val = 1500000.0 + (i * 300000.0)

        full_title = f"{tmpl_title} for {domain} [{org[0]} - SEC-{bid_counter}]"

        bids.append({
            "gem_bid_id": f"GEM/2026/B/{bid_counter}",
            "bid_number": f"GEM-{bid_counter}",
            "title": full_title,
            "organisation": org[0],
            "department": org[1],
            "ministry": org[2],
            "category": "IT & Cybersecurity Consultancy",
            "published_date": (base_date - timedelta(days=1)).isoformat(),
            "closing_date": (base_date + timedelta(days=days_closing)).isoformat(),
            "location": org[3],
            "estimated_value": val,
            "currency": "INR",
            "scope_of_work": f"Provision of {tmpl_title.lower()} for {domain}. Engagement requires experienced security engineers to conduct comprehensive reviews.",
            "technical_requirements": {
                "certifications_required": ["CERT-In", "ISO 27001"],
                "experience_years": 3,
            },
            "eligibility_criteria": {
                "annual_turnover_inr": val * 1.5,
            },
            "source_name": "synthetic_gem_dev_dataset",
            "source_url": f"https://gem.gov.in/bids/GEM-{bid_counter}",
        })

    # -------------------------------------------------------------------------
    # 3. NEEDS REVIEW BIDS (130 bids: peripheral IT/security scoring 0.25 - 0.44)
    # -------------------------------------------------------------------------
    needs_review_templates = [
        "Enterprise Network Firewall Maintenance and Security Monitoring",
        "IT Infrastructure Systems Administration and Periodic Backup Audit",
        "Cloud Infrastructure Migration and Architecture Review",
        "IT Asset Management and Hardware Inventory Tracking System",
        "Data Center Environmental Monitoring and Server Uptime Maintenance",
        "Enterprise Endpoint Antivirus Management and Patch Deployment",
    ]

    for i in range(130):
        bid_counter += 1
        tmpl_title = needs_review_templates[i % len(needs_review_templates)]
        domain = domains[i % len(domains)]
        org = organisations[i % len(organisations)]
        days_closing = 5 + (i % 20)
        val = 1000000.0 + (i * 200000.0)

        full_title = f"{tmpl_title} for {domain} [{org[0]} - OPS-{bid_counter}]"

        bids.append({
            "gem_bid_id": f"GEM/2026/B/{bid_counter}",
            "bid_number": f"GEM-{bid_counter}",
            "title": full_title,
            "organisation": org[0],
            "department": org[1],
            "ministry": org[2],
            "category": "IT Infrastructure Services",
            "published_date": base_date.isoformat(),
            "closing_date": (base_date + timedelta(days=days_closing)).isoformat(),
            "location": org[3],
            "estimated_value": val,
            "currency": "INR",
            "scope_of_work": f"Scope covers {tmpl_title.lower()} across enterprise data centers for {domain}. Focuses on operational reliability and infrastructure uptime.",
            "technical_requirements": {"uptime_sla": "99.5%"},
            "eligibility_criteria": {"prior_experience": "2 years in IT ops"},
            "source_name": "synthetic_gem_dev_dataset",
            "source_url": f"https://gem.gov.in/bids/GEM-{bid_counter}",
        })

    # -------------------------------------------------------------------------
    # 4. UNRELATED BIDS (350 bids: civil, furniture, catering, medical, AC, etc. scoring < 0.25)
    # -------------------------------------------------------------------------
    unrelated_templates = [
        ("Supply and Installation of Ergonomic Modular Office Furniture", "Supply, delivery, unboxing, and installation of executive chairs, desks, and storage cupboards.", "Office Furniture & Supplies"),
        ("Annual Maintenance Contract for Central Air Conditioning and Chiller Units", "Comprehensive AMC for 100-ton central chillers, air handling units, duct cleaning, and refrigerant refilling.", "HVAC Services"),
        ("Construction and Resurfacing of Bituminous Internal Access Roads", "Earthwork, sub-base preparation, bituminous concrete laying, and road markings for institutional campus.", "Civil Construction Works"),
        ("Catering, Canteen Management and Dining Services for Trainee Hostel", "Provision of hygienic breakfast, lunch, and dinner services for 500 residential trainees daily.", "Catering & Hospitality"),
        ("Procurement of Medical PPE Kits, Surgical Gloves, and Hospital Consumables", "Supply of sterile surgical gloves, 3-ply masks, N95 respirators, and protective face shields.", "Medical Supplies"),
        ("Hiring of Commercial Vehicles on Monthly Lease Basis", "Hiring of 15 commercial diesel SUVs with commercial drivers and fuel included for executive transport.", "Transportation & Vehicles"),
        ("Housekeeping, Deep Cleaning, and Facility Sanitization Services", "Mechanized floor scrubbing, washroom cleaning, waste disposal, and general housekeeping services.", "Facility Management"),
        ("Supply of Agricultural Tractors, Rotavators, and Harvester Implements", "Supply and commissioning of 50 HP diesel tractors and attached agricultural implements for research farm.", "Agricultural Machinery"),
        ("Printing, Binding, and Distribution of Annual Statistical Reports", "Offset printing of multi-color annual reports, hardbound binding, shrink-wrapping, and courier dispatch.", "Printing & Publication"),
        ("Supply and Commissioning of Rooftop Solar Photovoltaic Power Plant", "Installation of 100 kWp grid-connected rooftop solar PV panels with inverters, net metering, and 5-year warranty.", "Renewable Energy"),
        ("Supply of Laboratory Glassware, Reagents, and Diagnostic Centrifuges", "Supply of borosilicate beakers, conical flasks, analytical reagents, and high-speed centrifuges.", "Laboratory Equipment"),
        ("Annual Maintenance for Diesel Generator Sets and Transformer Substations", "Preventive maintenance, engine oil replacement, filter changes, and electrical transformer testing.", "Electrical Maintenance"),
    ]

    for i in range(350):
        bid_counter += 1
        tmpl_title, tmpl_scope, tmpl_cat = unrelated_templates[i % len(unrelated_templates)]
        org = unrelated_orgs[i % len(unrelated_orgs)]
        days_closing = 3 + (i % 30)
        val = 500000.0 + (i * 150000.0)

        full_title = f"{tmpl_title} for {org[0]} [Tender Ref #{bid_counter}]"

        bids.append({
            "gem_bid_id": f"GEM/2026/B/{bid_counter}",
            "bid_number": f"GEM-{bid_counter}",
            "title": full_title,
            "organisation": org[0],
            "department": org[1],
            "ministry": org[2],
            "category": tmpl_cat,
            "published_date": (base_date - timedelta(days=3)).isoformat(),
            "closing_date": (base_date + timedelta(days=days_closing)).isoformat(),
            "location": org[3],
            "estimated_value": val,
            "currency": "INR",
            "scope_of_work": f"{tmpl_scope} All materials and execution must comply with CPWD and relevant Indian standards.",
            "technical_requirements": {"warranty_months": 24, "delivery_period_days": 45},
            "eligibility_criteria": {"gem_reseller_authorization": True},
            "source_name": "synthetic_gem_dev_dataset",
            "source_url": f"https://gem.gov.in/bids/GEM-{bid_counter}",
        })

    # -------------------------------------------------------------------------
    # 5. MULTI-PRODUCT CANDIDATES (50 bids: tests differentiation rules)
    # -------------------------------------------------------------------------
    differentiation_pairs = [
        # Pair 1: SolidityShield vs AuditExpress
        ("Solidity smart contract security audit with expert review and manual verification",
         "Conducting Solidity smart contract security audit, vulnerability detection, and expert review with auditor validation for smart contracts."),
        ("Rapid automated smart contract security assessment without manual review",
         "Rapid automated security assessment, automated code scanning, and automated security assessment for smart contracts."),
        
        # Pair 2: SecureTrace vs SecureWatch
        ("Cryptocurrency forensic investigation and transaction fund flow tracing",
         "Blockchain investigation, blockchain forensics, wallet tracing, fund-flow analysis, and suspicious transaction investigation."),
        ("24/7 continuous monitoring and real-time alert generation for token movement",
         "Continuous monitoring of blockchain smart contracts, real-time alert generation, anomaly detection, and abnormal token movement."),

        # Pair 3: SecureCMS vs CookieHub
        ("Website cookie consent and tracking script management banner",
         "Cookie consent collection, tracking-script management, and consent-based script control for public portals."),
        ("Enterprise user consent records and privacy compliance audit trail",
         "User consent records, consent management, consent withdrawal management, and privacy compliance records."),

        # Pair 4: SecureX-DID vs SecureX-ID
        ("W3C decentralized identity DID and verifiable credentials issuance",
         "Decentralized identity, W3C DID, verifiable credentials, credential issuance, and identity wallet concepts."),
        ("KYC/AML identity verification and X-ID risk scoring compliance",
         "KYC, AML, identity verification, watchlist checks, and X-ID score risk assessment for Web3."),

        # Pair 5: PQCSuite vs QuantumVault
        ("Post-quantum cryptography migration and crypto agility framework",
         "Post-quantum cryptography, crypto agility, quantum-resistant cryptography, and cryptographic algorithm migration."),
        ("Hardware-backed cryptographic key protection and HSM key management",
         "Cryptographic key protection, hardware-backed key protection, HSM concepts, key storage, and key rotation."),
    ]

    for i in range(50):
        bid_counter += 1
        tmpl_title, tmpl_scope = differentiation_pairs[i % len(differentiation_pairs)]
        domain = domains[i % len(domains)]
        org = organisations[i % len(organisations)]
        days_closing = 12 + (i % 15)
        val = 4000000.0 + (i * 500000.0)

        full_title = f"{tmpl_title} for {domain} [{org[0]} - DIF-{bid_counter}]"

        bids.append({
            "gem_bid_id": f"GEM/2026/B/{bid_counter}",
            "bid_number": f"GEM-{bid_counter}",
            "title": full_title,
            "organisation": org[0],
            "department": org[1],
            "ministry": org[2],
            "category": "Specialized Cybersecurity & Web3",
            "published_date": (base_date - timedelta(days=1)).isoformat(),
            "closing_date": (base_date + timedelta(days=days_closing)).isoformat(),
            "location": org[3],
            "estimated_value": val,
            "currency": "INR",
            "scope_of_work": f"{tmpl_scope} Specialized procurement for {domain}. Strict compliance with architectural differentiation specifications.",
            "technical_requirements": {"compliance_standard": "NIST / W3C"},
            "eligibility_criteria": {"prior_experience_years": 4},
            "source_name": "synthetic_gem_dev_dataset",
            "source_url": f"https://gem.gov.in/bids/GEM-{bid_counter}",
        })

    # -------------------------------------------------------------------------
    # 6. DUPLICATES & UPDATE SCENARIOS (60 bids)
    # -------------------------------------------------------------------------
    # 30 exact duplicates (re-using exact gem_bid_id and hash from first 30 bids)
    for i in range(30):
        orig_bid = bids[i]
        bids.append({
            "gem_bid_id": orig_bid["gem_bid_id"],
            "bid_number": orig_bid["bid_number"],
            "title": orig_bid["title"],
            "organisation": orig_bid["organisation"],
            "department": orig_bid["department"],
            "ministry": orig_bid["ministry"],
            "category": orig_bid["category"],
            "published_date": orig_bid["published_date"],
            "closing_date": orig_bid["closing_date"],
            "location": orig_bid["location"],
            "estimated_value": orig_bid["estimated_value"],
            "currency": orig_bid["currency"],
            "scope_of_work": orig_bid["scope_of_work"],
            "source_name": "synthetic_gem_dev_dataset",
            "source_url": orig_bid["source_url"],
        })

    # 30 updated records (same gem_bid_id with amended closing dates or scope)
    for i in range(30):
        orig_bid = bids[30 + i]
        bids.append({
            "gem_bid_id": orig_bid["gem_bid_id"],
            "bid_number": orig_bid["bid_number"],
            "title": orig_bid["title"],
            "organisation": orig_bid["organisation"],
            "department": orig_bid["department"],
            "ministry": orig_bid["ministry"],
            "category": orig_bid["category"],
            "published_date": orig_bid["published_date"],
            "closing_date": (base_date + timedelta(days=45)).isoformat(),  # Extended deadline
            "location": orig_bid["location"],
            "estimated_value": orig_bid["estimated_value"] + 500000.0,
            "currency": orig_bid["currency"],
            "scope_of_work": f"{orig_bid['scope_of_work']} Corrigendum update: extended scope and timeline.",
            "source_name": "synthetic_gem_dev_dataset",
            "source_url": orig_bid["source_url"],
        })

    # -------------------------------------------------------------------------
    # 7. INCOMPLETE REQUIREMENT BIDS (40 bids: missing estimated values, minimal text)
    # -------------------------------------------------------------------------
    incomplete_templates = [
        "General Cybersecurity Advisory Services Notice",
        "Software Architecture Audit Services Notice",
        "Privacy Policy Review Services Notice",
        "Tokenomics Advisory Consultancy Notice",
    ]

    for i in range(40):
        bid_counter += 1
        tmpl_title = incomplete_templates[i % len(incomplete_templates)]
        domain = domains[i % len(domains)]
        org = organisations[i % len(organisations)]
        
        full_title = f"{tmpl_title} for {domain} [{org[0]} - MIN-{bid_counter}]"

        bids.append({
            "gem_bid_id": f"GEM/2026/B/{bid_counter}",
            "bid_number": f"GEM-{bid_counter}",
            "title": full_title,
            "organisation": org[0],
            "department": org[1],
            "ministry": org[2],
            "category": "Consultancy Services",
            "published_date": base_date.isoformat(),
            "closing_date": None,  # Missing closing date
            "location": org[3],
            "estimated_value": None,  # Missing estimated value
            "currency": "INR",
            "scope_of_work": f"General advisory notice for {domain}.",
            "technical_requirements": None,
            "eligibility_criteria": None,
            "source_name": "synthetic_gem_dev_dataset",
            "source_url": f"https://gem.gov.in/bids/GEM-{bid_counter}",
        })

    # Total bids check
    assert len(bids) == 1000, f"Expected 1000 bids, got {len(bids)}"

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(bids, f, indent=2)

    print(f"Successfully generated {len(bids)} synthetic GeM-style bids at: {output_path}")
    return len(bids)

if __name__ == "__main__":
    generate_synthetic_dataset()
