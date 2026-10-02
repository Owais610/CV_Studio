"""Workspace themes and sidebar-only section visibility regressions."""
import json
from pathlib import Path
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_entries import engine, ROOT, settle
from gui_support import save_screenshot
from cv_studio_appearance import (BUTTON_THEMES, DEFAULT_UI_THEME, DEFAULT_UI_MODE, DEFAULT_UI_STYLE, UI_STYLES,
                                  theme_palette, minimal_palette, navigation_material)
from cv_studio_ui import PALETTES, MINIMAL_PALETTES, NavigationButton, InspectorGroup


def contrast(first, second):
    def luminance(color):
        values = [int(color[i:i+2],16)/255 for i in (1,3,5)]
        values = [v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in values]
        return sum(v*w for v,w in zip(values,(.2126,.7152,.0722)))
    a,b = sorted((luminance(first),luminance(second)))
    return (b+.05)/(a+.05)


class AppearanceTests(unittest.TestCase):
    def test_default_mode_and_saved_light_mode(self):
        self.assertEqual(DEFAULT_UI_MODE,'Dark')
        self.assertEqual(engine.DEFAULT_DATA['settings']['ui_mode'],'Dark')
        self.assertEqual(engine.DEFAULT_DATA['settings']['ui_style'],DEFAULT_UI_STYLE)
        data = engine.migrate(engine.DEFAULT_DATA)
        data['settings'].pop('ui_mode')
        self.assertEqual(engine.migrate(data)['settings']['ui_mode'],'Dark')
        data['settings']['ui_mode'] = 'Light'
        self.assertEqual(engine.migrate(json.loads(json.dumps(data)))['settings']['ui_mode'],'Light')

    def test_all_themes_contrast_and_immutable_base(self):
        for mode,base in PALETTES.items():
            before = dict(base)
            for theme in BUTTON_THEMES:
                with self.subTest(mode=mode,theme=theme):
                    p = theme_palette(base,mode,theme)
                    material = navigation_material(NavigationButton.MATERIALS[mode],p,mode)
                    for background in ('accent','pressed'):
                        self.assertGreaterEqual(contrast(p['accent_text'],p[background]),4.5)
                    for background in ('button_face','hover','tint'):
                        self.assertGreaterEqual(contrast(p['button_ink'],p[background]),4.5)
                    self.assertGreaterEqual(contrast(p['selection_ink'],p['tint']),4.5)
                    self.assertGreaterEqual(contrast(material['ink'],material['active']),4.5)
                    self.assertEqual(base,before)

    def test_theme_save_load_and_legacy_default(self):
        for value in [*BUTTON_THEMES,'unknown',None,{},42]:
            data = engine.migrate(engine.DEFAULT_DATA)
            data['settings']['ui_theme'] = value
            saved = engine.migrate(json.loads(json.dumps(data)))
            expected = value if isinstance(value,str) and value in BUTTON_THEMES else DEFAULT_UI_THEME
            self.assertEqual(saved['settings']['ui_theme'],expected)
            self.assertEqual(engine.migrate(saved),saved)
        data['settings'].pop('ui_theme')
        self.assertEqual(engine.migrate(data)['settings']['ui_theme'],DEFAULT_UI_THEME)

    def test_interface_styles_are_saved_and_readable(self):
        for value in [*UI_STYLES,'Original','unknown',None,{},42]:
            data = engine.migrate(engine.DEFAULT_DATA)
            data['settings']['ui_style'] = value
            saved = engine.migrate(json.loads(json.dumps(data)))
            expected = 'Vibrant' if value == 'Original' else value if isinstance(value,str) and value in UI_STYLES else DEFAULT_UI_STYLE
            self.assertEqual(saved['settings']['ui_style'],expected)
            self.assertEqual(engine.migrate(saved),saved)
        data['settings'].pop('ui_style')
        self.assertEqual(engine.migrate(data)['settings']['ui_style'],DEFAULT_UI_STYLE)

    def test_minimal_palette_contrast(self):
        for mode,base in MINIMAL_PALETTES.items():
            before = dict(base)
            palette = minimal_palette(base,mode)
            self.assertGreaterEqual(contrast(palette['accent_text'],palette['accent']),4.5)
            self.assertGreaterEqual(contrast(palette['accent_text'],palette['pressed']),4.5)
            self.assertGreaterEqual(contrast(palette['text'],palette['tint']),4.5)
            self.assertGreaterEqual(contrast(palette['button_ink'],palette['button_face']),4.5)
            self.assertEqual(base,before)

    def test_button_themes_do_not_change_pdf_or_source_locations(self):
        data = engine.migrate(engine.DEFAULT_DATA)
        data['settings']['autofit'] = False
        for template in engine.TEMPLATES:
            data['settings']['template'] = template
            baseline = None
            for theme in BUTTON_THEMES:
                data['settings']['ui_theme'] = theme
                regions = []
                pdf,pages,links,af = engine.render_pdf(data,source_map=regions)
                with engine.pymupdf.open(stream=pdf,filetype='pdf') as doc:
                    result = (pages,links,af,regions,[p.get_pixmap().samples for p in doc])
                if baseline is None:
                    baseline = result
                else:
                    self.assertEqual(result,baseline,(template,theme))

    def test_interface_style_does_not_change_pdf(self):
        data = engine.migrate(engine.DEFAULT_DATA)
        data['settings']['autofit'] = False
        outputs = []
        for style in UI_STYLES:
            data['settings']['ui_style'] = style
            regions = []
            pdf,pages,links,af = engine.render_pdf(data,source_map=regions)
            with engine.pymupdf.open(stream=pdf,filetype='pdf') as doc:
                outputs.append((pages,links,af,regions,[page.get_pixmap().samples for page in doc]))
        self.assertEqual(*outputs)


