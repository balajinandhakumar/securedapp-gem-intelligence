# System Architecture - SecuredApp GeM Bid Intelligence Platform

## Overview
The SecuredApp GeM Bid Intelligence Platform is designed as a modular monolith to discover, parse, normalize, and evaluate Government e-Marketplace (GeM) tender opportunities for SecuredApp products and services.

## High-Level Architecture Diagram

```
                ┌────────────────────────┐
                │ GeM / Approved Source  │
                └────────────┬───────────┘
                             │
                             ▼
                ┌────────────────────────┐
                │ Bid Acquisition Layer  │
                │                         │
                │ CSV/XLSX/JSON          │
                │ Approved API            │
                │ Future GeM adapter      │
                └────────────┬───────────┘
                             │
                             ▼
                ┌────────────────────────┐
                │ Ingestion & Parsing     │
                └────────────┬───────────┘
                             │
                             ▼
                ┌────────────────────────┐
                │ Normalization           │
                └────────────┬───────────┘
                             │
                             ▼
                ┌────────────────────────┐
                │ Duplicate Detection     │
                │ Change Detection        │
                └────────────┬───────────┘
                             │
                             ▼
         ┌────────────────────────────────────────┐
         │       BID INTELLIGENCE ENGINE          │
         │                                        │
         │  1. Hard filters                       │
         │  2. Keyword/rule matching              │
         │  3. Semantic matching                  │
         │  4. Product/capability matching        │
         │  5. Eligibility analysis               │
         │  6. Deadline/urgency analysis          │
         │  7. Risk detection                     │
         │  8. LLM-assisted reasoning             │
         └────────────────────┬───────────────────┘
                              │
                              ▼
                ┌────────────────────────┐
                │ Opportunity Analysis   │
                │ Score + Explanation    │
                └────────────┬───────────┘
                             │
                 ┌───────────┴───────────┐
                 ▼                       ▼
         ┌───────────────┐       ┌───────────────┐
         │   Dashboard   │       │ Notifications │
         └───────────────┘       └───────┬───────┘
                                         │
                                  Email / WhatsApp
                                         │
                                         ▼
                                 Human Review
                                         │
                                         ▼
                                  Feedback Data
                                         │
                                         ▼
                              Evaluation / Improvement
```

## Architectural Principles
1. **Modular Monolith**: Clean separation between data ingestion, product knowledge base, intelligence engine, API endpoints, and notifications.
2. **Decoupled Acquisition Layer**: Ingestion layer accepts normalized Bid payloads regardless of source (CSV, XLSX, JSON, API).
3. **Configurable Knowledge Base**: Product capabilities, keywords, and exclusion criteria are stored in relational models—never hard-coded.
4. **Explainable AI**: Every surfaced opportunity must provide exact textual evidence and reasoning behind product matches and eligibility concerns.
5. **Human-in-the-Loop**: The platform assists decision-making; final bidding choices rest with human reviewers.
