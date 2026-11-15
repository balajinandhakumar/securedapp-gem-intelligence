"""
Product management API.

Follows the repository's existing pattern: plain `def` handlers that receive a
`Session` via `Depends(get_db)`, return Pydantic `response_model`s and raise
`HTTPException` with actionable messages.

Removal is soft by default (`DELETE` deactivates the product) so that
historical bid-analysis records referencing the product are never lost.
"""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.logging import logger
from app.api.v1.dependencies import require_admin, require_operator, require_viewer
from app.models.analysis import BidAnalysis, BidProductMatch
from app.models.product import (
    Product,
    ProductCapability,
    ProductCategory,
    ProductKeyword,
    ProductTechnology,
)
from app.models.user import User
from app.schemas.product import (
    ProductCapabilityCreate,
    ProductCapabilityResponse,
    ProductCategoryCreate,
    ProductCategoryResponse,
    ProductCreate,
    ProductKeywordCreate,
    ProductKeywordResponse,
    ProductResponse,
    ProductTechnologyCreate,
    ProductTechnologyResponse,
    ProductUpdate,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_product_or_404(db: Session, product_id: UUID) -> Product:
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )
    return product


def _count_analysis_references(db: Session, product_id: UUID) -> int:
    """
    Count stored bid analyses whose snapshot still names this product.

    `bid_analysis.product_matches` is a JSON snapshot, so it is not protected by
    a foreign key. A permanent delete has to respect it too, otherwise a stored
    analysis would be left pointing at a product that no longer exists.
    """
    key = str(product_id)
    count = 0
    rows = db.query(BidAnalysis.product_matches).filter(
        BidAnalysis.product_matches.isnot(None)
    ).all()
    for (matches,) in rows:
        if not isinstance(matches, list):
            continue
        for match in matches:
            if isinstance(match, dict) and str(match.get("product_id")) == key:
                count += 1
                break
    return count


def _assert_unique_in_payload(items, field: str, label: str) -> None:
    """Reject duplicate entries inside a single request payload."""
    seen = set()
    for item in items:
        value = getattr(item, field).strip().lower()
        if value in seen:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Duplicate {label} '{getattr(item, field)}' in request payload.",
            )
        seen.add(value)


def _apply_knowledge(db: Session, product: Product, payload: ProductCreate | ProductUpdate) -> None:
    """Persist the knowledge vectors supplied on a create/update payload.

    Only the collections actually present on the payload are touched, so a
    partial update never silently wipes capabilities, keywords, technologies
    or categories that were set up previously.
    """
    if payload.capabilities is not None:
        _assert_unique_in_payload(payload.capabilities, "name", "capability")
        db.query(ProductCapability).filter(
            ProductCapability.product_id == product.id
        ).delete(synchronize_session=False)
        for cap in payload.capabilities:
            db.add(ProductCapability(product_id=product.id, **cap.model_dump()))

    if payload.keywords is not None:
        _assert_unique_in_payload(payload.keywords, "keyword", "keyword")
        db.query(ProductKeyword).filter(
            ProductKeyword.product_id == product.id
        ).delete(synchronize_session=False)
        for kw in payload.keywords:
            db.add(ProductKeyword(product_id=product.id, **kw.model_dump()))

    if payload.technologies is not None:
        _assert_unique_in_payload(payload.technologies, "technology", "technology")
        db.query(ProductTechnology).filter(
            ProductTechnology.product_id == product.id
        ).delete(synchronize_session=False)
        for tech in payload.technologies:
            db.add(ProductTechnology(product_id=product.id, **tech.model_dump()))

    if payload.categories is not None:
        _assert_unique_in_payload(payload.categories, "category", "category")
        db.query(ProductCategory).filter(
            ProductCategory.product_id == product.id
        ).delete(synchronize_session=False)
        for cat in payload.categories:
            db.add(ProductCategory(product_id=product.id, **cat.model_dump()))


def _commit(db: Session) -> None:
    """Commit, translating driver errors into clean client-facing responses."""
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Product could not be saved because it conflicts with an existing record.",
        )
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while persisting product changes")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while saving the product.",
        )


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
@router.get("", response_model=List[ProductResponse])
def list_products(
    skip: int = 0,
    limit: Optional[int] = None,
    active: Optional[bool] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """List products. Filters are optional and default to returning everything."""
    query = db.query(Product)

    if active is not None:
        query = query.filter(Product.active.is_(active))

    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(Product.name.ilike(term), Product.description.ilike(term))
        )

    query = query.order_by(Product.name)
    if skip:
        query = query.offset(skip)
    # Cap page size to prevent over-fetching the catalogue.
    if limit is not None:
        query = query.limit(min(limit, 1000))
    return query.all()


