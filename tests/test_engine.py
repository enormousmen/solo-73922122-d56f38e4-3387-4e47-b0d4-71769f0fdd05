"""引擎关键场景自测。"""

from datetime import datetime, timedelta, timezone

import pytest

from app import engine

UTC = timezone.utc
T = lambda h, m=0, s=0: datetime(2026, 11, 21, h, m, s, tzinfo=UTC)
W10 = timedelta(minutes=10)
CUTOFF = T(12)


def alert(aid, service, fired, recovered=None, labels=None):
    return engine.Alert(
        id=aid,
        service=service,
        labels=labels or {"service": service, "alertname": "X"},
        fired_at=fired,
        recovered_at=recovered,
    )


def rule(rid, labels, start, end):
    return engine.SilenceRule(id=rid, labels=labels, start_at=start, end_at=end)


def first(alerts, rules, wait=W10, cutoff=CUTOFF):
    """返回该（唯一）轮次的模拟结果。"""
    results = engine.simulate(alerts, rules, wait, cutoff)
    assert len(results) == 1
    return results[0]


# --------------------------------------------------------------------------- #
# 基础计时
# --------------------------------------------------------------------------- #


def test_basic_first_call_after_wait():
    r = first([alert("a", "svc", T(10), T(11))], [])
    assert r.first_call_at == T(10, 10)
    assert r.called_alert_ids == ["a"]
    assert r.still_waiting_at_cutoff is False


def test_wait_zero_not_allowed_at_api_layer_but_engine_accepts():
    r = first([alert("a", "svc", T(10), T(11))], [], wait=timedelta(0))
    assert r.first_call_at == T(10)


def test_recovers_before_wait_elapsed_no_call():
    r = first([alert("a", "svc", T(10), T(10, 5))], [])
    assert r.first_call_at is None
    assert r.still_waiting_at_cutoff is False


def test_exact_cutoff_not_called():
    # 11:50 触发，等待 10 分钟 => 12:00 恰好等于截止，不应首呼
    r = first([alert("a", "svc", T(11, 50), None)], [])
    assert r.first_call_at is None
    assert r.still_waiting_at_cutoff is True
    assert r.stretches[-1].open_ended is True


def test_open_ended_stretch_calls_before_cutoff():
    r = first([alert("a", "svc", T(11, 40), None)], [])
    assert r.first_call_at == T(11, 50)
    assert r.still_waiting_at_cutoff is False


# --------------------------------------------------------------------------- #
# 静默规则语义
# --------------------------------------------------------------------------- #


def test_silence_delays_call_and_wait_restarts():
    # 10:00 触发；10:05-10:15 被静默 => 前段只积 5 分钟，重新等待 => 10:25 首呼
    r = first(
        [alert("a", "svc", T(10), T(10, 40))],
        [rule("s", {"alertname": "X"}, T(10, 5), T(10, 15))],
    )
    assert r.first_call_at == T(10, 25)
    assert len(r.stretches) == 2


def test_full_coverage_suppresses_call():
    r = first(
        [alert("a", "svc", T(10), T(10, 40))],
        [rule("s", {"alertname": "X"}, T(9), T(12))],
    )
    assert r.first_call_at is None
    assert r.stretches == []
    assert r.still_waiting_at_cutoff is False


def test_partial_label_match_does_not_silence():
    # 全标签匹配：规则带两个条件，告警只满足一个 => 不屏蔽
    a = alert("a", "svc", T(10), T(11), labels={"service": "svc"})
    r = first([a], [rule("s", {"service": "svc", "env": "prod"}, T(9), T(12))])
    assert r.first_call_at == T(10, 10)


def test_silence_ending_exactly_when_alert_recovers():
    # 静默 10:00-10:20，告警 10:00-10:20：同刻解除与恢复，之后无未静默告警
    r = first(
        [alert("a", "svc", T(10), T(10, 20))],
        [rule("s", {"alertname": "X"}, T(10), T(10, 20))],
    )
    assert r.first_call_at is None
    assert r.stretches == []


def test_silence_lifted_at_cutoff_still_no_call():
    # 11:50 静默解除 == 截止点；截止时刻本身不判定首呼
    r = first(
        [alert("a", "svc", T(11), None)],
        [rule("s", {"alertname": "X"}, T(11), T(12))],
    )
    assert r.first_call_at is None
    assert r.still_waiting_at_cutoff is False  # 截止点状态为空，不是开口段


# --------------------------------------------------------------------------- #
# 同刻变化
# --------------------------------------------------------------------------- #


def test_simultaneous_silence_lift_and_new_alert():
    # A 10:00-10:10 被静默；10:10 同刻静默解除且 B 触发，B 活到 10:40
    a = alert("a", "svc", T(10), T(10, 10))
    b = alert("b", "svc", T(10, 10), T(10, 40), labels={"service": "svc", "alertname": "Y"})
    # 规则只屏蔽 X
    r = first([a, b], [rule("s", {"alertname": "X"}, T(10), T(10, 10))])
    assert r.first_call_at == T(10, 20)
    assert r.called_alert_ids == ["b"]


def test_simultaneous_recovery_and_firing_keeps_round_and_timer():
    # A、B 同刻换岗（10:10），无静默：等待连续计时，10:10 即首呼
    a = alert("a", "svc", T(10), T(10, 10))
    b = alert("b", "svc", T(10, 10), T(10, 30), labels={"service": "svc", "alertname": "Y"})
    r = first([a, b], [])
    assert r.first_call_at == T(10, 10)
    assert r.called_alert_ids == ["b"]
    assert len(engine.build_rounds([a, b])) == 1


