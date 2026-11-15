/** Navigation destinations of the app shell (icon rail + top bar). */
export type AppTab =
  | 'dashboard'
  | 'bids'
  | 'closing-soon'
  | 'recent'
  | 'products'
  | 'ingestion'
  | 'notifications'
  | 'state-tenders'
  | 'state-wise-bids'
  | 'all-india-matches'
  | 'scraper-monitoring';

export interface BoqItem {
  item_number?: string | null;
  title?: string | null;
  description?: string | null;
  quantity?: string | number | null;
  unit?: string | null;
  consignee_id?: string | null;
  delivery_period?: string | null;
  [key: string]: unknown;
}

/**
 * Persisted Bill-of-Quantities evidence (`Bid.boq_items`). Present only on the
 * per-bid detail response, never on the list feed. `source_url` / `retrieved_at`
 * are the provenance of the parsed line items.
 */
export interface BoqEvidence {
  items: BoqItem[];
  item_count: number;
  source_url?: string | null;
  retrieved_at?: string | null;
}

export interface Bid {
  id: string;
  gem_bid_id: string | null;
  bid_number: string | null;
  title: string;
  organisation: string | null;
  department: string | null;
  ministry: string | null;
  category: string | null;
  bid_type: string | null;
  published_date: string | null;
  closing_date: string | null;
  location: string | null;
  estimated_value: number | null;
  currency: string;
  scope_of_work: string | null;
  technical_requirements: any;
  eligibility_criteria: any;
  qualification_requirements: any;
  experience_requirements: any;
  certification_requirements: any;
  emd_information: any;
  tender_fee_information: any;
  contact_information: any;
  source_url: string | null;
  original_bid_url: string | null;
  status: string;
  content_hash?: string;
  first_discovered_at?: string;
  last_updated_at?: string;
  boq_items?: BoqEvidence | null;
  boq_checked_at?: string | null;
}

export interface SignalItem {
  type: string;
  text: string;
  field: string;
  strength: string;
  snippet?: string;
}

export interface ProductMatch {
  product_id: string;
  product_name: string;
  match_state: 'MATCH' | 'POSSIBLE_MATCH' | 'NEEDS_REVIEW' | 'NO_MATCH';
  relevance_score: number;
  final_relevance_score: number;
  confidence: number;
  signals: SignalItem[];
  score_breakdown: {
    field_scores?: Record<string, number>;
    signal_scores?: string[];
    positive_adjustments?: number;
    negative_exclusion_adjustments?: number;
    raw_score?: number;
    normalized_score?: number;
    final_relevance_score?: number;
    classification?: string;
    confidence?: number;
    reason?: string;
  };
  reason: string;
}

export interface RequirementEvidence {
  finding: string;
  evidence: string;
  field: string;
  status: string;
}

export interface BidRequirement {
  category: string;
  requirement_text: string;
  evidence: RequirementEvidence;
  is_mandatory: boolean;
}

export interface EligibilityAssessment {
  requirement_name: string;
  status: 'CONFIRMED' | 'UNKNOWN' | 'REQUIRES_HUMAN_VERIFICATION' | 'POTENTIAL_CONFLICT';
  evidence_snippet: string;
  reason: string;
  requires_human: boolean;
}

export interface RiskIndicator {
  risk_type: string;
  severity: 'HIGH' | 'MEDIUM' | 'LOW';
  description: string;
  evidence_snippet: string | null;
}

export interface ProductReasoning {
  product_name: string;
  matched: boolean;
  confidence: number;
  relevance_score: number;
  match_state: string;
  signals: SignalItem[];
  reason: string;
}

export interface IntelligenceData {
  bid_id: string;
  bid_title: string;
  analysis_version: string;
  analyzed_at: string;
  deadline_intelligence: {
    published_date?: string;
    closing_date?: string;
    days_remaining?: number;
    status: 'NORMAL' | 'UPCOMING' | 'URGENT' | 'CLOSING_SOON' | 'CLOSED' | 'UNKNOWN';
  };
  requirements: BidRequirement[];
  eligibility_assessments: EligibilityAssessment[];
  risk_indicators: RiskIndicator[];
  product_reasoning: ProductReasoning[];
  missing_information: string[];
  human_verification_needed: boolean;
}

