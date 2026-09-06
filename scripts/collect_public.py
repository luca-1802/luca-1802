#!/usr/bin/env python3
"""Collect a bounded snapshot of current public, user-owned GitHub data.

The activity series is a sample of up to 300 public feed events, filtered to
repositories that are still public and owned by this account. It is not a
contribution graph or a count of every commit. No event bodies, commit messages,
actor identities, private repository metadata, or credentials are persisted.
Commit history separately samples three default-branch commits per public source
repository, including this profile, and displays the latest eight by commit date.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_ROOT = "https://api.github.com"
PER_PAGE = 100
MAX_REPO_PAGES = 10
MAX_EVENT_PAGES = 3
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
TIMEOUT_SECONDS = 20
LOGIN_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
REPO_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,100}\Z")
TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
SHA_PATTERN = re.compile(r"[0-9a-fA-F]{40}\Z")


class CollectionError(Exception):
    """A safe-to-display collection failure, without response bodies or tokens."""


class GitHubHTTPError(CollectionError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class NoRedirects(HTTPRedirectHandler):
    """Never forward the optional token to a redirected request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GitHubClient:
    def __init__(self, token: str | None = None):
        if token and any(ord(char) < 32 or ord(char) > 126 for char in token):
            raise CollectionError("GH_TOKEN contains invalid header characters; replace the token.")
        self.token = token
        self.opener = build_opener(NoRedirects())

    def get(self, path: str, **params):
        # All paths originate in this file; never follow URLs from API payloads.
        if not path.startswith("/") or not re.fullmatch(r"/[A-Za-z0-9_./-]+", path):
            raise CollectionError("Refusing an invalid GitHub API path.")
        url = API_ROOT + path
        if params:
            url += "?" + urlencode(params)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "public-profile-dashboard/1.0",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = Request(url, headers=headers)
        try:
            with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            guidance = {
                401: "Check GH_TOKEN or omit it for public requests.",
                403: "Check API rate limits and token permissions; retry after the limit resets.",
                404: "Check the login and that the repository is still public, then retry.",
                429: "GitHub rate-limited this request; retry after the limit resets.",
            }.get(error.code, "Check GitHub status and retry; repository redirects require a fresh snapshot.")
            raise GitHubHTTPError(error.code, f"GitHub HTTP {error.code} for {path}. {guidance}") from None
        except (URLError, TimeoutError, OSError):
            raise CollectionError(f"GitHub request failed for {path}; check the network and retry.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise CollectionError(f"GitHub response exceeded the size limit for {path}.")
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise CollectionError(f"GitHub returned invalid JSON for {path}; retry later.") from None


def validate_login(login: str) -> str:
    if not LOGIN_PATTERN.fullmatch(login) or "--" in login:
        raise CollectionError("Invalid login: use 1-39 letters, digits, or single internal hyphens.")
    return login


def text(value, limit: int, fallback: str = "") -> str:
    if value is None:
        return fallback
    if not isinstance(value, str):
        raise CollectionError("GitHub returned an invalid text field; snapshot was not updated.")
    # Strip control characters and collapse whitespace. SVG/XML escaping belongs
    # to the renderer, so preserve ordinary text such as ampersands here.
    return " ".join("".join(char for char in value if char.isprintable() or char.isspace()).split())[:limit]


def natural(value, field: str) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise CollectionError(f"GitHub returned an invalid {field}; snapshot was not updated.")
    return value


def timestamp(value, field: str, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if not isinstance(value, str) or not TIMESTAMP_PATTERN.fullmatch(value):
        raise CollectionError(f"GitHub returned an invalid {field}; snapshot was not updated.")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        raise CollectionError(f"GitHub returned an invalid {field}; snapshot was not updated.") from None
    return value


def repo_record(raw, login: str) -> dict | None:
    if not isinstance(raw, dict):
        raise CollectionError("GitHub returned an invalid repository entry.")
    owner = raw.get("owner")
    # Fail closed: a missing/non-boolean visibility marker is never public.
    if raw.get("private") is not False or not isinstance(owner, dict):
        return None
    owner_login = owner.get("login")
    if not isinstance(owner_login, str) or owner_login.casefold() != login.casefold():
        return None
    if raw.get("visibility", "public") != "public":
        return None
    name = raw.get("name")
    if not isinstance(name, str) or not REPO_PATTERN.fullmatch(name) or name in {".", ".."}:
        raise CollectionError("GitHub returned an invalid public repository name.")
    if type(raw.get("fork")) is not bool:
        raise CollectionError("GitHub returned an invalid repository fork marker.")
    language = text(raw.get("language"), 60) or None
    return {
        "name": name,
        "url": f"https://github.com/{login}/{name}",
        "stars": natural(raw.get("stargazers_count"), "star count"),
        "forks": natural(raw.get("forks_count"), "fork count"),
        "language": language,
        "description": text(raw.get("description"), 200),
        "is_fork": raw["fork"],
        "pushed_at": timestamp(raw.get("pushed_at"), "repository timestamp", nullable=True),
    }


EVENT_MESSAGES = {
    "CommitCommentEvent": "Commented on a commit",
    "CreateEvent": "Created a repository or ref",
    "DeleteEvent": "Deleted a ref",
    "DiscussionEvent": "Updated a discussion",
    "ForkEvent": "Forked a repository",
    "GollumEvent": "Updated the wiki",
    "IssueCommentEvent": "Commented on an issue",
    "IssuesEvent": "Updated an issue",
    "MemberEvent": "Updated repository access",
    "PublicEvent": "Made a repository public",
    "PullRequestEvent": "Updated a pull request",
    "PullRequestReviewEvent": "Reviewed a pull request",
    "PullRequestReviewCommentEvent": "Commented on a pull request",
    "PullRequestReviewThreadEvent": "Updated a review thread",
    "PushEvent": "Pushed commits",
    "ReleaseEvent": "Published a release",
    "SponsorshipEvent": "Updated a sponsorship",
    "WatchEvent": "Starred a repository",
}


def event_url(raw: dict, repo_url: str) -> str:
    payload = raw.get("payload")
    if not isinstance(payload, dict):
        return repo_url
    kind = raw.get("type")
    if kind == "PushEvent":
        head = payload.get("head")
        if isinstance(head, str) and SHA_PATTERN.fullmatch(head):
            return f"{repo_url}/commit/{head.lower()}"
    if kind in {"IssuesEvent", "IssueCommentEvent"}:
        issue = payload.get("issue")
        number = issue.get("number") if isinstance(issue, dict) else None
        if type(number) is int and 0 < number <= 2**31 - 1:
            return f"{repo_url}/issues/{number}"
    if kind in {"PullRequestEvent", "PullRequestReviewEvent", "PullRequestReviewCommentEvent", "PullRequestReviewThreadEvent"}:
        pull = payload.get("pull_request")
        number = pull.get("number") if isinstance(pull, dict) else payload.get("number")
        if type(number) is int and 0 < number <= 2**31 - 1:
            return f"{repo_url}/pull/{number}"
    return repo_url


def event_record(raw, allowed: dict[str, dict], sampled_at: str) -> dict | None:
    if not isinstance(raw, dict):
        raise CollectionError("GitHub returned an invalid event entry.")
    if raw.get("public") is not True:
        return None
    event_repo = raw.get("repo")
    full_name = event_repo.get("name") if isinstance(event_repo, dict) else None
    if not isinstance(full_name, str) or full_name.casefold() not in allowed:
        return None
    repo = allowed[full_name.casefold()]
    created = timestamp(raw.get("created_at"), "event timestamp")
    if created > sampled_at:
        return None
    kind = raw.get("type")
    # Unknown future types receive a fixed label; never serialize free-form text.
    if not isinstance(kind, str) or kind not in EVENT_MESSAGES:
        kind = "OtherEvent"
    return {
        "created_at": created,
        "kind": kind,
        "repo": repo["name"],
        "message": EVENT_MESSAGES.get(kind, "Updated repository activity"),
        "url": event_url(raw, repo["url"]),
    }


def commit_records(client: GitHubClient, login: str, repos: list[dict]) -> list[dict]:
    """Sample the default branch of public sources, including the profile repo."""
    commits = []
    seen = set()
    for repo in repos:
        if repo["is_fork"] or repo["pushed_at"] is None:
            continue
        try:
            raw_commits = client.get(f"/repos/{login}/{repo['name']}/commits", per_page=3)
        except GitHubHTTPError as error:
            # GitHub returns 409 for an empty repository. Other failures abort
            # the whole snapshot so a missing source is never silently hidden.
            if error.status_code == 409:
                continue
            raise
        if not isinstance(raw_commits, list) or len(raw_commits) > 3:
            raise CollectionError("GitHub returned an invalid repository commit sample.")
        for raw in raw_commits:
            if not isinstance(raw, dict):
                raise CollectionError("GitHub returned an invalid commit entry.")
            sha = raw.get("sha")
            if not isinstance(sha, str) or not SHA_PATTERN.fullmatch(sha):
                raise CollectionError("GitHub returned an invalid commit SHA.")
            sha = sha.lower()
            key = (repo["name"].casefold(), sha)
            if key in seen:
                continue
            seen.add(key)
            details = raw.get("commit")
            if not isinstance(details, dict):
                raise CollectionError("GitHub returned invalid commit metadata.")
            committer = details.get("committer")
            author = details.get("author")
            created_at = committer.get("date") if isinstance(committer, dict) else None
            if created_at is None:
                created_at = author.get("date") if isinstance(author, dict) else None
            commits.append({
                "sha": sha,
                "created_at": timestamp(created_at, "commit timestamp"),
                "repo": repo["name"],
                "message": f"commit {sha[:7]}",
                "url": f"{repo['url']}/commit/{sha}",
            })
    return sorted(commits, key=lambda commit: (commit["created_at"], commit["repo"].casefold(), commit["sha"]), reverse=True)[:8]


def collect(client: GitHubClient, login: str = "luca-1802", now: datetime | None = None) -> dict:
    login = validate_login(login)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise CollectionError("The sampling time must have an explicit timezone.")
    now = now.astimezone(timezone.utc)
    sampled_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    user = client.get(f"/users/{login}")
    if not isinstance(user, dict) or not isinstance(user.get("login"), str) or user["login"].casefold() != login.casefold():
        raise CollectionError("GitHub returned an unexpected account; snapshot was not updated.")
    profile = {
        "name": text(user.get("name"), 80) or login,
        "followers": natural(user.get("followers"), "follower count"),
        "following": natural(user.get("following"), "following count"),
        "created_at": timestamp(user.get("created_at"), "account creation timestamp"),
        "public_repos": natural(user.get("public_repos"), "public repository count"),
    }
    repos_by_name = {}
    for page in range(1, MAX_REPO_PAGES + 1):
        raw_repos = client.get(f"/users/{login}/repos", type="owner", sort="full_name", direction="asc", per_page=PER_PAGE, page=page)
        if not isinstance(raw_repos, list) or len(raw_repos) > PER_PAGE:
            raise CollectionError("GitHub returned an invalid repository page.")
        for raw in raw_repos:
            repo = repo_record(raw, login)
            if repo is not None:
                repos_by_name[repo["name"].casefold()] = repo
        if len(raw_repos) < PER_PAGE:
            break
    else:
        raise CollectionError(f"Repository pagination reached {MAX_REPO_PAGES} full pages; increase the explicit limit before retrying.")
    repos = sorted(repos_by_name.values(), key=lambda repo: (repo["is_fork"], -repo["stars"], repo["name"].casefold()))
    language_bytes = Counter()
    for repo in repos:
        if repo["is_fork"] or repo["name"].casefold() == login.casefold():
            continue
        raw_languages = client.get(f"/repos/{login}/{repo['name']}/languages")
        if not isinstance(raw_languages, dict):
            raise CollectionError("GitHub returned invalid repository languages.")
        for name, size in raw_languages.items():
            language = text(name, 60)
            if not language:
                raise CollectionError("GitHub returned an empty language name.")
            language_bytes[language] += natural(size, "language byte count")
    total_bytes = sum(language_bytes.values())
    languages = [
        {"name": name, "bytes": size, "percentage": round(100 * size / total_bytes, 2) if total_bytes else 0.0}
        for name, size in sorted(language_bytes.items(), key=lambda item: (-item[1], item[0].casefold()))
    ]
    commits = commit_records(client, login, repos)
    allowed = {f"{login}/{repo['name']}".casefold(): repo for repo in repos}
    events = []
    seen_event_ids = set()
    for page in range(1, MAX_EVENT_PAGES + 1):
        raw_events = client.get(f"/users/{login}/events/public", per_page=PER_PAGE, page=page)
        if not isinstance(raw_events, list) or len(raw_events) > PER_PAGE:
            raise CollectionError("GitHub returned an invalid public event page.")
        for raw in raw_events:
            event = event_record(raw, allowed, sampled_at)
            if event is None:
                continue
            event_id = raw.get("id")
            if not isinstance(event_id, str) or not re.fullmatch(r"[0-9]{1,30}", event_id):
                raise CollectionError("GitHub returned an invalid public event identifier.")
            if event_id in seen_event_ids:
                continue
            seen_event_ids.add(event_id)
            events.append(event)
        if len(raw_events) < PER_PAGE:
            break
    events.sort(key=lambda event: event["created_at"], reverse=True)
    daily_counts = Counter(event["created_at"][:10] for event in events)
    activity = [
        {"date": (now.date() - timedelta(days=offset)).isoformat(), "count": daily_counts[(now.date() - timedelta(days=offset)).isoformat()]}
        for offset in range(29, -1, -1)
    ]
    return {
        "schema_version": 1,
        "login": login,
        "sampled_at": sampled_at,
        "profile": profile,
        "repos": repos,
        "languages": languages,
        "commits": commits,
        "events": events[:12],
        "activity": activity,
    }


def write_snapshot(data: dict, output: Path) -> None:
    """Serialize fully, then atomically replace the destination on the same disk."""
    serialized = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n", prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login", default="luca-1802", help="GitHub account (default: luca-1802)")
    parser.add_argument("--output", type=Path, default=Path("assets/profile-data.json"))
    args = parser.parse_args(argv)
    try:
        validate_login(args.login)
        data = collect(GitHubClient(os.environ.get("GH_TOKEN")), args.login)
        write_snapshot(data, args.output)
    except CollectionError as error:
        print(f"Profile collection failed: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Profile snapshot could not be written; check the output path and permissions.", file=sys.stderr)
        return 1
    print(f"Collected {len(data['repos'])} public owned repositories, {len(data['commits'])} sampled commits, and {len(data['events'])} recent events.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
