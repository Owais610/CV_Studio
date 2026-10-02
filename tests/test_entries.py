"""Self-contained mixed-entry and portability regression tests.

python -m unittest discover -s tests -v
python tests/test_entries.py --gui [--screenshots]
"""
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT))
from gui_support import save_screenshot

ENGINE_NAME = 'CV_Studio_Generic'
engine = importlib.import_module(ENGINE_NAME)
from cv_studio_sections import ENTRY_CHOICES, ENTRY_TYPES, empty_entry, entry_type, normalize_entry
from cv_studio_richtext import Format, parse, serialize
from cv_studio_templates import _entry_link

KEY = 'custom_mixed_test'


def samples():
    result = []
    for kind in ENTRY_CHOICES:
        item = empty_entry(kind)
        for field in ENTRY_TYPES[kind].fields:
            value = f'{kind.title()} {field.key}'
            if field.mode == 'bullets':
                value = ['<b><i>Combined emphasis</i></b>', '<a href="https://example.com/project">Linked result</a>']
            elif field.mode == 'paragraphs':
                value = '<b><i>Combined emphasis</i></b>\n' + value
            item[field.key] = value
        result.append(item)
    by_kind = {item['entry_type']: item for item in result}
    by_kind['education'].update(degree='MSc Data Science', institution='Example University', dates='2024 – 2026', gpa='3.9 / 4.0')
    by_kind['publication'].update(title='Published research', authors='A. Researcher; B. Collaborator', venue='Journal of Research', dates='2026', link='10.1234/example')
    by_kind['project']['title'] = 'Open data project'
    by_kind['experience'].update(title='Research engineer', company='Example Lab', dates='2023 – Present')
    by_kind['reference'].update(name='Dr Example Referee', role='Research supervisor', organisation='Example University', email='referee@example.com', phone='+44 (20) 1234 5678')
    by_kind['certification'].update(title='Professional certification', issuer='Example Institute', link='https://example.com/credential')
    by_kind['award']['title'] = 'Research excellence award'
    by_kind['skills'].update(category='Research methods', items='Python · Statistics · Communication')
    by_kind['bullets']['title'] = 'Selected achievements'
    by_kind['text'].update(title='Additional information', description='Available for international collaboration.')
    return result


def document(entries=None):
    data = engine.migrate(engine.DEFAULT_DATA)
    data['custom_sections'][KEY] = samples() if entries is None else entries
    for section in data['settings']['sections']:
        section['visible'] = False
    data['settings']['sections'].insert(0, dict(key=KEY, title='Research & professional background', visible=True))
    data['settings']['autofit'] = False
    return data


