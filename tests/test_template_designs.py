"""Realistic and difficult CVs verify layout behavior across every template.

Visual exports: python test_artifacts/template_review.py
"""
import base64
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import io
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_entries import engine, ROOT
from cv_studio_pdf import SourceParagraph
from cv_studio_richtext import plain
from cv_studio_sections import ENTRY_TYPES, empty_entry, entry_type
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4


@dataclass
class ReviewFixture:
    name: str
    data: dict
    markers: dict
    links: tuple = ()
    min_pages: int = 1
    max_pages: int = None


def base_document():
    data = engine.migrate(engine.DEFAULT_DATA)
    data['personal'] = dict(name='Alex Morgan', role='Senior Product and Data Engineer')
    data['contacts'] = [dict(text='alex.morgan@example.com', url=''),
                        dict(text='portfolio.example.com/alex', url='https://portfolio.example.com/alex'),
                        dict(text='London, United Kingdom', url=''),
                        dict(text='+44 20 7946 0000', url='')]
    data['profile'] = ''
    for key in ('projects', 'skills', 'experience', 'education'):
        data[key] = []
    data['custom_sections'] = {}
    data['settings'].update(autofit=False, font_scale=100, margin_mm=14, photo='')
    for section in data['settings']['sections']:
        section['visible'] = True
    return data


def custom_section(data, key, title, entries, layout='auto'):
    data['custom_sections'][key] = entries
    data['settings']['sections'].append(dict(key=key, title=title, visible=True, entry_layout=layout))


def professional():
    data = base_document()
    data['profile'] = (
        'Product engineer with eight years of experience translating complex research into reliable services. '
        'Leads cross functional teams, improves analytical workflows, and connects customer needs to measurable outcomes. '
        'Combines practical Python engineering with clear communication and careful experimentation.')
    data['projects'] = [dict(title='Open climate intelligence platform',
                            meta='Civic Data Lab | 2024 - 2026 | <a href="https://example.com/climate">Project overview</a>',
                            bullets=['Built a reproducible data service used by 28 partner organisations across three countries.',
                                     'Reduced monthly processing time by 42 percent through automated validation and parallel workflows.']),
                        dict(title='Accessible service redesign', meta='Northstar Digital | 2023',
                             bullets=['Improved task completion by 18 percent through user research and simpler interaction patterns.'])]
    data['skills'] = [dict(category='Engineering', items='Python | SQL | PostgreSQL | APIs | Automated testing | Git'),
                      dict(category='Research and delivery', items='Experimental design | Product analytics | Accessibility | Stakeholder communication'),
                      dict(category='Languages', items='English (fluent) | French (working proficiency)')]
    data['experience'] = [dict(title='Senior Product Engineer', company='Northstar Digital | London', dates='2022 - Present',
                              description='Lead a team of five engineers delivering a public information platform for 120,000 monthly users.\n'
                                          'Introduced service monitoring and reduced support incidents by 35 percent while mentoring two new technical leads.'),
                          dict(title='Data Engineer', company='Civic Data Lab | Manchester', dates='2018 - 2022',
                               description='Developed data ingestion pipelines and collaborated with policy researchers to publish transparent, reproducible evidence.')]
    data['education'] = [dict(degree='MSc Computer Science', institution='University of Manchester', dates='2017 - 2018',
                             gpa='Distinction', distinction='Faculty research scholarship',
                             coursework='Distributed systems, statistical learning, human computer interaction')]
    custom_section(data, 'custom_professional_certifications', 'Certifications', [
        dict(empty_entry('certification'), title='Cloud Architecture Professional', issuer='Example Certification Institute',
             dates='2025', credential_id='CAP-2048', link='https://example.com/credentials/CAP-2048')])
    return ReviewFixture('professional', data, {},
                         ('mailto:alex.morgan@example.com', 'https://portfolio.example.com/alex',
                          'https://example.com/climate', 'https://example.com/credentials/CAP-2048'), max_pages=2)