@router.get("/catalogue-stats")
def product_catalogue_stats(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    """
    Return product catalogue statistics with matching tender data.

    Joins products with BidProductMatch records to compute, per product:
    - Number of matching tenders (distinct bids)
    - Total match rows
    - Highest relevance score and classification
    - Matched states, departments, organisations

    All figures come from persisted bid-product matches — nothing is estimated
    or fabricated.
    """
    from app.models.bid import Bid

    products = (
        db.query(Product)
        .filter(Product.active == True)
        .order_by(Product.name)
        .all()
    )

    # Collect all product matches joined with bids
    match_rows = (
        db.query(BidProductMatch, Bid)
        .join(Bid, BidProductMatch.bid_id == Bid.id)
        .all()
    )

    # Group matches by product
    product_matches: dict = {}
    for pm, bid in match_rows:
        pid = str(pm.product_id)
        product_matches.setdefault(pid, []).append((pm, bid))

    # Category set across all active products
    all_categories = set()
    for p in products:
        for c in p.categories:
            all_categories.add(c.category)

    product_stats = []
    products_with_matches = 0
    all_matching_bid_ids: set = set()

    for p in products:
        pm_list = product_matches.get(str(p.id), [])
        if not pm_list:
            product_stats.append({
                "product_id": str(p.id),
                "product_name": p.name,
                "matching_tenders": 0,
                "total_matches": 0,
                "highest_relevance_score": None,
                "highest_classification": None,
                "matched_states": [],
                "matched_departments": [],
                "matched_organisations": [],
            })
            continue

        products_with_matches += 1

        bid_ids = set()
        states = set()
        departments = set()
        organisations = set()
        best_score = 0.0
        best_classification = None

        for pm, bid in pm_list:
            bid_ids.add(str(bid.id))
            if bid.location:
                states.add(bid.location)
            if bid.department:
                departments.add(bid.department)
            if bid.organisation:
                organisations.add(bid.organisation)
            if pm.match_score > best_score:
                best_score = pm.match_score
                best_classification = (pm.evidence or {}).get("match_state")

        all_matching_bid_ids.update(bid_ids)

        product_stats.append({
            "product_id": str(p.id),
            "product_name": p.name,
            "matching_tenders": len(bid_ids),
            "total_matches": len(pm_list),
            "highest_relevance_score": round(best_score, 3) if best_score > 0 else None,
            "highest_classification": best_classification,
            "matched_states": sorted(states),
            "matched_departments": sorted(departments),
            "matched_organisations": sorted(organisations),
        })

    return {
        "total_products": len(products),
        "active_products": len(products),
        "total_categories": len(all_categories),
        "products_with_matches": products_with_matches,
        "total_matching_tenders": len(all_matching_bid_ids),
        "product_stats": product_stats,
    }


@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    product_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_viewer),
):
    return _get_product_or_404(db, product_id)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@router.post("", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_product(
    product_in: ProductCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    """Create a product together with its optional knowledge vector."""
    name = product_in.name.strip()

    existing = db.query(Product).filter(Product.name == name).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A product named '{name}' already exists.",
        )

    scalar_fields = {
        "name": name,
        "description": product_in.description,
        "active": product_in.active,
        "priority": product_in.priority,
    }
    product = Product(**scalar_fields)
    db.add(product)
    try:
        db.flush()
        _apply_knowledge(db, product, product_in)
        _commit(db)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while creating product")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while creating the product.",
        )

    db.refresh(product)
    return product


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------
@router.put("/{product_id}", response_model=ProductResponse)
def update_product(
    product_id: UUID,
    product_in: ProductUpdate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    """
    Update a product.

    Scalar fields that are omitted are left unchanged. Knowledge collections
    supplied on the payload replace the stored collection, so the matching
    engine immediately evaluates future bids against the updated knowledge.
    """
    product = _get_product_or_404(db, product_id)

    data = product_in.model_dump(exclude_unset=True)

    new_name = data.get("name")
    if new_name is not None:
        new_name = new_name.strip()
        clash = (
            db.query(Product)
            .filter(Product.name == new_name, Product.id != product.id)
            .first()
        )
        if clash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A product named '{new_name}' already exists.",
            )
        product.name = new_name

    if "description" in data:
        product.description = data["description"]
    if "active" in data:
        product.active = data["active"]
    if "priority" in data:
        product.priority = data["priority"]

    try:
        _apply_knowledge(db, product, product_in)
        _commit(db)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while updating product %s", product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while updating the product.",
        )

    db.refresh(product)
    return product


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------
@router.delete("/{product_id}")
def deactivate_product(
    product_id: UUID,
    hard: bool = False,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    """
    Remove a product from future matching.

    By default this is a soft delete: the product is marked inactive so it stops
    participating in bid matching while remaining resolvable for historical
    bid-analysis records.

    `hard=true` performs a permanent delete and is refused whenever the product
    is referenced by historical bid matches, so analysis history is never
    corrupted or silently dropped.
    """
    product = _get_product_or_404(db, product_id)

    if hard:
        historical_matches = (
            db.query(BidProductMatch)
            .filter(BidProductMatch.product_id == product_id)
            .count()
        )
        analysis_refs = _count_analysis_references(db, product_id)
        if historical_matches or analysis_refs:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Cannot permanently delete '{product.name}' because it is referenced by "
                    f"{historical_matches} historical bid match record(s) and "
                    f"{analysis_refs} stored bid analysis record(s). "
                    "Deactivate it instead to preserve analysis history."
                ),
            )
        deleted_name = product.name
        try:
            db.delete(product)
            _commit(db)
        except HTTPException:
            db.rollback()
            raise
        except SQLAlchemyError:
            db.rollback()
            logger.exception("Database error while deleting product %s", product_id)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="An internal error occurred while removing the product.",
            )
        return {
            "deleted": True,
            "permanent": True,
            "product_id": str(product_id),
            "detail": f"Product '{deleted_name}' permanently deleted.",
        }

    product.active = False
    try:
        _commit(db)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while deactivating product %s", product_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while deactivating the product.",
        )

    db.refresh(product)
    return product


