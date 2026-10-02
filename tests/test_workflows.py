"""Document safety regressions and optional GUI checks for compact windows."""
from pathlib import Path
from copy import deepcopy
import sys
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_entries import engine, ROOT, settle
from cv_studio_ui import Button, ScrollArea, SectionCard, StudioApp


class WorkflowTests(unittest.TestCase):
    def test_numeric_settings_handle_overflow_and_keep_limits(self):
        for value in ('inf','Infinity','-inf','1e309',float('inf'),10**500):
            with self.subTest(value=str(value)[:25]):
                self.assertEqual(StudioApp.number(value,13,6,24),13)
        self.assertEqual(StudioApp.number('2',13,6,24),6)
        self.assertEqual(StudioApp.number('30',13,6,24),24)
        self.assertEqual(StudioApp.number('15',13,6,24),15)

    def test_pending_section_rename_is_checked_before_discarding_document(self):
        for response,expected in ((None,False),(False,True),(True,True)):
            with self.subTest(response=response):
                app = SimpleNamespace(dirty=False,save=Mock(return_value=True))
                app.finish_section_rename = Mock(side_effect=lambda:setattr(app,'dirty',True))
                with patch('cv_studio_ui.messagebox.askyesnocancel',return_value=response) as prompt:
                    self.assertIs(StudioApp.confirm_replace(app),expected)
                app.finish_section_rename.assert_called_once_with()
                prompt.assert_called_once()
                self.assertEqual(app.save.call_count,int(response is True))

    def test_clean_document_does_not_prompt_after_finishing_rename(self):
        app = SimpleNamespace(dirty=False,finish_section_rename=Mock())
        with patch('cv_studio_ui.messagebox.askyesnocancel') as prompt:
            self.assertTrue(StudioApp.confirm_replace(app))
        app.finish_section_rename.assert_called_once_with()
        prompt.assert_not_called()

    def test_failed_save_blocks_document_replacement(self):
        app = SimpleNamespace(dirty=True,finish_section_rename=Mock(),save=Mock(return_value=False))
        with patch('cv_studio_ui.messagebox.askyesnocancel',return_value=True):
            self.assertFalse(StudioApp.confirm_replace(app))

    def test_navigation_clears_editor_only_when_changing_page(self):
        for destination in ('header','layout'):
            with self.subTest(destination=destination):
                editor = object()
                app = SimpleNamespace(current_section='header',active_editor=editor,
                    finish_section_rename=Mock(),after_idle=Mock(),
                    pages={key:Mock() for key in ('header','layout')},
                    nav={key:Mock(winfo_exists=Mock(return_value=True)) for key in ('header','layout')})
                StudioApp.navigate(app,destination)
                self.assertIs(app.active_editor,editor if destination=='header' else None)
                app.pages[destination].pack.assert_called_once_with(fill='both',expand=True)

    def test_hidden_editor_cannot_be_changed_through_edit_menu(self):
        editor = Mock(winfo_exists=Mock(return_value=True),winfo_viewable=Mock(return_value=False))
        editor.history_pos,editor.history = 1,[None,None]
        app = SimpleNamespace(active_editor=editor)
        menu = StudioApp.edit_menu(app)
        self.assertTrue(all(not item[3] for item in menu if item is not None))
        for action in ('cut','paste','undo','select_all'):
            StudioApp.edit_action(app,action)
        editor.input.focus_set.assert_not_called()
        editor.input.event_generate.assert_not_called()
        editor.undo.assert_not_called()

    def test_collapsing_active_entry_moves_focus_to_its_header(self):
        body = MagicMock()
        body.__str__.return_value = '.card.body'
        focused = MagicMock()
        focused.__str__.return_value = '.card.body.editor.input'
        editor = object()
        app = SimpleNamespace(focus_get=Mock(return_value=focused),active_editor=editor)
        card = SimpleNamespace(app=app,body=body,chevron=Mock(),refresh=Mock(),expanded=True)
        SectionCard.set_expanded(card,False)
        card.chevron.focus_set.assert_called_once_with()
        body.pack_forget.assert_called_once_with()
        self.assertIsNone(app.active_editor)
        self.assertFalse(card.expanded)

    def test_collapsing_other_entry_preserves_current_editor(self):
        body = MagicMock()
        body.__str__.return_value = '.card.body'
        focused = MagicMock()
        focused.__str__.return_value = '.another.editor.input'
        editor = object()
        app = SimpleNamespace(focus_get=Mock(return_value=focused),active_editor=editor)
        card = SimpleNamespace(app=app,body=body,chevron=Mock(),refresh=Mock(),expanded=True)
        SectionCard.set_expanded(card,False)
        card.chevron.focus_set.assert_not_called()
        self.assertIs(app.active_editor,editor)

    def test_failed_pdf_replacement_preserves_existing_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'existing.pdf'
            previous = b'%PDF existing CV'
            path.write_bytes(previous)
            app = SimpleNamespace(finish_section_rename=Mock(),last_dir=directory,last_pdf='previous.pdf',
                default_pdf_name=lambda:'existing.pdf',collect=lambda:engine.DEFAULT_DATA,
                engine=SimpleNamespace(render_pdf=Mock(return_value=(b'%PDF new CV',1,0,1))),
                _write_file=StudioApp._write_file,status=Mock())
            with patch('cv_studio_ui.filedialog.asksaveasfilename',return_value=str(path)), \
                 patch('cv_studio_ui.os.replace',side_effect=OSError('Cannot replace export')), \
                 patch('cv_studio_ui.messagebox.showerror') as error:
                StudioApp.export_pdf(app)
            self.assertEqual(path.read_bytes(),previous)
            self.assertEqual(list(Path(directory).iterdir()),[path])
            self.assertEqual(app.last_pdf,'previous.pdf')
            error.assert_called_once()

    def test_json_uses_atomic_writer_and_keeps_unicode(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'cv.json'
            data = {'name':'Zoë 你好'}
            app = SimpleNamespace(finish_section_rename=Mock(),collect=lambda:data,
                _write_file=StudioApp._write_file,set_dirty=Mock(),status=Mock())
            StudioApp._write_json(app,path)
            self.assertIn('Zoë 你好',path.read_text(encoding='utf-8'))
            self.assertEqual(app.saved_data,data)
            self.assertEqual(app.json_path,str(path))
            app.set_dirty.assert_called_once_with(False)


def check_scroll_bounds(app):
    """Exercise real Tk offsets: fitted canvases can report (0,1) yet still move."""
    def wheel(canvas,delta,state=0):
        app.wheel(SimpleNamespace(delta=delta,state=state,
            x_root=canvas.winfo_rootx()+canvas.winfo_width()-2,
            y_root=canvas.winfo_rooty()+20))
        app.update()

    # The actual category rail must stay put when every category is visible.
    if app.nav_body.winfo_height()<=app.nav_canvas.winfo_height():
        for delta in (120,-120,120,-120):
            wheel(app.nav_canvas,delta)
        assert app.nav_canvas.canvasy(0)==0,app.nav_canvas.canvasy(0)

    window = tk.Toplevel(app)
    window.geometry('260x300+80+80')
    area = ScrollArea(window,app)
    area.pack(fill='both',expand=True)
    content = tk.Frame(area.inner,width=180,height=80)
    content.pack()
    try:
        window.lift()
        app.update()
        canvas = area.canvas
        assert area.inner.winfo_height()<canvas.winfo_height()
        for delta in (120,-120,120,-120):
            wheel(canvas,delta)
            wheel(canvas,delta,state=1)
        # Also cover scrollbar/reveal/drag callers which use the canvas directly.
        canvas.yview_scroll(-1000,'units')
        canvas.yview_moveto(1)
        area.bar.press(SimpleNamespace(y=150))
        area.bar.motion(SimpleNamespace(y=250))
        app.update()
        assert canvas.canvasy(0)==0,canvas.canvasy(0)
        assert canvas.canvasx(0)==0,canvas.canvasx(0)

        content.configure(height=1000)
        app.update()
        wheel(canvas,-120)
        assert canvas.canvasy(0)>0,'Hidden content must remain scrollable'
        canvas.yview_moveto(1)
        app.update()
        bottom = canvas.canvasy(0)
        for _ in range(4):
            wheel(canvas,-120)
        assert canvas.canvasy(0)==bottom,'Scrolling past the bottom must stop'
        canvas.yview_moveto(0)
        for _ in range(4):
            wheel(canvas,120)
        assert canvas.canvasy(0)==0,'Scrolling past the top must stop'

        canvas.yview_moveto(1)
        content.configure(height=80)
        app.update()
        wheel(canvas,120)
        assert canvas.canvasy(0)==0,'Collapsing content must remove the old offset'
        content.configure(height=400)
        app.update()
        canvas.yview_moveto(1)
        window.geometry('260x540+80+80')
        app.update()
        wheel(canvas,120)
        wheel(canvas,-120)
        assert canvas.canvasy(0)==0,'Growing the viewport must remove the old offset'
    finally:
        window.destroy()
        app.lift()


def gui_checks(screenshots=False):
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    app = engine.CVEditor()
    errors = []
    app.report_callback_exception = lambda *args:errors.append(args)
    app.geometry('1460x920+40+40')
    app.lift()
    app.focus_force()
    try:
        settle(app,lambda:bool(app._preview_pages) and app.raster_future is None)
        check_scroll_bounds(app)
        app.navigate('profile')
        summary = app.fields[('profile',)]
        summary.set('**One** two\nthree')
        assert summary.word_count.get() == '3 words'
        summary.input.focus_force()
        app.update()
        summary.input.insert('end',' four')
        assert summary.word_count.get() == '4 words'
        summary.undo()
        assert summary.word_count.get() == '3 words'
        app.saved_data = app.collect()
        app.set_dirty(False)
        before = summary.get(),deepcopy(summary.history),summary.history_pos,app.collect()
        with patch('cv_studio_ui.filedialog.askopenfilename',return_value='') as picker:
            summary.input.event_generate('<Control-o>')
            app.update()
        picker.assert_called_once()
        assert before == (summary.get(),summary.history,summary.history_pos,app.collect())
        assert not app.dirty
        app.navigate('layout')
        app.update()
        assert app.active_editor is None
        assert all(not item[3] for item in app.edit_menu() if item)
        app.v_margin.set('inf')
        assert app.collect()['settings']['margin_mm'] == 13
        app.v_margin.set('13')

        app.geometry('1040x660+40+40')
        app.update()
        app.update_idletasks()
        assert app.editor_host.winfo_width() >= 405,app.editor_host.winfo_width()
        assert app.preview_host.winfo_width() >= 340,app.preview_host.winfo_width()
        app.json_path = 'A very long document name that should never hide Save or Export buttons.json'
        app.set_dirty(False)
        app.update()
        toolbar = app.file_label.master.master
        for button in toolbar.winfo_children():
            if isinstance(button,Button):
                assert button.winfo_width() >= button.font.measure(button.text)+26
        app.v_template.set('Creative / Photo CV')
        app.template_changed(render=False)
        app.update()
        for button in (app.photo_choose,app.photo_edit,app.photo_remove):
            assert button.winfo_width() >= button.font.measure(button.text)+26,(
                ascii(button.text),button.winfo_width(),button.font.measure(button.text)+26)
        app.pages['layout'].reveal(app.photo_panel)
        app.update()
        if screenshots:
            from gui_support import save_screenshot
            save_screenshot(app,ROOT/'test_artifacts'/'compact_design.png',settle)

        app.navigate('projects')
        card = app.lists['projects'].cards[0]
        card.set_expanded(True)
        card.fields['title'].input.focus_force()
        app.update()
        card.set_expanded(False)
        app.update()
        assert app.focus_get() is card.chevron and app.active_editor is None
        app.json_path = None
        app.saved_data = app.collect()
        app.set_dirty(False)
        app.rename_section('projects')
        rename = app.section_rename['entry']
        rename.delete(0,'end')
        rename.insert(0,'Updated work')
        with patch('cv_studio_ui.messagebox.askyesnocancel',return_value=None) as prompt:
            assert not app.confirm_replace()
        assert prompt.called and app.dirty
        assert app.nav['projects'].text == 'Updated work'
        app.last_pdf = 'previous-document.pdf'
        app.load(engine.DEFAULT_DATA)
        assert app.last_pdf is None
        assert not errors,errors
        print('GUI passed: scroll bounds and resize/collapse, compact panes, photo controls, long filenames, word count, safe Open shortcut, hidden editor focus, pending rename, document export history')
    finally:
        app.destroy()


if __name__=='__main__':
    if '--gui' in sys.argv:
        gui_checks('--screenshots' in sys.argv)
    else:
        unittest.main()
