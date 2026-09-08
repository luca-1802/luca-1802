#!/usr/bin/env python3
"""Collect aggregate activity from this profile's existing stats services.

Requests use fixed URLs without credentials. Only validated counts, rank, and
locally formatted dates are saved; remote SVG markup is never persisted.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET


LOGIN = "luca-1802"
SOURCES = {
    "stats": (
        "https://github-readme-xi-three.vercel.app/api?username=luca-1802"
        "&show_icons=true&include_all_commits=true&count_private=true",
        "image/svg+xml",
    ),
    "streak": ("https://streak-stats.demolab.com/?user=luca-1802&type=json", "application/json"),
}
MAX_RESPONSE_BYTES = 256 * 1024
TIMEOUT_SECONDS = 20
SVG = "{http://www.w3.org/2000/svg}"
RANKS = {"S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
STATS_DESCRIPTION = re.compile(
    r"Total Stars Earned: (?P<total_stars>[0-9]{1,19}), "
    r"Total Commits\s*: (?P<total_commits>[0-9]{1,19}), "
    r"Total PRs: (?P<total_prs>[0-9]{1,19}), "
    r"Total Issues: (?P<total_issues>[0-9]{1,19}), "
    r"Contributed to \(last year\): (?P<contributed_repos>[0-9]{1,19})"
)


class CollectionError(Exception):
    """A safe error message that contains no response bodies or credentials."""


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ActivityClient:
    def __init__(self):
        self.opener = build_opener(NoRedirects())

    def get(self, source: str) -> bytes:
        if source not in SOURCES:
            raise CollectionError("Unknown activity source.")
        url, content_type = SOURCES[source]
        request = Request(url, headers={"Accept": content_type, "User-Agent": "public-profile-dashboard/1.0"})
        try:
            with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                if response.status != 200 or response.geturl() != url:
                    raise CollectionError(f"Unexpected response from {source}; snapshot was not updated.")
                if response.headers.get_content_type() != content_type:
                    raise CollectionError(f"Unexpected content type from {source}; snapshot was not updated.")
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            raise CollectionError(f"Activity source {source} returned HTTP {error.code}; retry later.") from None
        except (URLError, TimeoutError, OSError, HTTPException):
            raise CollectionError(f"Activity source {source} could not be reached; retry later.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise CollectionError(f"Activity source {source} exceeded the response size limit.")
        return raw


def natural(value) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise CollectionError("Activity source returned an invalid count.")
    return value


def decode_response(raw: bytes) -> str:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise CollectionError("Activity source exceeded the response size limit.")
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        raise CollectionError("Activity source returned invalid UTF-8.") from None


def parse_stats(raw: bytes) -> dict:
    # The accessibility description contains exact integers, unlike abbreviated
    # display values. This deployed stats service has no documented JSON output.
    source = decode_response(raw)
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", source, re.IGNORECASE):
        raise CollectionError("Stats SVG contains an unsupported XML declaration.")
    try:
        root = ET.fromstring(source)
    except ET.ParseError:
        raise CollectionError("Stats source returned invalid SVG.") from None
    if root.tag != SVG + "svg":
        raise CollectionError("Stats source did not return an SVG card.")
    descriptions = list(root.iter(SVG + "desc"))
    ranks = [node for node in root.iter() if node.get("data-testid") == "level-rank-icon"]
    if len(descriptions) != 1 or len(ranks) != 1 or ranks[0].tag != SVG + "text":
        raise CollectionError("Stats card is missing unique totals or rank.")
    description = " ".join("".join(descriptions[0].itertext()).split())
    match = STATS_DESCRIPTION.fullmatch(description)
    rank = "".join(ranks[0].itertext()).strip()
    if match is None or rank not in RANKS:
        raise CollectionError("Stats card totals or rank were not recognized.")
    return {**{key: natural(int(value)) for key, value in match.groupdict().items()}, "rank": rank}


def unique_object(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise CollectionError("Streak source returned duplicate JSON fields.")
        result[key] = value
    return result


def parse_date(value) -> date:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise CollectionError("Streak source returned an invalid date.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise CollectionError("Streak source returned an invalid date.") from None


def date_label(value: date, year: int) -> str:
    label = f"{MONTHS[value.month - 1]} {value.day}"
    return label if value.year == year else f"{label}, {value.year:04d}"


def streak_record(value, year: int) -> tuple[int, str, date]:
    if not isinstance(value, dict):
        raise CollectionError("Streak source is missing a streak record.")
    length = natural(value.get("length"))
    start, end = parse_date(value.get("start")), parse_date(value.get("end"))
    if end < start or (end - start).days != max(0, length - 1):
        raise CollectionError("Streak source returned inconsistent dates and length.")
    label = date_label(start, year)
    if start != end:
        label += " - " + date_label(end, year)
    return length, label, start


def parse_streak(raw: bytes, today: date) -> dict:
    # JSON output is documented at DenverCoder1/github-readme-streak-stats.
    try:
        data = json.loads(decode_response(raw), object_pairs_hook=unique_object)
    except (ValueError, RecursionError):
        raise CollectionError("Streak source returned invalid JSON.") from None
    if not isinstance(data, dict) or "error" in data or data.get("mode") != "daily" or data.get("excludedDays") != []:
        raise CollectionError("Streak source did not return daily contribution stats.")
    total = natural(data.get("totalContributions"))
    current, current_range, current_start = streak_record(data.get("currentStreak"), today.year)
    longest, longest_range, longest_start = streak_record(data.get("longestStreak"), today.year)
    if not current <= longest <= total or (total > 0 and longest == 0):
        raise CollectionError("Streak source returned inconsistent totals.")
    if total == 0:
        # Upstream uses an empty firstContribution for an all-zero history.
        if data.get("firstContribution") != "":
            raise CollectionError("Streak source returned an inconsistent first contribution.")
        contribution_range = "No contributions yet"
    else:
        first = parse_date(data.get("firstContribution"))
        if first > longest_start or (current > 0 and first > current_start):
            raise CollectionError("Streak source returned an inconsistent first contribution.")
        contribution_range = date_label(first, today.year) + " - Present"
    return {
        "total_contributions": total,
        "current_days": current,
        "longest_days": longest,
        "contribution_range": contribution_range,
        "current_range": current_range,
        "longest_range": longest_range,
    }


def collect(client: ActivityClient, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise CollectionError("The sampling time must have an explicit timezone.")
    now = now.astimezone(timezone.utc)
    return {
        "schema_version": 1,
        "login": LOGIN,
        "sampled_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "stats": parse_stats(client.get("stats")),
        "streak": parse_streak(client.get("streak"), now.date()),
    }


def write_snapshot(data: dict, output: Path) -> None:
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
    parser.add_argument("--output", type=Path, default=Path("assets/activity-data.json"))
    args = parser.parse_args(argv)
    try:
        data = collect(ActivityClient())
        write_snapshot(data, args.output)
    except CollectionError as error:
        print(f"Activity collection failed: {error}", file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Activity snapshot could not be written; check the output path and permissions.", file=sys.stderr)
        return 1
    print("Collected profile stats and contribution streaks.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