def long_identity():
    data = base_document()
    data['personal'] = dict(name='Dr Alexandra Josephine Montgomery de la Cruz-Wellington',
                            role='Principal Research Scientist and Director of Responsible Artificial Intelligence Systems')
    long_url = 'https://research.example.com/people/alexandra-montgomery/publications/longitudinal-responsible-ai-evaluation-framework'
    data['contacts'] = [dict(text='alexandra.montgomery.delacruz@international-research.example.com', url=''),
                        dict(text=long_url.removeprefix('https://'), url=long_url),
                        dict(text='Department of Computer Science, International Research Campus, London, United Kingdom', url=''),
                        dict(text='+44 (0)20 7946 0832 ext. 204', url='')]
    data['profile'] = 'Develops transparent evaluation methods for complex systems operating across different institutions and languages. HeaderContactTailMarker'
    data['experience'] = [dict(title='Principal Scientist for International Responsible Artificial Intelligence Evaluation and Governance',
                              company='International Centre for Human Centred Research and Computational Social Science',
                              dates='January 2020 - September 2026',
                              description='Coordinated work across independent research teams and maintained reproducible evaluation protocols. ExperienceIdentityEndMarker')]
    custom_section(data, 'custom_long_titles', 'Selected Publications and International Research Contributions', [
        dict(empty_entry('publication'),
             title='A Longitudinal Framework for Assessing Transparent and Responsible Artificial Intelligence in Multilingual Public Services',
             authors='Alexandra J. Montgomery de la Cruz-Wellington; Priya Ramanathan; Mateo Fernandez',
             venue='International Journal of Human Centred Computing and Responsible Systems Engineering',
             dates='2026', link='10.1234/transparent-responsible-multilingual-public-service-evaluation',
             description='Combines deployment evidence with qualitative observations and rigorous reproducibility checks. PublicationIdentityEndMarker')])
    return ReviewFixture('long_identity', data, dict(HeaderContactTailMarker=1, ExperienceIdentityEndMarker=1, PublicationIdentityEndMarker=1),
                         ('mailto:alexandra.montgomery.delacruz@international-research.example.com', long_url,
                          'https://doi.org/10.1234/transparent-responsible-multilingual-public-service-evaluation'))


def many_sections():
    data = professional().data
    data['settings']['sections'] = [section for section in data['settings']['sections'] if not section['key'].startswith('custom_')]
    data['custom_sections'] = {}
    markers = {}
    links = ['https://doi.org/10.1234/review-0', 'mailto:referee.review@example.com']
    for number in range(9):
        marker = f'SectionMarker{number}'
        markers[marker] = 1
        publication = dict(empty_entry('publication'), title=f'Research evidence synthesis {number}',
                           authors='Alex Morgan; Priya Ramanathan', venue='Journal of Applied Research', dates='2026',
                           link=f'10.1234/review-{number}',
                           description=f'Evaluated deployment quality using transparent methods, stakeholder interviews, and reproducible evidence. {marker}')
        note = dict(empty_entry('text'), title=f'Practice and community contribution {number}',
                    description='Organised interdisciplinary workshops and published reusable technical guidance for practitioners.')
        entries = [publication, note]
        if number % 2 == 0:
            entries += [dict(empty_entry('award'), title=f'Community Research Award {number}', organisation='Research Network', dates='2025')]
        custom_section(data, f'custom_review_{number}', f'Research and Professional Contribution {number + 1}', entries)
    custom_section(data, 'custom_review_references', 'Professional References', [
        dict(empty_entry('reference'), name='Dr Priya Ramanathan', role='Research collaborator', organisation='Example University',
             email='referee.review@example.com', phone='+44 20 7946 0821'),
        dict(empty_entry('reference'), name='Professor Mateo Fernandez', role='Programme director', organisation='Example Institute',
             email='mateo.review@example.com')])
    return ReviewFixture('many_sections', data, markers, tuple(links), min_pages=2)


