"""Regression coverage for usable legacy files and complete PDF URL targets."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_entries import engine
from cv_studio_richtext import parse, serialize
from cv_studio_pdf import SourceParagraph
from reportlab.lib.styles import ParagraphStyle


class DocumentDataTests(unittest.TestCase):
    def test_parentheses_in_bare_and_markdown_urls(self):
        target = 'https://en.wikipedia.org/wiki/Function_(mathematics)'
        examples = (
            (target, target, target),
            ('(' + target + ').', '(' + target + ').', target),
            ('[Function](' + target + ')', 'Function', target),
            ('[**Function**](' + target + ')', 'Function', target),
            ('[Nested](https://example.com/a_(b_(c)))', 'Nested', 'https://example.com/a_(b_(c))'),
        )
        for source, visible, url in examples:
            with self.subTest(source=source):
                text, attrs = parse(source)
                self.assertEqual(text, visible)
                self.assertEqual({attr.link for attr in attrs if attr.link}, {url})
                self.assertEqual(parse(serialize(text, attrs)), (text, attrs))
        # Sentence punctuation and surrounding brackets are outside the target.
        text, attrs = parse('See (' + target + ').')
        self.assertFalse(attrs[-1].link)
        self.assertFalse(attrs[-2].link)
        self.assertEqual(attrs[-3].link, target)

    def test_parentheses_survive_pdf_export(self):
        target = 'https://en.wikipedia.org/wiki/Function_(mathematics)'
        data = engine.migrate(engine.DEFAULT_DATA)
        data['projects'] = [dict(title='URL examples', meta='[Function](' + target + ')', bullets=[target])]
        pdf, *_ = engine.render_pdf(data)
        with engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
            links = [link.get('uri') for page in document for link in page.get_links()]
            self.assertEqual(links.count(target), 2)
            self.assertNotIn(target[:-1], links)

    def test_legacy_string_bullets_keep_lines_and_formatting(self):
        data = engine.migrate({'projects': [{'title': 'Legacy project', 'bullets': '<b>First result</b>\nSecond result'}]})
        self.assertEqual(data['projects'][0]['bullets'], ['<b>First result</b>', 'Second result'])
        self.assertEqual(engine.migrate(json.loads(json.dumps(data))), data)
        pdf, *_ = engine.render_pdf(data)
        with engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
            text = ''.join(page.get_text() for page in document)
            self.assertIn('First result', text)
            self.assertIn('Second result', text)

    def test_null_fields_and_collections_are_usable(self):
        raw = dict(personal=dict(name=None, role=2026), profile=None, contacts=None,
                   projects=[dict(title=None, meta=None, bullets=None)], skills=None,
                   experience=[dict(title=None, description=None)],
                   education=[dict(degree=None, gpa=4)])
        data = engine.migrate(raw)
        self.assertEqual(data['personal'], dict(name='', role='2026'))
        self.assertEqual(data['profile'], '')
        self.assertEqual(data['contacts'], [])
        self.assertEqual(data['skills'], [])
        self.assertEqual(data['projects'][0], dict(title='', meta='', bullets=[]))
        self.assertEqual(data['education'][0]['gpa'], '4')
        for template in engine.TEMPLATES:
            with self.subTest(template=template):
                data['settings']['template'] = template
                pdf, pages, *_ = engine.render_pdf(data)
                self.assertTrue(pdf.startswith(b'%PDF-'))
                self.assertGreater(pages, 0)

    def test_numeric_settings_and_unknown_choices_are_normalized(self):
        for value in (None, 'invalid', float('inf'), float('-inf'), float('nan'), {}):
            with self.subTest(value=value):
                data = engine.migrate(dict(settings=dict(font_scale=value, margin_mm=value)))
                self.assertEqual(data['settings']['font_scale'], engine.DEFAULT_DATA['settings']['font_scale'])
                self.assertEqual(data['settings']['margin_mm'], engine.DEFAULT_DATA['settings']['margin_mm'])
        for value, scale, margin in (('105', 105, 24), (1, 80, 6), (1000, 115, 24)):
            data = engine.migrate(dict(settings=dict(font_scale=value, margin_mm=value)))
            self.assertEqual(data['settings']['font_scale'], scale)
            self.assertEqual(data['settings']['margin_mm'], margin)
        data = engine.migrate(dict(settings=dict(theme={}, template=[], ui_mode='unknown', autofit=None)))
        for key in ('theme', 'template', 'ui_mode', 'autofit'):
            self.assertEqual(data['settings'][key], engine.DEFAULT_DATA['settings'][key])

    def test_invalid_shapes_fail_with_clear_validation(self):
        examples = (
            ([], 'CV data'), (None, 'CV data'),
            (dict(settings=[]), 'Settings'), (dict(personal='text'), 'Personal details'),
            (dict(contacts={}), 'Contacts'), (dict(projects='text'), 'Projects'),
            (dict(experience=['text']), 'Experience entry 1'),
            (dict(skills=[['only category']]), 'Skills entry 1'),
            (dict(projects=[dict(bullets={})]), 'highlights'),
            (dict(personal=dict(name={})), 'Personal name'),
        )
        for raw, label in examples:
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(ValueError, label):
                    engine.migrate(raw)

    def test_missing_data_and_legacy_contacts_preserve_defaults(self):
        data = engine.migrate({})
        for key in ('personal', 'profile', 'contacts', 'projects', 'skills', 'experience', 'education'):
            self.assertEqual(data[key], engine.DEFAULT_DATA[key])
        data = engine.migrate(dict(personal=dict(phone='12345', email='person@example.com',
                                                github='https://github.com/person', github_display='My code')))
        self.assertEqual(data['contacts'], [dict(text='12345', url=''), dict(text='person@example.com', url=''),
                                            dict(text='My code', url='https://github.com/person')])

    def test_blank_builtin_sections_are_omitted_in_every_template(self):
        data = engine.migrate(dict(profile='<b></b>', contacts=[dict(text='  ', url='')],
                                   projects=[dict(title='', meta='<i></i>', bullets=['  '])],
                                   skills=[dict(category='', items='<b></b>')],
                                   experience=[dict(title='', description='\n ')],
                                   education=[dict(degree='', coursework='<i></i>')]))
        data['settings']['autofit'] = False
        for index, section in enumerate(data['settings']['sections']):
            section['title'] = f'EmptySectionMarker{index}'
        for template in engine.TEMPLATES:
            with self.subTest(template=template):
                data['settings']['template'] = template
                regions = []
                pdf, *_ = engine.render_pdf(data, source_map=regions)
                with engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
                    text = ''.join(page.get_text() for page in document)
                    self.assertNotIn('EMPTYSECTIONMARKER', text.upper())
                self.assertFalse(any(region['source'][0] in ('section', 'contacts') for region in regions))

    def test_blank_cards_preserve_following_pdf_source_indices(self):
        data = engine.migrate(dict(projects=[{}, dict(title='ProjectIndexMarker', bullets=['Real result'])],
                                   skills=[{}, dict(category='SkillsIndexMarker', items='Real skill')],
                                   experience=[{}, dict(title='ExperienceIndexMarker', description='Real outcome')],
                                   education=[{}, dict(degree='EducationIndexMarker')]))
        data['settings']['autofit'] = False
        for template in engine.TEMPLATES:
            with self.subTest(template=template):
                data['settings']['template'] = template
                regions = []
                pdf, *_ = engine.render_pdf(data, source_map=regions)
                sources = {region['source'] for region in regions}
                for section, field in (('projects', 'title'), ('skills', 'category'),
                                       ('experience', 'identity' if template == 'Modern Professional' else 'title'),
                                       ('education', 'degree')):
                    self.assertIn((section, 1, field), sources)
                    self.assertFalse(any(source[0] == section and len(source) > 1 and source[1] == 0 for source in sources))
                with engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
                    text = ''.join(page.get_text() for page in document)
                    for marker in ('ProjectIndexMarker', 'SkillsIndexMarker', 'ExperienceIndexMarker', 'EducationIndexMarker'):
                        self.assertIn(marker, text)

    def test_academic_fallback_preserves_unicode_and_serif_styles(self):
        # WinAnsi and Symbol characters already supported by Times stay serif.
        style = ParagraphStyle('serif_test', fontName='Times-Roman')
        self.assertEqual(SourceParagraph('Ren\u00e9 \u017deljko \u03a9 \u2192', style).style.fontName, 'Times-Roman')
        self.assertEqual(SourceParagraph('\u0141ukasz \u0100nand', style).style.fontName, 'CV')
        self.assertEqual(style.fontName, 'Times-Roman')
        bold = ParagraphStyle('bold_test', fontName='Times-Bold')
        self.assertEqual(SourceParagraph('\u0141ukasz', bold).style.fontName, 'CV-Bold')
        italic = ParagraphStyle('italic_test', fontName='Times-Italic')
        self.assertEqual(SourceParagraph('\u0100nand', italic).style.fontName, 'CV-Italic')
        data = engine.migrate(dict(personal=dict(name='\u0141ukasz \u0100nand'),
                                   profile='\u0100nand collaborates with <b>\u0141ukasz</b> on research.',
                                   projects=[dict(title='Ordinary serif title', bullets=[])],
                                   experience=[], education=[], skills=[]))
        data['settings'].update(template='Academic / Research', autofit=False)
        regions = []
        pdf, *_ = engine.render_pdf(data, source_map=regions)
        with engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
            text = ''.join(page.get_text() for page in document)
            self.assertIn('\u0141ukasz \u0100nand', text)
            self.assertIn('\u0100nand collaborates with \u0141ukasz', text)
            title_spans = [span for page in document for block in page.get_text('dict')['blocks'] if 'lines' in block
                           for line in block['lines'] for span in line['spans'] if 'Ordinary serif title' in span['text']]
            self.assertTrue(title_spans)
            self.assertTrue(all(span['font'] == 'Times-Bold' for span in title_spans))
        self.assertTrue(any(region['source'] == ('personal', 'name') for region in regions))
        self.assertTrue(any(region['source'] == ('profile',) for region in regions))


if __name__ == '__main__':
    unittest.main()