# ---------------------------------------------------------------------------
# Knowledge management
# ---------------------------------------------------------------------------
@router.post(
    "/{product_id}/capabilities",
    response_model=ProductCapabilityResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_capability(
    product_id: UUID,
    capability_in: ProductCapabilityCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    product = _get_product_or_404(db, product_id)
    name = capability_in.name.strip()
    duplicate = (
        db.query(ProductCapability)
        .filter(
            ProductCapability.product_id == product.id,
            func.lower(ProductCapability.name) == name.lower(),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Capability '{name}' already exists on this product.",
        )
    capability = ProductCapability(product_id=product.id, **capability_in.model_dump())
    db.add(capability)
    _commit(db)
    db.refresh(capability)
    return capability


@router.post(
    "/{product_id}/keywords",
    response_model=ProductKeywordResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_keyword(
    product_id: UUID,
    keyword_in: ProductKeywordCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    product = _get_product_or_404(db, product_id)
    keyword = keyword_in.keyword.strip()
    duplicate = (
        db.query(ProductKeyword)
        .filter(
            ProductKeyword.product_id == product.id,
            func.lower(ProductKeyword.keyword) == keyword.lower(),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Keyword '{keyword}' already exists on this product.",
        )
    row = ProductKeyword(product_id=product.id, **keyword_in.model_dump())
    db.add(row)
    _commit(db)
    db.refresh(row)
    return row


@router.put(
    "/{product_id}/keywords/{keyword_id}",
    response_model=ProductKeywordResponse,
)
def update_keyword(
    product_id: UUID,
    keyword_id: UUID,
    keyword_in: ProductKeywordCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    """Update an existing keyword on a product.

    Normalizes the keyword (strips whitespace, lowercases for comparison) and
    rejects duplicates against other keywords on the same product.
    """
    product = _get_product_or_404(db, product_id)
    row = (
        db.query(ProductKeyword)
        .filter(ProductKeyword.id == keyword_id, ProductKeyword.product_id == product.id)
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Keyword not found on this product.",
        )
    keyword = keyword_in.keyword.strip()
    # Check for duplicates excluding this row itself.
    duplicate = (
        db.query(ProductKeyword)
        .filter(
            ProductKeyword.product_id == product.id,
            ProductKeyword.id != keyword_id,
            func.lower(ProductKeyword.keyword) == keyword.lower(),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Keyword '{keyword}' already exists on this product.",
        )
    row.keyword = keyword
    if keyword_in.weight is not None:
        row.weight = keyword_in.weight
    if keyword_in.type is not None:
        row.type = keyword_in.type
    if keyword_in.active is not None:
        row.active = keyword_in.active
    _commit(db)
    db.refresh(row)
    return row


@router.delete(
    "/{product_id}/keywords/{keyword_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_keyword(
    product_id: UUID,
    keyword_id: UUID,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    """Delete a keyword from a product."""
    product = _get_product_or_404(db, product_id)
    row = (
        db.query(ProductKeyword)
        .filter(ProductKeyword.id == keyword_id, ProductKeyword.product_id == product.id)
        .first()
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Keyword not found on this product.",
        )
    try:
        db.delete(row)
        _commit(db)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError:
        db.rollback()
        logger.exception("Database error while deleting keyword %s", keyword_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An internal error occurred while deleting the keyword.",
        )
    return None


@router.post(
    "/{product_id}/technologies",
    response_model=ProductTechnologyResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_technology(
    product_id: UUID,
    technology_in: ProductTechnologyCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    product = _get_product_or_404(db, product_id)
    technology = technology_in.technology.strip()
    duplicate = (
        db.query(ProductTechnology)
        .filter(
            ProductTechnology.product_id == product.id,
            func.lower(ProductTechnology.technology) == technology.lower(),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Technology '{technology}' already exists on this product.",
        )
    row = ProductTechnology(product_id=product.id, **technology_in.model_dump())
    db.add(row)
    _commit(db)
    db.refresh(row)
    return row


@router.post(
    "/{product_id}/categories",
    response_model=ProductCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_category(
    product_id: UUID,
    category_in: ProductCategoryCreate,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(require_operator),
):
    product = _get_product_or_404(db, product_id)
    category = category_in.category.strip()
    duplicate = (
        db.query(ProductCategory)
        .filter(
            ProductCategory.product_id == product.id,
            func.lower(ProductCategory.category) == category.lower(),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Category '{category}' already exists on this product.",
        )
    row = ProductCategory(product_id=product.id, **category_in.model_dump())
    db.add(row)
    _commit(db)
    db.refresh(row)
    return row



