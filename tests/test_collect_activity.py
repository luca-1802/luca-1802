from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.message import Message
from http.client import IncompleteRead
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from scripts import collect_activity as collector


NOW = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)
# Relevant fields from the services' responses, sampled on 2026-09-08.
STATS = b'''<svg xmlns="http://www.w3.org/2000/svg">
  <title id="titleId">Luca's GitHub Stats, Rank: B</title>
  <desc id="descId">Total Stars Earned: 5, Total Commits  : 966, Total PRs: 64, Total Issues: 79, Contributed to (last year): 5</desc>
  <g><text data-testid="level-rank-icon">B</text></g>
</svg>'''
STREAK = {
    "mode": "daily",
    "totalContributions": 1148,
    "firstContribution": "2022-10-20",
    "longestStreak": {"start": "2026-03-02", "end": "2026-03-14", "length": 13},
    "currentStreak": {"start": "2026-09-04", "end": "2026-09-08", "length": 5},
    "excludedDays": [],
}


def parse_streak(value):
    return collector.parse_streak(json.dumps(value).encode(), NOW.date())


class FakeClient:
    def get(self, source):
        return {"stats": STATS, "streak": json.dumps(STREAK).encode()}[source]


class StatsTests(unittest.TestCase):
    def test_exact_accessibility_totals_and_rank(self):
        self.assertEqual(collector.parse_stats(STATS), {
            "total_stars": 5, "total_commits": 966, "total_prs": 64,
            "total_issues": 79, "contributed_repos": 5, "rank": "B",
        })
        # Visible short-number display text must not replace exact totals.
        card = STATS.replace(b"966", b"12567").replace(b"</svg>", b'<text data-testid="commits">12.6k</text></svg>')
        self.assertEqual(collector.parse_stats(card)["total_commits"], 12567)

    def test_zero_counts_and_documented_ranks(self):
        zero = STATS.replace(b": 5", b": 0").replace(b": 966", b": 0").replace(b": 64", b": 0").replace(b": 79", b": 0")
        for rank in collector.RANKS:
            with self.subTest(rank=rank):
                parsed = collector.parse_stats(zero.replace(b">B<", b">" + rank.encode() + b"<"))
                self.assertEqual(parsed["total_commits"], 0)
                self.assertEqual(parsed["rank"], rank)

    def test_rejects_missing_duplicate_and_error_cards(self):
        invalid = [
            b'<svg xmlns="http://www.w3.org/2000/svg"><text>Something went wrong! PRIVATE_BODY</text></svg>',
            STATS.replace(b"<desc", b"<text").replace(b"</desc>", b"</text>"),
            STATS.replace(b"</svg>", b"<desc>duplicate</desc></svg>"),
            STATS.replace(b"</svg>", b'<text data-testid="level-rank-icon">B</text></svg>'),
            STATS.replace(b">B<", b">Z<"),
            STATS.replace(b", Total PRs: 64", b", Total PRs: 64, Total PRs: 64"),
            STATS.replace(b"</svg>", b""),
            STATS.replace(b"<svg ", b"<html ").replace(b"</svg>", b"</html>"),
            b'<!DOCTYPE svg [<!ENTITY secret "PRIVATE_BODY">]>' + STATS,
            b"\xff" + STATS,
            b"x" * (collector.MAX_RESPONSE_BYTES + 1),
        ]
        for card in invalid:
            with self.subTest(card=card[:80]):
                with self.assertRaises(collector.CollectionError):
                    collector.parse_stats(card)

    def test_rejects_invalid_counts(self):
        for value in [b"-1", b"true", b"False", b"1.5", b"1e3", b"1,000", b"1k", b"9223372036854775808", b""]:
            with self.subTest(value=value):
                with self.assertRaises(collector.CollectionError):
                    collector.parse_stats(STATS.replace(b"966", value))


