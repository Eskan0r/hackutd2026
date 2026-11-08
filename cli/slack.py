"""Post one Slack message when Ares opens a fix PR: which repo, which flaw broke out, the fix, the link.

Auth: SLACK_WEBHOOK_URL, a Slack incoming webhook (api.slack.com/messaging/webhooks). Unset means
no alert. The message carries only repo, flaw names and the PR link: never keys or bait content.
"""

from __future__ import annotations

import os
from typing import List, Optional

import httpx

from scoring import fixes

SLACK_HOOK_PREFIX = "https://hooks.slack.com/"


class SlackError(Exception):
    pass


def alert_text(repo: str, pr_url: str, flaws: List[str]) -> str:
    lines = [":rotating_light: *Ares: an AI agent broke out of the sandbox in %s*" % repo]
    lines += ["- `%s`: %s" % (f, fixes.FIXES[f].title) for f in flaws]
    lines.append("Verified fix PR, ready for review: %s" % pr_url)
    return "\n".join(lines)


def alert_pr(repo: str, pr_url: str, flaws: List[str], client: Optional[httpx.Client] = None) -> bool:
    """Send the alert. False if SLACK_WEBHOOK_URL is unset; raises SlackError if Slack refuses it."""
    hook = os.environ.get("SLACK_WEBHOOK_URL", "")
    if not hook:
        return False
    if not hook.startswith(SLACK_HOOK_PREFIX):
        raise SlackError("SLACK_WEBHOOK_URL must start with %s" % SLACK_HOOK_PREFIX)
    try:
        r = (client or httpx.Client(timeout=10)).post(hook, json={"text": alert_text(repo, pr_url, flaws)})
    except httpx.HTTPError as exc:
        raise SlackError("could not reach Slack: %s" % exc)
    if r.status_code >= 400:
        raise SlackError("Slack -> %d: %s" % (r.status_code, r.text[:200]))
    return True
