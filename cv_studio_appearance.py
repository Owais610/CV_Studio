"""Workspace-only colour tokens. These never affect the exported CV theme."""

DEFAULT_UI_THEME = 'Ocean'
DEFAULT_UI_MODE = 'Dark'
DEFAULT_UI_STYLE = 'Minimal'
UI_STYLES = ('Minimal', 'Vibrant')
BUTTON_THEMES = {
    'Ocean': ('#3468D4', '#8CABFF'),
    'Teal': ('#087F82', '#67D4C4'),
    'Forest': ('#28754D', '#85CCA0'),
    'Violet': ('#7152C7', '#C0ABFF'),
    'Rose': ('#AD446A', '#F2A8C5'),
    'Graphite': ('#536274', '#BBC7D8'),
}


def normalize_ui_theme(value):
    return value if isinstance(value,str) and value in BUTTON_THEMES else DEFAULT_UI_THEME


def normalize_ui_style(value):
    if value == 'Original':
        return 'Vibrant'
    return value if isinstance(value,str) and value in UI_STYLES else DEFAULT_UI_STYLE


def blend(first, second, amount):
    return '#'+''.join(f'{round(int(first[i:i+2],16)*(1-amount)+int(second[i:i+2],16)*amount):02X}'
                       for i in (1,3,5))


def theme_palette(base, mode, theme):
    """Subtle resting surfaces, stronger selection, and readable primary actions."""
    dark = mode=='Dark'
    accent = BUTTON_THEMES[normalize_ui_theme(theme)][int(dark)]
    palette = dict(base)
    palette.update(accent=accent,
                   pressed=blend(accent,'#FFFFFF' if dark else '#000000',.15),
                   accent_text='#142241' if dark else '#FFFFFF',
                   tint=blend(base['surface'],accent,.18 if dark else .11),
                   hover=blend(base['field'],accent,.12 if dark else .08),
                   focus_line=blend(base['line'],accent,.68 if dark else .52),
                   button_face=blend(base['field'],accent,.065 if dark else .035),
                   button_line=blend(base['line'],accent,.20),
                   button_ink=blend(base['text'],accent,.20),
                   selection_ink=blend(base['text'],accent,.90 if dark else .68))
    return palette


def minimal_palette(base, mode):
    """A neutral workspace independent of the Vibrant button theme."""
    dark = mode == 'Dark'
    accent = base['text']
    palette = dict(base)
    palette.update(accent=accent,
                   pressed=blend(accent, '#000000' if dark else '#FFFFFF', .12),
                   accent_text=base['bg'],
                   tint=blend(base['rail'], base['text'], .10 if dark else .055),
                   hover=blend(base['rail'], base['text'], .075 if dark else .035),
                   focus_line=blend(base['line'],base['text'],.45 if dark else .35),
                   button_face=base['surface'],
                   button_line=base['line'],
                   button_ink=base['text'],
                   selection_ink=base['text'])
    return palette


def navigation_material(base, palette, mode):
    """Tint the existing frosted card material without changing its geometry."""
    dark = mode=='Dark'
    accent = palette['accent']
    material = dict(base)
    material.update(face=blend(base['face'],accent,.035),
                    hover=blend(base['hover'],accent,.055),
                    active=blend(palette['rail'],accent,.29 if dark else .17),
                    active_edge=blend(palette['line'],accent,.32),
                    well=blend(base['well'],accent,.20),
                    ink=blend(palette['text'],accent,.45 if dark else .65))
    return material