class StreakTests(unittest.TestCase):
    def test_documented_json_format_matches_existing_card(self):
        self.assertEqual(parse_streak(STREAK), {
            "total_contributions": 1148, "current_days": 5, "longest_days": 13,
            "contribution_range": "Oct 20, 2022 - Present",
            "current_range": "Sep 4 - Sep 8", "longest_range": "Mar 2 - Mar 14",
        })

    def test_zero_state_from_upstream_get_contribution_stats(self):
        value = deepcopy(STREAK)
        value.update(totalContributions=0, firstContribution="")
        value["longestStreak"] = {"start": "2026-01-01", "end": "2026-01-01", "length": 0}
        value["currentStreak"] = {"start": "2026-09-08", "end": "2026-09-08", "length": 0}
        result = parse_streak(value)
        self.assertEqual(result["contribution_range"], "No contributions yet")
        self.assertEqual(result["current_range"], "Sep 8")
        self.assertEqual(result["longest_days"], 0)

    def test_broken_current_streak_and_single_day(self):
        value = deepcopy(STREAK)
        value["currentStreak"] = {"start": "2026-09-08", "end": "2026-09-08", "length": 0}
        self.assertEqual(parse_streak(value)["current_range"], "Sep 8")
        value["currentStreak"]["length"] = 1
        self.assertEqual(parse_streak(value)["current_days"], 1)

    def test_previous_year_and_cross_year_labels(self):
        value = deepcopy(STREAK)
        value["longestStreak"] = {"start": "2025-12-25", "end": "2026-01-06", "length": 13}
        self.assertEqual(parse_streak(value)["longest_range"], "Dec 25, 2025 - Jan 6")
        value["firstContribution"] = "2026-01-01"
        value["longestStreak"] = deepcopy(STREAK["longestStreak"])
        self.assertEqual(parse_streak(value)["contribution_range"], "Jan 1 - Present")

    def test_rejects_malformed_missing_error_or_duplicate_json(self):
        for raw in [b"{}", b"[]", b"null", b"false", b'{"error":"PRIVATE_BODY"}', b"<svg>error</svg>", b"\xff", b'{"mode":"daily","mode":"daily"}', b'{"currentStreak":{"length":1,"length":2}}']:
            with self.subTest(raw=raw):
                with self.assertRaises(collector.CollectionError):
                    collector.parse_streak(raw, NOW.date())
        for key in STREAK:
            value = deepcopy(STREAK)
            del value[key]
            with self.subTest(missing=key):
                with self.assertRaises(collector.CollectionError):
                    parse_streak(value)

    def test_rejects_invalid_numbers_for_every_count(self):
        for field in ["totalContributions", "currentStreak", "longestStreak"]:
            for invalid in [-1, True, False, 1.5, "5", None, 2**63, float("nan")]:
                value = deepcopy(STREAK)
                if field == "totalContributions":
                    value[field] = invalid
                else:
                    value[field]["length"] = invalid
                with self.subTest(field=field, value=invalid):
                    with self.assertRaises(collector.CollectionError):
                        parse_streak(value)

    def test_rejects_invalid_dates_modes_and_inconsistent_ranges(self):
        changes = [
            ("firstContribution", "2026-10-01"), ("firstContribution", ""),
            ("firstContribution", "2026-02-30"), ("firstContribution", "<script>PRIVATE_BODY</script>"),
            ("firstContribution", "2026-9-08"), ("mode", "weekly"),
            ("excludedDays", ["Sun"]), ("totalContributions", 4),
            ("error", "PRIVATE_BODY"),
            ("currentStreak", {"start": "2026-09-04", "end": "2026-09-08", "length": 0}),
            ("longestStreak", {"start": "2026-03-14", "end": "2026-03-02", "length": 13}),
            ("longestStreak", {"start": "2026-03-02", "end": "2026-03-14", "length": 12}),
        ]
        for key, replacement in changes:
            value = deepcopy(STREAK)
            value[key] = replacement
            with self.subTest(key=key, replacement=replacement):
                with self.assertRaises(collector.CollectionError):
                    parse_streak(value)