class EntryTests(unittest.TestCase):
    def test_schemas_and_legacy(self):
        self.assertEqual(set(ENTRY_CHOICES), {'education','publication','project','experience','reference','certification','award','skills','bullets','text'})
        for kind in ENTRY_CHOICES:
            with self.subTest(kind=kind):
                item = empty_entry(kind)
                self.assertEqual(entry_type(item), kind)
                self.assertEqual(normalize_entry(item), item)
                self.assertEqual(len({f.key for f in ENTRY_TYPES[kind].fields}), len(ENTRY_TYPES[kind].fields))
        old = dict(title='Old entry', meta='Old details', description='Old description', bullets=['Old bullet'])
        self.assertEqual(normalize_entry(old), old)
        self.assertEqual(entry_type(old), 'legacy')
        unknown = dict(old, entry_type='future_type', extra={'keep': True})
        self.assertEqual(normalize_entry(unknown), unknown)
        self.assertEqual(normalize_entry(dict(entry_type='bullets', bullets='one\ntwo'))['bullets'], ['one','two'])

    def test_save_reload_order_and_metadata(self):
        data = document()
        data['custom_sections'][KEY].reverse()
        data['custom_sections'][KEY][0]['extra'] = {'keep': True}
        saved = engine.migrate(data)
        self.assertEqual(engine.migrate(json.loads(json.dumps(saved))), saved)
        self.assertEqual(engine.migrate(saved), saved)
        self.assertEqual(saved['settings']['sections'][0]['title'], 'Research & professional background')
        self.assertEqual([e['entry_type'] for e in saved['custom_sections'][KEY]], list(reversed(ENTRY_CHOICES)))
        self.assertEqual(saved['custom_sections'][KEY][0]['extra'], {'keep': True})

    def test_link_fields_and_clear_formatting(self):
        for value, mode, target in [('10.1234/example', 'link', 'https://doi.org/10.1234/example'),
                                    ('referee@example.com', 'link', 'mailto:referee@example.com'),
                                    ('+44 (20) 1234 5678', 'phone', 'tel:+442012345678'),
                                    ('example.com', 'link', 'https://example.com')]:
            _, attrs = parse(_entry_link(value, mode))
            self.assertTrue(all(a.link == target for a in attrs), (value, attrs))
        value = serialize('example.com', [Format(no_link=True)] * 11)
        self.assertEqual(_entry_link(value,'link'), value)
        explicit = '<a href="https://example.com/label"><b><i>Label</i></b></a>'
        self.assertEqual(_entry_link(explicit,'link'), explicit)

    def test_mixed_entries_every_layout(self):
        data = document()
        for template in engine.TEMPLATES:
            with self.subTest(template=template):
                data['settings']['template'] = template
                regions = []
                pdf, pages, _, _ = engine.render_pdf(data, source_map=regions)
                with engine.pymupdf.open(stream=pdf, filetype='pdf') as doc:
                    text = ''.join(page.get_text() for page in doc)
                    self.assertEqual(pages, len(doc))
                    offsets = [text.index(item[ENTRY_TYPES[item['entry_type']].title_key]) for item in data['custom_sections'][KEY]]
                    self.assertEqual(offsets, sorted(offsets))
                    self.assertIn('GPA / grade: 3.9 / 4.0', text)
                    self.assertIn('referee@example.com', text)
                    urls = {link.get('uri') for page in doc for link in page.get_links()}
                    for url in ('https://doi.org/10.1234/example', 'mailto:referee@example.com', 'https://example.com/credential', 'https://example.com/project'):
                        self.assertIn(url, urls)
                    # PyMuPDF classifies tel: as either URI or a launch action.
                    self.assertIn(b'tel:+442012345678', pdf)
                    spans = [s for p in doc for b in p.get_text('dict')['blocks'] if 'lines' in b for line in b['lines'] for s in line['spans']]
                    self.assertTrue(any('Combined emphasis' in s['text'] and ('BoldOblique' in s['font'] or 'BoldItalic' in s['font']) for s in spans))
                    for index, item in enumerate(data['custom_sections'][KEY]):
                        for field in ENTRY_TYPES[item['entry_type']].fields:
                            source = (KEY,index,field.key) + ((0,) if field.mode in ('paragraphs','bullets') else ())
                            self.assertTrue(any(r['source']==source for r in regions), source)
                    self.check_regions(doc, regions)

    def check_regions(self, doc, regions):
        for region in regions:
            x0,y0,x1,y1 = region['rect']
            page = doc[region['page']]
            self.assertTrue(0<=x0<x1<=page.rect.width+1 and 0<=y0<y1<=page.rect.height+1, region)

    def test_long_entries_empty_fields_and_visibility(self):
        entries = [empty_entry('education'), empty_entry('publication'), empty_entry('bullets'), empty_entry('text')]
        entries[0].update(degree='Oversized education', coursework='CourseMarker '*450)
        entries[1].update(title='Oversized publication', description='AbstractMarker '*450)
        entries[2]['bullets'] = ['BulletMarker '*450]
        entries[3]['description'] = 'Final typed content'
        data = document(entries)
        for template in engine.TEMPLATES:
            with self.subTest(template=template):
                data['settings'].update(template=template, font_scale=115, margin_mm=24)
                regions = []
                pdf, pages, _, _ = engine.render_pdf(data, source_map=regions)
                self.assertGreater(pages, 1)
                with engine.pymupdf.open(stream=pdf,filetype='pdf') as doc:
                    text = ''.join(p.get_text() for p in doc)
                    for marker in ('CourseMarker','AbstractMarker','BulletMarker'):
                        self.assertEqual(text.count(marker), 450)
                    self.assertIn('Final typed content', text)
                    self.assertNotIn('GPA / grade:', text)
                    self.check_regions(doc, regions)
                data['settings']['sections'][0]['visible'] = False
                hidden, *_ = engine.render_pdf(data)
                with engine.pymupdf.open(stream=hidden,filetype='pdf') as doc:
                    self.assertNotIn('CourseMarker', ''.join(p.get_text() for p in doc))
                data['settings']['sections'][0]['visible'] = True

    def test_relocated_installation_and_bundled_fonts(self):
        # Copy only the publishable application files. No parent folder, local
        # font directory, developer CWD, sibling edition, or personal path.
        with tempfile.TemporaryDirectory(prefix='cv-studio-') as temp:
            target = Path(temp)/'Portable CV – shared folder'
            target.mkdir()
            for file in [ROOT/(ENGINE_NAME+'.py'), *ROOT.glob('cv_studio_*.py')]:
                shutil.copy2(file, target/file.name)
            script = '''
import importlib, json, sys
from pathlib import Path
from unittest.mock import patch
folder = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(folder))
engine = importlib.import_module(sys.argv[2])
for name, module in list(sys.modules.items()):
    if name.startswith('cv_studio_'):
        assert Path(module.__file__).resolve().parent == folder, module.__file__
real_exists = Path.exists
with patch.object(Path, 'exists', lambda p: False if p.name.startswith('DejaVu') else real_exists(p)):
    assert engine.setup_fonts()[0] == 'Bitstream Vera'
data = engine.migrate(engine.DEFAULT_DATA)
assert engine.migrate(json.loads(json.dumps(data))) == data
for template in engine.TEMPLATES:
    data['settings']['template'] = template
    pdf, pages, links, _ = engine.render_pdf(data)
    assert pdf.startswith(b'%PDF-') and pages > 0 and links > 0
print('Relocated imports and all layouts with bundled fonts passed')
'''
            result = subprocess.run([sys.executable,'-E','-c',script,str(target),ENGINE_NAME],
                                    cwd=temp, capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+'\n'+result.stderr)


