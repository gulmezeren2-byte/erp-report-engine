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


def test_automation_payload_carries_card_findings_and_report():
    import base64

    p = delivery.automation_payload("2026-W28", ["Revenue up", "On-time down"], "<h1>report</h1>")
    assert p["source"] == "erp-report-engine" and p["week"] == "2026-W28"
    assert p["findings"] == ["Revenue up", "On-time down"]
    # the ready-to-post Adaptive Card is embedded (a flow posts it verbatim)
    assert p["card"]["type"] == "AdaptiveCard"
    assert any(b["text"] == "Revenue up" for b in p["card"]["body"])
    # the HTML report rides along as base64 so the flow can archive it
    assert p["report"]["filename"] == "report_2026-W28.html"
    assert base64.b64decode(p["report"]["contentBytesBase64"]).decode("utf-8") == "<h1>report</h1>"


def test_automation_payload_can_omit_the_report():
    p = delivery.automation_payload("2026-W28", ["x"], "<h1>r</h1>", include_report=False)
    assert "report" not in p
    p2 = delivery.automation_payload("2026-W28", ["x"])           # no html at all
    assert "report" not in p2


def test_power_automate_channel_posts_structured_payload(monkeypatch):
    posted = {}
    monkeypatch.setenv("T_PA", "https://prod-1.westeurope.logic.azure.com/workflows/abc/triggers/manual/paths/invoke")

    def fake_post(url, payload, timeout=15):
        posted["url"] = url
        posted["payload"] = payload
        return 202

    monkeypatch.setattr(delivery, "_post_json", fake_post)

    cfg = SimpleNamespace(delivery={"power_automate": {"webhook_url_env": "T_PA"}})
    res = delivery.send_report(cfg, week="2026-W28", findings=["Revenue up"], html="<p>x</p>")
    assert res["power_automate"] == "posted (202)"
    assert posted["url"].endswith("/invoke")
    assert posted["payload"]["week"] == "2026-W28"
    assert posted["payload"]["card"]["type"] == "AdaptiveCard"
    assert "report" in posted["payload"]                          # HTML archived by default


def test_power_automate_skipped_when_env_unset():
    cfg = SimpleNamespace(delivery={"power_automate": {"webhook_url_env": "DOES_NOT_EXIST"}})
    res = delivery.send_report(cfg, week="2026-W28", findings=["x"], html="<p>x</p>")
    assert res["power_automate"] == "skipped: webhook_url_env unset"
