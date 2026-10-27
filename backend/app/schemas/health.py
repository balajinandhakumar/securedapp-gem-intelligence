from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    project_name: str
    environment: str
    database_connected: bool
