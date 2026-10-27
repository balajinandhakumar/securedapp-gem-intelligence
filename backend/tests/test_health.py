def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database_connected"] is True
    assert "SecuredApp GeM Bid Intelligence Platform" in data["project_name"]
