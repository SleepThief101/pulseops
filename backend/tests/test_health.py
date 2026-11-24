def test_health_check_endpoint(client):
    """Verify GET /health returns 200 OK and status 'ok'."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_root_endpoint(client):
    """Verify GET / returns 200 OK and application details."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "PulseOps API is running"
    assert data["version"] == "0.1.0"
