"""Deliver the report - so it writes itself AND delivers itself.

Channels: SMTP e-mail (the HTML report inline), Slack and Microsoft Teams
webhooks (a summary), and a healthchecks.io dead-man's-switch that fires on
success or failure so a silent cron is detectable.

Secrets (SMTP password, webhook URLs, the healthcheck URL) come from environment
variables only - never from the config file, and never logged. A channel that
fails is recorded and logged, but never aborts the run: the report is already
written.

The payload builders are pure functions so they can be tested without a network.
For 143 services behind one URL grammar, install the optional `[notify]` extra
(apprise) and point a webhook at it.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import smtplib
import ssl
import urllib.request
from email.message import EmailMessage

_log = logging.getLogger("erp_report_engine")


def _env(name: str | None) -> str | None:
    return os.environ.get(name) if name else None


def slack_payload(week: str, findings: list[str]) -> dict:
    lines = "\n".join(f"• {f}" for f in findings[:6])
    return {"text": f"*Weekly ERP report — {week}*\n{lines}"}


def _adaptive_card(week: str, findings: list[str]) -> dict:
    """The Adaptive Card body shared by the Teams and Power Automate channels."""
    body = [{"type": "TextBlock", "text": f"Weekly ERP report — {week}",
             "weight": "Bolder", "size": "Large", "wrap": True}]
    body += [{"type": "TextBlock", "text": f, "wrap": True} for f in findings[:6]]
    return {"type": "AdaptiveCard", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4", "body": body}


def teams_payload(week: str, findings: list[str]) -> dict:
    # Power Automate Workflows (the successor to the retired Office 365
    # connectors) accepts an Adaptive Card wrapped in a message attachment.
    return {"type": "message",
            "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive",
                             "content": _adaptive_card(week, findings)}]}


def automation_payload(week: str, findings: list[str], html: str | None = None,
                       *, include_report: bool = True) -> dict:
    """A structured payload for a custom Power Automate flow (HTTP-request
    trigger). It carries the ready-to-post Adaptive Card, the plain findings for
    other steps (email, logging), and — so the flow can archive to SharePoint or
    OneDrive — the full HTML report as base64. The shape matches the flow's
    request JSON schema in automation/POWER-AUTOMATE.md."""
    payload: dict = {
        "source": "erp-report-engine",
        "week": week,
        "title": f"Weekly ERP report — {week}",
        "findings": list(findings[:12]),
        "card": _adaptive_card(week, findings),
    }
    if include_report and html is not None:
        payload["report"] = {
            "filename": f"report_{week}.html",
            "contentType": "text/html",
            "contentBytesBase64": base64.b64encode(html.encode("utf-8")).decode("ascii"),
        }
    return payload


def _post_json(url: str, payload: dict, timeout: int = 15) -> int:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - user-configured URL
        return getattr(resp, "status", 200)


def _get(url: str, timeout: int = 15) -> int:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
        return getattr(resp, "status", 200)


def _send_email(email_cfg: dict, week: str, html: str) -> str:
    to = email_cfg.get("to") or []
    if not to:
        return "skipped: no recipients"
    msg = EmailMessage()
    msg["Subject"] = (email_cfg.get("subject") or "Weekly ERP report {week}").format(week=week)
    msg["From"] = email_cfg["from_addr"]
    msg["To"] = ", ".join(to)
    msg.set_content("This report is best viewed as HTML.")
    msg.add_alternative(html, subtype="html")

    host = _env(email_cfg.get("host_env")) or email_cfg.get("host")
    port = int(email_cfg.get("port", 587))
    user = _env(email_cfg.get("user_env")) or email_cfg.get("user")
    password = _env(email_cfg.get("password_env"))
    with smtplib.SMTP(host, port, timeout=30) as s:
        if email_cfg.get("starttls", True):
            s.starttls(context=ssl.create_default_context())
        if user and password:
            s.login(user, password)
        s.send_message(msg)
    return f"sent to {len(to)} recipient(s)"


def send_report(cfg, *, week: str, findings: list[str], html: str) -> dict:
    """Deliver via every configured channel. Returns a per-channel status map;
    never raises. Pings the healthcheck last (success unless a channel errored)."""
    d = getattr(cfg, "delivery", None) or {}
    results: dict[str, str] = {}
    ok = True

    if d.get("email"):
        try:
            results["email"] = _send_email(d["email"], week, html)
        except Exception as e:  # noqa: BLE001 - a channel must not abort the run
            results["email"] = f"error: {type(e).__name__}"
            _log.warning("email delivery failed: %s", e)
            ok = False

    for name, build in (("slack", slack_payload), ("teams", teams_payload)):
        chan = d.get(name)
        if not chan:
            continue
        url = _env(chan.get("webhook_url_env"))
        if not url:
            results[name] = "skipped: webhook_url_env unset"
            continue
        try:
            results[name] = f"posted ({_post_json(url, build(week, findings))})"
        except Exception as e:  # noqa: BLE001
            results[name] = f"error: {type(e).__name__}"
            _log.warning("%s delivery failed: %s", name, e)
            ok = False

    pa = d.get("power_automate")
    if pa:
        url = _env(pa.get("webhook_url_env"))
        if not url:
            results["power_automate"] = "skipped: webhook_url_env unset"
        else:
            try:
                payload = automation_payload(week, findings, html,
                                             include_report=bool(pa.get("include_report", True)))
                results["power_automate"] = f"posted ({_post_json(url, payload)})"
            except Exception as e:  # noqa: BLE001
                results["power_automate"] = f"error: {type(e).__name__}"
                _log.warning("power_automate delivery failed: %s", e)
                ok = False

    hc = d.get("healthcheck") or {}
    hc_url = _env(hc.get("ping_url_env"))
    if hc_url:
        ping = hc_url if ok else hc_url.rstrip("/") + "/fail"
        try:
            _get(ping)
            results["healthcheck"] = "pinged" if ok else "pinged /fail"
        except Exception as e:  # noqa: BLE001
            results["healthcheck"] = f"error: {type(e).__name__}"
            _log.warning("healthcheck ping failed: %s", e)

    return results
