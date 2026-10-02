"""Prefer one page should use whitespace before text and keep useful results."""
from copy import deepcopy
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_entries import engine
from test_template_designs import base_document, custom_section, compact_text, expected_sources
from cv_studio_sections import empty_entry
from reportlab.platypus.doctemplate import LayoutError


NORMAL = (1.0, 1.0, 1.0)
FIT_STEPS = [NORMAL, (1.0, .92, 1.0), (1.0, .84, .97), (1.0, .76, .94),
             (.98, .76, .94), (.96, .76, .94), (.94, .76, .94), (.92, .76, .94)]


class AutoFitSelectionTests(unittest.TestCase):
    def render_candidates(self, counts, *, bottoms=None, enabled=True, scale=100, template=None):
        data = base_document()
        data['settings'].update(autofit=enabled, font_scale=scale,
                                template=template or engine.DEFAULT_TEMPLATE)
        original = deepcopy(data)
        built = []
        bottoms = [20] * len(counts) if bottoms is None else bottoms

        class CandidateBuilder:
            def __init__(self, data, af=1.0, spacing=1.0, leading=1.0):
                self.af, self.spacing, self.leading = af, spacing, leading
                self.index = len(built)
                self.links = 10 + self.index
                pages = counts[self.index] if isinstance(counts[self.index], int) else 1
                self.source_regions = [dict(source=('candidate', self.index), page=pages-1,
                                            rect=(10, 10, 20, bottoms[self.index]))]
                built.append((af, spacing, leading))

            def build(self, target):
                if isinstance(counts[self.index], Exception):
                    raise counts[self.index]
                target.write(f'candidate-{self.index}'.encode())
                return counts[self.index]

        regions = [dict(source=('old',))]
        with patch.object(engine, 'CVBuilder', CandidateBuilder), \
             patch.object(engine, 'build_template', lambda builder, target, template: builder.build(target)):
            result = engine.render_pdf(data, source_map=regions)
        self.assertEqual(data, original, 'Trying fit candidates changed the saved CV settings or content')
        return result, regions, built

    def assert_candidate(self, result, regions, index, pages, af, bottom=20):
        self.assertEqual(result, (f'candidate-{index}'.encode(), pages, 10 + index, af))
        self.assertEqual(regions, [dict(source=('candidate', index), page=pages-1,
                                       rect=(10, 10, 20, bottom))])

    def test_one_page_baseline_is_returned_without_changes(self):
        result, regions, built = self.render_candidates([1])
        self.assert_candidate(result, regions, 0, 1, 1)
        self.assertEqual(built, [NORMAL])

    def test_whitespace_fit_stops_before_any_font_reduction(self):
        result, regions, built = self.render_candidates([2, 2, 1])
        self.assert_candidate(result, regions, 2, 1, 1)
        self.assertEqual(built, FIT_STEPS[:3])

    def test_font_fit_stops_at_first_success(self):
        result, regions, built = self.render_candidates([2, 2, 2, 2, 2, 1])
        self.assert_candidate(result, regions, 5, 1, .96)
        self.assertEqual(built, FIT_STEPS[:6])

    def test_same_page_count_preserves_original_pdf_and_navigation(self):
        result, regions, built = self.render_candidates([3] * len(FIT_STEPS))
        self.assert_candidate(result, regions, 0, 3, 1)
        self.assertEqual(built, FIT_STEPS)

    def test_later_worse_results_do_not_replace_an_improvement(self):
        result, regions, built = self.render_candidates([4, 4, 3, 3, 3, 2, 3, 3])
        self.assert_candidate(result, regions, 5, 2, .96)
        self.assertEqual(built, FIT_STEPS)

    def test_equal_improvements_keep_the_least_compressed_result(self):
        result, regions, built = self.render_candidates([3, 2, 2, 2, 2, 2, 2, 2])
        self.assert_candidate(result, regions, 1, 2, 1)
        self.assertEqual(built, FIT_STEPS)

    def test_small_manual_fonts_only_try_whitespace_changes(self):
        for scale in (95, 80):
            with self.subTest(scale=scale):
                result, regions, built = self.render_candidates([2, 2, 2, 2], scale=scale)
                self.assert_candidate(result, regions, 0, 2, 1)
                self.assertEqual(built, FIT_STEPS[:4])

    def test_whitespace_reduces_overflow_on_the_same_number_of_pages(self):
        result, regions, built = self.render_candidates([3] * len(FIT_STEPS),
                                                       bottoms=[300, 280, 250, 235, 200, 180, 150, 140])
        self.assert_candidate(result, regions, 3, 3, 1, 235)
        self.assertEqual(built, FIT_STEPS)

    def test_small_overflow_differences_preserve_original_layout(self):
        result, regions, built = self.render_candidates([3] * len(FIT_STEPS),
                                                       bottoms=[300, 292, 289, 289, 200, 180, 150, 140])
        self.assert_candidate(result, regions, 0, 3, 1, 300)
        self.assertEqual(built, FIT_STEPS)

    def test_worse_page_count_cannot_win_through_a_shorter_tail(self):
        result, regions, built = self.render_candidates([2, 3, 2, 2, 2, 2, 2, 2],
                                                       bottoms=[300, 40, 290, 289, 200, 180, 150, 140])
        self.assert_candidate(result, regions, 0, 2, 1, 300)
        self.assertEqual(built, FIT_STEPS)

    def test_font_reduction_requires_a_page_count_improvement(self):
        result, regions, built = self.render_candidates([2] * len(FIT_STEPS),
                                                       bottoms=[300, 300, 300, 300, 250, 200, 150, 100])
        self.assert_candidate(result, regions, 0, 2, 1, 300)
        self.assertEqual(built, FIT_STEPS)

    def test_invalid_fit_candidate_is_skipped_without_losing_valid_results(self):
        for counts, index, pages, af in (
                ([3, LayoutError('invalid compact candidate'), 3, 3, 3, 2, 3, 3], 5, 2, .96),
                ([3, LayoutError('invalid compact candidate'), 3, 3, 3, 3, 3, 3], 0, 3, 1)):
            with self.subTest(candidate=index):
                result, regions, built = self.render_candidates(counts)
                self.assert_candidate(result, regions, index, pages, af)
                self.assertEqual(built, FIT_STEPS)

    def test_baseline_layout_error_is_reported(self):
        with self.assertRaisesRegex(LayoutError, 'baseline failure'):
            self.render_candidates([LayoutError('baseline failure')])

    def test_disabled_fitting_builds_once_in_each_render_path(self):
        for template in (engine.DEFAULT_TEMPLATE, 'Executive'):
            with self.subTest(template=template):
                result, regions, built = self.render_candidates([2], enabled=False, template=template)
                self.assert_candidate(result, regions, 0, 2, 1)
                self.assertEqual(built, [NORMAL])


