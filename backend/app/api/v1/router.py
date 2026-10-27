from fastapi import APIRouter

# NOTE: the import order below is significant. `ingestion` must be imported
# before `analysis`: `ingestion.pipeline` completes first, which is what keeps
# the pre-existing `batch_processor -> ingestion.pipeline` cycle resolvable.
# Reordering these imports breaks app
# start-up.
from app.api.v1.endpoints import health, products, bids, ingestion, analysis, dashboard, gem_direct
from app.api.v1.endpoints import sources

api_router = APIRouter()

api_router.include_router(health.router, tags=["Health"])
api_router.include_router(products.router, prefix="/products", tags=["Products"])
api_router.include_router(bids.router, prefix="/bids", tags=["Bids"])
api_router.include_router(ingestion.router, prefix="/ingestion", tags=["Ingestion"])
api_router.include_router(analysis.router, tags=["Intelligence & Analysis"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["Dashboard"])

# Direct GeM public collector. Manual-triggered collection of publicly
# reachable GeM pages. Uses no credentials and no third-party data provider.
api_router.include_router(gem_direct.router, prefix="/ingestion", tags=["Ingestion: GeM Direct"])

# Configurable multi-source registry. Mounted after the GeM paths so a source
# named like an existing route can never shadow them.
api_router.include_router(sources.router, tags=["Sources"])


