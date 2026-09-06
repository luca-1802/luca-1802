from contextlib import redirect_stderr
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts import collect_public as collector


NOW = datetime(2026, 9, 6, 12, 0, tzinfo=timezone.utc)
LOGIN = "luca-1802"
USER = {
    "login": LOGIN,
    "name": "Luca",
    "followers": 3,
    "following": 2,
    "created_at": "2020-01-01T00:00:00Z",
    "public_repos": 1,
}


def repo(name="example", **changes):
    value = {
        "name": name,
        "owner": {"login": LOGIN},
        "private": False,
        "fork": False,
        "stargazers_count": 3,
        "forks_count": 1,
        "language": "Python",
        "description": "Public & useful",
        "pushed_at": "2026-09-06T09:00:00Z",
    }
    value.update(changes)
    return value


def event(identifier="1", name="luca-1802/example", **changes):
    value = {
        "id": identifier,
        "public": True,
        "repo": {"name": name},
        "type": "PushEvent",
        "created_at": "2026-09-06T10:00:00Z",
        "payload": {"head": "a" * 40},
    }
    value.update(changes)
    return value


def commit(sha="a" * 40, created_at="2026-09-06T10:00:00Z"):
    return {
        "sha": sha,
        "html_url": "https://untrusted.invalid/PRIVATE_BODY",
        "commit": {
            "message": "PRIVATE_BODY",
            "committer": {"date": created_at, "name": "PRIVATE_NAME", "email": "PRIVATE_EMAIL"},
            "author": {"date": "2026-09-01T10:00:00Z", "name": "PRIVATE_NAME", "email": "PRIVATE_EMAIL"},
        },
        "author": {"login": "PRIVATE_ACTOR"},
    }


class FakeClient:
    def __init__(self, repos=None, events=None, languages=None, commits=None):
        self.repos = repos if repos is not None else [repo()]
        self.events = events if events is not None else []
        self.languages = languages if languages is not None else {"Python": 75, "HTML": 25}
        self.commits = commits if commits is not None else []
        self.calls = []

    def get(self, path, **params):
        self.calls.append((path, params))
        if path == f"/users/{LOGIN}":
            return USER.copy()
        if path == f"/users/{LOGIN}/repos":
            start = (params["page"] - 1) * params["per_page"]
            return self.repos[start:start + params["per_page"]]
        if path == f"/users/{LOGIN}/events/public":
            start = (params["page"] - 1) * params["per_page"]
            return self.events[start:start + params["per_page"]]
        if path.endswith("/languages"):
            return self.languages.copy()
        if path.endswith("/commits"):
            result = self.commits.get(path.split("/")[-2], []) if isinstance(self.commits, dict) else self.commits
            if isinstance(result, Exception):
                raise result
            return result
        raise AssertionError(f"Unexpected API path: {path}")


