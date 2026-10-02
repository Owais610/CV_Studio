#!/usr/bin/env python3
"""
CV Studio  -  build a professional CV on the left and review the live PDF on the right.

Requirements
    python -m pip install -r requirements.txt
    Python 3.10+ with Tkinter (see README for Windows/macOS/Linux setup).

Text formatting
    Select text and use Bold / Ctrl+B, Italic / Ctrl+I, or Link / Ctrl+K.
    Formatting is displayed visually. Existing Markdown/HTML JSON files still open.
    Keep cv_studio_ui.py, cv_studio_richtext.py, and cv_studio_pdf.py beside this file.

Fonts
    The PDF uses DejaVu Sans. If it is not installed, drop DejaVuSans.ttf,
    DejaVuSans-Bold.ttf, DejaVuSans-Oblique.ttf and DejaVuSans-BoldOblique.ttf
    into a folder called "fonts" next to this script. Otherwise the editor falls
    back to Bitstream Vera (bundled with ReportLab), which looks virtually identical.
"""

import base64
import io
import json
import os
import re
import subprocess
import sys
import tkinter as tk
from copy import deepcopy
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont

from cv_studio_richtext import plain, reportlab_markup
from cv_studio_pdf import SourceParagraph, contact_block
from cv_studio_templates import DEFAULT_TEMPLATE, TEMPLATES, RuledHeading, polish_classic_styles, build as build_template
from cv_studio_data import migrate_document
from cv_studio_sections import is_custom
from cv_studio_appearance import DEFAULT_UI_THEME, DEFAULT_UI_MODE, DEFAULT_UI_STYLE
from cv_studio_templates import custom_section
import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, LayoutError, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

try:  # optional: live preview
    import pymupdf
except Exception:
    try:
        import fitz as pymupdf
    except Exception:
        pymupdf = None


# ============================================================
# DEFAULT CV DATA
# ============================================================

DEFAULT_SECTIONS = [
    {"key": "profile", "title": "PROFILE", "visible": True},
    {"key": "projects", "title": "PROJECTS & ACHIEVEMENTS", "visible": True},
    {"key": "skills", "title": "SKILLS & EXPERTISE", "visible": True},
    {"key": "experience", "title": "EXPERIENCE", "visible": True},
    {"key": "education", "title": "EDUCATION", "visible": True},
]

DEFAULT_DATA = {
    "version": 2,
    "personal": {
        "name": "YOUR NAME",
        "role": "Professional title or target role",
    },
    "contacts": [
        {"text": "+00 000 000 0000", "url": ""},
        {"text": "you@example.com", "url": ""},
        {"text": "linkedin.com/in/your-name", "url": "https://linkedin.com/in/your-name"},
        {"text": "City, Country", "url": ""},
    ],
    "profile": (
        "Write a concise introduction that connects your experience, strongest skills, and the value you bring. "
        "Aim for two to four focused sentences tailored to the role you want. Replace this starter text before exporting."
    ),
    "projects": [
        {
            "title": "Featured project, publication, or achievement",
            "meta": "**Organisation or client** | Month Year - Month Year | [Project link](https://example.com)",
            "bullets": [
                "Start with a strong action verb and describe what you created, improved, or delivered.",
                "Add a measurable result where possible, such as time saved, growth achieved, or users supported.",
            ],
        },
    ],
    "skills": [
        {"category": "CORE SKILLS", "items": "Skill one | Skill two | Skill three | Skill four"},
        {"category": "TOOLS & TECHNOLOGIES", "items": "Tool one | Tool two | Tool three"},
        {"category": "LANGUAGES", "items": "Language one (level) | Language two (level)"},
    ],
    "experience": [
        {
            "title": "Job title",
            "company": "Company name | City, Country",
            "dates": "Month Year - Present",
            "description": (
                "Describe your scope, contribution, and outcome. Use specific evidence and results rather than "
                "responsibility-only statements."
            ),
        },
    ],
    "education": [
        {
            "degree": "Degree or qualification",
            "institution": "University, school, or training provider",
            "dates": "Year - Year",
            "distinction": "Optional honour, scholarship, or distinction",
            "gpa": "Optional GPA / grade",
            "coursework": "Optional relevant coursework, certification, or academic project",
        },
    ],
    "settings": {
        "theme": "Navy Blue",
        "template": DEFAULT_TEMPLATE,
        "photo": "",
        "ui_mode": DEFAULT_UI_MODE,
        "ui_theme": DEFAULT_UI_THEME,
        "ui_style": DEFAULT_UI_STYLE,
        "font_scale": 100,
        "margin_mm": 13,
        "autofit": True,
        "sections": deepcopy(DEFAULT_SECTIONS),
    },
}

