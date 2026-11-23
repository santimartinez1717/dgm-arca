"""The API must start with every phase pending and answer 501 with a useful message."""

from fastapi.testclient import TestClient

from api.app import app

client = TestClient(app)


def test_health_lists_all_phases():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body["phases"]) == {"reasoning", "tools", "rag", "agent"}
    for phase in body["phases"].values():
        assert phase["status"] in {"ready", "pending", "error"}


def test_pending_phase_returns_501_with_phase_name():
    response = client.post("/tools", json={"query": "¿Qué tiempo hace en Madrid?"})
    if response.status_code == 501:
        assert response.json()["detail"]["phase"] == "tools"
    else:
        assert response.status_code == 200


def test_request_validation():
    assert client.post("/reasoning", json={}).status_code == 422
    assert client.post("/rag", json={"question": "x", "retriever": "magic"}).status_code == 422
    assert client.post("/agent", json={"task": "x", "max_steps": 0}).status_code == 422


def test_docs_available():
    assert client.get("/docs").status_code == 200


def test_tools_endpoint_runs_the_loop_and_reports_the_calls():
    response = client.post("/tools", json={"query": "¿Barcelona es zona tensionada?"})
    assert response.status_code == 200
    body = response.json()
    assert body["turns"] == 2 and body["answer"] == "Barcelona es zona tensionada."
    [call] = body["tool_calls"]
    assert call["name"] == "get_rent_reference" and call["ok"]
    assert call["result"]["stressed_zone"] is True and call["latency_ms"] >= 0


class _RecordingAgent:
    """Stands in for the ReAct agent: records what /agent passes and answers at once."""

    def __init__(self):
        self.calls = []

    def run(self, task, max_steps=10, brain="rlm", session_id=None, confirm=False):
        from api.schemas import AgentResponse

        self.calls.append(
            {
                "task": task,
                "max_steps": max_steps,
                "brain": brain,
                "session_id": session_id,
                "confirm": confirm,
            }
        )
        return AgentResponse(final_answer="ok", steps=[], n_steps=0, session_id=session_id or "s1")


def _with_agent(monkeypatch):
    from api.app import backends

    fake = _RecordingAgent()
    monkeypatch.setitem(backends._cache, "agent", fake)
    return fake


def test_agent_old_contract_still_works(monkeypatch):
    """A client that only knows task, max_steps and brain gets the original fields back."""
    fake = _with_agent(monkeypatch)
    response = client.post(
        "/agent", json={"task": "¿Rentabilidad?", "max_steps": 3, "brain": "base"}
    )
    assert response.status_code == 200
    body = response.json()
    for key in ("final_answer", "steps", "n_steps", "succeeded", "model", "tokens_used"):
        assert key in body
    assert fake.calls == [
        {
            "task": "¿Rentabilidad?",
            "max_steps": 3,
            "brain": "base",
            "session_id": None,
            "confirm": False,
        }
    ]
    assert body["levers"] == [] and body["scenarios"] == [] and body["open_questions"] == []
    assert body["audit"] is None and body["case_file"] is None


def test_agent_passes_session_and_confirmation(monkeypatch):
    fake = _with_agent(monkeypatch)
    response = client.post(
        "/agent", json={"task": "Guárdalo en mi cartera", "session_id": "abc", "confirm": True}
    )
    assert response.status_code == 200 and response.json()["session_id"] == "abc"
    assert fake.calls[0]["session_id"] == "abc" and fake.calls[0]["confirm"] is True
