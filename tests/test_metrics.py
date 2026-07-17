"""Run metrics collection and summary API."""

from __future__ import annotations

from tests.test_platform import fake_run_config, make_executor

pytest_plugins = ("tests.test_platform",)

def test_run_metrics_persisted_and_summary(platform):
    client, app = platform
    run_id = client.post(
        "/api/v1/research",
        json={
            "question": "metrics please",
            "pipeline_id": "fast_research",
            "config": fake_run_config(),
        },
    ).json()["run_id"]

    executor = make_executor(app)
    run = client.portal.call(executor.execute, run_id)
    assert run.status.value == "completed"

    metrics = client.get(f"/api/v1/research/{run_id}/metrics").json()
    assert metrics["run_id"] == run_id
    assert metrics["llm_calls"] >= 1
    assert metrics["prompt_chars"] >= 1
    assert metrics["completion_chars"] >= 1
    # search may or may not fire depending on fast_research path with fake tools
    assert metrics["search_calls"] >= 0

    summary = client.get("/api/v1/metrics/summary").json()
    assert summary["runs"] >= 1
    assert summary["llm_calls"] >= metrics["llm_calls"]


def test_metrics_missing_run_404(platform):
    client, _ = platform
    assert client.get("/api/v1/research/nonexistent/metrics").status_code == 404
