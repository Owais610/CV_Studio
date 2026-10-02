"""Preview source locations recorded during ReportLab layout, not text guesses."""
from copy import deepcopy
from html import unescape
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import Flowable, Paragraph

from cv_studio_richtext import normalize_url


def _unicode_style(text, style):
    """Keep serif styles where possible; preserve names outside their encoding."""
    families = {'Times-Roman': 'CV', 'Times-Bold': 'CV-Bold',
                'Times-Italic': 'CV-Italic', 'Times-BoldItalic': 'CV-BoldItalic'}
    fallback = families.get(getattr(style, 'fontName', None))
    if not fallback or not text:
        return style
    visible = unescape(re.sub(r'<[^>]*>', '', str(text)))
    font = pdfmetrics.getFont(style.fontName)
    encodings = [font.encName, *(substitution.encName for substitution in font.substitutionFonts)]
    for char in set(visible):
        for encoding in encodings:
            try:
                char.encode(encoding)
                break
            except UnicodeEncodeError:
                pass
        else:
            # Clone the style so ordinary paragraphs keep their serif font.
            return ParagraphStyle(style.name + '_unicode', parent=style, fontName=fallback)
    return style


class SourceParagraph(Paragraph):
    def __init__(self, *args, source=None, regions=None, **kwargs):
        if len(args) >= 2:
            args = (args[0], _unicode_style(args[0], args[1]), *args[2:])
        elif 'style' in kwargs:
            kwargs['style'] = _unicode_style(args[0] if args else kwargs.get('text'), kwargs['style'])
        super().__init__(*args, **kwargs)
        self.source, self.regions = source, regions
        # A paragraph continued on another page needs at least two lines on
        # either side of the break. Long paragraphs remain free to split.
        self.allowWidows = self.allowOrphans = 0

    def __deepcopy__(self, memo):
        # BalancedColumns measures copies of paragraphs. The measurements may
        # draw the final fragments, so all copies must report to one source map.
        clone = self.__class__.__new__(self.__class__)
        memo[id(self)] = clone
        for name, value in self.__dict__.items():
            setattr(clone, name, value if name == 'regions' else deepcopy(value, memo))
        return clone

    def split(self, availWidth, availHeight):
        # Frame.split reports its unindented width. Keep the width used by
        # wrap(), including sidebar gutters and table cell padding.
        if getattr(self, 'width', 0) > 0:
            availWidth = min(availWidth, self.width)
        fragments = super().split(availWidth, availHeight)
        for i, fragment in enumerate(fragments):
            # ReportLab returns base Paragraph objects here. Keep our draw hook
            # on every fragment so click-to-edit survives page/column breaks.
            fragment.__class__ = self.__class__
            fragment.source, fragment.regions = self.source, self.regions
            if hasattr(self,'rule_color'):
                fragment.rule_color = self.rule_color if i==len(fragments)-1 else None
            if hasattr(self,'timeline_dot'):
                fragment.timeline_dot = self.timeline_dot if i==0 else False
        return fragments

    def draw(self):
        if self.source is not None and self.regions is not None:
            x, y = self.canv.absolutePosition(0, 0)
            height = self.canv._pagesize[1]
            self.regions.append(dict(page=self.canv.getPageNumber()-1,
                                     rect=(x, height-y-self.height, x+self.width, height-y),
                                     source=self.source))
        super().draw()