def long_entries():
    data = base_document()
    data['profile'] = 'Researcher experienced in clear evidence synthesis and practical engineering.'
    sentence = 'Evaluated long term service reliability using transparent methods and reproducible datasets. '
    data['experience'] = [dict(title='Lead Research Engineer', company='Example Research Institute', dates='2020 - Present',
                              description=('ResultsMarker ' + sentence) * 100 + 'ExperienceTailMarker')]
    data['skills'] = [dict(category='Methods', items='Analysis | Reproducibility | Communication')]
    custom_section(data, 'custom_long_publication', 'Extended Research Contributions', [
        dict(empty_entry('publication'), title='Longitudinal evidence and reproducibility', authors='Alex Morgan; Priya Ramanathan',
             venue='Journal of Applied Research', dates='2026', link='10.1234/long-review',
             description=('AbstractMarker ' + sentence) * 100 + 'AbstractTailMarker'),
        dict(empty_entry('bullets'), title='Extended project evidence',
             bullets=[('BulletMarker ' + sentence) * 60 + 'BulletTailMarker']),
        dict(empty_entry('text'), title='Final short entry', description='FinalVisibleMarker')])
    data['settings'].update(font_scale=115, margin_mm=24)
    return ReviewFixture('long_entries', data,
                         dict(ResultsMarker=100, ExperienceTailMarker=1, AbstractMarker=100, AbstractTailMarker=1,
                              BulletMarker=60, BulletTailMarker=1, FinalVisibleMarker=1),
                         ('https://doi.org/10.1234/long-review',), min_pages=3)


def uneven_columns():
    data = base_document()
    data['profile'] = 'Engineer skilled in reliable analysis and communication across a broad range of projects.'
    data['skills'] = [dict(category='A deliberately lengthy technical and interdisciplinary research skills category',
                           items='Python, SQL, data modelling, automation, stakeholder communication, reproducibility, accessibility, statistical learning. ' * 8 + 'SkillsTailMarker'),
                      dict(category='Languages', items='English'),
                      dict(category='Tools', items='Git | Linux | Docker | PostgreSQL | Observability')]
    data['experience'] = [dict(title='Research Engineer', company='Example Institute', dates='2025 - Present',
                              description='ShortDescriptionMarker'),
                          dict(title='Lead Engineer for Transparent International Evaluation and Responsible Research Systems',
                               company='Independent Research Consortium with Offices Across Europe', dates='2018 - 2025',
                               description=('UnevenExperienceMarker Reliable systems require careful validation, readable documentation, and clear ownership. ') * 55),
                          dict(title='Consultant', company='Example Studio', dates='2017', description='FinalExperienceMarker')]
    custom_section(data, 'custom_uneven_pairs', 'Selected Qualifications', [
        dict(empty_entry('education'), degree='MSc Data Science', institution='Example University', dates='2016',
             coursework='Statistics, reproducibility, distributed systems. ' * 35 + 'CourseworkTailMarker'),
        dict(empty_entry('education'), degree='Short Professional Qualification', institution='Example Institute', dates='2025'),
        dict(empty_entry('award'), title='Outstanding Research Communication Award', organisation='International Research Network', dates='2026')], 'columns')
    return ReviewFixture('uneven_columns', data,
                         dict(SkillsTailMarker=1, ShortDescriptionMarker=1, UnevenExperienceMarker=55,
                              FinalExperienceMarker=1, CourseworkTailMarker=1), min_pages=2)


