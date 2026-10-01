"""Small, lossless formatting bridge: legacy Markdown / HTML -> runs -> PDF.

New strings use a restricted HTML vocabulary (b, i, a), never arbitrary markup.
Each line is independently balanced so bullet/paragraph splitting stays safe.
"""
from dataclasses import dataclass
from html import escape, unescape
import re


@dataclass(frozen=True)
class Format:
    bold: bool = False
    italic: bool = False
    link: str = ""
    no_link: bool = False


NORMAL = Format()
TOKEN = re.compile(r'<(/?)(b|strong|i|em|a|link)\b([^>]*)>|<br\s*/?>', re.I)
HREF = re.compile(r'''href\s*=\s*(["'])(.*?)\1''', re.I)
MD_LINK = re.compile(r'\[([^\]\n]+)\]\(([^\s]+?)\)')
URL = re.compile(r'https?://[^\s<>]+')


def normalize_url(value):
    value = value.strip()
    if not value:
        return ""
    if re.match(r'^(https?://|mailto:|tel:)', value, re.I):
        return value
    if re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', value):
        return 'mailto:' + value
    return 'https://' + value


def parse(value):
    """Return visible text and one Format per Python character.

    HTML entities are our literal escape mechanism: e.g. &#42; stays a star.
    Legacy markers can nest, including ***bold italic*** and formatted links.
    Unmatched markers remain literal.
    """
    value = str(value or '')
    text, attrs = [], []

    def emit(s, state):
        s = unescape(s)
        text.append(s)
        attrs.extend([state] * len(s))

    def scan(s, state):
        pos = 0
        while pos < len(s):
            tag = TOKEN.match(s, pos)
            if tag and not tag.group(1):
                if tag.group(2) is None:
                    emit('\n', state)
                    pos = tag.end()
                    continue
                name = tag.group(2).lower()
                # Find the matching close, including nested tags of the same kind.
                depth, closing = 1, None
                for other in TOKEN.finditer(s, tag.end()):
                    if (other.group(2) or '').lower() == name:
                        depth += -1 if other.group(1) else 1
                        if not depth:
                            closing = other
                            break
                if closing:
                    href = HREF.search(tag.group(3))
                    new = Format(state.bold or name in ('b', 'strong'),
                                 state.italic or name in ('i', 'em'),
                                 normalize_url(unescape(href.group(2))) if href else state.link,
                                 not bool(href.group(2)) if href else state.no_link)
                    scan(s[tag.end():closing.start()], new)
                    pos = closing.end()
                    continue
            link = MD_LINK.match(s, pos)
            if link:
                scan(link.group(1), Format(state.bold, state.italic, normalize_url(link.group(2))))
                pos = link.end()
                continue
            if s[pos] == '*':
                count = min(3, len(s[pos:]) - len(s[pos:].lstrip('*')))
                marker = '*' * count
                end = s.find(marker, pos + count)
                if end > pos + count:
                    scan(s[pos + count:end], Format(state.bold or count >= 2,
                                                    state.italic or count in (1, 3), state.link, state.no_link))
                    pos = end + count
                    continue
            # Entities are consumed atomically so encoded syntax stays literal.
            entity = re.match(r'&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z]+);', s[pos:])
            if entity:
                emit(entity.group(), state)
                pos += len(entity.group())
            else:
                emit(s[pos], state)
                pos += 1

    scan(value, NORMAL)
    visible = ''.join(text)
    attrs = [NORMAL if ch == '\n' else state for ch, state in zip(visible, attrs)]
    # Bare URLs retain their full visible label and become clickable automatically.
    for match in URL.finditer(visible):
        end = match.end()
        while end > match.start() and visible[end - 1] in '.,;:!?)':
            end -= 1
        url = visible[match.start():end]
        for i in range(match.start(), end):
            old = attrs[i]
            if not old.link and not old.no_link:
                attrs[i] = Format(old.bold, old.italic, url)
    return visible, attrs


def runs(text, attrs):
    start = 0
    while start < len(text):
        state = attrs[start]
        end = start + 1
        while end < len(text) and attrs[end] == state and text[end - 1] != '\n' and text[end] != '\n':
            end += 1
        yield text[start:end], state
        start = end


def serialize(text, attrs):
    result = []
    for part, state in runs(text, attrs):
        if part == '\n':
            result.append(part)
            continue
        part = escape(part, quote=False).replace('*', '&#42;').replace('[', '&#91;')
        if state.italic:
            part = '<i>' + part + '</i>'
        if state.bold:
            part = '<b>' + part + '</b>'
        if state.link:
            part = '<a href="' + escape(state.link, quote=True) + '">' + part + '</a>'
        elif state.no_link:
            part = '<a href="">' + part + '</a>'
        result.append(part)
    return ''.join(result)


def plain(value):
    return parse(value)[0]


def reportlab_markup(value, clean=lambda s: s, link_color='#2D6F9F'):
    text, attrs = parse(value)
    result, links, previous_link = [], 0, ''
    for part, state in runs(text, attrs):
        content = escape(clean(part), quote=False).replace('\n', '<br/>')
        if state.italic:
            content = '<i>' + content + '</i>'
        if state.bold:
            content = '<b>' + content + '</b>'
        if state.link:
            content = '<link href="' + escape(state.link, quote=True) + '" color="' + link_color + '">' + content + '</link>'
            if previous_link != state.link:
                links += 1
        previous_link = state.link
        result.append(content)
    return ''.join(result), links
