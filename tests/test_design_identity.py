"""Preserve the established template designs while their layout is polished.

These checks use source positions, typography and PDF vector decorations rather
than screenshots, so improved spacing and line wrapping remain possible.
"""
import base64
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_entries import engine
from cv_studio_pdf import SourceParagraph
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY


def identity_document():
    data = engine.migrate(engine.DEFAULT_DATA)
    data['personal'] = dict(name='Alex Morgan', role='Senior Product and Data Engineer')
    data['contacts'] = [dict(text='alex.morgan@example.com', url=''),
                        dict(text='portfolio.example.com/alex', url='https://portfolio.example.com/alex'),
                        dict(text='London, United Kingdom', url=''),
                        dict(text='+44 20 7946 0000', url='')]
    data['profile'] = 'A careful engineering professional delivering reliable services through research and collaboration.'
    data['projects'] = [dict(title='Reliable service platform', meta='Research Lab | 2025',
                             bullets=['Built clear interfaces and reproducible research evidence.'])]
    data['skills'] = [dict(category='Engineering', items='Python | SQL | APIs')]
    data['experience'] = [dict(title='Senior Engineer', company='Research Lab', dates='2020 - Present',
                               description='Delivered reliable services with a collaborative multidisciplinary team.')]
    data['education'] = [dict(degree='MSc Computer Science', institution='Example University', dates='2019 - 2020',
                              gpa='3.9 / 4.0', distinction='Research scholarship',
                              coursework='Distributed systems and statistical learning')]
    data['custom_sections'] = {}
    data['settings'].update(theme='Navy Blue', autofit=False, font_scale=100, margin_mm=14, photo='')
    data['settings']['sections'] = [dict(key=key, title=title, visible=True) for key, title in
                                    [('profile', 'PROFILE'), ('projects', 'PROJECTS & ACHIEVEMENTS'),
                                     ('skills', 'SKILLS & EXPERTISE'), ('experience', 'EXPERIENCE'),
                                     ('education', 'EDUCATION')]]
    return data


def render_identity(template, data=None):
    data = identity_document() if data is None else data
    data['settings']['template'] = template
    regions, paragraphs = [], []
    original = SourceParagraph.draw

    def record(paragraph):
        if paragraph.source:
            paragraphs.append(dict(source=paragraph.source, font=paragraph.style.fontName,
                                   size=paragraph.style.fontSize, leading=paragraph.style.leading,
                                   alignment=paragraph.style.alignment, color=paragraph.style.textColor,
                                   kind=paragraph.__class__.__name__))
        return original(paragraph)

    with patch.object(SourceParagraph, 'draw', record):
        pdf, pages, _, autofit = engine.render_pdf(data, source_map=regions)
    with engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
        drawings = [page.get_drawings() for page in document]
        page_width, page_height = document[0].rect.width, document[0].rect.height
        images = [page.get_image_info() for page in document]
    return dict(data=data, regions=regions, paragraphs=paragraphs, drawings=drawings,
                pages=pages, autofit=autofit, width=page_width, height=page_height, images=images)


def region(review, source):
    return next(item['rect'] for item in review['regions'] if item['source'] == source)


def paragraph(review, source):
    return next(item for item in review['paragraphs'] if item['source'] == source)


def filled_rectangles(review, page=0):
    # Contact separator dots are also filled vector paths. Exclude those small
    # shapes when examining the masthead, shaded cells and continuous rails.
    return [item['rect'] for item in review['drawings'][page]
            if item.get('fill') and item['rect'].width > 20 and item['rect'].height > 8]