def test_simultaneous_silence_start_halts_timer_immediately():
    # 10:05 静默同刻生效 => 前 5 分钟不计入；10:15 解除后重新等待 => 10:25
    r = first(
        [alert("a", "svc", T(10), T(10, 40))],
        [rule("s", {"alertname": "X"}, T(10, 5), T(10, 15))],
    )
    assert r.first_call_at == T(10, 25)


# --------------------------------------------------------------------------- #
# 轮次切分与每轮一次首呼
# --------------------------------------------------------------------------- #


def test_gap_splits_rounds_and_each_calls_once():
    a = alert("a", "svc", T(10), T(10, 20))
    b = alert("b", "svc", T(10, 30), T(11), labels={"service": "svc", "alertname": "Y"})
    results = engine.simulate([a, b], [], W10, CUTOFF)
    assert len(results) == 2
    assert [r.round_index for r in results] == [1, 2]
    assert results[0].first_call_at == T(10, 10)
    assert results[1].first_call_at == T(10, 40)
    assert results[0].ended_at == T(10, 20)
    assert results[1].ended_at == T(11)


def test_unrecovered_alert_merges_later_alert_into_same_round():
    a = alert("a", "svc", T(10), None)
    b = alert("b", "svc", T(11), T(11, 30), labels={"service": "svc", "alertname": "Y"})
    rounds = engine.build_rounds([a, b])
    assert len(rounds) == 1
    assert rounds[0].ended_at is None
    r = engine.simulate([a, b], [], W10, CUTOFF)[0]
    assert r.first_call_at == T(10, 10)
    # 首呼只发一次：11 点 B 触发后不会产生第二次呼叫
    assert r.called_alert_ids == ["a"]


def test_round_ends_only_when_all_alerts_recovered():
    # A 未恢复，B 中途恢复：轮次仍未结束
    a = alert("a", "svc", T(10), None)
    b = alert("b", "svc", T(10, 5), T(10, 30), labels={"service": "svc", "alertname": "Y"})
    rounds = engine.build_rounds([a, b])
    assert len(rounds) == 1
    assert rounds[0].ended_at is None


def test_services_independent():
    a = alert("a", "svc-a", T(10), T(10, 30))
    b = alert("b", "svc-b", T(10), T(10, 30), labels={"service": "svc-b", "alertname": "Y"})
    results = engine.simulate([a, b], [], W10, CUTOFF)
    assert {r.service for r in results} == {"svc-a", "svc-b"}
    assert all(r.first_call_at == T(10, 10) for r in results)


# --------------------------------------------------------------------------- #
# 随首呼发出的未静默活动告警快照
# --------------------------------------------------------------------------- #


def test_called_snapshot_excludes_silenced_and_inactive():
    # A: 10:00-10:30；B: 10:05-10:25，10:10-10:20 被静默
    a = alert("a", "svc", T(10), T(10, 30))
    b = alert("b", "svc", T(10, 5), T(10, 25), labels={"service": "svc", "alertname": "Y"})
    r = first([a, b], [rule("s", {"alertname": "Y"}, T(10, 10), T(10, 20))])
    # 10:00-10:10 连续 10 分钟未静默（B 10:05 加入），首呼 10:10；
    # 10:10 同刻静默生效，快照按生效后状态 => 只有 A
    assert r.first_call_at == T(10, 10)
    assert r.called_alert_ids == ["a"]


# --------------------------------------------------------------------------- #
# 对照判定
# --------------------------------------------------------------------------- #


def test_compare_verdicts():
    alerts = [alert("a", "svc", T(10), T(10, 40))]
    before = engine.simulate(alerts, [], W10, CUTOFF)
    after = engine.simulate(
        alerts, [rule("s", {"alertname": "X"}, T(10, 5), T(10, 15))], W10, CUTOFF
    )
    rows = engine.compare(before, after)
    assert rows[0]["verdict"] == "delayed"
    assert rows[0]["delay_seconds"] == 900  # 10:10 -> 10:25
    summary = engine.summarize(rows)
    assert summary["delayed"] == 1
    assert summary["before_called"] == 1
    assert summary["after_called"] == 1


def test_compare_suppressed_verdict():
    alerts = [alert("a", "svc", T(10), T(10, 40))]
    before = engine.simulate(alerts, [], W10, CUTOFF)
    after = engine.simulate(
        alerts, [rule("s", {"alertname": "X"}, T(9), T(12))], W10, CUTOFF
    )
    rows = engine.compare(before, after)
    assert rows[0]["verdict"] == "suppressed"
    assert engine.summarize(rows)["not_called_after"] == 1


# --------------------------------------------------------------------------- #
# 时间解析
# --------------------------------------------------------------------------- #


def test_naive_time_treated_as_utc():
    dt = engine.parse_dt("2026-11-21T10:00:00")
    assert dt == T(10)
    assert dt.tzinfo is not None


def test_z_suffix_and_offset_equivalent():
    assert engine.parse_dt("2026-11-21T10:00:00Z") == engine.parse_dt(
        "2026-11-21T18:00:00+08:00"
    )


def test_half_open_interval_semantics():
    # 恢复时刻不再活动；静默终点时刻不再被屏蔽
    a = alert("a", "svc", T(10), T(10, 20))
    assert a.active_at(T(10, 20)) is False
    assert a.active_at(T(10)) is True
    s = rule("s", {"alertname": "X"}, T(10), T(10, 20))
    assert s.covers(a, T(10, 20)) is False
    assert s.covers(a, T(10, 19, 59)) is True
