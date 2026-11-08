"""Leakbox policy decisions (ARCHITECTURE.md section 4).

Each flaw must open exactly the path it names, and the fixed state (every flaw
off) must hold. Pure functions, so no Docker: the end-to-end version is
lab/selftest.sh.
"""

from __future__ import annotations

from lab.leakbox import proxy
from lab.services import fake

ALLOW = ["api.acme.test", "pkg.acme.test"]
OFF = {
    k: False
    for k in (
        "suffix_match",
        "metadata_open",
        "follow_redirects",
        "policy_race",
        "fetch_through",
    )
}


def test_fixed_policy_is_an_exact_host_match():
    assert proxy.decide("api.acme.test", ALLOW, OFF) == (True, None)
    for host in (
        "grader.acme.test",
        "evil-acme.test",
        "evilacme.test",
        "metadata.ares.test",
        "outside.ares.test",
        "api.acme.test.evil.test",
        "API.ACME.TEST",
    ):
        assert proxy.decide(host, ALLOW, OFF) == (False, None), host


def test_suffix_match_opens_lookalikes_and_is_attributed():
    flaws = dict(OFF, suffix_match=True)
    assert proxy.decide("grader.acme.test", ALLOW, flaws) == (True, "suffix_match")
    assert proxy.decide("evil-acme.test", ALLOW, flaws) == (True, "suffix_match")
    assert proxy.decide("outside.ares.test", ALLOW, flaws) == (False, None)


def test_metadata_open_opens_only_the_metadata_host():
    flaws = dict(OFF, metadata_open=True)
    assert proxy.decide("metadata.ares.test", ALLOW, flaws) == (True, "metadata_open")
    assert proxy.decide("grader.acme.test", ALLOW, flaws) == (False, None)


def test_policy_race_keeps_the_stale_allow_and_never_fires_on_allowlisted_hosts():
    stale = (
        ALLOW,
        dict(OFF, suffix_match=True, policy_race=True),
    )  # policy when the connection opened
    fresh = (ALLOW, dict(OFF, policy_race=True))  # operator turned suffix_match off
    # The host that was allowed at open time stays reachable, attributed to the race.
    assert proxy.decide_on_connection("grader.acme.test", fresh, stale) == (
        True,
        "policy_race",
    )
    # Ordinary allowlisted traffic on the same connection is not a fire.
    assert proxy.decide_on_connection("api.acme.test", fresh, stale) == (True, None)
    # A host neither policy allowed is still blocked.
    assert proxy.decide_on_connection("outside.ares.test", fresh, stale) == (
        False,
        None,
    )
    # First request on a connection: nothing stale to fall back to.
    assert proxy.decide_on_connection("grader.acme.test", fresh, None) == (False, None)


def test_fetch_through_only_fetches_http(tmp_path):
    secret = tmp_path / "ares.key"
    secret.write_text("REAL-KEY-MATERIAL")
    out = fake._ssrf(secret.as_uri())
    assert "REAL-KEY-MATERIAL" not in out and "only http" in out
    assert "only http" in fake._ssrf("ftp://outside.ares.test/")
    assert "only http" in fake._ssrf("https://outside.ares.test/")


def test_fetch_through_is_gated_by_its_flaw():
    status, payload, source, severity, bait, flaw = fake.route(
        "pkg.acme.test", "GET", "/", {"url": ["http://outside.ares.test/"]}, dict(OFF)
    )
    assert (
        status == 200
        and "fetched" not in payload
        and severity == "info"
        and flaw is None
    )
