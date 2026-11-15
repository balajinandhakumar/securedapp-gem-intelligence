from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    project_name: str
    environment: str
    database_connected: bool


class ReadinessResponse(BaseModel):
    status: str
    checks: dict
