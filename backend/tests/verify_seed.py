import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.core.database import SessionLocal
from app.models.product import Product
from app.seed import OFFICIAL_SECUREDAPP_PRODUCTS

def verify_seeded_products():
    db = SessionLocal()
    try:
        products = db.query(Product).all()
        print(f"\nFound {len(products)} products in database.")
        
        db_product_names = [p.name for p in products]
        
        print("\nVerifying official product names:")
        for idx, expected in enumerate(OFFICIAL_SECUREDAPP_PRODUCTS, start=1):
            assert expected in db_product_names, f"Missing product: {expected}"
            print(f"  {idx}. {expected} [VERIFIED]")
            
        print("\nVerifying zero invented product information:")
        for p in products:
            if p.name in OFFICIAL_SECUREDAPP_PRODUCTS:
                assert p.description is None or p.description == "", f"Description unexpectedly present for {p.name}"
                assert len(p.capabilities) == 0, f"Capabilities unexpectedly present for {p.name}"
                assert len(p.keywords) == 0, f"Keywords unexpectedly present for {p.name}"
                assert len(p.technologies) == 0, f"Technologies unexpectedly present for {p.name}"
                assert len(p.categories) == 0, f"Categories unexpectedly present for {p.name}"
        
        print("\nSUCCESS: All 11 SecuredApp products exist with ZERO fake/invented capabilities!")

    finally:
        db.close()

if __name__ == "__main__":
    verify_seeded_products()
