"""Tests for the Withings direct API connector.

All network is mocked (``withings.urlopen`` patched); fixtures model the public
API shapes from developer.withings.com, including both Withings quirks:

  * the ``{"status": 0, "body": {...}}`` envelope on every response,
  * token refresh through ``action=requesttoken`` + ``grant_type=refresh_token``,
  * mantissa+exponent measure values (75.5 kg -> value=75500, unit=-3).

Run directly:  PYTHONPATH=$PWD python3 tests/test_withings.py
"""

import json
import os
import stat
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from openhealth.connectors import withings


def _wrap(body, status=0, error=None):
    payload = {"status": status, "body": body}
    if error is not None:
        payload["error"] = error
    return payload


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(responses, calls):
    """Sequential fake: records (url, parsed form body, headers) per call."""
    queue = list(responses)

    def opener(request, timeout=0):
        body = parse_qs((request.data or b"").decode("utf-8"))
        flat = {k: v[0] for k, v in body.items()}
        calls.append({"url": request.full_url, "body": flat, "headers": dict(request.header_items())})
        return _FakeResponse(queue.pop(0))

    return opener


TOKEN_BODY = {
    "userid": 12345,
    "access_token": "acc-1",
    "refresh_token": "ref-1",
    "expires_in": 10800,
    "scope": "user.metrics,user.activity",
    "token_type": "Bearer",
}

# getmeas: weight 75.5 kg, fat 20.5 %, muscle 55.2 kg, bone 3.1 kg,
# bp 120/80 mmHg, hr 65 bpm. 2026-06-01 12:00:00 UTC = 1780315200.
GETMEAS_BODY = {
    "updatetime": 1780401600,
    "timezone": "UTC",
    "measuregrps": [
        {
            "grpid": 1,
            "date": 1780315200,
            "category": 1,
            "measures": [
                {"value": 75500, "type": 1, "unit": -3},
                {"value": 2050, "type": 6, "unit": -2},
                {"value": 55200, "type": 76, "unit": -3},
                {"value": 31, "type": 88, "unit": -1},
            ],
        },
        {
            "grpid": 2,
            "date": 1780315260,
            "category": 1,
            "measures": [
                {"value": 120, "type": 10, "unit": 0},
                {"value": 80, "type": 9, "unit": 0},
                {"value": 65, "type": 11, "unit": 0},
                {"value": 42, "type": 999, "unit": 0},  # unknown meastype: skipped
            ],
        },
    ],
}

SLEEP_BODY = {
    "series": [
        {
            "id": 1,
            "date": "2026-06-01",
            "data": {
                "total_sleep_time": 27000,  # 7.5 h
                "deepsleepduration": 6480,  # 1.8 h
                "remsleepduration": 5400,  # 1.5 h
                "lightsleepduration": 15120,  # 4.2 h
                "durationtosleep": 600,  # 10 min
                "hr_average": 52,
            },
        },
        {
            # No total_sleep_time: duration falls back to deep+rem+light.
            "id": 2,
            "date": "2026-06-02",
            "data": {
                "deepsleepduration": 7200,
                "remsleepduration": 3600,
                "lightsleepduration": 14400,
            },
        },
    ],
    "more": False,
    "offset": 0,
}


def _by(records, metric, date=None):
    for r in records:
        if r["metric_name"] == metric and (date is None or r["date"] == date):
            return r
    return None