def settle(app, predicate=lambda: True, timeout=20):
    start = time.monotonic()
    while time.monotonic()-start < timeout:
        app.update()
        if predicate():
            return
        time.sleep(.02)
    raise AssertionError('GUI did not settle: '+app.preview_state.get()+' / '+app.status.get())


def gui_checks(screenshots=False):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    app = engine.CVEditor()
    errors = []
    app.report_callback_exception = lambda *args: (errors.append(args),traceback.print_exception(*args))
    app.geometry('1460x920+40+40')
    app.lift()
    app.focus_force()

    def capture(name):
        if screenshots:
            save_screenshot(app, ROOT/'test_artifacts'/(name+'.png'), settle)

    def preview_ready():
        return getattr(app,'rendered_data',None)==app.collect() and app.raster_future is None and bool(app._preview_pages) and app._displayed_pdf==app._pdf

    try:
        settle(app,lambda:bool(app._preview_pages))
        original_profile = app.fields[('profile',)]
        key = app.add_custom_section()
        entry = app.section_rename['entry']
        entry.delete(0,'end')
        entry.insert(0,'Research & credentials')
        app.finish_section_rename()
        items = app.lists[key]
        assert not items.cards and app.fields[('profile',)] is original_profile
        app.update()
        items.add_button.invoke()
        app.update()
        assert [b.text for b in app.popup.buttons]==[ENTRY_TYPES[k].label for k in ENTRY_CHOICES]
        capture('entry_picker')
        app.popup.event_generate('<Escape>')
        app.update()
        assert not items.cards
        cards = []
        for index, sample in enumerate(samples()):
            kind = sample['entry_type']
            app.pages[key].canvas.yview_moveto(0)
            app.update()
            items.add_button.invoke()
            app.update()
            app.popup.buttons[index].invoke()
            settle(app,lambda:len(items.cards)==index+1)
            card = items.cards[-1]
            assert set(card.fields)=={f.key for f in ENTRY_TYPES[kind].fields}
            assert card.get()['entry_type']==kind and card.type_label.cget('text')==ENTRY_TYPES[kind].label.upper()
            first = next(iter(card.fields.values()))
            settle(app,lambda:app.focus_get() is first.input)
            for field, value in sample.items():
                if field!='entry_type':
                    card.fields[field].set('\n'.join(value) if isinstance(value,list) else value)
            card.refresh()
            cards.append(card)
            if kind in ('education','publication','reference'):
                capture(kind+'_form')
            card.set_expanded(False)
        # Unknown metadata, including keys used by a different form, survives.
        cards[0].saved_extras.update(extra={'keep':True},bullets=['Retained metadata'])
        assert cards[0].get()['bullets']==['Retained metadata']
        before = items.get_items()
        copy = items.duplicate(cards[0])
        assert copy.get()==cards[0].get()
        items.move(copy,-1)
        assert items.cards[0] is copy
        with patch('cv_studio_ui.messagebox.askyesno',return_value=True):
            items.remove(copy)
        assert items.get_items()==before
        # Real reorder controller, stable insertion marker, mixed card types.
        items.expand_all(False)
        app.pages[key].canvas.yview_moveto(0)
        app.update()
        source, target = cards[1], cards[0]
        x,y = source.title_label.winfo_rootx()+20,source.title_label.winfo_rooty()+6
        destination = target.winfo_rooty()+2
        controller = items.reorder
        controller.start(source,SimpleNamespace(x_root=x,y_root=y),source.title_label)
        controller.motion(SimpleNamespace(x_root=x,y_root=destination))
        app.update_idletasks()
        assert controller.marker.winfo_ismapped() and controller.ghost.winfo_ismapped()
        assert items.get_items()==before
        controller.end(SimpleNamespace(x_root=x,y_root=destination))
        settle(app,lambda:controller.state is None)
        assert items.cards[0] is source and items.cards[1] is target
        app.changed()
        settle(app,preview_ready)
        capture('mixed_entries')
        # A typed PDF field must reveal exactly the correct field, not a fixed
        # title/description slot from the original custom form.
        for index, field in ((1,'degree'),(0,'link'),(4,'name')):
            region = next(r for r in app._source_map if r['source']==(key,index,field))
            page = next(p for p in app._preview_pages if p['number']==region['page'])
            x0,y0,x1,y1 = region['rect']
            app.preview_double_click(SimpleNamespace(x=page['x']+(x0+x1)/2*page['scale']-app.pcanvas.canvasx(0),
                                                    y=page['y']+(y0+y1)/2*page['scale']-app.pcanvas.canvasy(0)))
            app.update()
            assert app.active_editor is items.cards[index].fields[field]
        # Rich-text edits and line ordering retain combined emphasis and URLs.
        bullets = cards[2].fields['bullets']
        bullets.set('First result\nSecond result')
        app.reveal_field(bullets,cards[2])
        app.update()
        bullets.input.tag_add('sel','1.0','1.5')
        bullets.toggle('bold')
        bullets.toggle('italic')
        assert all(a.bold and a.italic for a in bullets.attrs[:5])
        bullets.apply_link(0,5,'First','https://example.com/edited')
        assert all(a.link and a.bold and a.italic for a in bullets.attrs[:5])
        gutter = bullets.line_handles
        app.update()
        rows = gutter.rows()
        x = gutter.gutter.winfo_rootx()+12
        start, end = rows[0][2]+6, rows[1][2]+rows[1][4]-2
        gutter.start(SimpleNamespace(x_root=x,y_root=start))
        gutter.controller.motion(SimpleNamespace(x_root=x,y_root=end))
        gutter.controller.end(SimpleNamespace(x_root=x,y_root=end))
        settle(app,lambda:gutter.controller.state is None)
        assert bullets.visible().splitlines()==['Second result','First result']
        assert parse(bullets.get().splitlines()[1])[1][0].link=='https://example.com/edited'
        app.changed()
        settle(app,preview_ready)
        app.set_mode('Dark')
        items.expand_all(False)
        app.pages[key].canvas.yview_moveto(0)
        app.update()
        capture('mixed_entries_dark')
        app.set_mode('Light')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'mixed.json'
            app._write_json(path)
            saved = app.collect()
            app.load(json.loads(path.read_text(encoding='utf-8')))
            assert app.collect()==saved
            assert app.nav[key].text=='Research & credentials'
            assert app.lists[key].get_items()==saved['custom_sections'][key]
            exported = Path(temp)/'mixed.pdf'
            with patch('cv_studio_ui.filedialog.asksaveasfilename',return_value=str(exported)), \
                 patch('cv_studio_ui.messagebox.showinfo'), \
                 patch('cv_studio_ui.messagebox.showerror', side_effect=AssertionError):
                app.export_pdf()
            with engine.pymupdf.open(exported) as doc:
                urls = {link.get('uri') for page in doc for link in page.get_links()}
                assert {'https://doi.org/10.1234/example','https://example.com/edited','mailto:referee@example.com'} <= urls
        legacy = dict(title='Legacy entry',meta='Details',description='Original content',bullets=['Still here'])
        old = document([legacy])
        app.load(old)
        assert app.lists[KEY].cards[0].get()==legacy
        assert set(app.lists[KEY].cards[0].fields)=={'title','meta','description','bullets'}
        assert not errors, errors
        print('GUI passed: all entry types, focus, rich text, card/line drag, save/reopen, PDF links, click-to-edit, legacy entries')
    finally:
        app.destroy()


if __name__ == '__main__':
    if '--gui' in sys.argv:
        gui_checks('--screenshots' in sys.argv)
    else:
        unittest.main()