EDU_KEYS = ["degree", "institution", "dates", "distinction", "gpa", "coursework"]

THEMES = {
    "Navy Blue": dict(navy="#17324D", blue="#2D6F9F", light="#EEF3F7", mid="#687887", text="#20262C", line="#D8E0E6"),
    "Teal":      dict(navy="#0F4C5C", blue="#1B8A9C", light="#ECF5F6", mid="#5F7C82", text="#1D2A2D", line="#D3E4E7"),
    "Forest":    dict(navy="#1F4D3A", blue="#3C8D6B", light="#EEF5F1", mid="#6B7F75", text="#1F2A25", line="#D5E2DA"),
    "Burgundy":  dict(navy="#5A1F2E", blue="#A23B55", light="#F6EEF0", mid="#806B72", text="#2A2024", line="#E4D6DA"),
    "Slate":     dict(navy="#2B3440", blue="#5B6B7F", light="#F0F2F4", mid="#6E7885", text="#20262C", line="#D9DEE3"),
}


# ============================================================
# FONTS  (DejaVu Sans if available, otherwise bundled Bitstream Vera)
# ============================================================

def setup_fonts():
    here = Path(__file__).resolve().parent
    dirs = [
        here / "fonts", here / "assets" / "fonts", here,
        Path("/usr/share/fonts/truetype/dejavu"), Path("/usr/share/fonts/dejavu"),
        Path("/usr/share/fonts/TTF"), Path("/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"),
        Path.home() / ".local/share/fonts", Path.home() / ".fonts", Path.home() / "Library/Fonts",
    ]
    if sys.platform == "win32":
        windows_dir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
        local_data = os.environ.get("LOCALAPPDATA")
        if windows_dir:
            dirs.append(Path(windows_dir) / "Fonts")
        if local_data:
            dirs.append(Path(local_data) / "Microsoft/Windows/Fonts")
    try:
        import matplotlib
        dirs.append(Path(matplotlib.get_data_path()) / "fonts" / "ttf")
    except Exception:
        pass

    sets = [
        ("DejaVu Sans", ["DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans-Oblique.ttf", "DejaVuSans-BoldOblique.ttf"], dirs),
        ("Bitstream Vera", ["Vera.ttf", "VeraBd.ttf", "VeraIt.ttf", "VeraBI.ttf"], [Path(reportlab.__file__).parent / "fonts"]),
    ]
    for label, files, search in sets:
        for d in search:
            paths = [d / f for f in files]
            if all(p.exists() for p in paths):
                for name, p in zip(["CV", "CV-Bold", "CV-Italic", "CV-BoldItalic"], paths):
                    pdfmetrics.registerFont(TTFont(name, str(p)))
                pdfmetrics.registerFontFamily("CV", normal="CV", bold="CV-Bold",
                                              italic="CV-Italic", boldItalic="CV-BoldItalic")
                return label, set(pdfmetrics.getFont("CV").face.charToGlyph)
    raise RuntimeError("No usable TrueType font found. Put DejaVuSans*.ttf into a 'fonts' folder next to this script.")


FONT_LABEL, GLYPHS = setup_fonts()
GLYPH_FALLBACK = {
    "\u2014": "-", "\u2013": "-", "\u2212": "-", "\u2022": "*", "\u2192": "->", "\u2018": "'", "\u2019": "'",
    "\u201c": '"', "\u201d": '"', "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\u200b": "", "\u2026": "...",
}