class WithingsTestCase(unittest.TestCase):
    """Isolated OPENHEALTH_HOME per test; client creds from env fallback."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = {
            "OPENHEALTH_HOME": os.environ.get("OPENHEALTH_HOME"),
            withings.ENV_CLIENT_ID: os.environ.get(withings.ENV_CLIENT_ID),
            withings.ENV_CLIENT_SECRET: os.environ.get(withings.ENV_CLIENT_SECRET),
        }
        os.environ["OPENHEALTH_HOME"] = self._tmp.name
        os.environ[withings.ENV_CLIENT_ID] = "cid-env"
        os.environ[withings.ENV_CLIENT_SECRET] = "csec-env"

    def tearDown(self):
        for key, value in self._env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self._tmp.cleanup()

    def _write_config(self, tokens=None, client_id="cid-file", client_secret="csec-file"):
        withings.save_config(
            {"client_id": client_id, "client_secret": client_secret, "tokens": tokens}
        )


class ConfigTests(WithingsTestCase):
    def test_save_config_is_private_0600(self):
        self._write_config()
        path = withings.withings_config_path()
        self.assertTrue(path.is_file())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_load_config_prefers_file_over_env(self):
        self._write_config()
        config = withings.load_config()
        self.assertEqual(config["client_id"], "cid-file")
        self.assertEqual(config["client_secret"], "csec-file")

    def test_load_config_env_fallback_when_no_file(self):
        config = withings.load_config()
        self.assertEqual(config["client_id"], "cid-env")
        self.assertEqual(config["client_secret"], "csec-env")
        self.assertIsNone(config["tokens"])

    def test_missing_credentials_raise_not_configured(self):
        os.environ.pop(withings.ENV_CLIENT_ID)
        os.environ.pop(withings.ENV_CLIENT_SECRET)
        with self.assertRaises(withings.WithingsNotConfigured):
            withings.auth_url("http://localhost:8765/callback", state="abc")


class AuthTests(WithingsTestCase):
    def test_auth_url_contains_oauth_params(self):
        url = withings.auth_url("http://localhost:8765/callback", state="state42")
        parsed = urlparse(url)
        self.assertEqual(parsed.scheme + "://" + parsed.netloc + parsed.path, withings.AUTHORIZE_URL)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.assertEqual(query["response_type"], "code")
        self.assertEqual(query["client_id"], "cid-env")
        self.assertEqual(query["redirect_uri"], "http://localhost:8765/callback")
        self.assertEqual(query["scope"], "user.metrics,user.activity")
        self.assertEqual(query["state"], "state42")

    def test_exchange_code_unwraps_envelope_and_persists_tokens(self):
        calls = []
        with patch.object(withings, "urlopen", _fake_urlopen([_wrap(TOKEN_BODY)], calls)):
            tokens = withings.exchange_code("the-code", "http://localhost:8765/callback")

        # Non-standard Withings token call: action=requesttoken on /v2/oauth2.
        self.assertEqual(calls[0]["url"], withings.TOKEN_URL)
        self.assertEqual(calls[0]["body"]["action"], "requesttoken")
        self.assertEqual(calls[0]["body"]["grant_type"], "authorization_code")
        self.assertEqual(calls[0]["body"]["code"], "the-code")

        self.assertEqual(tokens["access_token"], "acc-1")
        self.assertEqual(tokens["refresh_token"], "ref-1")
        self.assertGreater(tokens["expires_at"], int(time.time()))

        saved = json.loads(withings.withings_config_path().read_text(encoding="utf-8"))
        self.assertEqual(saved["tokens"]["access_token"], "acc-1")
        self.assertEqual(stat.S_IMODE(withings.withings_config_path().stat().st_mode), 0o600)

    def test_refresh_goes_through_requesttoken_grant(self):
        self._write_config(tokens={"access_token": "old", "refresh_token": "ref-old", "expires_at": 100})
        refreshed_body = dict(TOKEN_BODY, access_token="acc-2", refresh_token="ref-2")
        calls = []
        with patch.object(withings, "urlopen", _fake_urlopen([_wrap(refreshed_body)], calls)):
            token = withings.ensure_access_token()

        self.assertEqual(token, "acc-2")
        self.assertEqual(calls[0]["url"], withings.TOKEN_URL)
        self.assertEqual(calls[0]["body"]["action"], "requesttoken")
        self.assertEqual(calls[0]["body"]["grant_type"], "refresh_token")
        self.assertEqual(calls[0]["body"]["refresh_token"], "ref-old")
        # Rotated refresh token persisted.
        saved = json.loads(withings.withings_config_path().read_text(encoding="utf-8"))
        self.assertEqual(saved["tokens"]["refresh_token"], "ref-2")

    def test_fresh_token_is_not_refreshed(self):
        self._write_config(
            tokens={"access_token": "acc-fresh", "refresh_token": "r", "expires_at": int(time.time()) + 3600}
        )
        calls = []
        with patch.object(withings, "urlopen", _fake_urlopen([], calls)):
            token = withings.ensure_access_token()
        self.assertEqual(token, "acc-fresh")
        self.assertEqual(calls, [])

    def test_missing_tokens_raise_not_configured(self):
        self._write_config(tokens=None)
        with self.assertRaises(withings.WithingsNotConfigured):
            withings.ensure_access_token()


class EnvelopeErrorTests(WithingsTestCase):
    def test_nonzero_status_raises_with_code(self):
        self._write_config(
            tokens={"access_token": "acc", "refresh_token": "r", "expires_at": int(time.time()) + 3600}
        )
        calls = []
        fake = _fake_urlopen([_wrap({}, status=401, error="The access token provided is invalid")], calls)
        with patch.object(withings, "urlopen", fake):
            with self.assertRaises(withings.WithingsError) as ctx:
                withings.fetch_measures("2026-06-01", "2026-06-02")
        self.assertIn("status=401", str(ctx.exception))
        self.assertIn("invalid", str(ctx.exception))

    def test_payload_without_envelope_raises(self):
        with self.assertRaises(withings.WithingsError):
            withings._unwrap({"access_token": "x"}, "token request")


class MeasureTests(WithingsTestCase):
    def setUp(self):
        super().setUp()
        self._write_config(
            tokens={"access_token": "acc", "refresh_token": "r", "expires_at": int(time.time()) + 3600}
        )

    def test_meastype_mapping_and_unit_exponent(self):
        calls = []
        with patch.object(withings, "urlopen", _fake_urlopen([_wrap(GETMEAS_BODY)], calls)):
            records = withings.fetch_measures("2026-06-01", "2026-06-02")

        self.assertEqual(calls[0]["url"], withings.MEASURE_URL)
        self.assertEqual(calls[0]["body"]["action"], "getmeas")
        self.assertEqual(calls[0]["body"]["category"], "1")
        self.assertEqual(calls[0]["headers"].get("Authorization"), "Bearer acc")

        # value * 10 ** unit decoding.
        self.assertEqual(_by(records, "weight_kg")["value"], 75.5)
        self.assertEqual(_by(records, "body_fat_pct")["value"], 20.5)
        self.assertEqual(_by(records, "muscle_mass_kg")["value"], 55.2)
        self.assertEqual(_by(records, "bone_mass_kg")["value"], 3.1)
        self.assertEqual(_by(records, "bp_systolic")["value"], 120)
        self.assertEqual(_by(records, "bp_diastolic")["value"], 80)
        self.assertEqual(_by(records, "hr_bpm")["value"], 65)
        # Unknown meastype 999 never produces a record.
        self.assertEqual(len(records), 7)

        weight = _by(records, "weight_kg")
        self.assertEqual(weight["date"], "2026-06-01")  # from measuregrp.date unix
        self.assertEqual(weight["source_id"], "withings")
        self.assertEqual(weight["confidence"], 0.9)
        self.assertEqual(weight["unit"], "kg")
        self.assertEqual(weight["record_type"], "Observation")
        self.assertIn("withings", weight["tags"])

    def test_latest_reading_per_day_wins(self):
        body = {
            "measuregrps": [
                {"date": 1780315200, "measures": [{"value": 76000, "type": 1, "unit": -3}]},  # 12:00
                {"date": 1780344000, "measures": [{"value": 75200, "type": 1, "unit": -3}]},  # 20:00
            ]
        }
        with patch.object(withings, "urlopen", _fake_urlopen([_wrap(body)], [])):
            records = withings.fetch_measures("2026-06-01", "2026-06-01")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["value"], 75.2)

    def test_pagination_follows_more_offset(self):
        page1 = {
            "measuregrps": [{"date": 1780315200, "measures": [{"value": 75500, "type": 1, "unit": -3}]}],
            "more": True,
            "offset": 17,
        }
        page2 = {
            "measuregrps": [{"date": 1780401600, "measures": [{"value": 75100, "type": 1, "unit": -3}]}],
            "more": False,
        }
        calls = []
        with patch.object(withings, "urlopen", _fake_urlopen([_wrap(page1), _wrap(page2)], calls)):
            records = withings.fetch_measures("2026-06-01", "2026-06-02")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("offset", calls[0]["body"])
        self.assertEqual(calls[1]["body"]["offset"], "17")
        self.assertEqual(len(records), 2)

    def test_bad_date_raises(self):
        with self.assertRaises(withings.WithingsError):
            withings.fetch_measures("yesterday-ish", "2026-06-02")


class SleepTests(WithingsTestCase):
    def setUp(self):
        super().setUp()
        self._write_config(
            tokens={"access_token": "acc", "refresh_token": "r", "expires_at": int(time.time()) + 3600}
        )

    def test_sleep_summary_mapping_seconds_to_hours(self):
        calls = []
        with patch.object(withings, "urlopen", _fake_urlopen([_wrap(SLEEP_BODY)], calls)):
            records = withings.fetch_sleep_summary("2026-06-01", "2026-06-03")

        self.assertEqual(calls[0]["url"], withings.SLEEP_URL)
        self.assertEqual(calls[0]["body"]["action"], "getsummary")
        self.assertEqual(calls[0]["body"]["startdateymd"], "2026-06-01")
        self.assertEqual(calls[0]["body"]["enddateymd"], "2026-06-03")

        self.assertEqual(_by(records, "sleep_duration_h", "2026-06-01")["value"], 7.5)
        self.assertEqual(_by(records, "sleep_deep_h", "2026-06-01")["value"], 1.8)
        self.assertEqual(_by(records, "sleep_rem_h", "2026-06-01")["value"], 1.5)
        self.assertEqual(_by(records, "sleep_light_h", "2026-06-01")["value"], 4.2)
        self.assertEqual(_by(records, "sleep_latency_min", "2026-06-01")["value"], 10.0)
        self.assertEqual(_by(records, "sleep_hr_avg_bpm", "2026-06-01")["value"], 52)

        # Night without total_sleep_time: duration = deep + rem + light.
        fallback = _by(records, "sleep_duration_h", "2026-06-02")
        self.assertEqual(fallback["value"], 7.0)
        self.assertEqual(fallback["source_id"], "withings")
        self.assertEqual(fallback["confidence"], 0.9)


class SummarizeTests(WithingsTestCase):
    def test_summarize_rollup(self):
        records = [
            withings._obs("2026-06-01", "weight", "weight_kg", 75.5, "kg", "body"),
            withings._obs("2026-06-02", "weight", "weight_kg", 75.2, "kg", "body"),
            withings._obs("2026-06-02", "sleep_session", "sleep_duration_h", 7.5, "h", "sleep"),
        ]
        info = withings.summarize(records)
        self.assertEqual(info["source"], "withings")
        self.assertEqual(info["total_records"], 3)
        self.assertEqual(info["metrics"], {"sleep_duration_h": 1, "weight_kg": 2})
        self.assertEqual(info["date_from"], "2026-06-01")
        self.assertEqual(info["date_to"], "2026-06-02")


if __name__ == "__main__":
    unittest.main()
