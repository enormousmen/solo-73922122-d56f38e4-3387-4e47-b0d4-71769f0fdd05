"""开箱即用的样例数据：覆盖延迟、收不到、未首呼、不变等关键场景。"""

SAMPLE_PAYLOAD = {
    "wait_minutes": 10,
    "cutoff_at": "2026-11-21T12:00:00Z",
    "current_silences": [
        {
            "id": "R1-test-env-maintenance",
            "labels": {"env": "test"},
            "start_at": "2026-11-21T00:00:00Z",
            "end_at": "2026-11-22T00:00:00Z",
        }
    ],
    "proposed_silences": [
        {
            "id": "S1-payment-cpu",
            "labels": {"service": "payment-api", "alertname": "HighCpu"},
            "start_at": "2026-11-21T10:05:00Z",
            "end_at": "2026-11-21T10:15:00Z",
        },
        {
            "id": "S2-order-db-all",
            "labels": {"service": "order-db"},
            "start_at": "2026-11-21T10:00:00Z",
            "end_at": "2026-11-21T12:00:00Z",
        },
        {
            "id": "S3-cache-memory",
            "labels": {"service": "cache", "alertname": "MemoryHigh"},
            "start_at": "2026-11-21T10:25:00Z",
            "end_at": "2026-11-21T10:35:00Z",
        },
        {
            "id": "S4-gateway-latency",
            "labels": {"service": "gateway", "alertname": "LatencyHigh"},
            "start_at": "2026-11-21T11:20:00Z",
            "end_at": "2026-11-21T11:30:00Z",
        },
        {
            "id": "S5-auth-cert",
            "labels": {"service": "auth", "alertname": "CertExpiry"},
            "start_at": "2026-11-21T11:20:00Z",
            "end_at": "2026-11-21T11:55:00Z",
        },
    ],
    "alerts": [
        # ---- payment-api：同一轮内告警换岗，S1 屏蔽前段 -> 首呼被推迟 ----
        {
            "id": "A1-payment-cpu",
            "service": "payment-api",
            "labels": {
                "service": "payment-api",
                "alertname": "HighCpu",
                "severity": "warning",
                "env": "prod",
            },
            "fired_at": "2026-11-21T10:00:00Z",
            "recovered_at": "2026-11-21T10:20:00Z",
        },
        {
            "id": "A2-payment-latency",
            "service": "payment-api",
            "labels": {
                "service": "payment-api",
                "alertname": "LatencyHigh",
                "severity": "critical",
                "env": "prod",
            },
            "fired_at": "2026-11-21T10:10:00Z",
            "recovered_at": "2026-11-21T10:40:00Z",
        },
        # ---- order-db：静默贯穿始终且告警未恢复 -> 加静默后收不到首呼 ----
        {
            "id": "A3-order-disk",
            "service": "order-db",
            "labels": {
                "service": "order-db",
                "alertname": "DiskFull",
                "severity": "critical",
                "env": "prod",
            },
            "fired_at": "2026-11-21T10:30:00Z",
            "recovered_at": None,
        },
        {
            "id": "A4-order-replica",
            "service": "order-db",
            "labels": {
                "service": "order-db",
                "alertname": "ReplicaLag",
                "severity": "warning",
                "env": "prod",
            },
            "fired_at": "2026-11-21T10:50:00Z",
            "recovered_at": "2026-11-21T11:30:00Z",
        },
        # ---- cache：两个独立轮次；第 1 轮被推迟，第 2 轮只活 5 分钟，
        #      短于 10 分钟等待，两套规则下都无法首呼（仍未首呼标记） ----
        {
            "id": "A5-cache-mem-1",
            "service": "cache",
            "labels": {
                "service": "cache",
                "alertname": "MemoryHigh",
                "severity": "warning",
                "env": "prod",
            },
            "fired_at": "2026-11-21T10:20:00Z",
            "recovered_at": "2026-11-21T10:50:00Z",
        },
        {
            "id": "A6-cache-mem-2",
            "service": "cache",
            "labels": {
                "service": "cache",
                "alertname": "MemoryHigh",
                "severity": "warning",
                "env": "prod",
            },
            "fired_at": "2026-11-21T11:00:00Z",
            "recovered_at": "2026-11-21T11:05:00Z",
        },
        # ---- auth：截止时仍在等待；加静默后首呼被压掉且未再凑满等待时长 ----
        {
            "id": "A7-auth-cert",
            "service": "auth",
            "labels": {
                "service": "auth",
                "alertname": "CertExpiry",
                "severity": "critical",
                "env": "prod",
            },
            "fired_at": "2026-11-21T11:15:00Z",
            "recovered_at": None,
        },
        # ---- gateway：静默窗口完全落在恢复之后 -> 首呼不变 ----
        {
            "id": "A8-gateway-latency",
            "service": "gateway",
            "labels": {
                "service": "gateway",
                "alertname": "LatencyHigh",
                "severity": "warning",
                "env": "prod",
            },
            "fired_at": "2026-11-21T11:00:00Z",
            "recovered_at": "2026-11-21T11:15:00Z",
        },
        # ---- test 环境：现行规则全程静默，两套模拟都不会首呼 ----
        {
            "id": "A9-test-svc",
            "service": "test-svc",
            "labels": {
                "service": "test-svc",
                "alertname": "ProbeFailed",
                "severity": "info",
                "env": "test",
            },
            "fired_at": "2026-11-21T09:00:00Z",
            "recovered_at": "2026-11-21T09:30:00Z",
        },
    ],
}
