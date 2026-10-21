import uuid
import pytest
from app import create_app, db


@pytest.fixture()
def client(tmp_path):
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}", "DEMO_MODE": True, "ALLOW_DEMO_ADMIN_HEADER": True})
    with app.app_context():
        db.drop_all(); db.create_all()
        from app import seed_data
        seed_data()
    with app.test_client() as client:
        yield client


def test_health(client):
    response = client.get('/api/health')
    assert response.status_code == 200 and response.json['status'] == 'ok'


def test_analysis_missing_location(client):
    response = client.post('/api/complaints/analyze', json={"description": "There is a pothole near the gate"})
    assert response.status_code == 200
    assert response.json['data']['category'] == 'Road Damage'
    assert 'location' in response.json['data']['missing_fields']


def test_ticket_lifecycle_and_private_lookup(client):
    key = str(uuid.uuid4())
    response = client.post('/api/complaints', headers={"Idempotency-Key": key}, json={"description": "Broken streetlight is unsafe at night", "location": "College north gate"})
    assert response.status_code == 201
    ticket = response.json['data']
    assert ticket['department'] == 'Electrical Maintenance'
    assert client.get('/api/tickets/' + ticket['ticket_id']).status_code == 403
    assert client.get('/api/tickets/' + ticket['ticket_id'], headers={"X-Tracking-Token": ticket['tracking_token']}).status_code == 200
    update = client.patch('/api/tickets/' + ticket['ticket_id'] + '/status', headers={"X-Demo-Role": "admin"}, json={"status": "Assigned"})
    assert update.status_code == 200
    assert update.json['data']['history'][-1]['to'] == 'Assigned'
    invalid = client.patch('/api/tickets/' + ticket['ticket_id'] + '/status', headers={"X-Demo-Role": "admin"}, json={"status": "Resolved"})
    assert invalid.status_code == 422


def test_idempotency(client):
    key = str(uuid.uuid4()); payload = {"description": "Water leak beside the public tap", "location": "Lake road tap"}
    first = client.post('/api/complaints', headers={"Idempotency-Key": key}, json=payload)
    second = client.post('/api/complaints', headers={"Idempotency-Key": key}, json=payload)
    assert first.status_code == 201 and second.status_code == 200
    assert first.json['data']['ticket_id'] == second.json['data']['ticket_id']


def test_public_ticket_does_not_expose_internal_notes(client):
    key = str(uuid.uuid4())
    response = client.post('/api/complaints', headers={"Idempotency-Key": key}, json={"description": "Broken streetlight near the north gate", "location": "North gate"})
    assert response.status_code == 201
    ticket = response.json['data']
    client.patch('/api/tickets/' + ticket['ticket_id'] + '/status', headers={"X-Demo-Role": "admin"}, json={"status": "Assigned", "internal_note": "STAFF ONLY", "note": "PRIVATE HISTORY NOTE"})
    public = client.get('/api/tickets/' + ticket['ticket_id'], headers={"X-Tracking-Token": ticket['tracking_token']})
    assert public.status_code == 200
    assert 'internal_note' not in public.json['data']
    assert all(item.get('note') is None for item in public.json['data']['history'])
    assert all('PRIVATE HISTORY NOTE' not in str(item) for item in public.json['data']['history'])
    admin = client.get('/api/tickets/' + ticket['ticket_id'], headers={"X-Demo-Role": "admin"})
    assert admin.status_code == 200 and admin.json['data']['internal_note'] == 'STAFF ONLY'


def test_invalid_pagination_returns_400(client):
    response = client.get('/api/tickets?page=abc', headers={"X-Demo-Role": "admin"})
    assert response.status_code == 400
    assert response.json['error']['code'] == 'invalid_pagination'


def test_resolution_requires_summary(client):
    key = str(uuid.uuid4())
    response = client.post('/api/complaints', headers={"Idempotency-Key": key}, json={"description": "Water leak beside the public tap", "location": "Lake road tap"})
    ticket = response.json['data']
    client.patch('/api/tickets/' + ticket['ticket_id'] + '/status', headers={"X-Demo-Role": "admin"}, json={"status": "Assigned"})
    client.patch('/api/tickets/' + ticket['ticket_id'] + '/status', headers={"X-Demo-Role": "admin"}, json={"status": "In Progress"})
    missing = client.patch('/api/tickets/' + ticket['ticket_id'] + '/status', headers={"X-Demo-Role": "admin"}, json={"status": "Resolved"})
    assert missing.status_code == 422
    resolved = client.patch('/api/tickets/' + ticket['ticket_id'] + '/status', headers={"X-Demo-Role": "admin"}, json={"status": "Resolved", "resolution_summary": "Pipe joint replaced and leak stopped."})
    assert resolved.status_code == 200


def test_idempotency_replay_does_not_repeat_tracking_token(client):
    key = str(uuid.uuid4()); payload = {"description": "Water leak beside the public tap", "location": "Lake road tap"}
    client.post('/api/complaints', headers={"Idempotency-Key": key}, json=payload)
    replay = client.post('/api/complaints', headers={"Idempotency-Key": key}, json=payload)
    assert replay.status_code == 200
    assert 'tracking_token' not in replay.json['data']


def test_demo_admin_header_is_not_accepted_when_demo_mode_is_off(tmp_path):
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'secure.db'}", "DEMO_MODE": False, "ALLOW_DEMO_ADMIN_HEADER": False})
    with app.test_client() as secure_client:
        response = secure_client.get('/api/tickets', headers={"X-Demo-Role": "admin"})
        assert response.status_code == 401


def test_tracking_replay_does_not_leak_token_but_original_does(client):
    key = str(uuid.uuid4()); payload = {"description": "A large pothole is damaging the road", "location": "Main road"}
    first = client.post('/api/complaints', headers={"Idempotency-Key": key}, json=payload)
    replay = client.post('/api/complaints', headers={"Idempotency-Key": key}, json=payload)
    assert first.status_code == 201 and first.json['data'].get('tracking_token')
    assert replay.status_code == 200 and 'tracking_token' not in replay.json['data']


def test_gemini_api_key_is_sent_in_header(monkeypatch):
    import json
    import app as app_module

    captured = {}
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            result = {
                "category": "Streetlight", "summary": "Streetlight out", "urgency": "Medium",
                "suggested_department": "Invented Department", "confidence": 0.9
            }
            return json.dumps({"candidates": [{"content": {"parts": [{"text": json.dumps(result)}]}}]}).encode()

    def fake_urlopen(req, timeout=8):
        captured["url"] = req.full_url
        captured["key"] = req.get_header("X-goog-api-key")
        return FakeResponse()

    monkeypatch.setattr(app_module, "urlopen", fake_urlopen)
    result = app_module.AnalysisAgent()._gemini(
        {"description": "Streetlight is not working", "location": "North gate"}, "test-secret"
    )
    assert "test-secret" not in captured["url"]
    assert captured["key"] == "test-secret"
    assert result["category"] == "Streetlight"


def test_analysis_department_mapping_is_canonical():
    from app import AnalysisAgent
    assert AnalysisAgent._department_name("Streetlight") == "Electrical Maintenance"
    assert AnalysisAgent._department_name("General Review") == "General Review Queue"
