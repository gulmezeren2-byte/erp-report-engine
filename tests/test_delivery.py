"""Delivery routing and payloads. No real network: the senders are monkeypatched
so we assert on routing, the untrusted-safe payloads, and the dead-man's-switch."""

from __future__ import annotations

from types import SimpleNamespace

from erp_report_engine import delivery


def test_slack_and_teams_payloads_are_well_formed():
    s = delivery.slack_payload("2026-W28", ["Revenue up", "On-time down"])
    assert "2026-W28" in s["text"] and "Revenue up" in s["text"]
    t = delivery.teams_payload("2026-W28", ["Revenue up"])
    assert t["type"] == "message"
    card = t["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard"
    assert any(b["text"] == "Revenue up" for b in card["body"])


def test_no_delivery_config_is_a_noop():
    cfg = SimpleNamespace(delivery=None)
    assert delivery.send_report(cfg, week="2026-W28", findings=[], html="<p>x</p>") == {}


def test_slack_channel_posts_and_healthcheck_pings(monkeypatch):
    posted, pinged = {}, {}
    monkeypatch.setenv("T_SLACK", "https://hooks.example/abc")
    monkeypatch.setenv("T_HC", "https://hc.example/uuid")

    def fake_post(url, payload, timeout=15):
        posted["url"] = url
        return 200

    def fake_get(url, timeout=15):
        pinged["url"] = url
        return 200

    monkeypatch.setattr(delivery, "_post_json", fake_post)
    monkeypatch.setattr(delivery, "_get", fake_get)

    cfg = SimpleNamespace(delivery={
        "slack": {"webhook_url_env": "T_SLACK"},
        "healthcheck": {"ping_url_env": "T_HC"},
    })
    res = delivery.send_report(cfg, week="2026-W28", findings=["Revenue up"], html="<p>x</p>")
    assert res["slack"] == "posted (200)"
    assert posted["url"] == "https://hooks.example/abc"
    assert res["healthcheck"] == "pinged"
    assert pinged["url"] == "https://hc.example/uuid"      # success ping, no /fail


def test_failed_channel_triggers_fail_ping(monkeypatch):
    pinged = {}
    monkeypatch.setenv("T_SLACK", "https://hooks.example/abc")
    monkeypatch.setenv("T_HC", "https://hc.example/uuid")

    def boom(url, payload, timeout=15):
        raise OSError("network down")

    def fake_get(url, timeout=15):
        pinged["url"] = url
        return 200

    monkeypatch.setattr(delivery, "_post_json", boom)
    monkeypatch.setattr(delivery, "_get", fake_get)

    cfg = SimpleNamespace(delivery={
        "slack": {"webhook_url_env": "T_SLACK"},
        "healthcheck": {"ping_url_env": "T_HC"},
    })
    res = delivery.send_report(cfg, week="2026-W28", findings=["x"], html="<p>x</p>")
    assert res["slack"].startswith("error")
    assert pinged["url"].endswith("/fail")                 # dead-man's-switch fired
