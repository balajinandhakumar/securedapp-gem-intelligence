# Dashboard & Bid Reporting

## Principle

Every figure rendered by the command center comes from the database. The
frontend performs no scoring, no keyword guessing and no fallback substitution.
If the backend reports zero, the dashboard shows zero; if a bid has never been
analyzed, the dashboard says so instead of estimating a score.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/dashboard/summary` | Command-strip metrics plus the priority, recent, action-required and activity work queues. Read-only. |
| `GET` | `/api/v1/bids/intelligence` | Every stored bid joined with its latest persisted analysis state. |
| `GET` | `/api/v1/bids` | Every stored bid, newest-updated first. |

Both reporting endpoints are read-only. They never trigger analysis and never
write. Analysis is produced only by `POST /api/v1/bids/{id}/analyze`,
`POST /api/v1/bids/{id}/match-products`, or the ingestion batch pipeline.

## Dashboard summary shape

```jsonc
{
  "metrics": {
    "total_bids": 0,            // count(bids)
    "analyzed_bids": 0,         // bids with a stored BidScore
    "pending_analysis": 0,      // total_bids - analyzed_bids
    "relevant_bids": 0,         // analyzed, relevance_score >= 0.70
    "possible_match_bids": 0,   // 0.45 <= relevance_score < 0.70
    "needs_review_bids": 0,     // 0.25 <= relevance_score < 0.45
    "closing_soon_bids": 0,     // 0 <= days_remaining <= closing_soon_window_days
    "closing_soon_window_days": 7,
    "notifications": 0          // count(notifications)
  },
  "priority_opportunities": [], // top analyzed bids at relevance >= 0.70
  "recent_bids": [],            // newest published bids, any analysis state
  "action_required": [],        // bids inside the submission window
  "recent_activity": []         // most recent Notification rows
}
```

### Analysis state on a row

Every bid row carries the same fields, whether or not it has been analyzed:

| Field | Analyzed bid | Unanalyzed bid |
| --- | --- | --- |
| `analyzed` | `true` | `false` |
| `relevance_score` | stored value, rounded to 3dp | `null` |
| `opportunity_score` | stored value, rounded to 3dp | `null` |
| `relevance_label` | stored label | `null` |
| `urgency` | stored urgency | `null` |
| `matched_product` | best product from the stored score breakdown | `null` |
| `match_state` | `MATCH` / `POSSIBLE_MATCH` / `NEEDS_REVIEW` / `NO_MATCH` | `null` |
| `days_remaining` | derived from `closing_date` | derived from `closing_date` |
| `deadline_status` | `OPEN` / `CLOSING_SOON` / `URGENT` / `CLOSED` / `UNKNOWN` | same |

`null` is meaningful: it means the analysis pipeline has not produced a value
for that bid. The UI renders it as "Not yet analyzed" and never as a number.

## Relevance bands

The bands are the canonical thresholds from the deterministic engine, defined
once in `app/services/intelligence/matching_engine.py` and reused by the
reporting layer:

| Band | Condition |
| --- | --- |
| `MATCH` | `relevance_score >= 0.70` |
| `POSSIBLE_MATCH` | `0.45 <= relevance_score < 0.70` |
| `NEEDS_REVIEW` | `0.25 <= relevance_score < 0.45` |
| `NO_MATCH` | `relevance_score < 0.25` |

## Deadline bands

Derived from `closing_date`; a bid with no closing date is `UNKNOWN` rather
than being treated as open:

| Status | Condition |
| --- | --- |
| `CLOSED` | `days_remaining < 0` |
| `CLOSING_SOON` | `0 <= days_remaining <= 3` |
| `URGENT` | `3 < days_remaining <= 7` |
| `OPEN` | `days_remaining > 7` |
| `UNKNOWN` | no closing date supplied |

## No fixed row cap

Neither reporting endpoint applies a hardcoded maximum. `total_bids` reflects
the full `bids` table and the bid feed returns every row, so a deployment that
ingests more bids grows rather than silently truncating. Bounded tables
(`priority_opportunities`, `recent_bids`, `action_required`, `recent_activity`)
are work queues and are intentionally limited to what fits on screen; the
authoritative totals are always in `metrics`.

## External data source

The live GeM connector is not implemented. The dashboard reports only data
already ingested through the file/export ingestion path. The navigation bar
states this as `GeM Source: Awaiting Authorized API` rather than implying a
live connection.
