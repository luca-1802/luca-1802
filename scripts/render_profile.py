"""Render the profile's light, dark and mobile SVGs from saved snapshots."""
from __future__ import annotations

import argparse
from datetime import datetime
from html import escape
import json
import math
from pathlib import Path
import re
from textwrap import wrap
from urllib.parse import quote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
LOGIN = 'luca-1802'
THEMES = {
    'light': dict(background='#f1f5fb', paper='#fdfefe', rule='#d8e0ec',
                  ink='#222b3a', muted='#637084', blue='#164ee6',
                  strong='#222b3a', secondary='#65738b', other='#dbe3ef'),
    'dark': dict(background='#0d1117', paper='#161b22', rule='#35404e',
                 ink='#e6edf3', muted='#a2adbd', blue='#8aaaff',
                 strong='#758398', secondary='#8290a5', other='#d0d9e6'),
}
PROJECTS = {
    'password-manager': ('APPLICATION', 'Self-hosted vault', ['TypeScript · React', 'Python']),
    'file-organizer': ('UTILITY', 'File classification', ['Python']),
    'weather-cli': ('COMMAND-LINE TOOL', 'OpenWeather client', ['Python · OpenWeather']),
}
BARCODE = [(0, 3), (7, 1), (12, 5), (21, 2), (27, 1), (32, 4), (40, 2),
           (46, 6), (56, 1), (61, 3), (68, 2), (74, 5), (83, 1), (88, 2),
           (94, 4), (102, 1), (107, 6), (117, 2), (123, 1), (128, 4),
           (136, 2), (142, 5), (151, 1), (156, 3), (163, 3)]


