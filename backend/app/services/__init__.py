"""
Ingestion service package for SecuredApp GeM Bid Intelligence Platform.

Provides source-independent bid ingestion through pluggable adapters.
Supported formats: JSON, CSV, XLSX.

Architecture:
    Adapter -> Parser -> Validator -> Normalizer -> Duplicate Detector -> Persistence
"""
