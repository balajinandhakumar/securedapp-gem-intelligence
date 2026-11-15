# Database Schema Documentation

## Database Entities

### 1. `users`
Tracks system users and authentication identifiers.
- `id`: UUID (Primary Key)
- `email`: VARCHAR(255) (Unique, Indexed)
- `name`: VARCHAR(255)
- `password_hash`: VARCHAR(255)
- `role`: VARCHAR(50) (admin, reviewer, viewer)
- `active`: BOOLEAN (Default: True)
- `created_at`, `updated_at`: TIMESTAMP WITH TIME ZONE

### 2. `products`
SecuredApp product catalog.
- `id`: UUID (Primary Key)
- `name`: VARCHAR(100) (Unique, Indexed)
- `description`: TEXT (Nullable)
- `active`: BOOLEAN (Default: True)
- `priority`: INTEGER (Default: 0)
- `created_at`, `updated_at`: TIMESTAMP WITH TIME ZONE

### 3. `product_capabilities`
Specific functional capabilities offered by a product.
- `id`: UUID (Primary Key)
- `product_id`: UUID (Foreign Key → `products.id`)
- `name`: VARCHAR(255)
- `description`: TEXT
- `weight`: FLOAT (Default: 1.0)
- `active`: BOOLEAN (Default: True)

### 4. `product_keywords`
Keyword signals and exclusions associated with products.
- `id`: UUID (Primary Key)
- `product_id`: UUID (Foreign Key → `products.id`)
- `keyword`: VARCHAR(255) (Indexed)
- `weight`: FLOAT (Default: 1.0)
- `type`: VARCHAR(50) (keyword, synonym, technology, positive_signal, exclusion)
- `active`: BOOLEAN (Default: True)

### 5. `product_technologies`
Supported tech stacks or tech platforms for products.
- `id`: UUID (Primary Key)
- `product_id`: UUID (Foreign Key → `products.id`)
- `technology`: VARCHAR(100)

### 6. `product_categories`
GeM or industry categories mapped to products.
- `id`: UUID (Primary Key)
- `product_id`: UUID (Foreign Key → `products.id`)
- `category`: VARCHAR(255)

### 7. `bids`
Normalized tender data.
- `id`: UUID (Primary Key)
- `gem_bid_id`: VARCHAR(100) (Indexed)
- `bid_number`: VARCHAR(100) (Indexed)
- `title`: TEXT
- `organisation`: VARCHAR(255)
- `department`: VARCHAR(255)
- `ministry`: VARCHAR(255)
- `category`: VARCHAR(255)
- `bid_type`: VARCHAR(100)
- `published_date`: TIMESTAMP WITH TIME ZONE
- `closing_date`: TIMESTAMP WITH TIME ZONE
- `location`: VARCHAR(255)
- `estimated_value`: NUMERIC(15, 2)
- `currency`: VARCHAR(10) (Default: 'INR')
- `scope_of_work`: TEXT
- `technical_requirements`: JSONB
- `eligibility_criteria`: JSONB
- `qualification_requirements`: JSONB
- `experience_requirements`: JSONB
- `certification_requirements`: JSONB
- `emd_information`: JSONB
- `tender_fee_information`: JSONB
- `contact_information`: JSONB
- `source_url`: TEXT
- `content_hash`: VARCHAR(64) (Indexed)
- `status`: VARCHAR(50) (NEW, PROCESSED, ARCHIVED, EXPIRED)
- `first_discovered_at`: TIMESTAMP WITH TIME ZONE
- `last_updated_at`: TIMESTAMP WITH TIME ZONE

### 8. `raw_bid_payloads`
Original raw input payloads before normalization.
- `id`: UUID (Primary Key)
- `collection_run_id`: UUID (Foreign Key → `collection_runs.id`)
- `raw_content`: JSONB
- `source_reference`: VARCHAR(255)
- `checksum`: VARCHAR(64)
- `ingested_at`: TIMESTAMP WITH TIME ZONE

### 9. `collection_runs`
Tracks ingestion job execution and metrics.
- `id`: UUID (Primary Key)
- `source_adapter`: VARCHAR(100)
- `started_at`, `finished_at`: TIMESTAMP WITH TIME ZONE
- `status`: VARCHAR(50) (SUCCESS, FAILED, PARTIAL)
- `records_found`, `records_new`, `records_duplicate`, `error_count`: INTEGER
- `notes`: TEXT

### 10. `bid_analysis`
Stores raw AI/ML evaluation outputs.
- `id`: UUID (Primary Key)
- `bid_id`: UUID (Foreign Key → `bids.id`)
- `engine_version`: VARCHAR(50)
- `model_used`: VARCHAR(100)
- `keyword_results`, `semantic_results`, `product_matches`, `eligibility_analysis`, `concerns`, `evidence`, `llm_output`: JSONB
- `analyzed_at`: TIMESTAMP WITH TIME ZONE

### 11. `bid_scores`
Calculated scores and label evaluations.
- `id`: UUID (Primary Key)
- `bid_id`: UUID (Foreign Key → `bids.id`)
- `analysis_id`: UUID (Foreign Key → `bid_analysis.id`)
- `relevance_score`: FLOAT
- `opportunity_score`: FLOAT
- `relevance_label`: VARCHAR(50)
- `urgency`: VARCHAR(50)
- `score_breakdown`: JSONB
- `created_at`: TIMESTAMP WITH TIME ZONE

### 12. `bid_product_matches`
Direct bid-to-product mapping scores and evidence.
- `id`: UUID (Primary Key)
- `bid_id`: UUID (Foreign Key → `bids.id`)
- `product_id`: UUID (Foreign Key → `products.id`)
- `match_score`: FLOAT
- `match_type`: VARCHAR(50)
- `evidence`: JSONB
- `confidence`: FLOAT

### 13. `human_reviews`
Decisions made by team reviewers.
- `id`: UUID (Primary Key)
- `bid_id`: UUID (Foreign Key → `bids.id`)
- `reviewer_id`: UUID (Foreign Key → `users.id`)
- `relevance_decision`: VARCHAR(50) (RELEVANT, NOT_RELEVANT, MAYBE)
- `pursue_decision`: VARCHAR(50) (PURSUE, DONT_PURSUE, PENDING)
- `comments`: TEXT
- `reviewed_at`: TIMESTAMP WITH TIME ZONE

### 14. `notifications`
Audit log of alerts sent via email/messaging.
- `id`: UUID (Primary Key)
- `bid_id`: UUID (Foreign Key → `bids.id`)
- `channel`: VARCHAR(50)
- `recipient`: VARCHAR(255)
- `notification_type`: VARCHAR(50)
- `deduplication_key`: VARCHAR(255)
- `status`: VARCHAR(50)
- `sent_at`: TIMESTAMP WITH TIME ZONE

### 15. `audit_logs`
System security and administrative audit trail.
- `id`: UUID (Primary Key)
- `entity_type`: VARCHAR(100)
- `entity_id`: UUID
- `action`: VARCHAR(100)
- `actor`: VARCHAR(255)
- `metadata`: JSONB
- `created_at`: TIMESTAMP WITH TIME ZONE

### 16. `bid_status_history`
Lifecycle state changes of bids.
- `id`: UUID (Primary Key)
- `bid_id`: UUID (Foreign Key → `bids.id`)
- `old_status`, `new_status`: VARCHAR(50)
- `changed_by`: VARCHAR(255)
- `reason`: TEXT
- `created_at`: TIMESTAMP WITH TIME ZONE
