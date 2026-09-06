"""Asset safety and content edge cases for the profile renderer."""
import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location('render_profile', Path(__file__).resolve().parents[1] / 'scripts' / 'render_profile.py')
renderer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(renderer)
SVG = '{http://www.w3.org/2000/svg}'


def data():
    return {'schema_version':1, 'login':'luca-1802', 'sampled_at':'2026-09-06T12:00:00Z',
            'profile':{'name':'Luca','followers':0,'created_at':'2022-10-20T00:00:00Z'},
            'repos':[], 'languages':[], 'commits':[], 'events':[], 'activity':[]}


class RenderTests(unittest.TestCase):
    def test_api_strings_cannot_inject_svg_elements(self):
        snapshot = data()
        snapshot['repos'] = [{'name':'<script>alert(1)</script>', 'is_fork':False,
                             'language':'X & Y', 'pushed_at':None, 'stars':0,'forks':0}]
        for mobile in (False, True):
            root = ET.fromstring(renderer.repos(snapshot, mobile))
            self.assertIsNone(root.find('.//' + SVG + 'script'))
            self.assertIn('X & Y', ''.join(root.itertext()))

    def test_empty_public_data_panels_remain_valid_and_readable(self):
        for mobile in (False, True):
            for fn in (renderer.stats, renderer.repos, renderer.languages, renderer.events):
                root = ET.fromstring(fn(data(), mobile))
                height = float(root.attrib['height'])
                texts = root.findall('.//' + SVG + 'text')
                for text in texts:
                    self.assertLess(float(text.attrib['y']), height)
                if fn in (renderer.repos, renderer.languages, renderer.events):
                    empty = [t for t in texts if (t.text or '').startswith('No ')]
                    self.assertEqual(len(empty), 1)
                    self.assertLess(float(empty[0].attrib['y']), height - 29)

    def test_identity_markup_and_motion_have_text_fallbacks(self):
        for content in (renderer.mark(), renderer.hero(data()), renderer.hero(data(), True),
                        renderer.ticker(), renderer.ticker(True), renderer.boot(), renderer.hexdump(True)):
            root = ET.fromstring(content)
            self.assertTrue(root.find(SVG+'title').text)
            self.assertTrue(root.find(SVG+'desc').text)
            self.assertIn('prefers-reduced-motion:reduce', content)
            self.assertNotIn('<script', content)
            self.assertNotIn('<foreignObject', content)
            self.assertNotIn('href=', content)

    def test_generated_transcript_labels_bounded_activity(self):
        text = renderer.transcript(data())
        self.assertIn('NOT TOTAL CONTRIBUTIONS', text)
        self.assertIn('RECENT PUBLIC COMMITS / UTC', text)


if __name__ == '__main__':
    unittest.main()
