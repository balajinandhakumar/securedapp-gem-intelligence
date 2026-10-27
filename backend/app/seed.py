import sys
import os

# Ensure backend directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal, engine, Base
from app.models.product import Product
from app.core.logging import logger
from app.db.seed_knowledge import bootstrap_product_knowledge

OFFICIAL_SECUREDAPP_PRODUCTS = [
    "SolidityShield",
    "SecureCMS",
    "SecureTrace",
    "CookieHub",
    "PQCSuite",
    "SecureX-DID",
    "SecureWatch",
    "AuditExpress",
    "SecurePad",
    "SecureX-ID",
    "QuantumVault"
]


def seed_products():
    """
    Idempotent deployment bootstrap.

    Guarantees the 11 official SecuredApp product rows exist AND that the
    product knowledge layer (capabilities, keywords/positive signals,
    exclusion signals, technologies, categories) is populated from the single
    repository source of truth in `app/db/seed_knowledge.py`.

    The matching engine relies on those knowledge vectors; without them every
    bid would score 0.0 against every product. Re-running this function (e.g. on
    container restart) creates no duplicates and never overwrites knowledge that
    an administrator has since edited through the Product Management API.
    """
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        missing = [
            name
            for name in OFFICIAL_SECUREDAPP_PRODUCTS
            if db.query(Product).filter(Product.name == name).first() is None
        ]

        result = bootstrap_product_knowledge(db)

        message = (
            f"Seed completed: {result['created']} products created, "
            f"{result['backfilled']} knowledge vectors backfilled, "
            f"{result['preserved']} existing products left unchanged."
        )
        if missing:
            message = f"Missing before seed: {missing}. " + message
        logger.info(message)
        print(message)
    except Exception as e:
        db.rollback()
        logger.error(f"Error seeding products: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed_products()
