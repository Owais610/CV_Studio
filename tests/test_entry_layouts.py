"""Compact PDF entries: geometry, persistence, ordering, and page safety."""
import io
import json
from pathlib import Path
import sys
import tempfile
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_entries import engine, document, KEY, ROOT, settle
from gui_support import save_screenshot
from cv_studio_sections import ENTRY_TYPES, empty_entry
from cv_studio_templates import CompactEntryPair
from reportlab.pdfgen.canvas import Canvas


def reference(number):
    return dict(empty_entry('reference'), name=f'Dr Referee {number}', role='Research supervisor',
                organisation='Example University', email=f'referee{number}@example.com', phone='+44 20 1234 5678')


def render(entries, template, layout='auto'):
    data = document(entries)
    data['settings'].update(template=template,autofit=False)
    data['settings']['sections'][0]['entry_layout'] = layout
    regions = []
    pdf, pages, _, _ = engine.render_pdf(data,source_map=regions)
    return data, pdf, pages, regions


def region(regions, index, field='name'):
    return next(r for r in regions if r['source']==(KEY,index,field))


def same_row(left, right):
    return left['page']==right['page'] and abs(left['rect'][1]-right['rect'][1])<.1


class EntryLayoutTests(unittest.TestCase):
    def test_references_auto_single_and_odd_entry_every_template(self):
        for template in engine.TEMPLATES:
            for layout in ('auto','single','columns'):
                with self.subTest(template=template,layout=layout):
                    entries = [reference(i) for i in range(3)]
                    _,pdf,_,regions = render(entries,template,layout)
                    first,second,third = [region(regions,i) for i in range(3)]
                    paired = layout=='columns' or (layout=='auto' and template!='Minimal / ATS-friendly')
                    self.assertEqual(same_row(first,second),paired)
                    if paired:
                        self.assertGreater(second['rect'][0],first['rect'][2])
                        self.assertGreater(third['rect'][2]-third['rect'][0],first['rect'][2]-first['rect'][0])
                    self.assertGreater(third['rect'][1],second['rect'][1])
                    with engine.pymupdf.open(stream=pdf,filetype='pdf') as doc:
                        urls = {link.get('uri') for p in doc for link in p.get_links()}
                        self.assertTrue({f'mailto:referee{i}@example.com' for i in range(3)} <= urls)
                        self.check_bounds(doc,regions)
                    # A pair saves real vertical space, not just horizontal placement.
                    if paired:
                        _,_,_,stacked = render(entries,template,'single')
                        self.assertLess(third['rect'][1],region(stacked,2)['rect'][1])

    def check_bounds(self,doc,regions):
        for r in regions:
            x0,y0,x1,y1 = r['rect']
            self.assertTrue(0<=x0<x1<=doc[r['page']].rect.width+1 and 0<=y0<y1<=doc[r['page']].rect.height+1,r)

    def test_compact_categories_and_mixed_order(self):
        for kind in ('reference','certification','award','skills','education'):
            with self.subTest(kind=kind):
                key = ENTRY_TYPES[kind].title_key
                entries = [dict(empty_entry(kind), **{key:f'Entry {i}'}) for i in range(3)]
                _,_,_,regions = render(entries,'Modern Professional')
                self.assertTrue(same_row(region(regions,0,key),region(regions,1,key)))
        entries = [reference(0),dict(empty_entry('text'),title='Middle note',description='Keep this between references.'),reference(1),reference(2)]
        _,pdf,_,regions = render(entries,'Modern Professional')
        self.assertFalse(same_row(region(regions,0),region(regions,1,'title')))
        self.assertTrue(same_row(region(regions,2),region(regions,3)))
        with engine.pymupdf.open(stream=pdf,filetype='pdf') as doc:
            text = ''.join(p.get_text() for p in doc)
            positions = [text.index(name) for name in ('Dr Referee 0','Middle note','Dr Referee 1','Dr Referee 2')]
            self.assertEqual(positions,sorted(positions))
        # Opt-in columns also supports projects/publications/free text, without
        # changing their default long-form presentation.
        for kind in ('project','publication','experience','text','bullets'):
            entries = [dict(empty_entry(kind),title=f'Entry {i}') for i in range(2)]
            for layout in ('auto','columns'):
                _,_,_,regions = render(entries,'Modern Professional',layout)
                self.assertEqual(same_row(region(regions,0,'title'),region(regions,1,'title')),layout=='columns')

    def test_layout_migration_save_and_reorder(self):
        data = document([reference(1),reference(2)])
        for layout in ('auto','single','columns','unknown',None,{},5):
            with self.subTest(layout=layout):
                data['settings']['sections'][0]['entry_layout'] = layout
                saved = engine.migrate(json.loads(json.dumps(data)))
                self.assertEqual(saved['settings']['sections'][0].get('entry_layout','auto'),layout if layout in ('single','columns') else 'auto')
                self.assertEqual(engine.migrate(saved),saved)
        saved['settings']['sections'][0]['entry_layout'] = 'columns'
        saved['custom_sections'][KEY].reverse()
        saved['settings']['sections'].reverse()
        saved['settings']['sections'][-1]['title'] = 'Professional referees'
        self.assertEqual(engine.migrate(json.loads(json.dumps(saved))),saved)
        _,pdf,_,regions = render(saved['custom_sections'][KEY],'Modern Professional','columns')
        self.assertTrue(same_row(region(regions,0),region(regions,1)))
        with engine.pymupdf.open(stream=pdf,filetype='pdf') as doc:
            self.assertLess(doc[0].get_text().index('Dr Referee 2'),doc[0].get_text().index('Dr Referee 1'))

    def test_long_pairs_and_many_rows_no_loss_or_clipping(self):
        for template in engine.TEMPLATES:
            for oversized in (False,True):
                with self.subTest(template=template,oversized=oversized):
                    entries = [reference(i) for i in range(21)]
                    if oversized:
                        entries[0]['description'] = '<b><i>LongReferenceMarker </i></b>'*600
                        entries[1]['description'] = 'OtherReferenceMarker '*450
                    data = document(entries)
                    data['settings'].update(template=template,font_scale=115,margin_mm=24,autofit=False)
                    data['settings']['sections'][0]['entry_layout'] = 'columns'
                    regions = []
                    pdf,pages,_,_ = engine.render_pdf(data,source_map=regions)
                    _,_,_,baseline = render([reference(0)],template,'single')
                    left_edge,_,right_edge,_ = region(baseline,0)['rect']
                    for r in regions:
                        if r['source'][0]==KEY:
                            self.assertGreaterEqual(r['rect'][0],left_edge-.1,r)
                            self.assertLessEqual(r['rect'][2],right_edge+.1,r)
                    self.assertGreater(pages,1)
                    with engine.pymupdf.open(stream=pdf,filetype='pdf') as doc:
                        text = ''.join(p.get_text() for p in doc)
                        for i in range(21):
                            self.assertIn(f'Dr Referee {i}',text)
                            self.assertTrue(any(r['source']==(KEY,i,'name') for r in regions))
                        self.assertEqual(text.count('LongReferenceMarker'),600 if oversized else 0)
                        self.assertEqual(text.count('OtherReferenceMarker'),450 if oversized else 0)
                        self.check_bounds(doc,regions)
                    if oversized:
                        self.assertFalse(same_row(region(regions,0),region(regions,1)))

    def test_narrow_container_falls_back_without_stretching(self):
        builder = engine.CVBuilder(document())
        entries = [[builder.para(f'Entry {i}',builder.S['project'],source=(KEY,i,'name'))] for i in range(2)]
        pair = CompactEntryPair(*entries,builder)
        canvas = Canvas(io.BytesIO())
        width,height = pair.wrapOn(canvas,110,700)
        self.assertAlmostEqual(width,110)
        pair.drawOn(canvas,20,700-height)
        left,right = [region(builder.source_regions,i) for i in range(2)]
        self.assertFalse(same_row(left,right))
        self.assertAlmostEqual(left['rect'][0],right['rect'][0])


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
        return getattr(app,'rendered_data',None)==app.collect() and app.raster_future is None and bool(app._preview_pages) and app._displayed_pdf==app._pdf

    def capture(name):
        if screenshots:
            save_screenshot(app, ROOT/'test_artifacts'/(name+'.png'), settle)

    try:
        data = engine.migrate(engine.DEFAULT_DATA)
        data['settings']['autofit'] = False
        data['custom_sections'][KEY] = [reference(1),reference(2)]
        data['settings']['sections'].append(dict(key=KEY,title='Professional references',visible=True))
        app.load(data)
        app.navigate(KEY)
        items = app.lists[KEY]
        items.expand_all(False)
        settle(app,ready)
        assert items.get_layout()=='auto'
        assert same_row(region(app._source_map,0),region(app._source_map,1))
        capture('references_auto')
        for index,mode in ((1,'single'),(2,'columns'),(0,'auto')):
            items.layout_choice.invoke()
            app.update()
            assert len(app.popup.buttons)==3
            if index==1:
                capture('entry_layout_picker')
            app.popup.buttons[index].invoke()
            settle(app,lambda:items.get_layout()==mode and ready())
            assert same_row(region(app._source_map,0),region(app._source_map,1))==(mode!='single')
            assert app.dirty==(mode!='auto')
            assert next(s for s in app.collect()['settings']['sections'] if s['key']==KEY).get('entry_layout','auto')==mode
        for template in engine.TEMPLATES:
            app.v_template.set(template)
            app.template_changed()
            settle(app,ready)
            assert same_row(region(app._source_map,0),region(app._source_map,1))==(template!='Minimal / ATS-friendly')
            # Click the second reference's email in the PDF, in either column
            # layout. It must focus the second reference, never the first.
            target = region(app._source_map,1,'email')
            page = next(p for p in app._preview_pages if p['number']==target['page'])
            x0,y0,x1,y1 = target['rect']
            app.preview_double_click(SimpleNamespace(x=page['x']+(x0+x1)/2*page['scale']-app.pcanvas.canvasx(0),
                                                    y=page['y']+(y0+y1)/2*page['scale']-app.pcanvas.canvasy(0)))
            app.update()
            assert app.active_editor is items.cards[1].fields['email']
            if screenshots:
                output = ROOT/'test_artifacts'
                with engine.pymupdf.open(stream=app._pdf,filetype='pdf') as doc:
                    name = template.split(' / ')[0].replace(' ','_').lower()
                    doc[target['page']].get_pixmap(matrix=engine.pymupdf.Matrix(1.6,1.6)).save(output/(name+'_references_pdf.png'))
        app.v_template.set('Modern Professional')
        app.template_changed()
        items.layout_choice.choose('Two columns')
        original = items.cards[1]
        items.move(original,-1)
        settle(app,ready)
        assert items.cards[0] is original and items.get_items()[0]['name']=='Dr Referee 2'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)/'references.json'
            app._write_json(path)
            saved = app.collect()
            app.load(json.loads(path.read_text(encoding='utf-8')))
            assert app.collect()==saved and app.lists[KEY].get_layout()=='columns'
            export = Path(temp)/'references.pdf'
            with patch('cv_studio_ui.filedialog.asksaveasfilename',return_value=str(export)), \
                 patch('cv_studio_ui.messagebox.showinfo'), \
                 patch('cv_studio_ui.messagebox.showerror',side_effect=AssertionError):
                app.export_pdf()
            with engine.pymupdf.open(export) as doc:
                urls = {link.get('uri') for p in doc for link in p.get_links()}
                assert {'mailto:referee1@example.com','mailto:referee2@example.com'}<=urls
        app.lists[KEY].expand_all(False)
        app.pages[KEY].canvas.yview_moveto(0)
        app.set_mode('Dark')
        app.update()
        capture('references_dark')
        app.set_mode('Light')
        assert not errors,errors
        print('GUI passed: entry layout picker, six templates, two-column click-to-edit, reordered references, JSON persistence, PDF links')
    finally:
        app.destroy()


if __name__=='__main__':
    if '--gui' in sys.argv:
        gui_checks('--screenshots' in sys.argv)
    else:
        unittest.main()