export interface ComponentScore {
  name: string;
  weight: number;
  raw_value: number;
  weighted_score: number;
  description: string;
}

export interface OpportunityData {
  bid_id: string;
  bid_title: string;
  relevance_score: number;
  opportunity_score: number;
  opportunity_label: 'HIGH_OPPORTUNITY' | 'MEDIUM_OPPORTUNITY' | 'LOW_OPPORTUNITY' | 'UNMATCHED';
  urgency_label: string;
  score_breakdown: ComponentScore[];
  missing_information: string[];
  reason: string;
}

export interface AnalysisData {
  bid_id: string;
  bid_title: string;
  intelligence?: IntelligenceData;
  opportunity?: OpportunityData;
  candidate_products?: ProductMatch[];
}

export interface HumanReview {
  id: string;
  bid_id: string;
  reviewer_id?: string;
  relevance_decision: 'RELEVANT' | 'NOT_RELEVANT' | 'MAYBE';
  pursue_decision?: string;
  comments: string | null;
  reviewed_at: string;
}

export interface NotificationItem {
  id: string;
  bid_id: string;
  channel: string;
  recipient: string;
  notification_type: string;
  deduplication_key: string;
  status: string;
  sent_at?: string | null;
  /** Derived delivery state: QUEUED | DELIVERED | FAILED. */
  delivery_state?: string;
  /** Whether an external delivery provider is configured in this deployment. */
  delivery_configured?: boolean;
  delivery_note?: string;
}

export interface EvaluationMetrics {
  total_evaluated_reviews: number;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  true_negatives: number;
  precision: number;
  recall: number;
  agreement_rate: number;
  message?: string;
}

export interface ProductCapability {
  id: string;
  name: string;
  description?: string;
  weight: number;
  active: boolean;
}

export interface ProductKeyword {
  id: string;
  keyword: string;
  weight: number;
  type: string;
  active: boolean;
}

export interface ProductTechnology {
  id: string;
  technology: string;
}

export interface ProductCategory {
  id: string;
  category: string;
}

export interface Product {
  id: string;
  name: string;
  description: string | null;
  active: boolean;
  priority: number;
  capabilities: ProductCapability[];
  keywords: ProductKeyword[];
  technologies: ProductTechnology[];
  categories: ProductCategory[];
}

/* -------------------------------------------------------------------------- */
/* Product catalogue matching stats                                           */
/* Populated by joining bids with their BidProductMatch records.              */
/* -------------------------------------------------------------------------- */

export interface ProductMatchingStats {
  product_id: string;
  product_name: string;
  matching_tenders: number;      // distinct tenders with at least one match
  total_matches: number;         // total (tender, product) match rows
  highest_relevance_score: number | null;  // 0-1 normalized
  highest_classification: string | null;   // MATCH / POSSIBLE_MATCH / NEEDS_REVIEW
  matched_states: string[];      // distinct state/location names
  matched_departments: string[]; // distinct departments
  matched_organisations: string[]; // distinct organisations
}

export interface ProductCatalogueSummary {
  total_products: number;
  active_products: number;
  total_categories: number;
  products_with_matches: number;
  total_matching_tenders: number;
  product_stats: ProductMatchingStats[];
}

/* -------------------------------------------------------------------------- */
/* Product detail view                                                        */
/* -------------------------------------------------------------------------- */

export interface ProductDetailView {
  product: Product;
  matching_stats: ProductMatchingStats | null;
  matching_tenders: ProductMatchTender[];
}

export interface ProductMatchTender {
  bid_id: string;
  tender_id: string | null;
  title: string;
  state: string;
  department: string | null;
  organisation: string | null;
  closing_date: string | null;
  estimated_value: number | null;
  relevance_score: number;
  match_classification: string;
  explanation: string;
  source_url: string | null;
}

export interface IngestionRun {
  id: string;
  source_adapter: string;
  started_at: string;
  finished_at?: string;
  status: string;
  records_found: number;
  records_new: number;
  records_duplicate: number;
  error_count: number;
  notes?: string;
}

