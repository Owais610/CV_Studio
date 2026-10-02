"""Exercise bundled fonts, Tk, photos, preview and export in the actual executable."""
from pathlib import Path
import base64
import io
import json
import sys
import traceback


def run(engine,report_path):
    from PIL import Image, ImageTk
    from cv_studio_app import configure_window
    from cv_studio_photo import crop_image, decode_photo
    from cv_studio_ui import filedialog

    report_path = report_path.resolve()
    report_path.parent.mkdir(parents=True,exist_ok=True)
    output = report_path.parent / (report_path.stem+'_files')
    output.mkdir(exist_ok=True)
    app = None
    report = dict(ok=False,frozen=bool(getattr(sys,'frozen',False)),
                  font=engine.FONT_LABEL,templates=[],checks=[])
    try:
        if engine.pymupdf is None:
            raise RuntimeError('The PDF preview library is missing from the app.')
        app = engine.CVEditor()
        configure_window(app)
        app.withdraw()
        callback_errors = []
        app.report_callback_exception = lambda *args:callback_errors.append(str(args[1]))
        app.update_idletasks()
        assert app.last_dir!=str(Path(engine.__file__).resolve().parent)
        report['checks'].append('window, icons and user save directory')

        portrait = Image.new('RGB',(90,120),'#A4B8CF')
        for format in ('PNG','JPEG'):
            raw = io.BytesIO()
            portrait.save(raw,format=format)
            encoded = base64.b64encode(raw.getvalue()).decode('ascii')
            cropped = crop_image(decode_photo(encoded),None,size=128,circle=True)
            assert cropped.size==(128,128)
            thumb = ImageTk.PhotoImage(cropped,master=app)
            assert thumb.width()==128
        report['checks'].append('PNG/JPEG photos, cropping and Tk thumbnails')

        data = engine.migrate(engine.DEFAULT_DATA)
        data['settings']['photo'] = encoded
        for index,template in enumerate(engine.TEMPLATES):
            data['settings']['template'] = template
            regions = []
            pdf,pages,links,_ = engine.render_pdf(data,source_map=regions)
            (output/f'template_{index+1}.pdf').write_bytes(pdf)
            with engine.pymupdf.open(stream=pdf,filetype='pdf') as document:
                assert len(document)==pages and pages>0
                assert data['personal']['name'] in ''.join(page.get_text() for page in document)
                assert regions
                assert document[0].get_pixmap().width>0
                if template=='Creative / Photo CV':
                    assert document[0].get_images()
            report['templates'].append(dict(name=template,pages=pages,links=links))
        report['checks'].append('all six PDF designs, embedded fonts, links and source locations')

        app.load(data)
        _,_,pdf,pages,_,_,regions = app.render_document(app.collect(),0)
        app._pdf,app._source_map = pdf,regions
        _,images = app.rasterize(pdf,900,800,1,'page',0)
        app.draw_preview(images)
        assert len(app._preview_pages)==pages and len(app._photos)==pages
        report['checks'].append('live preview rasterization and Tk page images')

        saved = output/'cv_data.json'
        app._write_json(saved)
        assert engine.migrate(json.loads(saved.read_text(encoding='utf-8')))==app.collect()
        original_picker = filedialog.asksaveasfilename
        exported = output/'export.pdf'
        try:
            filedialog.asksaveasfilename = lambda **kwargs:str(exported)
            app.export_pdf()
        finally:
            filedialog.asksaveasfilename = original_picker
        with engine.pymupdf.open(exported) as document:
            assert len(document)==pages
        assert not callback_errors,callback_errors
        report['checks'].append('JSON save/reload and atomic PDF export')
        report['ok'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    finally:
        if app is not None:
            app.destroy()
        report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return 0 if report['ok'] else 1
