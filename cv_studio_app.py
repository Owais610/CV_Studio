"""Windowed entry point for the standalone Generic Windows application."""
from logging.handlers import RotatingFileHandler
from pathlib import Path
import base64
import logging
import os
import sys
import tempfile

APP_NAME = 'CV Studio'
APP_VERSION = '1.0.0'


def configure_logging():
    directory = Path(os.environ.get('LOCALAPPDATA') or tempfile.gettempdir()) / APP_NAME
    path = directory / 'app.log'
    try:
        directory.mkdir(parents=True,exist_ok=True)
        handler = RotatingFileHandler(path,maxBytes=512_000,backupCount=2,encoding='utf-8')
    except OSError:
        handler = logging.NullHandler()
        path = None
    logging.basicConfig(level=logging.INFO,handlers=[handler],
                        format='%(asctime)s %(levelname)s %(message)s',force=True)
    return path


def user_document_directory():
    home = Path.home()
    documents = home / 'Documents'
    return documents if documents.is_dir() else home


def configure_window(app):
    import tkinter as tk
    icon = Path(__file__).resolve().parent / 'assets' / 'icon.png'
    if icon.is_file():
        app._application_icon = tk.PhotoImage(master=app,data=base64.b64encode(icon.read_bytes()))
        app.iconphoto(True,app._application_icon)
    app.last_dir = str(user_document_directory())


def show_error(message, parent=None):
    try:
        from tkinter import messagebox
        messagebox.showerror(APP_NAME,message,parent=parent)
    except Exception:
        if sys.platform=='win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,message,APP_NAME,0x10)


def main():
    log_path = configure_logging()
    if sys.platform=='win32':
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('CVStudio.Generic.1')
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError,OSError):
            pass
    app = None
    try:
        import CV_Studio_Generic as engine
        if len(sys.argv)>1 and sys.argv[1]=='--smoke-test':
            if len(sys.argv)!=3:
                raise ValueError('Use --smoke-test with a report file path.')
            from cv_studio_smoke import run
            return run(engine,Path(sys.argv[2]))
        app = engine.CVEditor()
        configure_window(app)

        def callback_error(kind,value,traceback):
            logging.error('Window callback failed',exc_info=(kind,value,traceback))
            message = 'An action could not be completed. Your open CV is still available.'
            if log_path:
                message += '\n\nDetails: '+str(log_path)
            show_error(message,parent=app)

        app.report_callback_exception = callback_error
        logging.info('Starting %s %s',APP_NAME,APP_VERSION)
        app.mainloop()
        return 0
    except Exception:
        logging.exception('Application startup failed')
        # Diagnostics must exit without an unattended popup blocking the build.
        if len(sys.argv)>1 and sys.argv[1]=='--smoke-test':
            import json
            import traceback
            if len(sys.argv)==3:
                report = Path(sys.argv[2])
                report.parent.mkdir(parents=True,exist_ok=True)
                report.write_text(json.dumps({'ok':False,'error':traceback.format_exc()},indent=2),encoding='utf-8')
        else:
            message = 'CV Studio could not start.'
            if log_path:
                message += '\n\nDetails: '+str(log_path)
            show_error(message,parent=app)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
