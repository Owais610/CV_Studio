"""Portable custom-section data; titles never double as storage identifiers."""
from copy import deepcopy
import re
from uuid import uuid4


CUSTOM_FIELDS = ('title', 'meta', 'description', 'bullets')


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
            clean = {field: str(entry.get(field) or '') for field in CUSTOM_FIELDS if field != 'bullets'}
            bullets = entry.get('bullets') or []
            if isinstance(bullets, str):
                bullets = bullets.splitlines()
            clean['bullets'] = [str(line) for line in bullets if line is not None] if isinstance(bullets, list) else []
            result[key].append(clean)
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
        sections.append(dict(key=key, title=title, visible=bool(section.get('visible', True))))
        seen.add(key)
    sections.extend(section for key, section in known.items() if key not in seen)
    sections.extend(dict(key=key, title='Custom section', visible=True) for key in result if key not in seen)
    data['custom_sections'] = result
    data['settings']['sections'] = sections
