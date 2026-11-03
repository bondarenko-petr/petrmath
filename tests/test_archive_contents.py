import unittest
from html.parser import HTMLParser
from urllib.parse import unquote
from archive_contents import render_contents

class Links(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]; self.external=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='a': self.links.append(attrs['href'])
        if tag in ('script','link','img'): self.external.append(tag)

class ContentsTests(unittest.TestCase):
    def test_offline_relative_links_and_untrusted_text(self):
        path='2026-10-06_урок/Конспект #1.pdf'
        page=render_contents([{'starts_at':1791280800,'topic':'<script>alert(1)</script>','links':[path]}], 'Europe/Moscow','<img src=x onerror=alert(1)>')
        parser=Links();parser.feed(page)
        self.assertEqual([unquote(link) for link in parser.links],[path])
        self.assertEqual(parser.external,[])
        self.assertNotIn('<script>',page)
        self.assertIn('&lt;script&gt;',page)
        self.assertIn('&lt;img',page)
        self.assertIn('Файлов: 1',page)
        self.assertIn('Занятий: 1',page)
        self.assertIn('name="viewport"',page)
    def test_period_uses_student_timezone(self):
        page=render_contents([{'starts_at':0,'topic':'','links':[]}], 'America/New_York')
        self.assertIn('31.12.1969 — 31.12.1969',page)
        self.assertIn('19:00',page)
