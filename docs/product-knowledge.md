# Product Knowledge Base Architecture

## Principles
1. **Database-Sourced Knowledge**: Product capabilities, keywords, positive matching signals, and exclusion filters live in relational models and are managed at runtime through the Product Management API. The matching engine never contains product knowledge in code.
2. **Idempotent Bootstrap**: A single source of truth, `backend/app/db/seed_knowledge.py` (`PRODUCTS_KNOWLEDGE`), defines the 11 official SecuredApp products and their baseline knowledge vectors.
3. **Non-Destructive Seeding**: `bootstrap_product_knowledge()` is called on startup. It creates missing products, backfills products that have no knowledge vector yet, and leaves any product that already has one completely untouched — so edits made through the API survive redeployments. `seed_product_knowledge()` is a deliberate force-reseed used only by tests and local tooling.

## Seeded Products List
1. `SolidityShield`
2. `SecureCMS`
3. `SecureTrace`
4. `CookieHub`
5. `PQCSuite`
6. `SecureX-DID`
7. `SecureWatch`
8. `AuditExpress`
9. `SecurePad`
10. `SecureX-ID`
11. `QuantumVault`

## Knowledge Schema Structure

```
Product
  ├── Capabilities (name, description, weight 0.1-10, active)
  ├── Keywords (keyword, type: positive_signal/keyword/synonym/technology/exclusion, weight -10..10, active)
  ├── Technologies (technology stack items)
  └── Categories (GeM product/service category codes)
```

Negative weights are accepted only for `exclusion` signals, which is how closely related products are kept apart during matching.

## Product Management API

All endpoints live under `/api/v1/products`.

| Method | Path | Behaviour |
| --- | --- | --- |
| `GET` | `/api/v1/products` | Lists products. Optional `active` boolean filter, `search` over name/description, `skip`, and `limit`. |
| `GET` | `/api/v1/products/{id}` | Returns one product with its full knowledge vector. |
| `POST` | `/api/v1/products` | Creates a product, optionally with nested capabilities, keywords, technologies and categories in one request. |
| `PUT` | `/api/v1/products/{id}` | Partial update. Omitted fields are untouched; supplying a knowledge collection (including an empty list) replaces that stored collection. |
| `DELETE` | `/api/v1/products/{id}` | Soft delete: marks the product inactive. It stops participating in future matching but stays readable for historical bid analysis. |
| `DELETE` | `/api/v1/products/{id}?hard=true` | Permanent delete. Refused with `409` if any `bid_product_matches` row or any stored `bid_analysis` snapshot references the product. |
| `POST` | `/api/v1/products/{id}/capabilities` | Appends a single capability. |
| `POST` | `/api/v1/products/{id}/keywords` | Appends a single keyword or signal. |
| `POST` | `/api/v1/products/{id}/technologies` | Appends a single technology. |
| `POST` | `/api/v1/products/{id}/categories` | Appends a single category. |

Duplicate names are rejected with `409`. Blank names, out-of-range weights, negative weights on non-exclusion signals, and priorities outside `0-100` are rejected with `422`.

## Effect of Deactivation

Only products with `active = true` are considered by `match_bid_against_products`. A deactivated product is excluded from all future matching runs; its stored knowledge and all historical bid analysis records remain intact and are still returned by `GET /api/v1/products/{id}`. Products can be reactivated at any time with `PUT {"active": true}`.