class DesignIdentityTests(unittest.TestCase):
    def assert_columns(self, left, right):
        self.assertLess(left[2], right[0], 'The original separate columns were flattened or overlap')
        self.assertAlmostEqual(left[1], right[1], delta=1)

    def test_original_type_scale_and_prose_alignment(self):
        expected = {'Modern Professional': (25, 8.15, 11.3),
                    'Minimal / ATS-friendly': (27, 8.6, 12.2),
                    'Executive': (28, 8.6, 12.2),
                    'Two-Column': (28, 8.6, 12.2),
                    'Academic / Research': (26, 10, 14),
                    'Creative / Photo CV': (29, 8.6, 12.2)}
        self.assertEqual(set(expected), set(engine.TEMPLATES))
        for template, (name_size, body_size, body_leading) in expected.items():
            with self.subTest(template=template):
                review = render_identity(template)
                self.assertEqual(review['pages'], 1)
                self.assertEqual(review['autofit'], 1)
                self.assertAlmostEqual(paragraph(review, ('personal', 'name'))['size'], name_size)
                body = paragraph(review, ('profile',))
                self.assertAlmostEqual(body['size'], body_size)
                self.assertAlmostEqual(body['leading'], body_leading)
                self.assertEqual(body['alignment'], TA_JUSTIFY)

    def test_modern_keeps_shaded_profile_skill_grid_and_experience_columns(self):
        review = render_identity('Modern Professional')
        profile_label, profile = region(review, ('section', 'profile')), region(review, ('profile',))
        category, items = region(review, ('skills', 0, 'category')), region(review, ('skills', 0, 'items'))
        self.assert_columns(profile_label, profile)
        self.assert_columns(category, items)
        self.assert_columns(region(review, ('experience', 0, 'identity')),
                            region(review, ('experience', 0, 'description', 0)))
        shaded = filled_rectangles(review)
        self.assertTrue(any(box.x0 < profile_label[0] and box.x1 > profile[2]
                            and box.y0 <= profile[1] < box.y1 for box in shaded),
                        'The original shaded profile panel is missing')
        self.assertTrue(any(box.x0 < category[0] < box.x1 < items[0]
                            and box.y0 <= category[1] < box.y1 for box in shaded),
                        'The skill category shading is missing')
        degree, gpa = region(review, ('education', 0, 'degree')), region(review, ('education', 0, 'gpa'))
        self.assertGreater(gpa[0], degree[0] + (degree[2]-degree[0])*.85)
        self.assertAlmostEqual(gpa[1], degree[1], delta=1)

    def test_executive_keeps_two_column_masthead_and_editorial_section_rail(self):
        review = render_identity('Executive')
        name, contact = region(review, ('personal', 'name')), region(review, ('contacts', 0, 'text'))
        self.assertLess(name[2], contact[0])
        self.assertAlmostEqual(name[1], contact[1], delta=20)
        self.assertTrue(any(box.x0 < name[0] and box.x1 > contact[2]
                            and box.y0 < name[1] and box.y1 > name[3]
                            for box in filled_rectangles(review)), 'The original full masthead is missing')
        self.assertEqual(paragraph(review, ('personal', 'name'))['color'].hexval(), '0xffffff')
        self.assert_columns(region(review, ('section', 'projects')), region(review, ('projects', 0, 'title')))
        self.assert_columns(region(review, ('section', 'experience')), region(review, ('experience', 0, 'title')))

    def test_executive_without_contacts_paginates_an_oversized_identity(self):
        for field, text, marker in (
                ('name', 'Alexandria ' * 100, 'NameTailMarker'),
                ('role', 'Senior Principal Engineer ' * 180, 'RoleTailMarker')):
            with self.subTest(field=field):
                data = identity_document()
                data['contacts'] = []
                data['personal'][field] = text + marker
                data['settings']['template'] = 'Executive'
                pdf, pages, _, autofit = engine.render_pdf(data)
                self.assertGreater(pages, 1)
                self.assertEqual(autofit, 1)
                with engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
                    content = ''.join(page.get_text() for page in document)
                self.assertEqual(content.count(marker), 1)
                self.assertEqual(content.count('MSc Computer Science'), 1)

    def test_two_column_keeps_continuous_shaded_section_rail_on_every_page(self):
        data = identity_document()
        data['projects'] *= 12
        review = render_identity('Two-Column', data)
        self.assertGreater(review['pages'], 1)
        for page in range(review['pages']):
            with self.subTest(page=page):
                rails = [box for box in filled_rectangles(review, page)
                         if box.height > review['height']*.8 and box.width < review['width']*.3]
                self.assertEqual(len(rails), 1, 'The full section rail must not become a header-only block')
        self.assertLess(region(review, ('contacts', 0, 'text'))[2], region(review, ('personal', 'name'))[0])
        self.assert_columns(region(review, ('section', 'projects')), region(review, ('projects', 0, 'title')))

    def test_photo_keeps_full_height_navy_rail_portrait_and_timeline(self):
        from PIL import Image
        encoded = io.BytesIO()
        Image.new('RGB', (80, 100), '#A4B8CF').save(encoded, format='PNG')
        data = identity_document()
        data['settings']['photo'] = base64.b64encode(encoded.getvalue()).decode('ascii')
        review = render_identity('Creative / Photo CV', data)
        rails = [box for box in filled_rectangles(review)
                 if box.height > review['height']*.99 and box.width < review['width']*.35]
        self.assertEqual(len(rails), 1)
        rail = rails[0]
        self.assertAlmostEqual(rail.x0, 0, delta=.1)
        self.assertTrue(review['images'][0], 'The portrait was dropped')
        photo = review['images'][0][0]['bbox']
        self.assertLess(photo[2], rail.x1)
        self.assertGreater(photo[0], rail.x0)
        self.assertGreater(region(review, ('personal', 'name'))[0], rail.x1)
        self.assert_columns(region(review, ('section', 'experience')), region(review, ('experience', 0, 'title')))
        self.assertEqual(paragraph(review, ('experience', 0, 'title'))['kind'], 'TimelineParagraph')
        self.assertEqual(paragraph(review, ('education', 0, 'degree'))['kind'], 'TimelineParagraph')

    def test_academic_keeps_centered_serif_identity_and_single_reading_column(self):
        review = render_identity('Academic / Research')
        self.assertEqual(paragraph(review, ('personal', 'name'))['font'], 'Times-Bold')
        self.assertEqual(paragraph(review, ('personal', 'name'))['alignment'], TA_CENTER)
        self.assertEqual(paragraph(review, ('personal', 'role'))['alignment'], TA_CENTER)
        self.assertEqual(paragraph(review, ('profile',))['font'], 'Times-Roman')
        self.assertEqual(paragraph(review, ('experience', 0, 'company'))['font'], 'Times-Italic')
        self.assertAlmostEqual(region(review, ('section', 'projects'))[0], region(review, ('projects', 0, 'title'))[0])
        self.assertEqual(filled_rectangles(review), [])

    def test_minimal_keeps_quiet_monochrome_single_column(self):
        review = render_identity('Minimal / ATS-friendly')
        self.assertEqual(filled_rectangles(review), [])
        for item in review['paragraphs']:
            channels = (item['color'].red, item['color'].green, item['color'].blue)
            self.assertLess(max(channels)-min(channels), .08, item['source'])
        for label, content in [(('section', 'profile'), ('profile',)),
                               (('section', 'projects'), ('projects', 0, 'title')),
                               (('section', 'experience'), ('experience', 0, 'title'))]:
            self.assertAlmostEqual(region(review, label)[0], region(review, content)[0])


if __name__ == '__main__':
    unittest.main()