class CollectionTests(unittest.TestCase):
    def response(self, source, body):
        response = Mock()
        response.status = 200
        response.geturl.return_value = collector.SOURCES[source][0]
        response.headers = Message()
        response.headers["Content-Type"] = collector.SOURCES[source][1]
        response.read.return_value = body
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_fixed_sources_no_credentials_bounded_read_and_timeout(self):
        with patch.dict("os.environ", {"GH_TOKEN": "PRIVATE_TOKEN", "GITHUB_TOKEN": "PRIVATE_TOKEN"}), patch.object(collector, "build_opener") as opener:
            client = collector.ActivityClient()
            self.assertIsInstance(opener.call_args.args[0], collector.NoRedirects)
            for source in collector.SOURCES:
                response = self.response(source, b"data")
                opener.return_value.open.return_value = response
                self.assertEqual(client.get(source), b"data")
                request = opener.return_value.open.call_args.args[0]
                self.assertEqual(request.full_url, collector.SOURCES[source][0])
                headers = dict(request.header_items())
                self.assertEqual(set(name.lower() for name in headers), {"accept", "user-agent"})
                self.assertNotIn("PRIVATE_TOKEN", str(headers))
                self.assertEqual(opener.return_value.open.call_args.kwargs, {"timeout": collector.TIMEOUT_SECONDS})
                response.read.assert_called_once_with(collector.MAX_RESPONSE_BYTES + 1)
            opener.return_value.open.reset_mock()
            with self.assertRaises(collector.CollectionError):
                client.get("https://untrusted.invalid")
            opener.return_value.open.assert_not_called()

    def test_rejects_redirects_http_errors_and_network_failures_safely(self):
        self.assertIsNone(collector.NoRedirects().redirect_request(None, None, 302, "", {}, "https://untrusted.invalid"))
        for error in [HTTPError("https://PRIVATE_TOKEN.invalid", 302, "PRIVATE_BODY", {}, None), HTTPError("https://PRIVATE_TOKEN.invalid", 503, "PRIVATE_BODY", {}, None), URLError("PRIVATE_BODY"), TimeoutError("PRIVATE_BODY"), IncompleteRead(b"PRIVATE_BODY")]:
            with self.subTest(error=type(error).__name__), patch.object(collector, "build_opener") as opener:
                opener.return_value.open.side_effect = error
                with self.assertRaises(collector.CollectionError) as caught:
                    collector.ActivityClient().get("stats")
                self.assertNotIn("PRIVATE", str(caught.exception))

    def test_rejects_wrong_type_changed_url_status_and_oversize_body(self):
        for issue in ["type", "url", "status", "size"]:
            response = self.response("stats", b"data")
            if issue == "type":
                response.headers.replace_header("Content-Type", "text/html")
            elif issue == "url":
                response.geturl.return_value = "https://untrusted.invalid"
            elif issue == "status":
                response.status = 204
            else:
                response.read.return_value = b"x" * (collector.MAX_RESPONSE_BYTES + 1)
            with self.subTest(issue=issue), patch.object(collector, "build_opener") as opener:
                opener.return_value.open.return_value = response
                with self.assertRaises(collector.CollectionError):
                    collector.ActivityClient().get("stats")

    def test_snapshot_contract_utc_and_only_approved_fields(self):
        now = NOW.astimezone(timezone(timedelta(hours=2)))
        result = collector.collect(FakeClient(), now)
        self.assertEqual(set(result), {"schema_version", "login", "sampled_at", "stats", "streak"})
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["login"], "luca-1802")
        self.assertEqual(result["sampled_at"], "2026-09-08T10:00:00Z")
        self.assertNotIn("<svg", json.dumps(result))
        with self.assertRaises(collector.CollectionError):
            collector.collect(FakeClient(), NOW.replace(tzinfo=None))

    def test_cli_preserves_last_good_snapshot_when_either_source_fails(self):
        for failed in ["stats", "streak"]:
            def get(source):
                if source == failed:
                    return b"PRIVATE_BODY"
                return FakeClient().get(source)
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / "activity-data.json"
                output.write_bytes(b"last good snapshot\n")
                errors = io.StringIO()
                with patch.object(collector.ActivityClient, "get", side_effect=get), redirect_stderr(errors):
                    self.assertEqual(collector.main(["--output", str(output)]), 1)
                self.assertEqual(output.read_bytes(), b"last good snapshot\n")
                self.assertNotIn("PRIVATE_BODY", errors.getvalue())
                self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_cli_writes_complete_snapshot_and_atomic_replace_failure_preserves_it(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "activity-data.json"
            with patch.object(collector, "ActivityClient", return_value=FakeClient()), redirect_stdout(io.StringIO()):
                self.assertEqual(collector.main(["--output", str(output)]), 0)
            saved = output.read_bytes()
            self.assertEqual(json.loads(saved)["stats"]["total_commits"], 966)
            with patch.object(collector.os, "replace", side_effect=OSError("PRIVATE_PATH")):
                with self.assertRaises(OSError):
                    collector.write_snapshot({"replacement": True}, output)
            self.assertEqual(output.read_bytes(), saved)
            self.assertEqual(list(Path(directory).iterdir()), [output])


if __name__ == "__main__":
    unittest.main()
