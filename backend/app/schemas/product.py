from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Keyword signal types understood by the deterministic matching engine.
ProductKeywordType = Literal[
    "keyword",
    "synonym",
    "technology",
    "positive_signal",
    "exclusion",
]


def _strip_required(value: str, field_name: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be blank")
    return cleaned


class ProductCapabilityBase(BaseModel):
    name: str = Field(..., max_length=255)
    description: Optional[str] = None
    weight: float = Field(1.0, gt=0, le=10)
    active: bool = True

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return _strip_required(v, "Capability name")


class ProductCapabilityCreate(ProductCapabilityBase):
    pass


class ProductCapabilityResponse(ProductCapabilityBase):
    id: UUID
    product_id: UUID

    model_config = ConfigDict(from_attributes=True)


class ProductKeywordBase(BaseModel):
    keyword: str = Field(..., max_length=255)
    weight: float = Field(1.0, ge=-10, le=10)
    type: ProductKeywordType = "keyword"
    active: bool = True

    @field_validator("keyword")
    @classmethod
    def _validate_keyword(cls, v: str) -> str:
        return _strip_required(v, "Keyword")

    @model_validator(mode="after")
    def _validate_weight(self):
        # Exclusion signals are the only place a negative weight is meaningful,
        # matching the convention already used by the seeded knowledge base.
        if self.weight < 0 and self.type != "exclusion":
            raise ValueError("Only 'exclusion' keywords may carry a negative weight.")
        return self


class ProductKeywordCreate(ProductKeywordBase):
    pass


class ProductKeywordResponse(ProductKeywordBase):
    id: UUID
    product_id: UUID

    model_config = ConfigDict(from_attributes=True)


class ProductTechnologyBase(BaseModel):
    technology: str = Field(..., max_length=100)

    @field_validator("technology")
    @classmethod
    def _validate_technology(cls, v: str) -> str:
        return _strip_required(v, "Technology")


class ProductTechnologyCreate(ProductTechnologyBase):
    pass


class ProductTechnologyResponse(ProductTechnologyBase):
    id: UUID
    product_id: UUID

    model_config = ConfigDict(from_attributes=True)


class ProductCategoryBase(BaseModel):
    category: str = Field(..., max_length=255)

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v: str) -> str:
        return _strip_required(v, "Category")


class ProductCategoryCreate(ProductCategoryBase):
    pass


class ProductCategoryResponse(ProductCategoryBase):
    id: UUID
    product_id: UUID

    model_config = ConfigDict(from_attributes=True)


class ProductBase(BaseModel):
    name: str = Field(..., max_length=100)
    description: Optional[str] = None
    active: bool = True
    priority: int = Field(0, ge=0, le=100)

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: str) -> str:
        return _strip_required(v, "Product name")


class ProductCreate(ProductBase):
    """Product creation payload including the optional knowledge vector.

    Knowledge lists are optional: a product may be created bare and have its
    capability vectors added later via the dedicated knowledge endpoints.
    """

    capabilities: Optional[List[ProductCapabilityCreate]] = None
    keywords: Optional[List[ProductKeywordCreate]] = None
    technologies: Optional[List[ProductTechnologyCreate]] = None
    categories: Optional[List[ProductCategoryCreate]] = None


class ProductUpdate(BaseModel):
    """Partial update payload.

    Scalar fields left as `None` are untouched. Knowledge collections use the
    same convention: `None` leaves the existing vectors alone, an explicit
    list (including an empty one) replaces the stored collection.
    """

    name: Optional[str] = Field(None, max_length=100)
    description: Optional[str] = None
    active: Optional[bool] = None
    priority: Optional[int] = Field(None, ge=0, le=100)

    capabilities: Optional[List[ProductCapabilityCreate]] = None
    keywords: Optional[List[ProductKeywordCreate]] = None
    technologies: Optional[List[ProductTechnologyCreate]] = None
    categories: Optional[List[ProductCategoryCreate]] = None

    @field_validator("name")
    @classmethod
    def _validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        return _strip_required(v, "Product name")


class ProductResponse(ProductBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    capabilities: List[ProductCapabilityResponse] = []
    keywords: List[ProductKeywordResponse] = []
    technologies: List[ProductTechnologyResponse] = []
    categories: List[ProductCategoryResponse] = []

    model_config = ConfigDict(from_attributes=True)