class ContactBlock(Flowable):
    """Wrap whole contact entries; draw separators only within a complete row.

    A long email or URL gets its own wrapping paragraph. No separator can be
    stranded at the end/start of a line, and every link remains live text.
    """
    def __init__(self, paragraphs, style, *, stacked=False, separator=True, gap=14,
                 row_gap=3):
        super().__init__()
        self.paragraphs, self.style = list(paragraphs), style
        self.stacked, self.separator = stacked, separator
        self.gap, self.row_gap = gap, row_gap
        self.spaceAfter = style.spaceAfter
        self.rows = []

    def __bool__(self):
        return bool(self.paragraphs)

    def _copy(self, paragraphs):
        return ContactBlock(paragraphs, self.style, stacked=self.stacked,
                            separator=self.separator, gap=self.gap, row_gap=self.row_gap)

    def wrap(self, availWidth, availHeight):
        canvas = getattr(self, 'canv', None)
        self.rows = []
        row, used, height = [], 0, 0

        def finish():
            nonlocal row, used, height
            if row:
                self.rows.append((row, used, height))
            row, used, height = [], 0, 0

        for paragraph in self.paragraphs:
            text = paragraph.getPlainText()
            natural = pdfmetrics.stringWidth(text, paragraph.style.fontName,
                                              paragraph.style.fontSize) + .5
            width = availWidth if self.stacked else min(availWidth, max(1, natural))
            if row and (self.stacked or used + self.gap + width > availWidth + .01):
                finish()
            paragraph.wrapOn(canvas, width, 1e8)
            x = used + (self.gap if row else 0)
            row.append((paragraph, x))
            used, height = x + width, max(height, paragraph.height)
            if self.stacked or natural > availWidth:
                finish()
        finish()
        self.width = availWidth
        self.height = sum(row[2] for row in self.rows) + self.row_gap * max(0, len(self.rows)-1)
        return self.width, self.height

    def split(self, availWidth, availHeight):
        if getattr(self, 'width', 0) > 0:
            availWidth = min(availWidth, self.width)
        self.wrap(availWidth, availHeight)
        used, count = 0, 0
        for items, _, height in self.rows:
            needed = height + (self.row_gap if count else 0)
            if used + needed > availHeight + .01:
                break
            used += needed
            count += 1
        if count == len(self.rows):
            return [self]
        if count:
            first = [p for items, _, _ in self.rows[:count] for p, _ in items]
            rest = [p for items, _, _ in self.rows[count:] for p, _ in items]
            return [self._copy(first), self._copy(rest)]
        if self.rows and len(self.rows[0][0]) == 1:
            paragraph = self.rows[0][0][0][0]
            fragments = paragraph.splitOn(getattr(self, 'canv', None), availWidth, availHeight)
            if fragments:
                rest = [p for items, _, _ in self.rows[1:] for p, _ in items]
                return fragments + ([self._copy(rest)] if rest else [])
        return []

    def draw(self):
        top = self.height
        for items, used, height in self.rows:
            offset = (self.width-used)/2 if self.style.alignment == TA_CENTER and not self.stacked else 0
            for index, (paragraph, x) in enumerate(items):
                if index and self.separator:
                    self.canv.saveState()
                    self.canv.setFillColor(self.style.textColor)
                    baseline = top - paragraph.style.leading + paragraph.style.fontSize * .35
                    self.canv.circle(offset + x - self.gap/2, baseline,
                                     max(.6, paragraph.style.fontSize*.09), stroke=0, fill=1)
                    self.canv.restoreState()
                paragraph.drawOn(self.canv, offset+x, top-paragraph.height)
            top -= height + self.row_gap


def contact_block(builder, style=None, *, stacked=False, separator=True, gap=None):
    """Build an atomic, source-aware contact row for any CV masthead/sidebar."""
    style = style or builder.S['contact']
    # Each entry aligns naturally; only the complete row may be centered.
    item_style = ParagraphStyle(style.name+'_entry', parent=style, alignment=TA_LEFT,
                                splitLongWords=1, uriWasteReduce=.3, spaceBefore=0, spaceAfter=0)
    paragraphs = []
    for index, contact in enumerate(builder.d.get('contacts', [])):
        text = (contact.get('text') or '').strip()
        url = (contact.get('url') or '').strip()
        if not (text or url):
            continue
        if not text:
            text = re.sub(r'^https?://(?:www\.)?', '', url).rstrip('/')
        text = builder.clean_glyphs(text)
        target = normalize_url(url) if url else ('mailto:'+text if re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',text) else '')
        markup = builder.esc(text)
        if target:
            builder.links += 1
            color = colors.toColor(style.textColor).hexval().replace('0x', '#')
            markup = f'<link href="{builder.esc(target).replace(chr(34), "%22")}" color="{color}">{markup}</link>'
        paragraphs.append(SourceParagraph(markup, item_style, source=('contacts',index,'text'),
                                          regions=builder.source_regions))
    return ContactBlock(paragraphs, style, stacked=stacked, separator=separator,
                        gap=gap if gap is not None else 14*builder.k,
                        row_gap=3*builder.k*getattr(builder,'spacing',1))
