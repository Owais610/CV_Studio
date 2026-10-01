"""Portable custom-section data; titles never double as storage identifiers."""
from copy import deepcopy
from dataclasses import dataclass
import re
from uuid import uuid4


CUSTOM_FIELDS = ('title', 'meta', 'description', 'bullets')
ENTRY_LAYOUTS = {'auto': 'Automatic', 'single': 'Single column', 'columns': 'Two columns'}


def entry_layout(value):
    return value if isinstance(value, str) and value in ENTRY_LAYOUTS else 'auto'


@dataclass(frozen=True)
class EntryField:
    key: str
    label: str
    rich: bool = False
    lines: int = 1
    hint: str = ''
    style: str = 'body'
    mode: str = 'single'
    prefix: str = ''

    def form(self):
        return self.key, self.label, self.rich, self.lines, self.hint


@dataclass(frozen=True)
class EntryType:
    label: str
    title_key: str
    fields: tuple
    compact: bool = False


# One schema drives the form, JSON normalization, and flowing PDF paragraphs.
# New entry types do not need new sections or a separate CVBuilder implementation.
F = EntryField
TITLE = F('title', 'Title', style='project')
DETAILS = F('meta', 'Details & links', True, 2, 'Optional dates, organisation, or website.', 'meta')
CONTENT = F('description', 'Content', True, 4, 'Use the toolbar for formatting and links.', mode='paragraphs')
BULLETS = F('bullets', 'Highlights', True, 4, 'One bullet per line.', 'bullet', 'bullets', '• ')
LINK = F('link', 'Website / link', True, 1, 'Optional. Paste a URL or insert a labelled link.', 'meta', 'link')
ENTRY_TYPES = {
    'education': EntryType('Education', 'degree', (
        F('degree', 'Degree or qualification', style='edu'), F('institution', 'Institution', style='edumeta'),
        F('dates', 'Dates', style='edumeta'), F('gpa', 'GPA / grade', style='distinction', prefix='GPA / grade: '),
        F('distinction', 'Distinction', style='distinction'),
        F('coursework', 'Relevant coursework', True, 3, 'Optional.', 'small', 'paragraphs', 'Coursework: ')), compact=True),
    'publication': EntryType('Publication', 'title', (
        F('title', 'Publication title', style='project'), F('authors', 'Authors', True, 2, style='meta'),
        F('venue', 'Journal, conference, or publisher', True, 2, style='meta'),
        F('dates', 'Year / publication date', style='meta'),
        F('link', 'DOI / publication link', True, 1, 'A DOI (10.…/…), URL, or labelled link.', 'meta', 'link'),
        F('description', 'Abstract / contribution', True, 4, 'Optional.', mode='paragraphs'))),
    'project': EntryType('Project', 'title', (F('title', 'Project title', style='project'), DETAILS, BULLETS)),
    'experience': EntryType('Experience', 'title', (
        F('title', 'Position', style='project'), F('company', 'Company & location', style='meta'),
        F('dates', 'Dates', style='meta'),
        F('description', 'Contribution & achievements', True, 4, 'One paragraph per line.', 'body', 'paragraphs'))),
    'reference': EntryType('Referee / Reference', 'name', (
        F('name', 'Referee name', style='project'), F('role', 'Position / relationship', style='meta'),
        F('organisation', 'Organisation', style='meta'),
        F('email', 'Email', style='meta', mode='link', prefix='Email: '),
        F('phone', 'Phone', style='meta', mode='phone', prefix='Phone: '),
        F('description', 'Additional details', True, 3, 'Optional. Include contact details only with permission.', mode='paragraphs')), compact=True),
    'certification': EntryType('Certification', 'title', (
        F('title', 'Certification', style='project'), F('issuer', 'Issuing organisation', style='meta'),
        F('dates', 'Issued / expiry dates', style='meta'),
        F('credential_id', 'Credential ID', style='meta', prefix='Credential ID: '), LINK,
        F('description', 'Details', True, 3, 'Optional.', mode='paragraphs')), compact=True),
    'award': EntryType('Award', 'title', (
        F('title', 'Award or honour', style='project'), F('organisation', 'Awarding organisation', style='meta'),
        F('dates', 'Date', style='meta'),
        F('description', 'Achievement', True, 3, 'Optional.', mode='paragraphs')), compact=True),
    'skills': EntryType('Skills', 'category', (
        F('category', 'Category', style='skillhead'),
        F('items', 'Skills', True, 3, 'Separate skills with commas or a middle dot.', 'skilltext', 'paragraphs')), compact=True),
    'bullets': EntryType('Bullet List', 'title', (F('title', 'Title (optional)', style='project'), BULLETS)),
    'text': EntryType('Free Text', 'title', (F('title', 'Title (optional)', style='project'), CONTENT)),
    # Pre-type custom entries retain every original field and their JSON shape.
    'legacy': EntryType('Flexible entry', 'title', (TITLE, DETAILS, CONTENT, BULLETS)),
}
ENTRY_CHOICES = tuple(key for key in ENTRY_TYPES if key != 'legacy')


