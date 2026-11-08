"""cli/slack.py: one Slack message when Ares opens a fix PR. Hermetic: Slack is a MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from cli import slack

HOOK = "https://hooks.slack.com/services/T000/B000/xyz"
URL = "https://github.com/acme/sandbox/pull/1"


def _client(seen, status=200):
    def handle(req):
        seen.append(req)
        return httpx.Response(status, text="ok" if status == 200 else "invalid_token")

    return httpx.Client(transport=httpx.MockTransport(handle))


def test_no_webhook_means_nothing_is_sent():
    seen = []
    assert (
        slack.alert_pr("acme/sandbox", URL, ["suffix_match"], client=_client(seen))
        is False
    )
    assert seen == []


def test_alert_names_the_repo_flaw_fix_and_pr(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", HOOK)
    seen = []

    assert (
        slack.alert_pr(
            "acme/sandbox", URL, ["suffix_match", "fetch_through"], client=_client(seen)
        )
        is True
    )

    assert len(seen) == 1 and str(seen[0].url) == HOOK
    text = json.loads(seen[0].content)["text"]
    assert "acme/sandbox" in text and URL in text
    assert "`suffix_match`" in text and "`fetch_through`" in text
    assert (
        "Stop the package proxy fetching arbitrary URLs" in text
    )  # the fix title, not just the flag


def test_slack_error_is_raised_not_swallowed(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", HOOK)
    with pytest.raises(slack.SlackError, match="403"):
        slack.alert_pr(
            "acme/sandbox", URL, ["suffix_match"], client=_client([], status=403)
        )


def test_webhook_that_is_not_slack_is_refused(monkeypatch):
    """The message carries repo and flaw names; a typo'd URL must not send them somewhere else."""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://example.com/hook")
    seen = []
    with pytest.raises(slack.SlackError, match="hooks.slack.com"):
        slack.alert_pr("acme/sandbox", URL, ["suffix_match"], client=_client(seen))
    assert seen == []
