"""Data correctness, accessible fallbacks, and safe deterministic Manifest output."""
import copy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import quote
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/render_profile.py'
spec = importlib.util.spec_from_file_location('render_profile', SCRIPT)
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
SVG = '{http://www.w3.org/2000/svg}'


def data():
    return {'schema_version': 1, 'login': 'luca-1802', 'sampled_at': '2026-09-06T12:00:00Z',
            'profile': {'name': 'Luca', 'followers': 6, 'following': 5,
                        'public_repos': 0, 'created_at': '2022-10-20T00:00:00Z'},
            'repos': [], 'languages': [], 'commits': [], 'events': [], 'activity': []}


def repo(name, *, fork=False, stars=0, language='Python', description=''):
    return {'name': name, 'url': 'https://github.com/luca-1802/' + quote(name, safe='-._~'),
            'stars': stars, 'forks': 0, 'language': language, 'description': description,
            'is_fork': fork, 'pushed_at': '2026-09-01T12:00:00Z'}


def commit(name, n, day=6):
    sha = f'{n:07x}' + 'a' * 33
    return {'repo': name, 'sha': sha, 'created_at': f'2026-09-{day:02}T10:00:00Z',
            'message': 'THIS IS AN UNTRUSTED COMMIT MESSAGE',
            'url': f'https://github.com/luca-1802/{quote(name, safe="-._~")}/commit/{sha}'}


def language(name, size, percentage=0):
    return {'name': name, 'bytes': size, 'percentage': percentage}


def visible_text(root):
    return [''.join(node.itertext()) for node in root.findall('.//' + SVG + 'text')]