def synthetic_portrait():
    """A locally drawn placeholder makes the photo fixture portable."""
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (480, 640), '#D7E4EC')
    drawing = ImageDraw.Draw(image)
    drawing.rectangle((0, 400, 480, 640), fill='#B7CFDE')
    drawing.ellipse((93, 335, 395, 790), fill='#354B64')
    drawing.ellipse((155, 125, 326, 350), fill='#E4B995')
    drawing.pieslice((142, 80, 335, 281), 180, 355, fill='#39404A')
    drawing.line((195, 243, 208, 243), fill='#4B4644', width=4)
    drawing.line((267, 243, 280, 243), fill='#4B4644', width=4)
    drawing.arc((216, 267, 266, 293), 0, 180, fill='#A56B58', width=3)
    output = io.BytesIO()
    image.save(output, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')


def portrait():
    fixture = professional()
    fixture.name = 'portrait'
    fixture.data['settings'].update(photo=synthetic_portrait(), photo_crop=dict(x=.5, y=.43, zoom=1.1))
    return fixture


FIXTURE_BUILDERS = (professional, long_identity, many_sections, long_entries, uneven_columns, portrait)


def compact_text(value):
    return re.sub(r'\s+', '', value).replace('\u00ad', '')


def visible_text(data):
    """Fields that should survive PDF export, independent of layout styling."""
    yield from data['personal'].values()
    for contact in data['contacts']:
        if contact.get('text'):
            yield contact['text']
    for section in data['settings']['sections']:
        if not section.get('visible', True):
            continue
        key = section['key']
        if key == 'profile':
            yield plain(data[key])
        elif key in data['custom_sections']:
            for entry in data['custom_sections'][key]:
                for field in ENTRY_TYPES[entry_type(entry)].fields:
                    value = entry.get(field.key, '')
                    yield from (plain(line) for line in value) if isinstance(value, list) else (plain(value),)
        else:
            for entry in data[key]:
                for value in entry.values():
                    yield from (plain(line) for line in value) if isinstance(value, list) else (plain(value),)


def text_lines(page):
    for block in page.get_text('dict')['blocks']:
        for line in block.get('lines', ()):
            text = ''.join(span['text'] for span in line['spans'])
            if text.strip():
                yield text, engine.pymupdf.Rect(line['bbox'])


def is_body(source):
    return source and (source == ('profile',) or any(field in source for field in ('description', 'bullets', 'coursework')))


def expected_sources(data):
    for field, value in data['personal'].items():
        if value.strip():
            yield ('personal', field)
    if any(contact.get('text') or contact.get('url') for contact in data['contacts']):
        yield ('contacts',)
    for section in data['settings']['sections']:
        if not section.get('visible', True):
            continue
        key = section['key']
        if key == 'profile':
            if plain(data[key]).strip():
                yield ('profile',)
            continue
        entries = data['custom_sections'].get(key, data.get(key, []))
        for index, entry in enumerate(entries):
            if key in data['custom_sections']:
                fields = [field.key for field in ENTRY_TYPES[entry_type(entry)].fields]
            else:
                fields = list(entry)
            for field in fields:
                value = entry.get(field, '')
                if isinstance(value, list):
                    for line_index, line in enumerate(value):
                        if plain(line).strip():
                            yield (key, index, field, line_index)
                elif plain(value).strip():
                    yield (key, index, field)


def render_review(fixture, template):
    data = deepcopy(fixture.data)
    data['settings']['template'] = template
    paragraphs = []
    original_draw = SourceParagraph.draw
    def record_draw(paragraph):
        if paragraph.source:
            paragraphs.append(dict(source=paragraph.source, alignment=paragraph.style.alignment,
                                   justify_last_line=getattr(paragraph.style, 'justifyLastLine', 0)))
        return original_draw(paragraph)
    regions = []
    with patch.object(SourceParagraph, 'draw', record_draw):
        pdf, pages, links, autofit = engine.render_pdf(data, source_map=regions)
    issues = []
    with engine.pymupdf.open(stream=pdf, filetype='pdf') as doc:
        extracted = ''.join(page.get_text() for page in doc)
        compact = compact_text(extracted)
        identity_fields = [*data['personal'].values(), *(contact.get('text', '') for contact in data['contacts'])]
        for value in identity_fields:
            if value.strip() and compact_text(engine.clean_glyphs(value)) not in compact:
                issues.append(f'Identity text loss: {value!r}')
        expected_words = Counter(re.findall(r'[A-Za-z0-9]{6,}', ' '.join(visible_text(data))))
        for word, count in expected_words.items():
            if compact.count(word) < count:
                issues.append(f'Text loss: {word!r}, expected at least {count}, found {compact.count(word)}')
        for marker, count in fixture.markers.items():
            found = compact.count(marker)
            if found != count:
                issues.append(f'Marker loss or duplication: {marker}, expected {count}, found {found}')
        if pages != len(doc) or not fixture.min_pages <= len(doc) or (fixture.max_pages and len(doc) > fixture.max_pages):
            issues.append(f'Unexpected pagination: returned {pages}, actual {len(doc)}, expected {fixture.min_pages}..{fixture.max_pages or "unbounded"}')
        if not data['settings']['autofit'] and autofit != 1:
            issues.append(f'Unexpected autofit with autofit disabled: {autofit}')
        name = data['personal']['name'].casefold()
        if doc.metadata['author'].casefold() != name or name not in doc.metadata['title'].casefold() or not doc.metadata['creator']:
            issues.append(f'Metadata omitted the CV identity: {doc.metadata}')
        actual_links = {link.get('uri') for page in doc for link in page.get_links()}
        for link in fixture.links:
            if link not in actual_links:
                issues.append(f'Missing PDF link: {link}')
        for region in regions:
            if not 0 <= region['page'] < len(doc):
                issues.append(f'Invalid source page: {region}')
                continue
            x0, y0, x1, y1 = region['rect']
            page = doc[region['page']]
            if not (-.5 <= x0 < x1 <= page.rect.width+.5 and -.5 <= y0 < y1 <= page.rect.height+.5):
                issues.append(f'Clipped source region: {region}')
        for source in expected_sources(data):
            if any(tuple(region['source'][:len(source)]) == source for region in regions):
                continue
            if source[0] == 'experience' and source[-1] in ('title', 'company', 'dates'):
                # The classic template may group these fields into one identity
                # paragraph; clicking it still reveals the corresponding entry.
                if any(region['source'] == (*source[:2], 'identity') for region in regions):
                    continue
            issues.append(f'Missing source region: {source}')
        for section in data['settings']['sections']:
            key = section['key']
            content = [r for r in regions if r['source'][0] == key]
            if not content:
                continue
            headings = [r for r in regions if r['source'] == ('section', key)]
            first_page = min(r['page'] for r in content)
            if not headings or min(r['page'] for r in headings) != first_page:
                issues.append(f'Heading separated from first content: {key}')
        for page in doc:
            if abs(page.rect.width-A4[0]) > .1 or abs(page.rect.height-A4[1]) > .1:
                issues.append(f'Unexpected page size: {page.number+1}, {page.rect}')
            if not any(region['page'] == page.number for region in regions):
                issues.append(f'Page has no editable content: {page.number+1}')
            for link in page.get_links():
                box = link['from']
                if not (-.5 <= box.x0 < box.x1 <= page.rect.width+.5 and -.5 <= box.y0 < box.y1 <= page.rect.height+.5):
                    issues.append(f'Clipped PDF link on page {page.number+1}: {link.get("uri", "")}, {tuple(box)}')
                if not any(region['page'] == page.number and box.intersects(engine.pymupdf.Rect(region['rect'])) for region in regions):
                    issues.append(f'PDF link has no click-to-edit source on page {page.number+1}: {link.get("uri", "")}')
            lines = sorted(text_lines(page), key=lambda item: item[1].y0)
            for index, (text, box) in enumerate(lines):
                if not (-.5 <= box.x0 <= box.x1 <= page.rect.width+.5 and -.5 <= box.y0 <= box.y1 <= page.rect.height+.5):
                    issues.append(f'Clipped text on page {page.number+1}: {text!r}, {tuple(box)}')
                if text.strip() in ('·', '|', '•'):
                    contacts = [r for r in regions if r['source'] == ('contacts',) and r['page'] == page.number]
                    if any(box.intersects(engine.pymupdf.Rect(r['rect'])) for r in contacts):
                        issues.append(f'Standalone contact separator on page {page.number+1}')
                for other_text, other_box in lines[index+1:]:
                    if other_box.y0 >= box.y1:
                        break
                    overlap_x = min(box.x1, other_box.x1) - max(box.x0, other_box.x0)
                    overlap_y = min(box.y1, other_box.y1) - max(box.y0, other_box.y0)
                    if overlap_x > .75 and overlap_y > min(box.height, other_box.height)*.3:
                        issues.append(f'Overlapping text on page {page.number+1}: {text[:65]!r} / {other_text[:65]!r}')
        if template == 'Creative / Photo CV' and data['settings']['photo'] and not any(page.get_images() for page in doc):
            issues.append('The supplied portrait is missing from the photo template')
        for paragraph in paragraphs:
            source = paragraph['source']
            if 'items' in source:
                # Skills are lists rather than continuous prose. Either left
                # alignment or justification can suit the selected template.
                if paragraph['justify_last_line']:
                    issues.append(f'Skills last line is stretched: {source}')
                continue
            if is_body(source):
                if paragraph['alignment'] != TA_JUSTIFY:
                    issues.append(f'Body text is not justified: {source}')
                if paragraph['justify_last_line']:
                    issues.append(f'Body last line is stretched: {source}')
            elif paragraph['alignment'] == TA_JUSTIFY:
                issues.append(f'Identity or label text is justified: {source}')
        report = dict(fixture=fixture.name, template=template, pages=len(doc), links=links, font_factor=autofit,
                      source_regions=len(regions), issues=list(dict.fromkeys(issues)),
                      metadata=doc.metadata, text_characters=len(extracted))
    return pdf, report


class TemplateDesignTests(unittest.TestCase):
    def test_realistic_and_adversarial_documents_every_template(self):
        for build_fixture in FIXTURE_BUILDERS:
            fixture = build_fixture()
            for template in engine.TEMPLATES:
                with self.subTest(fixture=fixture.name, template=template):
                    _, report = render_review(fixture, template)
                    self.assertEqual(report['issues'], [], '\n'.join(report['issues']))

    def test_short_entry_metadata_stays_with_its_first_body_lines(self):
        sentence = 'Clear engineering evidence helps teams deliver reliable and accessible services. '
        body = ('AttachmentBodyMarker Led a small research team, validated deployment evidence, and published clear '
                'guidance that improved reliability and made technical decisions easier to review.')
        for template in engine.TEMPLATES:
            for kind in ('experience', 'project', 'publication'):
                with self.subTest(template=template, entry_type=kind):
                    data = base_document()
                    data['settings']['template'] = template
                    if kind == 'experience':
                        data['experience'] = [dict(title='Research Engineer', company='Example Institute',
                                                   dates='2020 - Present', description=body)]
                        key, identity_fields, body_field = 'experience', ('title', 'company', 'dates'), 'description'
                    elif kind == 'project':
                        data['projects'] = [dict(title='Reliable Research Services',
                                                meta='Example Institute | 2025 - 2026', bullets=[body])]
                        key, identity_fields, body_field = 'projects', ('title', 'meta'), 'bullets'
                    else:
                        key = 'custom_attachment_publication'
                        custom_section(data, key, 'Selected Publications', [
                            dict(empty_entry('publication'), title='Transparent Service Evaluation',
                                 authors='Alex Morgan; Priya Ramanathan', venue='Journal of Applied Research',
                                 dates='2026', link='10.1234/attachment', description=body)])
                        identity_fields, body_field = ('title', 'authors', 'venue', 'dates', 'link'), 'description'
                    cache = {}

                    def pages_at(repetitions):
                        if repetitions not in cache:
                            data['profile'] = sentence * repetitions
                            regions = []
                            engine.render_pdf(data, source_map=regions)
                            pages = {}
                            for field in (*identity_fields, body_field):
                                source = (key, 0, field)
                                matches = [r for r in regions if tuple(r['source'][:3]) == source]
                                if not matches and key == 'experience' and field in identity_fields:
                                    matches = [r for r in regions if r['source'] == (key, 0, 'identity')]
                                self.assertTrue(matches, f'Missing entry field: {template}, {kind}, {source}')
                                pages[field] = min(r['page'] for r in matches)
                            cache[repetitions] = pages
                        return cache[repetitions]

                    # Locate the page boundary for this layout rather than
                    # depending on a particular font size or section spacing.
                    low, high = 0, 128
                    self.assertEqual(pages_at(low)[body_field], 0)
                    self.assertGreater(pages_at(high)[body_field], 0)
                    while high-low > 1:
                        middle = (low+high)//2
                        if pages_at(middle)[body_field] == 0:
                            low = middle
                        else:
                            high = middle
                    for repetitions in range(max(0, high-3), high+4):
                        pages = pages_at(repetitions)
                        self.assertEqual(len(set(pages.values())), 1,
                                         f'Short identity/metadata separated from body at profile length {repetitions}: {pages}')

    def test_autofit_preserves_readability_and_manual_small_text(self):
        sentence = 'AutoFitRunMarker Clear engineering evidence helps teams deliver reliable and accessible services. '
        for template in engine.TEMPLATES:
            for scale in (100, 95, 80):
                with self.subTest(template=template, font_scale=scale):
                    data = base_document()
                    data['settings'].update(template=template, autofit=True, font_scale=scale)
                    data['profile'] = sentence * 100 + 'AutoFitTailMarker'
                    pdf, pages, _, autofit = engine.render_pdf(data)
                    self.assertGreaterEqual(autofit, .92)
                    if scale < 100:
                        self.assertEqual(autofit, 1, 'Manual small text was shrunk again by AutoFit')
                    if scale == 100:
                        self.assertGreater(pages, 1, 'Long content was compressed into one page')
                    with engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
                        self.assertEqual(pages, len(document))
                        text = compact_text(''.join(page.get_text() for page in document))
                        self.assertIn('AutoFitTailMarker', text)
                        self.assertEqual(text.count('AutoFitRunMarker'), 100)


if __name__ == '__main__':
    unittest.main()
