import uuid
from sqlalchemy import Column, String, Text, Boolean, Float, Integer, ForeignKey
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base_mixins import GUID, TimestampMixin


class Product(Base, TimestampMixin):
    __tablename__ = "products"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, index=True, nullable=False)
    description = Column(Text(), nullable=True)
    active = Column(Boolean(), default=True, nullable=False)
    priority = Column(Integer(), default=0, nullable=False)

    capabilities = relationship("ProductCapability", back_populates="product", cascade="all, delete-orphan")
    keywords = relationship("ProductKeyword", back_populates="product", cascade="all, delete-orphan")
    technologies = relationship("ProductTechnology", back_populates="product", cascade="all, delete-orphan")
    categories = relationship("ProductCategory", back_populates="product", cascade="all, delete-orphan")


class ProductCapability(Base):
    __tablename__ = "product_capabilities"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    product_id = Column(GUID(), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text(), nullable=True)
    weight = Column(Float(), default=1.0, nullable=False)
    active = Column(Boolean(), default=True, nullable=False)

    product = relationship("Product", back_populates="capabilities")


class ProductKeyword(Base):
    __tablename__ = "product_keywords"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    product_id = Column(GUID(), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    keyword = Column(String(255), index=True, nullable=False)
    weight = Column(Float(), default=1.0, nullable=False)
    type = Column(String(50), default="keyword", nullable=False)  # keyword, synonym, technology, positive_signal, exclusion
    active = Column(Boolean(), default=True, nullable=False)

    product = relationship("Product", back_populates="keywords")


class ProductTechnology(Base):
    __tablename__ = "product_technologies"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    product_id = Column(GUID(), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    technology = Column(String(100), nullable=False)

    product = relationship("Product", back_populates="technologies")


class ProductCategory(Base):
    __tablename__ = "product_categories"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    product_id = Column(GUID(), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    category = Column(String(255), nullable=False)

    product = relationship("Product", back_populates="categories")
