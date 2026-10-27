"""
Batch processing runner and performance benchmark script for Stage 2.
Loads the synthetic 1,000-bid dataset, runs the end-to-end intelligence pipeline,
and reports comprehensive verification metrics.
"""
import json
import os
import sys
import time

# Ensure backend directory is in python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from app.core.database import SessionLocal, engine
from app.db.seed_knowledge import seed_product_knowledge
from app.models.analysis import BidAnalysis, BidScore
from app.models.bid import Bid
from app.models.notification import Notification
from app.models.review import HumanReview
from app.services.intelligence.batch_processor import run_batch_intelligence_pipeline

def run_benchmark(dataset_path: str = "data/sample_bids/synthetic_1000_bids.json"):
    print("=" * 70)
    print("STAGE 2: GeM BID INTELLIGENCE BATCH PROCESSING BENCHMARK")
    print("=" * 70)

    if not os.path.exists(dataset_path):
        print(f"Dataset not found at {dataset_path}, generating...")
        from app.scripts.generate_synthetic_bids import generate_synthetic_dataset
        generate_synthetic_dataset(dataset_path)

    with open(dataset_path, "r", encoding="utf-8") as f:
        raw_json_str = f.read()

    db = SessionLocal()
    try:
        # Ensure knowledge base is seeded
        seed_product_knowledge(db)

        print(f"Loaded synthetic dataset: {dataset_path}")
        print(f"Starting batch intelligence pipeline execution...")
        start_time = time.perf_counter()

        summary = run_batch_intelligence_pipeline(
            db=db,
            file_content=raw_json_str,
            file_type="json",
            source_name="synthetic_gem_dev_dataset",
            allow_update_duplicates=True,
            auto_notify=True,
        )

        total_time = time.perf_counter() - start_time

        print("\n" + "-" * 70)
        print("STAGE 2 BATCH PIPELINE EXECUTION RESULTS")
        print("-" * 70)
        print(f"Total Input Bids:          {summary.total_input_bids}")
        print(f"Successfully Processed:    {summary.successfully_processed}")
        print(f"Rejected / Failed:         {summary.rejected}")
        print(f"Duplicates Detected:       {summary.duplicates}")
        print(f"Updated Records:           {summary.updated_records}")
        print(f"Relevant Matches (>=0.70): {summary.relevant_matches}")
        print(f"Possible Matches (0.45-0.7):{summary.possible_matches}")
        print(f"Needs Review (0.25-0.45):  {summary.needs_review_records}")
        print(f"No Match (<0.25):          {summary.no_match_records}")
        print(f"Notifications Generated:   {summary.notifications_generated}")
        print(f"Total Processing Time:     {round(total_time, 3)} s")
        print(f"Average Time Per Bid:      {round(summary.avg_time_per_bid_ms, 2)} ms")
        print("-" * 70)

        return summary
    finally:
        db.close()

if __name__ == "__main__":
    run_benchmark()