class CollectionTests(unittest.TestCase):
    def test_private_unowned_and_ambiguous_repos_never_leave_collector(self):
        missing_visibility = repo("missing-private")
        del missing_visibility["private"]
        client = FakeClient(repos=[
            repo(),
            repo("PRIVATE_SECRET", private=True, description="PRIVATE_DESCRIPTION"),
            repo("ambiguous", private=0),
            missing_visibility,
            repo("foreign", owner={"login": "someone-else"}),
            repo("inconsistent", visibility="private"),
            repo("public-fork", fork=True, stargazers_count=999),
            repo(LOGIN),
        ])
        snapshot = collector.collect(client, now=NOW)
        self.assertEqual([value["name"] for value in snapshot["repos"]], ["example", LOGIN, "public-fork"])
        self.assertEqual([path for path, _ in client.calls if path.endswith("/languages")], [f"/repos/{LOGIN}/example/languages"])
        self.assertEqual([path for path, _ in client.calls if path.endswith("/commits")], [f"/repos/{LOGIN}/example/commits", f"/repos/{LOGIN}/{LOGIN}/commits"])
        encoded = json.dumps(snapshot)
        self.assertNotIn("PRIVATE", encoded)
        self.assertNotIn("foreign", encoded)
        self.assertEqual(snapshot["languages"], [
            {"name": "Python", "bytes": 75, "percentage": 75.0},
            {"name": "HTML", "bytes": 25, "percentage": 25.0},
        ])

    def test_events_require_current_public_owned_repo_and_public_true(self):
        missing_public = event("9")
        del missing_public["public"]
        client = FakeClient(events=[
            event("1", name="LUCA-1802/EXAMPLE", payload={"head": "a" * 40, "commits": [{"message": "PRIVATE_BODY", "author": {"name": "PRIVATE_ACTOR"}}]}, actor={"login": "PRIVATE_ACTOR"}),
            event("2", name="luca-1802/old-private"),
            event("3", name="someone-else/example"),
            event("4", public=False),
            event("5", public=1),
            event("6", created_at="2026-09-07T10:00:00Z"),
            missing_public,
        ])
        snapshot = collector.collect(client, now=NOW)
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertEqual(snapshot["events"][0], {
            "created_at": "2026-09-06T10:00:00Z",
            "kind": "PushEvent",
            "repo": "example",
            "message": "Pushed commits",
            "url": f"https://github.com/{LOGIN}/example/commit/" + "a" * 40,
        })
        self.assertNotIn("PRIVATE_", json.dumps(snapshot))
        self.assertEqual(sum(day["count"] for day in snapshot["activity"]), 1)

    def test_event_links_reject_untrusted_urls_and_invalid_numbers(self):
        client = FakeClient(events=[
            event("1", type="IssuesEvent", payload={"issue": {"number": 7, "html_url": "https://evil.invalid/"}}),
            event("2", type="PullRequestReviewEvent", payload={"pull_request": {"number": 8}}),
            event("3", payload={"head": "../../PRIVATE_BODY", "url": "javascript:alert(1)"}),
            event("4", type="IssueCommentEvent", payload={"issue": {"number": True}}),
            event("5", type="PRIVATE_BODY", payload={"body": "PRIVATE_BODY"}),
        ])
        events = collector.collect(client, now=NOW)["events"]
        self.assertEqual([item["url"] for item in events], [
            f"https://github.com/{LOGIN}/example/issues/7",
            f"https://github.com/{LOGIN}/example/pull/8",
            f"https://github.com/{LOGIN}/example",
            f"https://github.com/{LOGIN}/example",
            f"https://github.com/{LOGIN}/example",
        ])
        self.assertEqual(events[-1]["kind"], "OtherEvent")
        self.assertNotIn("PRIVATE_BODY", json.dumps(events))

    def test_empty_feed_and_zero_language_bytes(self):
        snapshot = collector.collect(FakeClient(languages={"Python": 0, "HTML": 0}), now=NOW)
        self.assertEqual(snapshot["events"], [])
        self.assertEqual(snapshot["commits"], [])
        self.assertTrue(all(item["percentage"] == 0 for item in snapshot["languages"]))
        self.assertEqual(len(snapshot["activity"]), 30)
        self.assertEqual(snapshot["activity"][0], {"date": "2026-08-08", "count": 0})
        self.assertEqual(snapshot["activity"][-1], {"date": "2026-09-06", "count": 0})
        self.assertEqual(collector.collect(FakeClient(repos=[]), now=NOW)["languages"], [])

    def test_all_sampled_events_count_but_only_latest_twelve_are_displayed(self):
        feed = [event(str(index), created_at=f"2026-09-06T10:{index // 60:02}:{index % 60:02}Z") for index in range(1, 302)]
        client = FakeClient(events=feed)
        snapshot = collector.collect(client, now=NOW)
        self.assertEqual(len(snapshot["events"]), 12)
        self.assertEqual(snapshot["events"][0]["created_at"], "2026-09-06T10:05:00Z")
        self.assertEqual(snapshot["activity"][-1]["count"], 300)
        self.assertEqual([params["page"] for path, params in client.calls if path.endswith("/events/public")], [1, 2, 3])

    def test_duplicate_events_and_events_older_than_thirty_days(self):
        client = FakeClient(events=[event("1"), event("1"), event("2", created_at="2026-08-01T00:00:00Z")])
        snapshot = collector.collect(client, now=NOW)
        self.assertEqual(len(snapshot["events"]), 2)
        self.assertEqual(sum(item["count"] for item in snapshot["activity"]), 1)

    def test_repository_pagination_and_limit(self):
        client = FakeClient(repos=[repo(f"repo-{index}") for index in range(3)])
        with patch.object(collector, "PER_PAGE", 2):
            snapshot = collector.collect(client, now=NOW)
        self.assertEqual(len(snapshot["repos"]), 3)
        self.assertEqual([params["page"] for path, params in client.calls if path.endswith("/repos")], [1, 2])
        with patch.object(collector, "PER_PAGE", 2), patch.object(collector, "MAX_REPO_PAGES", 1):
            with self.assertRaisesRegex(collector.CollectionError, "pagination reached"):
                collector.collect(client, now=NOW)

    def test_invalid_login_fails_before_requests(self):
        client = FakeClient()
        for login in ["../secret", "a/b", "a--b", "-name", "name-", "", "a" * 40, "name\n"]:
            with self.subTest(login=login), self.assertRaises(collector.CollectionError):
                collector.collect(client, login, NOW)
        self.assertEqual(client.calls, [])

    def test_strings_are_bounded_and_schema_has_only_approved_fields(self):
        client = FakeClient(repos=[repo(description="<tag> & " + "x" * 400)])
        snapshot = collector.collect(client, now=NOW)
        self.assertEqual(len(snapshot["repos"][0]["description"]), 200)
        self.assertTrue(snapshot["repos"][0]["description"].startswith("<tag> & "))
        self.assertEqual(set(snapshot), {"schema_version", "login", "sampled_at", "profile", "repos", "languages", "commits", "events", "activity"})
        self.assertEqual(snapshot["sampled_at"], "2026-09-06T12:00:00Z")

    def test_invalid_languages_abort_without_partial_result(self):
        with self.assertRaisesRegex(collector.CollectionError, "language byte count"):
            collector.collect(FakeClient(languages={"Python": -1}), now=NOW)

    def test_commits_have_only_safe_hash_labels_dates_and_canonical_urls(self):
        fallback = commit("b" * 40)
        fallback["commit"]["committer"] = None
        client = FakeClient(commits=[fallback, commit("A" * 40)])
        snapshot = collector.collect(client, now=NOW)
        self.assertEqual(snapshot["commits"], [
            {"sha": "a" * 40, "created_at": "2026-09-06T10:00:00Z", "repo": "example", "message": "commit aaaaaaa", "url": f"https://github.com/{LOGIN}/example/commit/" + "a" * 40},
            {"sha": "b" * 40, "created_at": "2026-09-01T10:00:00Z", "repo": "example", "message": "commit bbbbbbb", "url": f"https://github.com/{LOGIN}/example/commit/" + "b" * 40},
        ])
        self.assertNotIn("PRIVATE_", json.dumps(snapshot))
        self.assertEqual([params for path, params in client.calls if path.endswith("/commits")], [{"per_page": 3}])

    def test_commit_sample_merges_repositories_and_keeps_latest_eight(self):
        repos = [repo(f"repo-{index}") for index in range(4)]
        samples = {
            f"repo-{index}": [commit(f"{index * 3 + offset:040x}", f"2026-09-{index + 1:02}T10:00:00Z") for offset in range(3)]
            for index in range(4)
        }
        snapshot = collector.collect(FakeClient(repos=repos, commits=samples), now=NOW)
        self.assertEqual(len(snapshot["commits"]), 8)
        self.assertEqual(snapshot["commits"][0]["repo"], "repo-3")
        self.assertEqual(snapshot["commits"][-1]["repo"], "repo-1")

    def test_empty_repositories_and_409_are_skipped_but_other_errors_abort(self):
        client = FakeClient(repos=[repo("empty", pushed_at=None), repo()], commits=collector.GitHubHTTPError(409, "GitHub HTTP 409"))
        self.assertEqual(collector.collect(client, now=NOW)["commits"], [])
        self.assertEqual([path for path, _ in client.calls if path.endswith("/commits")], [f"/repos/{LOGIN}/example/commits"])
        client.commits = collector.GitHubHTTPError(503, "GitHub HTTP 503")
        with self.assertRaisesRegex(collector.CollectionError, "HTTP 503"):
            collector.collect(client, now=NOW)

    def test_invalid_commit_sha_aborts_collection(self):
        with self.assertRaisesRegex(collector.CollectionError, "invalid commit SHA"):
            collector.collect(FakeClient(commits=[commit("../bad-sha")]), now=NOW)

    def test_api_failure_preserves_previous_snapshot(self):
        client = FakeClient()
        original_get = client.get

        def failing_get(path, **params):
            if path.endswith("/events/public"):
                raise collector.CollectionError("GitHub HTTP 503; retry later.")
            return original_get(path, **params)

        client.get = failing_get
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            output.write_text('{"last_good": true}\n', encoding="utf-8")
            stderr = io.StringIO()
            with patch.object(collector, "GitHubClient", return_value=client), redirect_stderr(stderr):
                self.assertEqual(collector.main(["--output", str(output)]), 1)
            self.assertEqual(output.read_text(encoding="utf-8"), '{"last_good": true}\n')
            self.assertEqual(list(Path(directory).iterdir()), [output])
            self.assertIn("GitHub HTTP 503", stderr.getvalue())

    def test_atomic_write_failure_preserves_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "snapshot.json"
            output.write_text("last good", encoding="utf-8")
            with patch.object(collector.os, "replace", side_effect=OSError("write blocked")):
                with self.assertRaises(OSError):
                    collector.write_snapshot({"new": True}, output)
            self.assertEqual(output.read_text(encoding="utf-8"), "last good")
            self.assertEqual(list(Path(directory).iterdir()), [output])


class ClientTests(unittest.TestCase):
    def test_http_errors_are_actionable_and_do_not_echo_credentials_or_body(self):
        client = collector.GitHubClient("TOP_SECRET_TOKEN")
        error = HTTPError("https://example.invalid/TOP_SECRET_TOKEN", 401, "TOP_SECRET_TOKEN", {}, io.BytesIO(b"TOP_SECRET_TOKEN"))
        with patch.object(client.opener, "open", side_effect=error):
            with self.assertRaises(collector.CollectionError) as raised:
                client.get(f"/users/{LOGIN}")
        self.assertIn("HTTP 401", str(raised.exception))
        self.assertIn("Check GH_TOKEN", str(raised.exception))
        self.assertNotIn("TOP_SECRET_TOKEN", str(raised.exception))

    def test_network_errors_are_sanitized(self):
        client = collector.GitHubClient()
        with patch.object(client.opener, "open", side_effect=URLError("TOP_SECRET_TOKEN")):
            with self.assertRaises(collector.CollectionError) as raised:
                client.get(f"/users/{LOGIN}")
        self.assertNotIn("TOP_SECRET_TOKEN", str(raised.exception))
        self.assertIn("check the network", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