def clean_glyphs(text):
    out = []
    for ch in text:
        if ch in "\n\r\t" or ord(ch) in GLYPHS:
            out.append(ch)
        else:
            out.append(GLYPH_FALLBACK.get(ch, ""))
    return "".join(out)


# ============================================================
# RICH TEXT  (**bold**, *italic*, [label](url), bare URLs)
# ============================================================

LINK_MD = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
BARE_URL = re.compile(r"https?://[^\s<>\[\]()]+")
BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
ITALIC = re.compile(r"(?<![\*\w])\*(?![\s*])(.+?)(?<![\s*])\*(?![\*\w])", re.S)
EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def esc(text):
    return str(text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def to_markup(s):
    """Legacy and new formatting are parsed by the shared rich-text bridge."""
    return s


def norm_url(u):
    u = (u or "").strip()
    if not u:
        return ""
    if re.match(r"^(https?://|mailto:|tel:)", u, re.I):
        return u
    if EMAIL.fullmatch(u):
        return "mailto:" + u
    return "https://" + u


def display_url(u):
    u = re.sub(r"^https?://(www\.)?", "", u).rstrip("/")
    return re.sub(r"^(dx\.)?doi\.org/", "", u)


def strip_markup(s):
    return plain(s)


# ============================================================
# PDF ENGINE
# ============================================================

def make_styles(t, k):
    """ParagraphStyles for a theme `t` at overall scale `k`."""
    C = {n: colors.HexColor(v) for n, v in t.items()}

    def S(name, font, size, lead, color, **kw):
        for key in ("spaceBefore", "spaceAfter"):
            if key in kw:
                kw[key] *= k
        return ParagraphStyle(name, fontName=font, fontSize=size * k, leading=lead * k, textColor=color, allowWidows=0, allowOrphans=0, splitLongWords=1,
                              justifyLastLine=0, justifyBreaks=0, **kw)

    return dict(
        name=S("name", "CV-Bold", 25, 27, C["navy"]),
        role=S("role", "CV", 11.5, 14, C["blue"]),
        contact=S("contact", "CV", 8.2, 10.5, C["mid"]),
        section=S("section", "CV-Bold", 10.2, 12, C["navy"], spaceBefore=9, spaceAfter=5),
        body=S("body", "CV", 8.15, 11.3, C["text"], alignment=TA_JUSTIFY),
        small=S("small", "CV", 7.7, 10.2, C["text"], alignment=TA_JUSTIFY),
        project=S("project", "CV-Bold", 9.4, 11.5, C["text"]),
        meta=S("meta", "CV", 7.7, 10, C["mid"]),
        bullet=S("bullet", "CV", 7.9, 10.6, C["text"], leftIndent=10 * k, firstLineIndent=-5 * k,
                 alignment=TA_JUSTIFY, spaceAfter=1.8),
        edu=S("edu", "CV-Bold", 8.8, 11, C["text"]),
        edumeta=S("edumeta", "CV-Bold", 8.1, 10.2, C["mid"]),
        distinction=S("distinction", "CV-Bold", 8.6, 10.5, C["blue"]),
        skillhead=S("skillhead", "CV-Bold", 7.7, 9.7, C["navy"]),
        skilltext=S("skilltext", "CV", 7.7, 10.1, C["text"], alignment=TA_LEFT),
        gpalabel=S("gpalabel", "CV-Bold", 8, 10, C["mid"], alignment=TA_RIGHT),
        gpa=S("gpa", "CV-Bold", 12, 14, C["blue"], alignment=TA_RIGHT),
    )


class CVBuilder:
    def __init__(self, data, af=1.0, spacing=1.0, leading=1.0):
        self.d = data
        self.esc, self.clean_glyphs = esc, clean_glyphs
        st = data["settings"]
        self.t = THEMES.get(st["theme"], THEMES["Navy Blue"])
        self.C = {n: colors.HexColor(v) for n, v in self.t.items()}
        self.af = af
        self.spacing, self.leading = spacing, leading
        self.k = af * st["font_scale"] / 100.0
        self.S = polish_classic_styles(make_styles(self.t, self.k), self.k)
        # SimpleDocTemplate's default frame also reserves 6pt on either side.
        self.content_width = A4[0]-34*mm-12
        self.links = 0
        self.source_regions = []

    # ---- helpers ----
    def sp(self, v):
        return Spacer(1, v * self.af * self.spacing)

    def adjust_spacing(self):
        """Compact the final template styles without changing their type sizes."""
        if self.spacing==1 and self.leading==1:
            return
        for key, style in self.S.items():
            self.S[key] = ParagraphStyle(style.name+'_fit',parent=style,
                spaceBefore=style.spaceBefore*self.spacing,
                spaceAfter=style.spaceAfter*self.spacing,
                leading=min(style.leading,max(style.fontSize*1.18,style.leading*self.leading)))

    def column_widths(self, *proportions):
        """Fit the original table proportions inside the usable document frame."""
        total = sum(proportions)
        return [self.content_width * width / total for width in proportions]

    def rich(self, text, lc=None):
        markup, links = reportlab_markup(text, clean_glyphs, lc or self.t["mid"])
        self.links += links
        return markup

    def para(self, text, style, lc=None, prefix="", source=None):
        try:
            return SourceParagraph(prefix + self.rich(text, lc), style,
                                   source=source, regions=self.source_regions)
        except Exception:
            return SourceParagraph(prefix + esc(clean_glyphs(strip_markup(str(text or "")))), style,
                                   source=source, regions=self.source_regions)

    def contact_line(self):
        parts = []
        for c in self.d["contacts"]:
            text, url = (c.get("text") or "").strip(), (c.get("url") or "").strip()
            if not (text or url):
                continue
            text = clean_glyphs(text or display_url(url))
            url = norm_url(url) if url else (f"mailto:{text}" if EMAIL.fullmatch(text) else "")
            if url:
                self.links += 1
                parts.append("<link href='%s' color='%s'>%s</link>" % (url.replace("&", "&amp;").replace("'", "%27"), self.t["mid"], esc(text)))
            else:
                parts.append(esc(text))
        return " &nbsp;&nbsp;·&nbsp;&nbsp; ".join(parts)

    # ---- sections ----
    def sec_profile(self, title):
        if not plain(self.d["profile"]).strip():
            return []
        a = self.af * self.spacing
        profile_heading = ParagraphStyle('profile_heading', parent=self.S['section'], keepWithNext=False)
        tbl = Table([[SourceParagraph(esc(clean_glyphs(title)), profile_heading, source=("section", "profile"), regions=self.source_regions), self.para(self.d["profile"], self.S["body"], source=("profile",))]],
                    colWidths=self.column_widths(29, 144), hAlign="LEFT", splitInRow=1)
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), self.C["light"]),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6 * a), ("BOTTOMPADDING", (0, 0), (-1, -1), 6 * a),
            ("BOX", (0, 0), (-1, -1), 0.5, self.C["line"]),
        ]))
        return [tbl]

    def heading(self, title, key):
        return RuledHeading(esc(clean_glyphs(title)), self.S["section"], source=("section", key), regions=self.source_regions,
                            rule_color=self.t['line'])

    def sec_projects(self, title):
        entries = [(i, p) for i, p in enumerate(self.d["projects"])
                   if any(plain(value).strip() for value in (p['title'], p['meta'], *p['bullets']))]
        if not entries:
            return []
        out = [self.heading(title, "projects")]
        title_style = ParagraphStyle('project_keep', parent=self.S['project'], keepWithNext=1)
        meta_style = ParagraphStyle('meta_keep', parent=self.S['meta'], keepWithNext=1)
        for i, p in entries:
            elems = [self.para(p["title"], title_style, source=("projects", i, "title"))]
            if plain(p["meta"]).strip():
                elems.append(self.para(p["meta"], meta_style, source=("projects", i, "meta")))
            elems += [self.para(b, self.S["bullet"], prefix="• ", source=("projects", i, "bullets", n)) for n, b in enumerate(p["bullets"]) if plain(b).strip()]
            for flowable in elems[:-1]:
                flowable.keepWithNext = len(flowable.getPlainText()) < 220
            if elems:
                elems[-1].keepWithNext = False
            out += elems + [self.sp(4)]
        return out

    def sec_skills(self, title):
        rows = [[self.para(s["category"], self.S["skillhead"], source=("skills", i, "category")), self.para(s["items"], self.S["skilltext"], source=("skills", i, "items"))]
                for i, s in enumerate(self.d["skills"]) if plain(s["category"]).strip() or plain(s["items"]).strip()]
        if not rows:
            return []
        a = self.af * self.spacing
        tbl = Table(rows, colWidths=self.column_widths(39, 134), hAlign="LEFT", splitInRow=1)
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.4, self.C["line"]),
            ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4 * a), ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * a),
            ("BACKGROUND", (0, 0), (0, -1), self.C["light"]),
        ]))
        return [self.heading(title, "skills"), tbl]

    def sec_experience(self, title):
        entries = [(i, e) for i, e in enumerate(self.d["experience"])
                   if any(plain(e[key]).strip() for key in ('title', 'company', 'dates', 'description'))]
        if not entries:
            return []
        a, out = self.af * self.spacing, [self.heading(title, "experience")]
        identity_style = ParagraphStyle('experience_identity', parent=self.S['body'], alignment=TA_LEFT)
        for i, e in entries:
            sub = " · ".join(x for x in (e["company"].strip(), e["dates"].strip()) if x)
            left = SourceParagraph(
                f"<b>{esc(clean_glyphs(e['title']))}</b><br/><font color='{self.t['mid']}'>{esc(clean_glyphs(sub))}</font>",
                identity_style, source=("experience", i, "identity"), regions=self.source_regions)
            lines = [self.para(l, self.S["small"], source=("experience", i, "description", n)) for n, l in enumerate(e["description"].splitlines()) if plain(l).strip()]
            tbl = Table([[left, lines or ""]], colWidths=self.column_widths(64, 109), hAlign="LEFT", splitInRow=1)
            tbl.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBEFORE", (1, 0), (1, 0), 1, self.C["blue"]),
                ("LEFTPADDING", (0, 0), (0, 0), 0), ("LEFTPADDING", (1, 0), (1, 0), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4 * a), ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * a),
            ]))
            out.append(tbl)
        return out

    def sec_education(self, title):
        entries = [(i, e) for i, e in enumerate(self.d["education"])
                   if any(plain(value).strip() for value in e.values())]
        if not entries:
            return []
        rows = []
        for i, e in entries:
            left = [self.para(e["degree"], self.S["edu"], source=("education", i, "degree")), self.para(e["institution"], self.S["edumeta"], source=("education", i, "institution"))]
            if plain(e["dates"]).strip():
                left.append(self.para(e["dates"], self.S["edumeta"], source=("education", i, "dates")))
            if plain(e["distinction"]).strip():
                left.append(self.para(e["distinction"], self.S["distinction"], source=("education", i, "distinction")))
            if plain(e["coursework"]).strip():
                left.append(self.sp(3))
                left += [self.para(line, self.S['small'], prefix='<b>Coursework:</b> ' if n == 0 else '',
                                   source=('education', i, 'coursework'))
                         for n, line in enumerate(e['coursework'].splitlines()) if plain(line).strip()]
            right = ""
            if plain(e["gpa"]).strip():
                right = [SourceParagraph("GPA", self.S["gpalabel"], source=("education", i, "gpa"), regions=self.source_regions), self.sp(3), self.para(e["gpa"], self.S["gpa"], source=("education", i, "gpa"))]
            rows.append([left, right])
        a = self.af * self.spacing
        tbl = Table(rows, colWidths=self.column_widths(141, 32), hAlign="LEFT", splitInRow=1)
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, self.C["line"]),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 4 * a), ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * a),
        ]))
        return [self.heading(title, "education"), tbl]

    # ---- assembly ----
    def page_footer(self,canvas,document):
        """Keep later-page numbering inside even the smallest document margin."""
        canvas.saveState()
        canvas.setFillColor(self.C['mid'])
        canvas.setFont('CV',6.8)
        canvas.drawRightString(A4[0]-document.rightMargin-6,
                               max(9,document.bottomMargin*.5),f'Page {document.page}')
        canvas.restoreState()

    def build(self, target):
        self.adjust_spacing()
        d, st = self.d, self.d["settings"]
        name = d["personal"]["name"].strip()
        margin = st["margin_mm"] * mm
        doc = SimpleDocTemplate(
            target, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=margin, bottomMargin=margin,
            title=f"{name} - Curriculum Vitae" if name else "Curriculum Vitae",
            author=name, subject="Curriculum Vitae", creator="CV Studio",
        )
        story = []
        if name:
            story.append(SourceParagraph(esc(clean_glyphs(name)), self.S["name"], source=("personal", "name"), regions=self.source_regions))
        if d["personal"]["role"].strip():
            story.append(SourceParagraph(esc(clean_glyphs(d["personal"]["role"])), self.S["role"], source=("personal", "role"), regions=self.source_regions))
        contact = contact_block(self)
        if contact:
            story.append(contact)
        story.append(self.sp(7))
        for sec in st["sections"]:
            if sec.get("visible", True):
                title = sec['title'].strip().upper()
                if is_custom(sec['key']):
                    story += custom_section(self, sec['key'], title)
                else:
                    story += getattr(self, "sec_" + sec["key"])(title)
        doc.build(story,onLaterPages=self.page_footer)
        return doc.page