def entry_type(entry):
    kind = entry.get('entry_type')
    return kind if isinstance(kind, str) and kind in ENTRY_TYPES else 'legacy'


def empty_entry(kind):
    spec = ENTRY_TYPES[kind]
    return dict(entry_type=kind, **{field.key: [] if field.mode=='bullets' else '' for field in spec.fields})


def normalize_entry(entry):
    # Retain extra fields and unknown future type metadata rather than destroying
    # data when a newer document is opened with an older form registry.
    clean = deepcopy(entry)
    for field in ENTRY_TYPES[entry_type(entry)].fields:
        value = entry.get(field.key)
        if field.mode == 'bullets':
            if isinstance(value, str):
                value = value.splitlines()
            clean[field.key] = [str(line) for line in value if line is not None] if isinstance(value, list) else []
        else:
            clean[field.key] = str(value) if value is not None else ''
    return clean


def is_custom(key):
    return isinstance(key, str) and re.fullmatch(r'custom_[A-Za-z0-9_-]+', key) is not None


def new_section_key():
    return 'custom_' + uuid4().hex


def normalize_sections(data, raw, settings, defaults):
    """Keep legacy defaults, custom content, and one ordered descriptor per ID.

    Content is already rich-text-normalized by each edition's migration. Missing
    descriptors are recovered rather than silently losing otherwise valid data.
    """
    custom = raw.get('custom_sections') or {}
    custom = custom if isinstance(custom, dict) else {}
    result = {}
    for key, entries in custom.items():
        if not is_custom(key) or not isinstance(entries, list):
            continue
        result[key] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            result[key].append(normalize_entry(entry))
    known = {section['key']: deepcopy(section) for section in defaults}
    sections, seen = [], set()
    candidates = settings.get('sections') or []
    for section in candidates if isinstance(candidates, list) else []:
        if not isinstance(section, dict):
            continue
        key = section.get('key')
        if not isinstance(key, str) or key in seen or (key not in known and not is_custom(key)):
            continue
        if is_custom(key):
            result.setdefault(key, [])
        title = str(section.get('title') or '').strip() or known.get(key, {}).get('title', 'Custom section')
        descriptor = dict(key=key, title=title, visible=bool(section.get('visible', True)))
        layout = entry_layout(section.get('entry_layout'))
        if is_custom(key) and layout != 'auto':
            descriptor['entry_layout'] = layout
        sections.append(descriptor)
        seen.add(key)
    sections.extend(section for key, section in known.items() if key not in seen)
    sections.extend(dict(key=key, title='Custom section', visible=True) for key in result if key not in seen)
    data['custom_sections'] = result
    data['settings']['sections'] = sections
