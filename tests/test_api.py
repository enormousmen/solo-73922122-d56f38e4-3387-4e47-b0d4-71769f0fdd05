"""FastAPI 接口层自测。"""

from fastapi.testclient import TestClient

from app.main import app
from app.sample import SAMPLE_PAYLOAD

client = TestClient(app)


def test_sample_endpoint():
    r = client.get("/api/sample")
    assert r.status_code == 200
    assert len(r.json()["alerts"]) >= 5


def test_index_page_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "静默规则首呼预演".encode() in r.content


def test_full_simulation_sample():
    r = client.post("/api/simulate", json=SAMPLE_PAYLOAD)
    assert r.status_code == 200, r.text
    data = r.json()
    s = data["summary"]

    # 7 个故障轮次：auth/cache(2)/gateway/order-db/payment-api/test-svc
    assert s["total_rounds"] == 7
    # payment-api 推迟、cache#1 推迟、auth 被压掉、order-db 被压掉
    assert s["delayed"] == 2
    assert s["suppressed"] == 2
    # gateway 无变化；cache#2 与 test-svc 前后均未首呼
    assert s["unchanged"] == 1
    assert s["still_not_called"] == 2
    assert s["before_called"] == 5
    assert s["after_called"] == 3

    by_key = {(x["service"], x["round_index"]): x for x in data["rounds"]}

    pay = by_key[("payment-api", 1)]
    assert pay["before"]["first_call_at"].endswith("10:10:00Z")
    assert pay["after"]["first_call_at"].endswith("10:20:00Z")
    # 随呼快照：10:20 时 A1 仍在静默窗口内，只剩 A2
    assert pay["after"]["called_alert_ids"] == ["A2-payment-latency"]
    assert pay["delay_seconds"] == 600

    order = by_key[("order-db", 1)]
    assert order["verdict"] == "suppressed"
    assert order["after"]["first_call_at"] is None
    assert order["ended_at"] is None  # A3 未恢复 => 轮次未结束

    auth = by_key[("auth", 1)]
    assert auth["verdict"] == "suppressed"
    assert auth["after"]["still_waiting_at_cutoff"] is True
    assert auth["before"]["first_call_at"].endswith("11:25:00Z")

    gw = by_key[("gateway", 1)]
    assert gw["verdict"] == "unchanged"
    assert gw["before"]["first_call_at"] == gw["after"]["first_call_at"]

    cache2 = by_key[("cache", 2)]
    assert cache2["verdict"] == "still_not_called"
    assert cache2["before"]["first_call_at"] is None


def test_validation_duplicate_alert_ids():
    payload = {
        **SAMPLE_PAYLOAD,
        "alerts": [dict(SAMPLE_PAYLOAD["alerts"][0]), dict(SAMPLE_PAYLOAD["alerts"][0])],
    }
    r = client.post("/api/simulate", json=payload)
    assert r.status_code == 422
    assert "重复" in r.json()["detail"]


def test_validation_recovered_before_fired():
    payload = {
        "alerts": [
            {
                "id": "x",
                "service": "svc",
                "labels": {},
                "fired_at": "2026-11-21T11:00:00Z",
                "recovered_at": "2026-11-21T10:00:00Z",
            }
        ],
        "current_silences": [],
        "proposed_silences": [],
        "wait_minutes": 10,
        "cutoff_at": "2026-11-21T12:00:00Z",
    }
    r = client.post("/api/simulate", json=payload)
    assert r.status_code == 422
    assert "恢复时刻早于触发时刻" in r.json()["detail"]


def test_alert_after_cutoff_ignored():
    payload = {
        "alerts": [
            {
                "id": "late",
                "service": "svc",
                "labels": {"x": "y"},
                "fired_at": "2026-11-21T13:00:00Z",
                "recovered_at": None,
            },
            {
                "id": "ok",
                "service": "svc",
                "labels": {"x": "y"},
                "fired_at": "2026-11-21T11:00:00Z",
                "recovered_at": None,
            },
        ],
        "current_silences": [],
        "proposed_silences": [],
        "wait_minutes": 10,
        "cutoff_at": "2026-11-21T12:00:00Z",
    }
    r = client.post("/api/simulate", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["ignored_alerts_after_cutoff"] == ["late"]
    assert data["rounds"][0]["alert_ids"] == ["ok"]


def test_bad_rule_interval_rejected():
    payload = {
        "alerts": [
            {
                "id": "a",
                "service": "svc",
                "labels": {"x": "y"},
                "fired_at": "2026-11-21T11:00:00Z",
                "recovered_at": None,
            }
        ],
        "current_silences": [],
        "proposed_silences": [
            {
                "id": "bad",
                "labels": {"x": "y"},
                "start_at": "2026-11-21T11:30:00Z",
                "end_at": "2026-11-21T11:00:00Z",
            }
        ],
        "wait_minutes": 10,
        "cutoff_at": "2026-11-21T12:00:00Z",
    }
    r = client.post("/api/simulate", json=payload)
    assert r.status_code == 422
    assert "终点必须晚于起点" in r.json()["detail"]