class ManifestTests(unittest.TestCase):
    def test_empty_snapshot_has_truthful_readable_states_in_every_variant(self):
        for theme in ('light', 'dark'):
            for mobile in (False, True):
                with self.subTest(theme=theme, mobile=mobile):
                    root = ET.fromstring(renderer.manifest(data(), theme, mobile))
                    texts = visible_text(root)
                    for state in ('No public projects available.', 'No language data available.',
                                  'No sampled public commits.'):
                        self.assertIn(state, texts)
                    self.assertIn('00 SELECTED / 00 PUBLIC', texts)
                    self.assertNotIn('100.0%', texts)
                    self.assertIsNone(root.find(f'.//{SVG}g[@id="language-bar"]'))
                    for node in root.findall('.//' + SVG + 'text'):
                        self.assertGreater(float(node.attrib['x']), 0)
                        self.assertLess(float(node.attrib['x']), float(root.attrib['width']))
                        self.assertGreater(float(node.attrib['y']), 0)
                        self.assertLess(float(node.attrib['y']), float(root.attrib['height']))

    def test_xml_metacharacters_never_create_elements_or_attributes(self):
        snapshot = data()
        name = '<script>x</script>'
        snapshot['repos'] = [repo(name, language='X & Y', description='A < B & "quoted"')]
        snapshot['languages'] = [language('X & Y', 1)]
        snapshot['commits'] = [commit(name, 1)]
        for mobile in (False, True):
            rendered = renderer.manifest(snapshot, mobile=mobile)
            root = ET.fromstring(rendered)
            self.assertIsNone(root.find('.//' + SVG + 'script'))
            self.assertIn('A < B & "quoted"', visible_text(root))
            self.assertIn('X & Y', visible_text(root))
            self.assertIn(name, visible_text(root))
            self.assertIn('&lt;script&gt;', rendered)
            self.assertFalse(any('onload' in node.attrib for node in root.iter()))

    def test_counts_use_enumerated_repos_and_original_stars(self):
        snapshot = data()
        snapshot['profile']['public_repos'] = 999  # API metadata is not enumeration.
        snapshot['repos'] = [repo('source', stars=4), repo('forked', fork=True, stars=999), repo('luca-1802', stars=2)]
        snapshot['languages'] = [language('Rust', 3), language('Go', 1)]
        root = ET.fromstring(renderer.manifest(snapshot))
        values = [t.text for t in root.findall('.//' + SVG + 'text') if t.attrib['y'] == '413']
        self.assertEqual(values, ['03', '06', '06', '02'])
        description = root.find(SVG + 'desc').text
        self.assertIn('6 stars on original repositories', description)
        self.assertIn('2 source languages', description)
        transcript = renderer.transcript(snapshot)
        self.assertIn('Public repositories: 3', transcript)
        self.assertIn('Stars on original repositories: 6', transcript)

    def test_inventory_prefers_approved_public_originals_then_fills_from_sources(self):
        snapshot = data()
        snapshot['repos'] = [repo('luca-1802', stars=500), repo('weather-cli'), repo('new-source', stars=100),
                             repo('file-organizer'), repo('password-manager'), repo('forked', fork=True, stars=1000)]
        self.assertEqual([r['name'] for r in renderer.selected_projects(snapshot)],
                         ['password-manager', 'file-organizer', 'weather-cli'])
        snapshot['repos'][4]['is_fork'] = True
        self.assertEqual([r['name'] for r in renderer.selected_projects(snapshot)],
                         ['file-organizer', 'weather-cli', 'new-source'])
        snapshot['repos'] = [repo('luca-1802'), repo('password-manager', fork=True)]
        texts = visible_text(ET.fromstring(renderer.manifest(snapshot)))
        self.assertIn('No public projects available.', texts)
        self.assertNotIn('Self-hosted vault', texts)

    def test_long_new_names_are_shortened_without_losing_transcript_details(self):
        snapshot = data()
        name = 'a-new-public-project-' * 5
        description = 'A descriptive sentence with many words ' * 10
        snapshot['repos'] = [repo(name, language='An unusually long source language name', description=description)]
        for mobile in (False, True):
            texts = visible_text(ET.fromstring(renderer.manifest(snapshot, mobile=mobile)))
            self.assertNotIn(name, texts)
            self.assertTrue(any(t.startswith('a-new-public') and t.endswith('…') for t in texts))
            self.assertIn('PUBLIC PROJECT', texts)
        transcript = renderer.transcript(snapshot)
        self.assertIn(name, transcript)
        self.assertIn(description, transcript)
        self.assertIn(snapshot['repos'][0]['url'], transcript)

    def test_language_order_and_geometry_use_bytes_not_cached_percentages(self):
        snapshot = data()
        snapshot['languages'] = [language('TypeScript', 10, 99), language('CSS', 5, 1),
                                 language('Rust', 75, 0), language('Python', 10, 0)]
        # Alphabetical tie-breaking makes Python the second language; Other combines TS and CSS.
        self.assertEqual(renderer.language_groups(snapshot), [('Rust', 75, 75.0), ('Python', 10, 10.0), ('Other', 15, 15.0)])
        for mobile, width in ((False, 730), (True, 380)):
            root = ET.fromstring(renderer.manifest(snapshot, mobile=mobile))
            bar = root.find(f'.//{SVG}g[@id="language-bar"]')
            self.assertEqual(bar.attrib['aria-label'], 'Rust 75.0 percent, Python 10.0 percent, Other 15.0 percent')
            rects = bar.findall(SVG + 'rect')
            widths = [Decimal(r.attrib['width']) for r in rects]
            self.assertEqual(sum(widths), Decimal(width))
            self.assertEqual(widths, [Decimal(width) * Decimal(p) for p in ('0.75', '0.1', '0.15')])
            for left, right in zip(rects, rects[1:]):
                self.assertEqual(Decimal(left.attrib['x']) + Decimal(left.attrib['width']), Decimal(right.attrib['x']))

    def test_language_rounding_and_small_samples_are_complete(self):
        snapshot = data()
        for weights in ([1, 1, 1], [1], [1, 1], [0, 0], [99999999, 1, 1, 1]):
            with self.subTest(weights=weights):
                snapshot['languages'] = [language(chr(65 + i), size) for i, size in enumerate(weights)]
                groups = renderer.language_groups(snapshot)
                self.assertEqual(sum(Decimal(str(pct)) for _, _, pct in groups), Decimal(100 if sum(weights) else 0))
                self.assertEqual(sum(size for _, size, _ in groups), sum(weights))
                if not sum(weights):
                    self.assertIn('No language data available.', visible_text(ET.fromstring(renderer.manifest(snapshot))))
        snapshot['languages'] = [language('A', 1), language('B', 1), language('C', 1)]
        self.assertEqual([p for _, _, p in renderer.language_groups(snapshot)], [33.4, 33.3, 33.3])

    def test_three_recent_references_are_actual_shas_and_repository_names(self):
        snapshot = data()
        snapshot['repos'] = [repo('source')]
        snapshot['commits'] = [commit('source', 1, 1), commit('source', 2, 6), commit('source', 3, 3), commit('source', 4, 5)]
        for mobile in (False, True):
            rendered = renderer.manifest(snapshot, mobile=mobile)
            texts = visible_text(ET.fromstring(rendered))
            shas = [t for t in texts if re.fullmatch('[0-9a-f]{7}', t)]
            self.assertEqual(shas, ['0000002', '0000004', '0000003'])
            self.assertEqual(texts.count('source'), 4)  # Inventory plus three references.
            self.assertNotIn('THIS IS AN UNTRUSTED COMMIT MESSAGE', rendered)
        transcript = renderer.transcript(snapshot)
        for row in snapshot['commits']:
            self.assertIn(row['sha'], transcript)
            self.assertIn(row['url'], transcript)
        self.assertNotIn('THIS IS AN UNTRUSTED COMMIT MESSAGE', transcript)

    def test_transcript_preserves_all_snapshot_details_and_bounded_activity_label(self):
        snapshot = data()
        snapshot['repos'] = [repo(f'project-{i}', fork=i == 4, description=f'Description {i}') for i in range(5)]
        snapshot['events'] = [{'repo': 'project-4', 'kind': 'IssuesEvent', 'message': 'Opened an issue',
                               'created_at': '2026-09-06T10:00:00Z', 'url': 'https://github.com/luca-1802/project-4/issues/7'}]
        snapshot['activity'] = [{'date': '2026-09-06', 'count': 3}]
        transcript = renderer.transcript(snapshot)
        for row in snapshot['repos']:
            self.assertIn(row['url'], transcript)
            self.assertIn(row['description'], transcript)
        self.assertIn('https://github.com/luca-1802/project-4/issues/7', transcript)
        self.assertIn('2026-09-06: 3', transcript)
        self.assertIn('30-DAY PUBLIC EVENT SAMPLE / NOT TOTAL CONTRIBUTIONS', transcript)
        self.assertIn('up to 300 public feed events', transcript)
        self.assertIn('up to three default-branch commits', transcript)

    def test_themes_have_equal_content_and_exact_approved_palettes(self):
        snapshot = json.loads((ROOT / 'assets/profile-data.json').read_text(encoding='utf-8'))
        for mobile in (False, True):
            light = ET.fromstring(renderer.manifest(snapshot, 'light', mobile))
            dark = ET.fromstring(renderer.manifest(snapshot, 'dark', mobile))
            self.assertEqual(visible_text(light), visible_text(dark))
            self.assertEqual(light.attrib, dark.attrib)
            self.assertEqual(light.find(SVG + 'desc').text, dark.find(SVG + 'desc').text)
        expected = {'light': {'#f1f5fb', '#fdfefe', '#d8e0ec', '#222b3a', '#637084', '#164ee6', '#65738b', '#dbe3ef'},
                    'dark': {'#0d1117', '#161b22', '#35404e', '#e6edf3', '#a2adbd', '#8aaaff', '#758398', '#8290a5', '#d0d9e6'}}
        for theme in expected:
            self.assertEqual(set(re.findall(r'#[0-9a-f]{6}', renderer.manifest(snapshot, theme))), expected[theme])

    def test_static_svg_source_has_only_barcode_motion_and_accessible_identity(self):
        for theme in ('light', 'dark'):
            for mobile in (False, True):
                rendered = renderer.manifest(data(), theme, mobile)
                root = ET.fromstring(rendered)
                self.assertEqual(root.attrib['viewBox'], '0 0 480 2260' if mobile else '0 0 900 1600')
                self.assertEqual(root.attrib['aria-labelledby'], 'title description')
                self.assertTrue(root.find(SVG + 'title').text)
                self.assertTrue(root.find(SVG + 'desc').text)
                self.assertEqual(len(root.findall(f'.//{SVG}rect[@class="scan"]')), 1)
                self.assertEqual(rendered.count('@keyframes'), 1)
                self.assertIn('@media (prefers-reduced-motion: reduce)', rendered)
                self.assertIn('.scan { animation: none; transform: none;', rendered)
                for forbidden in ('<script', '<foreignObject', '<image', 'href=', '@import', 'http://fonts', 'https://', 'PREVIEW', 'Concept E', 'E—01'):
                    self.assertNotIn(forbidden, rendered)
                self.assertEqual(re.findall(r'url\(([^)]+)\)', rendered), ['#registration-grid', '#barcode-clip'])
                self.assertIn('SNAPSHOT · 2026-09-06', visible_text(root))
                self.assertIn('Public snapshot · refreshed daily.', visible_text(root))

    def test_model_rejects_invalid_or_unexpected_snapshot_data(self):
        valid = data()
        valid['repos'] = [repo('source')]
        valid['languages'] = [language('Python', 1)]
        valid['commits'] = [commit('source', 1)]
        paths = [('schema_version', 2), ('schema_version', True), ('login', 'someone-else'),
                 ('sampled_at', '2026-02-30T12:00:00Z'), ('profile.followers', -1),
                 ('profile.followers', True), ('repos.0.stars', 1.5), ('repos.0.is_fork', 'false'),
                 ('repos.0.description', '\x00'), ('repos.0.url', 'https://example.com/source'),
                 ('languages.0.bytes', -5), ('languages.0.bytes', True),
                 ('languages.0.percentage', float('nan')), ('languages.0.percentage', 101),
                 ('commits.0.sha', 'invented'), ('commits.0.repo', 'not-public'),
                 ('commits.0.url', 'https://example.com/commit'), ('events', {})]
        for path, invalid in paths:
            with self.subTest(path=path, invalid=invalid):
                snapshot = copy.deepcopy(valid)
                keys = path.split('.')
                cursor = snapshot
                for key in keys[:-1]:
                    cursor = cursor[int(key)] if key.isdigit() else cursor[key]
                cursor[keys[-1]] = invalid
                with self.assertRaises(ValueError):
                    renderer.manifest(snapshot)
        for field in ('repos', 'languages'):
            snapshot = copy.deepcopy(valid)
            snapshot[field] *= 2
            with self.assertRaises(ValueError):
                renderer.validate_snapshot(snapshot)
        with self.assertRaises(ValueError):
            renderer.manifest(valid, 'unknown')

    def test_cli_is_deterministic_and_does_not_write_for_invalid_input(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            snapshot_file = temp / 'snapshot.json'
            snapshot_file.write_text(json.dumps(data()), encoding='utf-8')
            output = temp / 'rendered'
            command = [sys.executable, str(SCRIPT), '--data', str(snapshot_file), '--output-dir', str(output)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            expected = {'manifest-light.svg', 'manifest-dark.svg', 'manifest-light-mobile.svg', 'manifest-dark-mobile.svg', 'profile.txt'}
            self.assertEqual({p.name for p in output.iterdir()}, expected)
            original = {p.name: p.read_bytes() for p in output.iterdir()}
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, original)
            for invalid in ('{not json', json.dumps({'schema_version': 1}), json.dumps(dict(data(), languages=[language('X', -1)]))):
                snapshot_file.write_text(invalid, encoding='utf-8')
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Manifest rendering failed:', result.stderr)
                self.assertNotIn('Traceback', result.stderr)
                self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, original)


if __name__ == '__main__':
    unittest.main()