/* -------------------------------------------------------------------------- */
/* Dashboard summary (GET /api/v1/dashboard/summary)                          */
/* Every numeric field below is produced by the backend from persisted data.    */
/* Nullable score fields stay null for bids that have not been analyzed.        */
/* -------------------------------------------------------------------------- */

export type MatchState = 'MATCH' | 'POSSIBLE_MATCH' | 'NEEDS_REVIEW' | 'NO_MATCH' | 'UNMATCHED';

export type DeadlineStatus = 'CLOSING_SOON' | 'URGENT' | 'OPEN' | 'CLOSED' | 'UNKNOWN';

export interface DashboardBidRow {
  id: string;
  gem_bid_id: string | null;
  bid_number: string | null;
  title: string;
  organisation: string | null;
  category: string | null;
  status: string;
  published_date: string | null;
  closing_date: string | null;
  last_updated_at: string | null;
  days_remaining: number | null;
  deadline_status: DeadlineStatus;
  estimated_value: number | null;
  currency: string;
  analyzed: boolean;
  relevance_score: number | null;
  relevance_label: string | null;
  opportunity_score: number | null;
  matched_product: string | null;
  match_state: MatchState | null;
}

export interface DashboardActivity {
  id: string;
  bid_id: string | null;
  bid_title: string | null;
  notification_type: string;
  channel: string;
  status: string;
  recipient: string;
}

export interface DashboardMetrics {
  /** Open / active bids only (closing_date is null or in the future). This is
   *  NOT the total number of bids in the database — closed bids are excluded. */
  total_bids: number;
  /** Bids whose submission deadline has passed. */
  closed_bids: number;
  analyzed_bids: number;
  pending_analysis: number;
  relevant_bids: number;
  possible_match_bids: number;
  needs_review_bids: number;
  closing_soon_bids: number;
  closing_soon_window_days: number;
  notifications: number;
}

export interface DashboardSummary {
  metrics: DashboardMetrics;
  priority_opportunities: DashboardBidRow[];
  possible_matches: DashboardBidRow[];
  recent_bids: DashboardBidRow[];
  action_required: DashboardBidRow[];
  recent_activity: DashboardActivity[];
}

/**
 * One row of `GET /api/v1/bids/intelligence`: a stored bid plus the analysis
 * state the backend actually persisted for it. Unanalyzed bids keep null scores.
 */
export interface BidIntelligenceRow extends DashboardBidRow {
  department: string | null;
  location: string | null;
  scope_of_work: string | null;
  urgency: string | null;
  source_url: string | null;
  original_bid_url: string | null;
}

export interface BidIntelligenceFeed {
  total: number;
  bids: BidIntelligenceRow[];
}

/* -------------------------------------------------------------------------- */
/* State-wise bids (GET /api/v1/bids/state-wise)                              */
/* Each row is one (bid, product_match) combination. A bid matching multiple  */
/* products appears once per matched product.                                 */
/* -------------------------------------------------------------------------- */

export interface StateWiseProductMatch {
  product_id: string;
  product_name: string;
  match_score: number;
  match_type: string | null;
  confidence: number | null;
  evidence: Record<string, unknown> | null;
  matching_keywords: string[];
}

export interface StateWiseBidRow {
  id: string;
  state: string;
  state_id: string;
  source: string;
  source_id: string;
  adapter_key: string;
  bid_number: string | null;
  gem_bid_id: string | null;
  tender_id: string | null;
  title: string;
  organisation: string | null;
  department: string | null;
  matched_product: string | null;
  match_state: string | null;
  relevance_score: number | null;
  analyzed: boolean;
  estimated_value: number | null;
  currency: string;
  published_date: string | null;
  closing_date: string | null;
  days_remaining: number | null;
  deadline_status: string;
  status: string;
  matching_status: string | null;
  matched_at: string | null;
  source_url: string | null;
  original_bid_url: string | null;
  product_matches: StateWiseProductMatch[];
  matched_product_count: number;
}

export interface StateWiseBidsResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  bids: StateWiseBidRow[];
}