def near_boundary_document(template, count):
    data = base_document()
    data['settings']['template'] = template
    data['profile'] = 'Engineering professional delivering reliable services through research and collaboration.'
    entries = [dict(empty_entry('text'), title=f'FitEntryMarker{index:03d}',
                    description=('Delivered accessible services using clear technical evidence and collaborative engineering. '
                                 '<a href="https://example.com/fit-review">Review evidence</a>'))
               for index in range(count)]
    custom_section(data, 'custom_fit_review', 'Selected Contributions', entries)
    return data


def content_fonts(document):
    # Page numbers are outside the content area and disappear on a one-page CV.
    return {(span['font'], round(span['size'], 3))
            for page in document for block in page.get_text('dict')['blocks']
            for line in block.get('lines', ()) for span in line['spans']
            if span['text'].strip() and span['bbox'][1] < page.rect.height - 30}


def last_source_bottom(regions, pages):
    return max((region['rect'][3] for region in regions if region['page'] == pages-1), default=0)


class AutoFitPDFTests(unittest.TestCase):
    def assert_complete_content(self, document, data, count, regions, links):
        text = compact_text(''.join(page.get_text() for page in document))
        for index in range(count):
            self.assertEqual(text.count(f'FitEntryMarker{index:03d}'), 1)
        self.assertEqual(text.count('Deliveredaccessibleservices'), count)
        for source in expected_sources(data):
            self.assertTrue(any(region['source'][:len(source)] == source for region in regions), source)
        uris = [link.get('uri') for page in document for link in page.get_links()]
        self.assertEqual(uris.count('https://example.com/fit-review'), count)
        self.assertGreaterEqual(links, count)
        for region in regions:
            self.assertTrue(0 <= region['page'] < len(document))
            page = document[region['page']]
            x0, y0, x1, y1 = region['rect']
            self.assertTrue(-.5 <= x0 < x1 <= page.rect.width + .5)
            self.assertTrue(-.5 <= y0 < y1 <= page.rect.height + .5)
        for page in document:
            for block in page.get_text('dict')['blocks']:
                for line in block.get('lines', ()):
                    x0, y0, x1, y1 = line['bbox']
                    self.assertTrue(-.5 <= x0 < x1 <= page.rect.width + .5)
                    self.assertTrue(-.5 <= y0 < y1 <= page.rect.height + .5)
            for link in page.get_links():
                self.assertTrue(page.rect.contains(link['from']))

    def test_near_boundary_cvs_fit_through_whitespace_without_text_loss(self):
        for template in engine.TEMPLATES:
            with self.subTest(template=template):
                # Find the boundary in the installed fonts rather than relying
                # on a particular machine's exact line wrapping or page count.
                lower, upper = 1, 32
                data = near_boundary_document(template, upper)
                self.assertGreater(engine.render_pdf(data)[1], 1)
                while lower < upper:
                    middle = (lower + upper) // 2
                    if engine.render_pdf(near_boundary_document(template, middle))[1] > 1:
                        upper = middle
                    else:
                        lower = middle + 1
                data = near_boundary_document(template, lower)
                baseline_pdf, baseline_pages, _, _ = engine.render_pdf(data)
                self.assertEqual(baseline_pages, 2)
                data['settings']['autofit'] = True
                saved = deepcopy(data)
                regions = []
                pdf, pages, links, af = engine.render_pdf(data, source_map=regions)
                self.assertEqual(data, saved)
                self.assertEqual((pages, af), (1, 1), 'A near-boundary CV needed font shrinking before spacing could fit it')
                with engine.pymupdf.open(stream=baseline_pdf, filetype='pdf') as baseline, \
                     engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
                    self.assertEqual(content_fonts(document), content_fonts(baseline))
                    self.assertEqual(len(document), 1)
                    self.assert_complete_content(document, data, lower, regions, links)

    def test_longer_cvs_reduce_overflow_without_shrinking_text(self):
        for template in engine.TEMPLATES:
            with self.subTest(template=template):
                selected = None
                # These documents deliberately contain too much for one page.
                # Find a stable two/three-page case in the available font set.
                for count in (24, 28, 36, 44):
                    data = near_boundary_document(template, count)
                    original_regions = []
                    baseline_pdf, baseline_pages, _, _ = engine.render_pdf(data, source_map=original_regions)
                    data['settings']['autofit'] = True
                    saved = deepcopy(data)
                    regions = []
                    pdf, pages, links, af = engine.render_pdf(data, source_map=regions)
                    self.assertEqual(data, saved)
                    if (pages == baseline_pages > 1 and af == 1 and
                            last_source_bottom(original_regions, pages) - last_source_bottom(regions, pages) >= 12):
                        selected = (count, data, baseline_pdf, pdf, pages, links, regions)
                        break
                self.assertIsNotNone(selected, 'No useful spacing adjustment was returned for a longer CV')
                count, data, baseline_pdf, pdf, pages, links, regions = selected
                with engine.pymupdf.open(stream=baseline_pdf, filetype='pdf') as baseline, \
                     engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
                    self.assertEqual(len(document), pages)
                    self.assertEqual(content_fonts(document), content_fonts(baseline))
                    self.assert_complete_content(document, data, count, regions, links)

    def test_photo_rail_continuation_handles_compressed_entries(self):
        # The gentle .92 spacing step previously produced an oversized first
        # split; also check the most compact spacing without the fallback.
        count = 28
        data = near_boundary_document('Creative / Photo CV', count)
        baseline_pdf, baseline_pages, _, _ = engine.render_pdf(data)
        # Exercise the continued table directly so skipping a failed candidate
        # in render_pdf cannot conceal a regression in its split measurement.
        for spacing, leading in ((.92,1),(.76,.94)):
            with self.subTest(spacing=spacing,leading=leading):
                builder = engine.CVBuilder(data, spacing=spacing, leading=leading)
                target = io.BytesIO()
                direct_pages = engine.build_template(builder, target, data['settings']['template'])
                with engine.pymupdf.open(stream=target.getvalue(), filetype='pdf') as document:
                    self.assertEqual(len(document), direct_pages)
                    self.assert_complete_content(document, data, count, builder.source_regions, builder.links)
        data['settings']['autofit'] = True
        saved = deepcopy(data)
        regions = []
        pdf, pages, links, af = engine.render_pdf(data, source_map=regions)
        self.assertEqual(data, saved)
        self.assertLessEqual(pages, baseline_pages)
        self.assertGreaterEqual(af, .92)
        with engine.pymupdf.open(stream=baseline_pdf, filetype='pdf') as baseline, \
             engine.pymupdf.open(stream=pdf, filetype='pdf') as document:
            self.assertEqual(len(document), pages)
            if af == 1:
                self.assertEqual(content_fonts(document), content_fonts(baseline))
            self.assert_complete_content(document, data, count, regions, links)


if __name__ == '__main__':
    unittest.main()
