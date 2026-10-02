"""Validate and normalize portable CV data before replacing the open document."""
from copy import deepcopy
import math
import re

from cv_studio_appearance import normalize_ui_style, normalize_ui_theme
from cv_studio_photo import normalize_crop
from cv_studio_sections import normalize_sections


def _object(value, label):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f'{label} must be a JSON object.')
    return value


def _text(value, label):
    if value is None:
        return ''
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    raise ValueError(f'{label} must contain text.')


def _entries(value, label):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f'{label} must be a list of entries.')
    return value


def _bullets(value, label):
    if isinstance(value, str):
        return value.splitlines()
    return [_text(line, label) for line in _entries(value, label) if line is not None]


def _number(value, default, low, high):
    try:
        number = float(value)
        return max(low, min(high, round(number))) if math.isfinite(number) else default
    except (TypeError, ValueError, OverflowError):
        return default


def _display_url(value):
    value = re.sub(r'^https?://(www\.)?', '', value).rstrip('/')
    return re.sub(r'^(dx\.)?doi\.org/', '', value)


def migrate_document(raw, defaults, default_sections, themes, templates):
    """Retain missing-field defaults while making accepted legacy data usable."""
    if not isinstance(raw, dict):
        raise ValueError('CV data must be a JSON object.')
    data = deepcopy(defaults)
    settings = _object(raw.get('settings'), 'Settings')
    personal = _object(raw.get('personal'), 'Personal details')
    for key in ('name', 'role'):
        if key in personal:
            data['personal'][key] = _text(personal[key], f'Personal {key}')

    if 'contacts' in raw:
        data['contacts'] = []
        for index, value in enumerate(_entries(raw['contacts'], 'Contacts'), 1):
            label = f'Contact {index}'
            entry = _object(value, label)
            data['contacts'].append({key: _text(entry.get(key), f'{label} {key}') for key in ('text', 'url')})
    elif any(key in personal for key in ('phone', 'email', 'github', 'orcid')):
        data['contacts'] = []
        for key in ('phone', 'email'):
            if personal.get(key):
                data['contacts'].append(dict(text=_text(personal[key], key), url=''))
        for key in ('github', 'orcid'):
            if personal.get(key):
                url = _text(personal[key], key)
                label = _text(personal.get(key + '_display'), key + ' label') or _display_url(url)
                data['contacts'].append(dict(text=label, url=url))

    if 'profile' in raw:
        data['profile'] = _text(raw['profile'], 'Profile')
    fields = {
        'projects': ('title', 'meta', 'bullets'),
        'skills': ('category', 'items'),
        'experience': ('title', 'company', 'dates', 'description'),
        'education': ('degree', 'institution', 'dates', 'distinction', 'gpa', 'coursework'),
    }
    for section, keys in fields.items():
        if section not in raw:
            continue
        data[section] = []
        for index, value in enumerate(_entries(raw[section], section.title()), 1):
            label = f'{section.title()} entry {index}'
            if section == 'skills' and isinstance(value, (list, tuple)):
                if len(value) < 2:
                    raise ValueError(f'{label} needs a category and skills text.')
                value = dict(category=value[0], items=value[1])
            entry = _object(value, label)
            data[section].append({key: (_bullets(entry.get(key), f'{label} highlights') if key == 'bullets'
                                       else _text(entry.get(key), f'{label} {key}')) for key in keys})

    result = data['settings']
    result.update({key: value for key, value in settings.items() if key != 'sections'})
    for key, choices in (('theme', themes), ('template', templates), ('ui_mode', ('Dark', 'Light'))):
        if not isinstance(result.get(key), str) or result[key] not in choices:
            result[key] = defaults['settings'][key]
    result['ui_theme'] = normalize_ui_theme(result.get('ui_theme'))
    result['ui_style'] = normalize_ui_style(result.get('ui_style'))
    result['font_scale'] = _number(result.get('font_scale'), defaults['settings']['font_scale'], 80, 115)
    result['margin_mm'] = _number(result.get('margin_mm'), defaults['settings']['margin_mm'], 6, 24)
    if not isinstance(result.get('autofit'), bool):
        result['autofit'] = defaults['settings']['autofit']
    if not isinstance(result.get('photo'), str):
        result['photo'] = ''
    result['photo_crop'] = normalize_crop(result.get('photo_crop'))
    normalize_sections(data, raw, settings, default_sections)
    return data
