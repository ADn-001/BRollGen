"""
Phase 6A — Adapter lifecycle management tests.

Run from backend/ directory (app must be running or use TestClient):
    pytest tests/phase_06/test_adapter_lifecycle.py -v --tb=short
"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    import sys, pathlib
    # This file is at backend/tests/phase_06/test_adapter_lifecycle.py — three
    # .parent hops already lands on backend/, so do NOT append "backend" again
    # (see GATELOG.md "Crucial Discovered Facts" — this exact bug cost real
    # debugging time in Phase 4's test suite).
    sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent))
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def profile_with_adapter(client):
    """Create a source + profile with a custom_adapter source that has adapter_script_path."""
    import pathlib
    adapter_script = str(
        pathlib.Path(__file__).parent.parent.parent.parent /
        "CustomAdapters" / "wh40k" / "loc_adapter.py"
    )
    # Create source
    r = client.post("/api/sources", json={
        "name": "Phase6TestAdapter",
        "type": "custom_adapter",
        "config": {
            "adapter_url": "http://localhost:3002",
            "adapter_script_path": adapter_script,
        },
        "enabled": True,
    })
    source_id = r.json()["id"]

    # Create profile
    r = client.post("/api/profiles", json={
        "name": "Phase6TestProfile",
        "default_item_count": 1,
    })
    profile_id = r.json()["id"]

    # Link source to profile
    client.put(f"/api/profiles/{profile_id}/sources", json={"source_ids": [source_id]})

    yield profile_id, source_id

    # Cleanup
    client.delete(f"/api/profiles/{profile_id}")
    client.delete(f"/api/sources/{source_id}")


def test_start_adapters_endpoint_exists(client, profile_with_adapter):
    profile_id, _ = profile_with_adapter
    r = client.post(f"/api/profiles/{profile_id}/adapters/start")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"


def test_start_adapters_returns_adapter_list(client, profile_with_adapter):
    profile_id, _ = profile_with_adapter
    r = client.post(f"/api/profiles/{profile_id}/adapters/start")
    data = r.json()
    assert "adapters" in data, "Response must contain 'adapters' key"
    assert isinstance(data["adapters"], list)


def test_start_adapters_result_has_source_name_and_status(client, profile_with_adapter):
    profile_id, _ = profile_with_adapter
    r = client.post(f"/api/profiles/{profile_id}/adapters/start")
    for adapter in r.json().get("adapters", []):
        assert "source" in adapter
        assert "status" in adapter
        assert adapter["status"] in (
            "already_running", "started", "start_timeout",
            "launch_failed", "not_running", "skipped"
        )


def test_start_adapters_profile_no_custom_sources(client):
    """Profile with no custom_adapter sources returns empty adapter list."""
    r = client.post("/api/profiles", json={"name": "NoAdapterProfile", "default_item_count": 1})
    pid = r.json()["id"]
    try:
        r2 = client.post(f"/api/profiles/{pid}/adapters/start")
        assert r2.status_code == 200
        assert r2.json().get("adapters") == []
    finally:
        client.delete(f"/api/profiles/{pid}")


def test_app_state_has_adapter_processes(client):
    """app.state must have adapter_processes dict after startup."""
    assert hasattr(client.app.state, "adapter_processes"), \
        "app.state must have adapter_processes dict"
    assert isinstance(client.app.state.adapter_processes, dict)


def test_start_adapters_endpoint_returns_404_for_unknown_profile(client):
    """POST /profiles/{id}/adapters/start on a non-existent profile must 404."""
    r = client.post("/api/profiles/999999/adapters/start")
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"
