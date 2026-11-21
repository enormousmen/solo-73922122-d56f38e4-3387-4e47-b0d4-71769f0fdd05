"""FastAPI 预演服务：导入告警/静默规则，输出加静默前后的首呼对照。"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import engine
from .sample import SAMPLE_PAYLOAD


class AlertIn(BaseModel):
    id: str = Field(..., min_length=1)
    service: str = Field(..., min_length=1)
    labels: dict[str, str] = Field(default_factory=dict)
    fired_at: str
    recovered_at: Optional[str] = None


class SilenceRuleIn(BaseModel):
    id: str = Field(..., min_length=1)
    labels: dict[str, str]
    start_at: str
    end_at: str


class SimulationRequest(BaseModel):
    alerts: list[AlertIn]
    current_silences: list[SilenceRuleIn] = Field(default_factory=list)
    proposed_silences: list[SilenceRuleIn] = Field(default_factory=list)
    wait_minutes: float = Field(..., gt=0)
    cutoff_at: str


app = FastAPI(title="静默规则首呼预演", version="1.0.0")


def _build_alert(a: AlertIn) -> engine.Alert:
    try:
        fired = engine.parse_dt(a.fired_at)
        recovered = engine.parse_dt(a.recovered_at) if a.recovered_at else None
    except ValueError as exc:
        raise HTTPException(422, f"告警 {a.id} 时间格式无法解析: {exc}")
    if recovered is not None and recovered < fired:
        raise HTTPException(422, f"告警 {a.id} 的恢复时刻早于触发时刻")
    return engine.Alert(
        id=a.id,
        service=a.service,
        labels=dict(a.labels),
        fired_at=fired,
        recovered_at=recovered,
    )


def _build_rule(r: SilenceRuleIn) -> engine.SilenceRule:
    try:
        start = engine.parse_dt(r.start_at)
        end = engine.parse_dt(r.end_at)
    except ValueError as exc:
        raise HTTPException(422, f"静默规则 {r.id} 时间格式无法解析: {exc}")
    if end <= start:
        raise HTTPException(422, f"静默规则 {r.id} 的终点必须晚于起点")
    if not r.labels:
        raise HTTPException(422, f"静默规则 {r.id} 至少需要一个标签条件")
    return engine.SilenceRule(
        id=r.id, labels=dict(r.labels), start_at=start, end_at=end
    )


def _validate(req: SimulationRequest):
    if not req.alerts:
        raise HTTPException(422, "至少导入一条告警")

    ids = [a.id for a in req.alerts]
    if len(set(ids)) != len(ids):
        raise HTTPException(422, "告警 ID 存在重复")
    rule_ids = [r.id for r in req.current_silences + req.proposed_silences]
    if len(set(rule_ids)) != len(rule_ids):
        raise HTTPException(422, "静默规则 ID 存在重复")

    try:
        cutoff = engine.parse_dt(req.cutoff_at)
    except ValueError as exc:
        raise HTTPException(422, f"观察截止时间无法解析: {exc}")

    alerts = [_build_alert(a) for a in req.alerts]
    dropped = [a.id for a in alerts if a.fired_at >= cutoff]
    alerts = [a for a in alerts if a.fired_at < cutoff]
    if not alerts:
        raise HTTPException(422, "观察截止之前没有任何告警触发，无法预演")

    current = [_build_rule(r) for r in req.current_silences]
    proposed = [_build_rule(r) for r in req.proposed_silences]
    wait = timedelta(minutes=req.wait_minutes)
    return alerts, current, proposed, wait, cutoff, dropped


@app.post("/api/simulate")
def simulate(req: SimulationRequest):
    alerts, current, proposed, wait, cutoff, dropped = _validate(req)

    before = engine.simulate(alerts, current, wait, cutoff)
    after = engine.simulate(alerts, current + proposed, wait, cutoff)
    rows = engine.compare(before, after)
    return {
        "cutoff_at": engine.dt_iso(cutoff),
        "wait_minutes": req.wait_minutes,
        "ignored_alerts_after_cutoff": dropped,
        "summary": engine.summarize(rows),
        "rounds": rows,
    }


@app.get("/api/sample")
def sample():
    return SAMPLE_PAYLOAD


@app.get("/")
def index():
    return FileResponse("app/static/index.html")


app.mount("/static", StaticFiles(directory="app/static"), name="static")