def text_value(value, field, *, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or any(
        ord(c) < 32 and c not in '\t\n\r' or 0xD800 <= ord(c) <= 0xDFFF
        or ord(c) in (0xFFFE, 0xFFFF) for c in value
    ):
        raise ValueError(f'{field} must be XML-safe text')


def natural(value, field):
    if type(value) is not int or value < 0:
        raise ValueError(f'{field} must be a nonnegative integer')


def timestamp(value, field, *, date_only=False):
    text_value(value, field)
    pattern = '%Y-%m-%d' if date_only else '%Y-%m-%dT%H:%M:%SZ'
    try:
        if datetime.strptime(value, pattern).strftime(pattern) != value:
            raise ValueError
    except ValueError:
        raise ValueError(f'{field} must be a valid {"date" if date_only else "UTC timestamp"}') from None


def validate_snapshot(data):
    """Fail before writing assets if a snapshot cannot support accurate output."""
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1 or data.get('login') != LOGIN:
        raise ValueError('Unexpected profile snapshot identity or schema')
    timestamp(data.get('sampled_at'), 'sampled_at')
    profile = data.get('profile')
    if not isinstance(profile, dict):
        raise ValueError('profile must be an object')
    text_value(profile.get('name'), 'profile.name')
    for key in ('followers', 'following', 'public_repos'):
        natural(profile.get(key), 'profile.' + key)
    timestamp(profile.get('created_at'), 'profile.created_at')
    for key in ('repos', 'languages', 'commits', 'events', 'activity'):
        if not isinstance(data.get(key), list) or any(not isinstance(row, dict) for row in data[key]):
            raise ValueError(f'{key} must be an array of objects')
    repo_names = set()
    for row in data['repos']:
        name = row.get('name')
        text_value(name, 'repository name')
        if not name or name.casefold() in repo_names:
            raise ValueError('Repository names must be nonempty and unique')
        repo_names.add(name.casefold())
        for key in ('stars', 'forks'):
            natural(row.get(key), 'repository ' + key)
        if type(row.get('is_fork')) is not bool:
            raise ValueError('repository is_fork must be a boolean')
        text_value(row.get('language'), 'repository language', nullable=True)
        text_value(row.get('description'), 'repository description')
        if row.get('url') != f'https://github.com/{LOGIN}/{quote(name, safe="-._~")}':
            raise ValueError('Repository URL must identify its public GitHub repository')
        if row.get('pushed_at') is not None:
            timestamp(row['pushed_at'], 'repository pushed_at')
    language_names = set()
    for row in data['languages']:
        name = row.get('name')
        text_value(name, 'language name')
        if not name or name.casefold() in language_names:
            raise ValueError('Language names must be nonempty and unique')
        language_names.add(name.casefold())
        natural(row.get('bytes'), 'language bytes')
        pct = row.get('percentage')
        if type(pct) not in (int, float) or not math.isfinite(pct) or not 0 <= pct <= 100:
            raise ValueError('Invalid language percentage')
    for key in ('commits', 'events'):
        for row in data[key]:
            name = row.get('repo')
            text_value(name, key + ' repository')
            if name.casefold() not in repo_names:
                raise ValueError(f'{key} must refer to a public repository in the snapshot')
            timestamp(row.get('created_at'), key + ' created_at')
            url = row.get('url')
            base = f'https://github.com/{LOGIN}/{quote(name, safe="-._~")}'
            if key == 'commits':
                sha = row.get('sha')
                if not isinstance(sha, str) or not re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', sha):
                    raise ValueError('Invalid public commit SHA')
                if url != f'{base}/commit/{sha}':
                    raise ValueError('Commit URL does not match its public reference')
                # Commit messages are intentionally not consumed or rendered.
            else:
                text_value(row.get('kind'), 'event kind')
                text_value(row.get('message'), 'event message')
                if not isinstance(url, str) or not (url == base or re.fullmatch(re.escape(base) + r'/(?:commit/(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})|(?:issues|pull)/[0-9]+)', url)):
                    raise ValueError('Event URL must identify a public GitHub reference')
    dates = set()
    for row in data['activity']:
        timestamp(row.get('date'), 'activity date', date_only=True)
        natural(row.get('count'), 'activity count')
        if row['date'] in dates:
            raise ValueError('Activity dates must be unique')
        dates.add(row['date'])
    return data


def e(value):
    return escape(str(value), quote=True)


def validate_activity(data):
    if not isinstance(data, dict) or data.get('login') != LOGIN or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('Unexpected activity snapshot identity or schema')
    timestamp(data.get('sampled_at'), 'activity sampled_at')
    for group, fields in (
        ('stats', ('total_commits', 'total_stars', 'total_prs', 'total_issues', 'contributed_repos')),
        ('streak', ('total_contributions', 'current_days', 'longest_days')),
    ):
        if not isinstance(data.get(group), dict):
            raise ValueError(f'activity {group} must be an object')
        for field in fields:
            value = data[group].get(field)
            natural(value, field)
            if value > 2**63 - 1:
                raise ValueError(f'{field} is too large')
    if data['stats'].get('rank') not in ('S', 'A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C'):
        raise ValueError('Unexpected GitHub stats rank')
    for field in ('contribution_range', 'current_range', 'longest_range'):
        value = data['streak'].get(field)
        text_value(value, field)
        if not value or len(value) > 60 or any(char in value for char in '\r\n\t'):
            raise ValueError(f'{field} must be a short date label')
    return data


def short(value, limit):
    value = ' '.join(str(value or '').split())
    return value if len(value) <= limit else value[:limit - 1] + '…'


def txt(x, y, value, classes='mono ink', size=None, extra=''):
    font = f' font-size="{size}"' if size is not None else ''
    return f'<text x="{x}" y="{y}" class="{classes}"{font} {extra}>{e(value)}</text>\n'


def rule(x, y, right, theme, strong=False):
    return f'<path d="M{x} {y}H{right}" stroke="{theme["strong" if strong else "rule"]}" stroke-width="{1.5 if strong else 1}"/>\n'


def metric(x, y, value, label, *, width, size=48, accent=False, note=''):
    value = str(value)
    size = round(min(size, width / max(len(value), 1) / .62), 2)
    parts = [txt(x, y, value, 'mono blue' if accent else 'mono ink', size,
                 'font-weight="600" letter-spacing="-2"'),
             txt(x, y + 32, label, 'mono label muted')]
    if note:
        lines = wrap(note, width=int(width / (13 * .62)), max_lines=2, placeholder='…')
        parts.extend(txt(x, y + 61 + index * 17, line, 'mono muted', 13)
                     for index, line in enumerate(lines))
    return ''.join(parts)


def selected_projects(data):
    candidates = {r['name'].casefold(): r for r in data['repos']
                  if not r['is_fork'] and r['name'].casefold() != data['login'].casefold()}
    selected = [candidates[name] for name in PROJECTS if name in candidates]
    remaining = [r for name, r in candidates.items() if name not in PROJECTS]
    selected += sorted(remaining, key=lambda r: (-r['stars'], r['name'].casefold()))[:3 - len(selected)]
    return selected


def apportion(weights, units):
    """Largest remainders keep displayed totals exact, including tied shares."""
    total = sum(weights)
    if not total:
        return [0] * len(weights)
    values = [weight * units // total for weight in weights]
    order = sorted(range(len(weights)), key=lambda i: (-(weights[i] * units % total), i))
    for i in order[:units - sum(values)]:
        values[i] += 1
    return values


def language_groups(data):
    rows = sorted(data['languages'], key=lambda r: (-r['bytes'], r['name'].casefold()))
    if not sum(row['bytes'] for row in rows):
        return []
    groups = [(row['name'], row['bytes']) for row in rows[:2]]
    groups.append(('Other', sum(row['bytes'] for row in rows[2:])))
    tenths = apportion([size for _, size in groups], 1000)
    return [(name, size, pct / 10) for (name, size), pct in zip(groups, tenths)]


def recent_commits(data):
    return sorted(data['commits'], key=lambda r: (r['created_at'], r['repo'].casefold(), r['sha']), reverse=True)[:3]


def start_sheet(data, theme, mobile, activity=None):
    width, height = (480, 2260) if mobile else (900, 1600)
    if activity is not None:
        height += 794 if mobile else 494
    edge, margin, hole_x = (10, 40, 24) if mobile else (18, 62, 39)
    bx, by = (276, 152) if mobile else (658, 131)
    stars = sum(r['stars'] for r in data['repos'] if not r['is_fork'])
    desc = (f"Luca, {data['login']}, Germany. Software and automation. "
            f"{len(data['repos'])} public repositories, {stars} stars on original repositories, "
            f"{data['profile']['followers']} followers, {len(data['languages'])} source languages. "
            f"Public snapshot sampled {data['sampled_at']}. Selected projects: "
            + (', '.join(r['name'] for r in selected_projects(data)) or 'none') + '. '
            'Language shares use bytes from original repositories, excluding the profile repository. '
            'Public commit references are a bounded default-branch sample, not total contributions. '
            'Full details and links are in the accompanying profile.txt. '
            'The decorative barcode is the only animation and respects reduced motion.')
    if activity is not None:
        stats, streak = activity['stats'], activity['streak']
        desc += (f" Account totals sampled {activity['sampled_at']}: "
                 f"{stats['total_commits']} total commits, {stats['total_prs']} pull requests, "
                 f"{stats['total_issues']} issues, {stats['total_stars']} stars earned, "
                 f"{stats['contributed_repos']} repositories contributed to in the past year, rank {stats['rank']}. "
                 f"{streak['total_contributions']} total contributions, current streak {streak['current_days']} days, "
                 f"longest streak {streak['longest_days']} days. "
                 'Account totals can include private activity. Contributions include more than commits.')
    out = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">
<title id="title">Luca — Public software manifest</title>
<desc id="description">{e(desc)}</desc>
<defs>
  <pattern id="registration-grid" width="12" height="12" patternUnits="userSpaceOnUse"><path d="M12 0H0V12" fill="none" stroke="{theme['blue']}" stroke-width="0.6" opacity="0.08"/></pattern>
  <clipPath id="barcode-clip"><rect x="{bx}" y="{by}" width="166" height="62"/></clipPath>
  <style>
    .mono {{ font-family: 'Cascadia Mono', 'Consolas', 'Liberation Mono', monospace; }}
    .sans {{ font-family: 'Bahnschrift', 'DIN Alternate', 'Segoe UI', sans-serif; }}
    .ink {{ fill: {theme['ink']}; }}
    .muted {{ fill: {theme['muted']}; }}
    .blue {{ fill: {theme['blue']}; }}
    .meta {{ font-size: 14px; letter-spacing: 0.5px; }}
    .label {{ font-size: {18 if mobile else 16}px; }}
    .rule {{ stroke: {theme['rule']}; stroke-width: 1; }}
    .scan {{ animation: scan 7s ease-in-out infinite; }}
    @keyframes scan {{
      0%, 16% {{ transform: translateX(0); opacity: 0.25; }}
      55% {{ transform: translateX(146px); opacity: 0.65; }}
      80%, 100% {{ transform: translateX(0); opacity: 0.25; }}
    }}
    @media (prefers-reduced-motion: reduce) {{
      .scan {{ animation: none; transform: none; opacity: 0.35; }}
    }}
  </style>
</defs>
<rect width="{width}" height="{height}" fill="{theme['background']}"/>
<path d="M{edge} {edge}H{width-edge}V{height-edge}H{edge}Z" fill="{theme['paper']}" stroke="{theme['rule']}"/>
<path d="M{margin} {edge}V{height-edge}" class="rule" stroke-dasharray="2 5"/>
<g fill="{theme['background']}" stroke="{theme['rule']}" stroke-width="1" aria-hidden="true">
'''
    for y in range(139, height - 40, 228):
        out += f'<circle cx="{hole_x}" cy="{y}" r="{4 if mobile else 6}"/>\n'
    return out + '</g>\n'


def barcode(theme, mobile):
    x, y = (276, 152) if mobile else (658, 131)
    out = f'<g aria-hidden="true"><rect x="{x-8}" y="{y-9}" width="182" height="80" fill="url(#registration-grid)"/>\n'
    for offset, width in BARCODE:
        out += f'<rect x="{x+offset}" y="{y}" width="{width}" height="62" fill="{theme["ink"]}"/>\n'
    out += f'<g clip-path="url(#barcode-clip)"><rect class="scan" x="{x+2}" y="{y}" width="18" height="62" fill="{theme["blue"]}" opacity="0.35"/></g></g>\n'
    return out


def section(number, title, y, mobile, right=''):
    x, rx, mx = (62, 442, 27) if mobile else (94, 824, 34)
    out = txt(mx, y, f'{number:02}', 'mono meta blue', extra=f'transform="rotate(-90 {mx} {y})"')
    out += txt(x, y, title, 'mono meta blue', extra='font-weight="700"')
    if right:
        out += txt(rx, y, right, 'mono meta muted', extra='text-anchor="end"')
    return out


def identity(data, theme, mobile):
    x, rx = (62, 442) if mobile else (94, 824)
    out = txt(x, 48 if mobile else 62, 'MANIFEST', 'mono meta blue', extra='font-weight="700"')
    out += txt(rx, 76 if mobile else 62, 'SNAPSHOT · ' + data['sampled_at'][:10], 'mono meta muted', extra='text-anchor="end"')
    out += rule(x, 98 if mobile else 84, rx, theme, True)
    out += txt(x, 130 if mobile else 124, 'PUBLIC SOFTWARE MANIFEST', 'mono meta muted')
    out += txt(x - 4, 205 if mobile else 195, 'Luca', 'sans ink', 64 if mobile else 68, 'font-weight="650" letter-spacing="-2"')
    out += txt(x, 245 if mobile else 229, '@' + data['login'], 'mono blue', 20 if mobile else 22)
    out += barcode(theme, mobile)
    out += txt(rx, 244 if mobile else 223, 'ID / LUCA-1802', 'mono muted' if mobile else 'mono meta muted', 12 if mobile else None, 'text-anchor="end"')
    if mobile:
        out += txt(x, 294, 'Software &', 'sans ink', 29) + txt(x, 327, 'automation', 'sans ink', 29)
        out += txt(x, 362, 'DE / Germany', 'mono label ink')
    else:
        out += txt(x, 279, 'Software & automation', 'sans ink', 29)
        out += txt(rx, 279, 'DE / Germany', 'mono label ink', extra='text-anchor="end"')
    return out + rule(x, 390 if mobile else 310, rx, theme, True)


def counts(data, theme, mobile):
    values = [len(data['repos']), sum(r['stars'] for r in data['repos'] if not r['is_fork']),
              data['profile']['followers'], len(data['languages'])]
    labels = ['Public repos', 'Stars', 'Followers', 'Languages']
    out = section(1, 'PROFILE COUNTS', 428 if mobile else 348, mobile, '' if mobile else 'SNAPSHOT VALUES')
    for n, (value, label) in enumerate(zip(values, labels)):
        x = 62 + n % 2 * 202 if mobile else 94 + n * 188
        y = 488 + n // 2 * 96 if mobile else 413
        out += metric(x, y, f'{value:02}', label, width=165 if mobile else 155)
    out += '<path d="M252 461V621M62 546H442" class="rule"/>\n' if mobile else '<path d="M257 378V448M445 378V448M633 378V448" class="rule"/>\n'
    return out + rule(62 if mobile else 94, 648 if mobile else 475, 442 if mobile else 824, theme)


def inventory(data, theme, mobile):
    rows = selected_projects(data)
    selected = f'{len(rows):02} SELECTED / {len(data["repos"]):02} PUBLIC'
    out = section(2, 'PACKAGE INVENTORY', 688 if mobile else 515, mobile, '' if mobile else selected)
    if mobile:
        out += txt(62, 718, selected, 'mono meta muted')
    else:
        out += txt(94, 556, 'PACKAGE', 'mono meta muted') + txt(385, 556, 'PURPOSE / RUNTIME', 'mono meta muted')
        out += txt(824, 556, 'NO.', 'mono meta muted', extra='text-anchor="end"')
    out += rule(62 if mobile else 94, 740 if mobile else 572, 442 if mobile else 824, theme, True)
    for n, row in enumerate(rows):
        tag, purpose, runtime = PROJECTS.get(row['name'].casefold(), ('PUBLIC PROJECT', row['description'] or 'Original public repository', [row['language'] or 'Language unavailable']))
        y = 778 + n * 174 if mobile else [611, 724, 821][n]
        out += txt(62 if mobile else 94, y, short(row['name'], 27 if mobile else 22), 'mono ink', 22 if mobile else 20, 'font-weight="600"')
        out += txt(62 if mobile else 94, y + (28 if mobile else 27), tag, 'mono meta muted')
        out += txt(62 if mobile else 385, y + (64 if mobile else 0), short(purpose, 34), 'mono label ink')
        for j, value in enumerate(runtime[:2]):
            out += txt(62 if mobile else 385, y + (94 + j * 26 if mobile else 27 + j * 24), short(value, 34 if mobile else 40), 'mono label muted')
        out += txt(442 if mobile else 824, y + (28 if mobile else 0), f'{n+1:02}', 'mono label blue', extra='text-anchor="end"')
        if n < 2:
            out += rule(62 if mobile else 94, 916 + n * 174 if mobile else [684, 781][n], 442 if mobile else 824, theme)
    if not rows:
        out += txt(62 if mobile else 94, 790 if mobile else 624, 'No public projects available.', 'mono label muted')
    return out + rule(62 if mobile else 94, 1264 if mobile else 878, 442 if mobile else 824, theme, True)


def composition(data, theme, mobile):
    groups = language_groups(data)
    out = section(3, 'LANGUAGE COMPOSITION', 1304 if mobile else 918, mobile, '' if mobile or not groups else '100.0%')
    if groups:
        x, y, width = (62, 1340, 380) if mobile else (94, 943, 730)
        widths = apportion([size for _, size, _ in groups], width * 100)
        label = ', '.join(f'{name} {pct:.1f} percent' for name, _, pct in groups)
        out += f'<g id="language-bar" aria-label="{e(label)}">\n'
        offset = 0
        for units, color in zip(widths, ('blue', 'secondary', 'other')):
            out += f'<rect x="{x + offset / 100:.2f}" y="{y}" width="{units / 100:.2f}" height="12" fill="{theme[color]}"/>\n'
            offset += units
        out += '</g>\n'
        for n, (name, _, pct) in enumerate(groups):
            x = [62, 202, 342][n] if mobile else [94, 410, 686][n]
            out += txt(x, 1393 if mobile else 1001, f'{pct:.1f}%', 'mono blue' if n == 0 else 'mono ink', 28 if mobile else 32, 'font-weight="600" letter-spacing="-1"')
            out += txt(x, 1425 if mobile else 1029, short(name, 10 if mobile else 14), 'mono label muted')
    else:
        out += txt(62 if mobile else 94, 1393 if mobile else 986, 'No language data available.', 'mono label muted')
    if mobile:
        out += txt(62, 1460, 'Original sources · byte share', 'mono label muted')
    return out + rule(62 if mobile else 94, 1490 if mobile else 1059, 442 if mobile else 824, theme)


def toolchain(theme, mobile):
    out = section(4, 'TOOLCHAIN', 1530 if mobile else 1099, mobile)
    if mobile:
        out += txt(62, 1570, 'Python / TypeScript', 'mono ink', 18)
        out += txt(62, 1602, 'React / Docker / Git', 'mono ink', 18)
    else:
        for x, value in [(94, 'Python'), (196, '/'), (233, 'TypeScript'), (382, '/'), (419, 'React'), (510, '/'), (547, 'Docker'), (649, '/'), (686, 'Git')]:
            out += txt(x, 1138, value, 'mono muted' if value == '/' else 'mono ink', 18)
    return out + rule(62 if mobile else 94, 1632 if mobile else 1168, 442 if mobile else 824, theme)


def changelog(data, theme, mobile):
    rows = recent_commits(data)
    out = section(5, 'CHANGELOG EXCERPT', 1672 if mobile else 1208, mobile, '' if mobile else 'PUBLIC COMMIT REFERENCES')
    if mobile:
        out += txt(62, 1704, 'Public commit references', 'mono label muted')
    for n, row in enumerate(rows):
        y = 1743 + n * 78 if mobile else 1250 + n * 42
        out += txt(62 if mobile else 94, y, row['sha'][:7], 'mono blue', 18)
        out += txt(62 if mobile else 259, y + 28 if mobile else y, short(row['repo'], 34 if mobile else 47), 'mono ink', 18)
        if mobile:
            out += txt(442, y, row['created_at'][:10], 'mono meta muted', extra='text-anchor="end"')
    if not rows:
        out += txt(62 if mobile else 94, 1755 if mobile else 1250, 'No sampled public commits.', 'mono label muted')
    elif not mobile:
        out += '<path d="M235 1233V1339" class="rule"/>\n'
        for n in range(len(rows)):
            out += rule(806, 1244 + n * 42, 824, theme)
    return out + rule(62 if mobile else 94, 1961 if mobile else 1372, 442 if mobile else 824, theme, True)


def account_activity(activity, theme, mobile):
    stats, streak = activity['stats'], activity['streak']
    left, right = (62, 442) if mobile else (94, 824)
    columns = (62, 264) if mobile else (94, 350, 606)
    rows = (2066, 2182, 2298) if mobile else (1491, 1591)
    cells = (
        (f"{stats['total_commits']:,}", 'Total commits'),
        (f"{stats['total_prs']:,}", 'Pull requests'),
        (f"{stats['total_issues']:,}", 'Issues opened'),
        (f"{stats['total_stars']:,}", 'Stars earned'),
        (f"{stats['contributed_repos']:,}", 'Repos / past year'),
        (stats['rank'], 'GitHub rank'),
    )
    parts = ['<g id="account-activity">',
             section(6, 'ALL-TIME ACTIVITY', 2001 if mobile else 1412, mobile,
                     '' if mobile else 'ACCOUNT TOTALS')]
    for index, (value, label) in enumerate(cells):
        x = columns[index % len(columns)]
        y = rows[index // len(columns)]
        parts.append(metric(x, y, value, label, width=174 if mobile else 216,
                            accent=index == 0, size=58 if index == 0 else 48))
    if mobile:
        parts.append('<path d="M252 2034V2352M62 2128H442M62 2244H442" class="rule"/>\n')
    else:
        parts.append('<path d="M326 1450V1630M582 1450V1630M94 1540H824" class="rule"/>\n')
    parts.append(rule(left, 2380 if mobile else 1656, right, theme))
    parts.append(section(7, 'CONTRIBUTION HISTORY', 2420 if mobile else 1696, mobile))
    entries = (
        (streak['total_contributions'], 'Contributions', streak['contribution_range']),
        (streak['current_days'], 'Current streak', streak['current_range']),
        (streak['longest_days'], 'Longest streak', streak['longest_range']),
    )
    for index, (value, label, date_range) in enumerate(entries):
        if mobile:
            x, y = (62, 2485) if index == 0 else (columns[index - 1], 2655)
        else:
            x, y = columns[index], 1764
        parts.append(metric(x, y, f'{value:,}', label, width=174 if mobile and index else 216,
                            accent=index == 0, note=date_range))
    if mobile:
        parts.append('<path d="M62 2580H442M252 2618V2734" class="rule"/>\n')
    else:
        parts.append('<path d="M326 1730V1838M582 1730V1838" class="rule"/>\n')
    parts.append(rule(left, 2755 if mobile else 1866, right, theme, True))
    parts.append('</g>\n')
    return ''.join(parts)


def footer(data, theme, mobile, offset=0, activity=None):
    x, rx = (62, 442) if mobile else (94, 824)
    out = txt(x, 2001 if mobile else 1409, 'DOCUMENT NOTE', 'mono meta blue', extra='font-weight="700"')
    if mobile:
        out += txt(x, 2039, 'A public profile, rendered', 'sans ink', 20)
        out += txt(x, 2069, 'as a software artifact.', 'sans ink', 20)
    else:
        out += txt(x, 1443, 'A public profile, rendered as a software artifact.', 'sans ink', 20)
    out += txt(x, 2110 if mobile else 1475, 'Snapshots refreshed daily.' if activity else 'Public snapshot · refreshed daily.', 'mono label muted')
    out += rule(x, 2150 if mobile else 1513, rx, theme)
    out += txt(x, 2190 if mobile else 1541, 'github.com/' + data['login'], 'mono ink' if mobile else 'mono meta ink', 16 if mobile else None)
    out += txt(rx, 2224 if mobile else 1541, 'END OF MANIFEST', 'mono meta muted', extra='text-anchor="end"')
    path = (f'M450 30H460V40M460 {2220 + offset}V{2230 + offset}H450' if mobile
            else f'M844 38H862V56M862 {1544 + offset}V{1562 + offset}H844')
    return (f'<g transform="translate(0 {offset})">\n{out}</g>\n'
            f'<path d="{path}" stroke="{theme["blue"]}" stroke-width="1" fill="none"/>\n')


def manifest(data, theme='light', mobile=False, activity=None):
    validate_snapshot(data)
    if activity is not None:
        validate_activity(activity)
    if theme not in THEMES:
        raise ValueError('Unknown Manifest theme')
    palette = THEMES[theme]
    parts = [start_sheet(data, palette, mobile, activity), identity(data, palette, mobile),
             counts(data, palette, mobile), inventory(data, palette, mobile),
             composition(data, palette, mobile), toolchain(palette, mobile),
             changelog(data, palette, mobile)]
    offset = 0
    if activity is not None:
        parts.append(account_activity(activity, palette, mobile))
        offset = 794 if mobile else 494
    parts.append(footer(data, palette, mobile, offset, activity))
    parts.append('</svg>\n')
    return ''.join(parts)


def transcript(data, activity=None):
    validate_snapshot(data)
    profile = data['profile']
    parts = ['LUCA-1802 / PUBLIC SOFTWARE MANIFEST', 'Sampled ' + data['sampled_at'],
             'Public snapshot · refreshed daily.', 'https://github.com/' + data['login'], '',
             'Luca. Software & automation. Germany.', 'Python, TypeScript, React, Docker, Git, CLI.', '',
             'STATISTICS', f"Public repositories: {len(data['repos'])}",
             f"Stars on original repositories: {sum(r['stars'] for r in data['repos'] if not r['is_fork'])}",
             f"Followers: {profile['followers']}", f"Languages: {len(data['languages'])}",
             f"Following: {profile['following']}", f"Account created: {profile['created_at']}",
             f"Profile name in snapshot: {profile['name']}", f"API public repository count: {profile['public_repos']}", '',
             'SELECTED ORIGINAL PUBLIC PROJECTS']
    for row in selected_projects(data):
        parts.append(f"{row['name']} | {row['url']}")
    parts += ['', 'ALL PUBLIC REPOSITORIES']
    for row in data['repos']:
        parts += [f"{row['name']} | {'fork' if row['is_fork'] else 'original'} | {row['language'] or 'no language'} | {row['stars']} stars | {row['forks']} forks | pushed {row['pushed_at'] or 'unknown'} | {row['url']}",
                  'Description: ' + (row['description'] or 'none supplied')]
    parts += ['', 'LANGUAGE BYTES / ORIGINAL REPOSITORIES / EXCLUDING PROFILE REPOSITORY']
    total = sum(row['bytes'] for row in data['languages'])
    for row in data['languages']:
        parts.append(f"{row['name']}: {100 * row['bytes'] / total if total else 0:.2f}% ({row['bytes']} bytes)")
    parts += ['', 'MANIFEST LANGUAGE COMPOSITION / TOP TWO PLUS OTHER',
              'Shares are derived from bytes and apportioned to total 100.0% at one decimal.']
    parts += [f'{name}: {pct:.1f}% ({size} bytes)' for name, size, pct in language_groups(data)]
    parts += ['', 'RECENT PUBLIC COMMITS / UTC',
              'Bounded sample: up to three default-branch commits per public original repository; eight most recent retained. Not total contributions.']
    parts += [f"{row['created_at']} | {row['sha']} | {row['repo']} | {row['url']}" for row in data['commits']]
    parts += ['', 'RECENT PUBLIC EVENTS / UTC']
    parts += [f"{row['created_at']} | {row['kind']} | {row['message']} | {row['repo']} | {row['url']}" for row in data['events']]
    parts += ['', '30-DAY PUBLIC EVENT SAMPLE / NOT TOTAL CONTRIBUTIONS',
              'Sample of up to 300 public feed events, filtered to owned public repositories; recent-event details retain up to 12 entries.']
    parts += [f"{row['date']}: {row['count']}" for row in data['activity']]
    if activity is not None:
        validate_activity(activity)
        stats, streak = activity['stats'], activity['streak']
        parts += ['', 'ACCOUNT ACTIVITY', 'Sampled ' + activity['sampled_at'],
                  'Account totals can include private activity; they differ from the owned public repository counts above.',
                  f"Total commits (all time): {stats['total_commits']}",
                  f"Pull requests: {stats['total_prs']}", f"Issues opened: {stats['total_issues']}",
                  f"Stars earned: {stats['total_stars']}",
                  f"Repositories contributed to (past year): {stats['contributed_repos']}",
                  f"GitHub stats rank: {stats['rank']}",
                  f"Total contributions: {streak['total_contributions']} | {streak['contribution_range']}",
                  f"Current streak: {streak['current_days']} days | {streak['current_range']}",
                  f"Longest streak: {streak['longest_days']} days | {streak['longest_range']}",
                  'Contributions include more than commits.',
                  'Totals source: github-readme-xi-three.vercel.app (include_all_commits=true).',
                  'Contribution and streak source: streak-stats.demolab.com.']
    return '\n'.join(parts) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'assets/profile-data.json')
    parser.add_argument('--activity-data', type=Path, default=ROOT / 'assets/activity-data.json')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'assets')
    args = parser.parse_args(argv)
    try:
        data = validate_snapshot(json.loads(args.data.read_text(encoding='utf-8')))
        activity = validate_activity(json.loads(args.activity_data.read_text(encoding='utf-8')))
        assets = {}
        for theme in THEMES:
            for mobile in (False, True):
                name = f'manifest-{theme}{"-mobile" if mobile else ""}.svg'
                assets[name] = manifest(data, theme, mobile, activity)
                ET.fromstring(assets[name])
        assets['profile.txt'] = transcript(data, activity)
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for name, content in assets.items():
            (args.output_dir / name).write_text(content, encoding='utf-8', newline='\n')
    except (ValueError, OSError, ET.ParseError) as error:
        parser.exit(1, f'Manifest rendering failed: {error}\n')
    print('Rendered 4 Manifest SVG assets and an accessible text view.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