AUTOFIT_STEPS = [1.0, 0.98, 0.96, 0.94, 0.92]


def render_pdf(data, source_map=None):
    """Reduce pages or overflow using spacing first and preserve full-size text when possible."""
    scale = data['settings']['font_scale']/100
    candidates = [(1.0,1.0,1.0)]
    if data['settings']['autofit']:
        candidates += [(1.0,.92,1.0),(1.0,.84,.97),(1.0,.76,.94)]
        if scale>=1:
            candidates += [(af,.76,.94) for af in AUTOFIT_STEPS[1:]]
    best = None
    for af, spacing, leading in candidates:
        buf, builder = io.BytesIO(), CVBuilder(data, af, spacing=spacing, leading=leading)
        template = data['settings'].get('template', DEFAULT_TEMPLATE)
        try:
            pages = builder.build(buf) if template == DEFAULT_TEMPLATE else build_template(builder, buf, template)
        except LayoutError:
            if best is None:
                raise
            # A rejected compact layout must not break an otherwise valid CV.
            continue
        last_bottom = max((region['rect'][3] for region in builder.source_regions
                           if region['page']==pages-1),default=0)
        # A spacing-only fit can improve the page flow even when the content
        # still needs two pages. Never reduce text just to shorten that tail.
        better_overflow = (best is not None and pages==best[1] and af==best[3]==1
                           and last_bottom<=best[5]-12)
        if best is None or pages<best[1] or better_overflow:
            best = (buf.getvalue(),pages,builder.links,af,builder.source_regions,last_bottom)
        if pages <= 1:
            break
    if source_map is not None:
        source_map[:] = best[4]
    return best[:4]


# ============================================================
# DATA MIGRATION  (old JSON files keep working)
# ============================================================

def migrate(raw):
    return migrate_document(raw, DEFAULT_DATA, DEFAULT_SECTIONS, THEMES, TEMPLATES)


# The shared UI keeps the two editions visually and behaviorally consistent.
from cv_studio_ui import StudioApp


class CVEditor(StudioApp):
    def __init__(self):
        super().__init__(sys.modules[__name__], edition="Starter")


if __name__ == "__main__":
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    CVEditor().mainloop()