/* -------------------------------------------------------------------------- */
/* All-India product-relevant bid matching dashboard (GET /api/v1/dashboard/all-india/*) */
/* Every figure below is derived from persisted bid-to-product matches only.   */
/* -------------------------------------------------------------------------- */

export type AllIndiaClassification =
  | 'Highly Relevant'
  | 'Relevant'
  | 'Potentially Relevant'
  | 'Not Relevant';

export interface AllIndiaMatchRow {
  bid_id: string;
  gem_bid_id: string | null;
  bid_number: string | null;
  tender_id: string | null;
  title: string;
  location: string;        // bid location, or 'Location Not Disclosed by Source'
  state: string;           // normalized state or same as location for filtering
  city: string | null;     // city/district component when available
  location_quality: string; // 'AVAILABLE' | 'NOT_DISCLOSED' | 'EXTRACTION_FAILED'
  department: string | null;
  organisation: string | null;
  procuring_authority: string | null;
  estimated_value: number | null;
  currency: string;
  published_date: string | null;
  closing_date: string | null;
  days_remaining: number | null;
  product_id: string;
  product_name: string;
  relevance_score_100: number;   // 0-100
  classification: AllIndiaClassification;
  match_state: string | null;
  confidence: number;
  matching_keywords: string[];
  explanation: string;
  technical_requirements: string;
  source_url: string | null;
  original_bid_url: string | null;
  score_breakdown: Record<string, unknown>;
}

export interface AllIndiaBidsResponse {
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
  min_score: number;
  bids: AllIndiaMatchRow[];
}

export interface AllIndiaStateBucket {
  location: string;
  bid_count: number;
  highly_relevant: number;
  relevant: number;
  potentially_relevant: number;
}

export interface AllIndiaProductBucket {
  product_name: string;
  bid_count: number;
}

export interface AllIndiaSummary {
  total_bids: number;
  total_relevant_bids: number;
  highly_relevant_bids: number;
  relevant_bids: number;
  potentially_relevant_bids: number;
  states_covered: number;
  products_with_matches: number;
  location_qualities?: { AVAILABLE: number; NOT_DISCLOSED: number; EXTRACTION_FAILED: number };
  state_distribution: AllIndiaStateBucket[];
  product_distribution: AllIndiaProductBucket[];
}

/* -------------------------------------------------------------------------- */
/* Product management payloads                                                 */
/* -------------------------------------------------------------------------- */

/** The only product fields the simplified Products page submits. */
export interface ProductCreatePayload {
  name: string;
  description?: string | null;
}

export interface ProductKeywordPayload {
  keyword: string;
  weight?: number;
  type?: string;
  active?: boolean;
}

export interface ApiError {
  detail: string;
}

/* -------------------------------------------------------------------------- */
/* Authentication types (Phase 5.1 — Backend auth integration)                */
/* Contract: PHASE_5_0_AUTH_API_CONTRACT.md                                   */
/* -------------------------------------------------------------------------- */

export type UserRole = 'admin' | 'operator' | 'viewer';

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  active: boolean;
}

export interface AuthTokens {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number; // seconds
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: AuthUser;
}

export interface RefreshRequest {
  refresh_token: string;
}

export interface RefreshResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

/**
 * Role-based capability matrix from the verified backend contract.
 * Frontend permissions improve UX; backend authorization remains the boundary.
 */
export const ROLE_CAPABILITIES: Record<UserRole, {
  canRead: boolean;
  canWriteProducts: boolean;
  canManageSources: boolean;
  canManageUsers: boolean;
  canRunMatching: boolean;
}> = {
  admin: {
    canRead: true,
    canWriteProducts: true,
    canManageSources: true,
    canManageUsers: true,
    canRunMatching: true,
  },
  operator: {
    canRead: true,
    canWriteProducts: true,
    canManageSources: true,
    canManageUsers: false,
    canRunMatching: true,
  },
  viewer: {
    canRead: true,
    canWriteProducts: false,
    canManageSources: false,
    canManageUsers: false,
    canRunMatching: false,
  },
};

/**
 * Returns true when the given role is permitted to perform a write action
 * (create/update/delete) on products.
 */
