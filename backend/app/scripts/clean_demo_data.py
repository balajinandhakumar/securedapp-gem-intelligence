"""
Utility script to remove all synthetic/demo runtime bids and associated data from the database.

Preserves:
- The 11 official SecuredApp products and their knowledge base.
- System configurations.

Purges:
- Bids
- BidAnalyses
- BidScores
- RawBidPayloads
- CollectionRuns
- Notifications
- HumanReviews
"""
import os
import sys

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app.core.database import SessionLocal, engine, Base
from app.models.analysis import BidAnalysis, BidScore
from app.models.bid import Bid
from app.models.collection import CollectionRun, RawBidPayload
from app.models.notification import Notification
from app.models.product import Product
from app.models.review import HumanReview
from app.db.seed_knowledge import bootstrap_product_knowledge


def clean_demo_data():
    db = SessionLocal()
    try:
        print("Purging synthetic runtime data...")
        num_scores = db.query(BidScore).delete()
        num_analyses = db.query(BidAnalysis).delete()
        num_notifications = db.query(Notification).delete()
        num_reviews = db.query(HumanReview).delete()
        num_payloads = db.query(RawBidPayload).delete()
        num_runs = db.query(CollectionRun).delete()
        num_bids = db.query(Bid).delete()

        # Ensure product knowledge is bootstrapped cleanly
        seed_res = bootstrap_product_knowledge(db)

        db.commit()
        print(f"Cleanup summary:")
        print(f"  Bids deleted: {num_bids}")
        print(f"  Analyses deleted: {num_analyses}")
        print(f"  Scores deleted: {num_scores}")
        print(f"  Notifications deleted: {num_notifications}")
        print(f"  Reviews deleted: {num_reviews}")
        print(f"  Raw payloads deleted: {num_payloads}")
        print(f"  Collection runs deleted: {num_runs}")
        print(f"  Products verified: {db.query(Product).count()} official products")
    except Exception as e:
        db.rollback()
        print(f"Error during cleanup: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    clean_demo_data()