def gui_checks(screenshots=False):
    if sys.platform=='win32':
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    app = engine.CVEditor()
    errors = []
    app.report_callback_exception = lambda *args:(errors.append(args),traceback.print_exception(*args))
    app.geometry('1460x920+40+40')
    app.lift()
    app.focus_force()

    def ready():
        current,rendered = app.collect(),getattr(app,'rendered_data',None)
        if rendered:
            rendered = json.loads(json.dumps(rendered))
            for key in ('ui_mode','ui_theme','ui_style','sidebar_width'):
                rendered['settings'][key] = current['settings'][key]
        return rendered==current and app.raster_future is None and bool(app._preview_pages) and app._displayed_pdf==app._pdf

    def capture(name):
        if screenshots:
            save_screenshot(app, ROOT/'test_artifacts'/(name+'.png'), settle)

    def pdf_double_click(source):
        target = next(r for r in app._source_map if r['source']==source)
        page = next(p for p in app._preview_pages if p['number']==target['page'])
        x0,y0,x1,y1 = target['rect']
        app.preview_double_click(SimpleNamespace(x=page['x']+(x0+x1)/2*page['scale']-app.pcanvas.canvasx(0),
                                                y=page['y']+(y0+y1)/2*page['scale']-app.pcanvas.canvasy(0)))
        app.update()

    try:
        settle(app,ready)
        assert app.ui.mode == 'Dark' and app.ui.style == 'Minimal'
        assert not any('frame' in row or 'entry' in row for row in app.sections.rows)
        app.navigate('layout')
        app.update()
        groups = [w for w in app.pages['layout'].inner.winfo_children() if isinstance(w,InspectorGroup)]
        titles = [child.cget('text') for group in groups for child in group.winfo_children()
                  if child.winfo_class()=='Label']
        assert 'Sections' not in titles and 'Workspace' in titles and 'Page layout' in titles
        category = app.nav['projects']
        category.event_generate('<Enter>')
        time.sleep(.7)
        app.update()
        assert not category.winfo_children(), 'Category hover opened a popup'
        category.event_generate('<Leave>')
        chooser = app.button_theme_choice
        assert chooser.values==list(BUTTON_THEMES)
        assert int(chooser.cget('width'))==max(chooser.font.measure(name+'   ▾') for name in BUTTON_THEMES)+26
        assert chooser.font is app.ui.fonts['small']
        assert int(chooser.cget('height'))==max(28,chooser.font.metrics('linespace')+2)
        assert all(chooser.font.measure(name+'   ▾')+26<=int(chooser.cget('width')) for name in BUTTON_THEMES)
        field = app.fields[('profile',)]
        before_field = field
        original_pdf,original_revision = app._pdf,app.revision
        original_document_theme = app.v_theme.get()
        style_choice = app.ui_style_choice
        assert style_choice.values == list(UI_STYLES)
        assert not chooser.winfo_manager()
        for style in ('Vibrant','Minimal'):
            style_choice.focus_force()
            style_choice.event_generate('<Return>')
            app.update()
            assert app.popup is not None
            app.popup.buttons[UI_STYLES.index(style)].focus_set()
            app.popup.buttons[UI_STYLES.index(style)].event_generate('<Return>')
            settle(app,lambda:app.popup is None and app.ui.style==style)
            assert app.v_ui_style.get()==style and app._pdf==original_pdf and app.revision==original_revision
            assert bool(chooser.winfo_manager()) == (style=='Vibrant')
            capture('design_style_'+style.lower())
        app.set_ui_style('Vibrant')
        assert chooser.winfo_manager()
        accent_color = None
        for mode in ('Light','Dark'):
            app.set_mode(mode)
            for index,theme in enumerate(BUTTON_THEMES):
                chooser.focus_force()
                app.update()
                chooser.event_generate('<Return>')
                app.update()
                menu = app.popup
                assert menu is not None
                expected_width = max(chooser.winfo_width(),
                                     max(chooser.font.measure('✓  '+name) for name in BUTTON_THEMES)+50)
                assert menu.winfo_width()==expected_width
                assert all(b.font is chooser.font and int(b.cget('height'))==30 and b.font.measure(b.text)+26<=b.winfo_width()
                           for b in menu.buttons)
                assert [b.text.replace('✓','').strip() for b in menu.buttons]==list(BUTTON_THEMES)
                assert [b.text for b in menu.buttons if '✓' in b.text]==['✓  '+app.v_button_theme.get()]
                # Navigate the actual dropdown with the keyboard, then select.
                for _ in range(index):
                    menu.event_generate('<Down>')
                    app.update()
                assert app.focus_get() is menu.buttons[index]
                menu.buttons[index].event_generate('<Return>')
                settle(app,lambda:app.popup is None and app.ui.theme==theme and app.focus_get() is chooser)
                assert app.ui.theme==theme and app.v_button_theme.get()==theme
                assert chooser.text==theme+'   ▾'
                assert app.v_theme.get()==original_document_theme
                assert app._pdf==original_pdf and app.revision==original_revision
                assert app.focus_get() is chooser and app.fields[('profile',)] is before_field
                color = app.ui['accent']
                if accent_color is not None:
                    assert color!=accent_color
                accent_color = color
            app.set_button_theme('Violet' if mode=='Light' else 'Teal')
            capture('design_themes_'+mode.lower())
            # Mouse opening and Escape cancellation keep the current setting.
            current_theme = app.v_button_theme.get()
            chooser.event_generate('<ButtonPress-1>',x=30,y=15)
            chooser.event_generate('<ButtonRelease-1>',x=30,y=15)
            app.update()
            assert app.popup is not None
            capture('button_theme_dropdown_'+mode.lower())
            app.popup.event_generate('<Escape>')
            app.update()
            assert app.popup is None and app.v_button_theme.get()==current_theme
        # Appearance changes while editing must not reset the caret, selection,
        # formatting, undo stack, or invalidate the existing PDF click map.
        app.navigate('profile')
        field.input.focus_force()
        field.input.mark_set('insert','1.7')
        field.input.tag_add('sel','1.0','1.4')
        history = list(field.history)
        before = field.get()
        app.set_ui_style('Minimal')
        assert app.ui.style == 'Minimal'
        assert not chooser.winfo_manager()
        app.set_ui_style('Vibrant')
        app.update()
        assert app.nav['layout'].find_withtag('nav_shadow')
        assert app.ui_style_choice.text.startswith('Vibrant')
        app.set_ui_style('Minimal')
        app.update()
        assert not app.nav['layout'].find_withtag('nav_shadow')
        app.set_button_theme('Rose')
        app.update()
        assert app.focus_get() is field.input and field.input.index('insert')=='1.7'
        assert tuple(map(str,field.input.tag_ranges('sel')))==('1.0','1.4')
        assert field.get()==before and field.history==history
        pdf_double_click(('projects',0,'meta'))
        assert app.active_editor is app.lists['projects'].cards[0].fields['meta']
        # PDF section headings now rename in the sidebar, not a removed panel.
        pdf_double_click(('section','projects'))
        assert app.section_rename and app.section_rename['key']=='projects'
        rename = app.section_rename['entry']
        rename.delete(0,'end')
        rename.insert(0,'Selected work')
        rename.event_generate('<Return>')
        app.update()
        assert app.nav['projects'].text=='Selected work'
        settle(app,ready)
        content = app.collect()['projects']
        # Native right-click binding offers a checked Show on CV option.
        app.nav['projects'].event_generate('<Button-3>',x=30,y=15)
        app.update()
        assert app.popup.buttons[1].text=='✓  Show on CV'
        assert int(app.popup.buttons[1].cget('width'))==320  # Other menus retain their sizing.
        capture('section_visibility_checked')
        app.popup.buttons[1].invoke()
        settle(app,lambda:app.nav['projects'].hidden and ready())
        assert app.collect()['projects']==content
        assert not any(r['source'][0]=='projects' for r in app._source_map)
        app.sidebar_menu('projects')
        app.update()
        assert app.popup.buttons[1].text.strip()=='Show on CV'
        assert '✓' not in app.popup.buttons[1].text
        capture('section_visibility_hidden')
        app.popup.close()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'workspace.json'
            app._write_json(path)
            saved = app.collect()
            app.load(json.loads(path.read_text(encoding='utf-8')))
            assert app.collect()==saved and app.ui.theme=='Rose' and app.ui.mode=='Dark' and app.ui.style=='Minimal'
            assert app.nav['projects'].hidden and app.nav['projects'].text=='Selected work'
            settle(app,ready)
            exported = Path(temp)/'hidden.pdf'
            with patch('cv_studio_ui.filedialog.asksaveasfilename',return_value=str(exported)), \
                 patch('cv_studio_ui.messagebox.showinfo'), \
                 patch('cv_studio_ui.messagebox.showerror',side_effect=AssertionError):
                app.export_pdf()
            with engine.pymupdf.open(exported) as doc:
                assert 'SELECTED WORK' not in ''.join(p.get_text() for p in doc).upper()
        app.sidebar_menu('projects')
        app.popup.buttons[1].invoke()
        settle(app,lambda:not app.nav['projects'].hidden and ready())
        assert any(r['source'][0]=='projects' for r in app._source_map)
        # Custom sections share visibility, and removal safely releases traces.
        key = app.add_custom_section()
        app.finish_section_rename()
        card = app.lists[key].create_entry('text')
        card.fields['description'].set('Custom visibility marker')
        app.changed()
        settle(app,ready)
        app.toggle_section(key)
        settle(app,ready)
        assert app.nav[key].hidden and not any(r['source'][0]==key for r in app._source_map)
        with patch('cv_studio_ui.messagebox.askyesno',return_value=True):
            app.remove_custom_section(key)
        assert key not in app.nav
        assert not errors,errors
        print('GUI passed: theme dropdown, keyboard/mouse selection and cancellation, six themes in light/dark, focus/history preservation, PDF independence, sidebar visibility, inline heading rename, save/reopen/export')
    finally:
        app.destroy()


if __name__=='__main__':
    if '--gui' in sys.argv:
        gui_checks('--screenshots' in sys.argv)
    else:
        unittest.main()