export function canWriteProducts(role: UserRole | null): boolean {
  if (!role) return false;
  return ROLE_CAPABILITIES[role].canWriteProducts;
}

/**
 * Returns true when the given role is permitted to manage data sources.
 */
export function canManageSources(role: UserRole | null): boolean {
  if (!role) return false;
  return ROLE_CAPABILITIES[role].canManageSources;
}

/**
 * Returns true when the given role is permitted to manage users.
 */
export function canManageUsers(role: UserRole | null): boolean {
  if (!role) return false;
  return ROLE_CAPABILITIES[role].canManageUsers;
}

/**
 * Returns true when the given role is permitted to run matching.
 */
export function canRunMatching(role: UserRole | null): boolean {
  if (!role) return false;
  return ROLE_CAPABILITIES[role].canRunMatching;
}

/* -------------------------------------------------------------------------- */
/* Configurable data-source registry (GET /api/v1/sources/*)                  */
/* The SDK of the multi-source engine: adapter catalog, configured sources,    */
/* and per-source collection runs. Configs arrive sanitized (secrets masked,   */
/* auth refs referenced by env-var name only) and are never re-displayed.      */
/* -------------------------------------------------------------------------- */

export type SourceStatus =
  | 'IDLE'
  | 'RUNNING'
  | 'SUCCESS'
  | 'ERROR'
  | 'CONFIG_ERROR'
  | 'NEEDS_ATTENTION'
  | 'BLOCKED'
  | 'PARTIAL'
  | 'FAILED'
  | 'NO_RECORDS'
  | 'SKIPPED'
  | 'BUSY'
  | 'PREVIEW'
  | 'NOT_CONFIGURED';

export interface AdapterMeta {
  adapter_key: string;
  adapter_label: string;
  source_types: string[];
  method: string;
  requires_credentials: boolean;
  requires_browser: boolean;
  integration_note: string;
}

export interface SourcesMeta {
  adapters: AdapterMeta[];
  scheduler: {
    enabled: boolean;
    note: string;
  };
}

export interface ConfiguredSource {
  id: string;
  source_id: string;
  name: string;
  base_url: string | null;
  source_type: string;
  adapter_key: string;
  adapter_label: string;
  enabled: boolean;
  collection_interval_minutes: number;
  config: Record<string, unknown>;
  notes: string | null;
  status: SourceStatus;
  last_attempt_at: string | null;
  last_success_at: string | null;
  last_error: string | null;
  last_discovered: number;
  last_validated: number;
  last_rejected: number;
  last_inserted: number;
  last_updated: number;
  last_duplicates: number;
  total_runs: number;
  total_inserted: number;
  total_updated: number;
  total_duplicates: number;
  total_rejected: number;
  has_credentials: boolean;
  next_run_at: string | null;
}

export interface SourceRunRow {
  id: string;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  status: string;
  pages_visited: number;
  discovered: number;
  validated: number;
  rejected: number;
  inserted: number;
  updated: number;
  duplicates: number;
  errors: Array<{ field: string; message: string }>;
  notes: string | null;
}

export interface SourceSyncResult {
  run_id: string | null;
  source_id: string;
  source_name: string;
  source_type: string;
  adapter_key: string;
  status: SourceStatus;
  trigger: string;
  preview: boolean;
  message: string;
  pages_visited: number;
  discovered: number;
  validated: number;
  rejected: number;
  inserted: number;
  updated: number;
  duplicates: number;
  errors: Array<{ field: string; message: string }>;
  duration_seconds: number;
}

export interface SourceCreatePayload {
  source_id: string;
  name: string;
  base_url?: string | null;
  source_type: string;
  adapter_key?: string | null;
  config: Record<string, unknown>;
  enabled?: boolean;
  collection_interval_minutes?: number;
  notes?: string | null;
}

export interface SourceUpdatePayload {
  name?: string | null;
  base_url?: string | null;
  source_type?: string | null;
  adapter_key?: string | null;
  config?: Record<string, unknown> | null;
  enabled?: boolean | null;
  collection_interval_minutes?: number | null;
  notes?: string | null;
}
