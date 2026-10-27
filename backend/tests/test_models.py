from app.models.user import User
from app.models.collection import CollectionRun, RawBidPayload
from app.models.analysis import BidAnalysis, BidScore
from app.models.bid import Bid
from app.models.review import HumanReview
from app.core.security import hash_password, verify_password


def test_user_password_hashing(db):
    pwd = "SuperSecretPassword123!"
    hashed = hash_password(pwd)
    assert verify_password(pwd, hashed) is True
    assert verify_password("WrongPassword", hashed) is False

    user = User(email="admin@securedapp.io", name="Admin User", password_hash=hashed, role="admin")
    db.add(user)
    db.commit()

    fetched = db.query(User).filter(User.email == "admin@securedapp.io").first()
    assert fetched is not None
    assert fetched.role == "admin"


def test_collection_run_and_payload_relationship(db):
    run = CollectionRun(source_adapter="ManualFileAdapter", status="SUCCESS", records_found=5, records_new=5)
    db.add(run)
    db.commit()

    payload = RawBidPayload(collection_run_id=run.id, raw_content={"title": "Sample Bid Json"})
    db.add(payload)
    db.commit()

    db.refresh(run)
    assert len(run.raw_payloads) == 1
    assert run.raw_payloads[0].raw_content["title"] == "Sample Bid Json"
