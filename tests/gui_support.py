"""Shared GUI test helpers that keep screenshots limited to CV Studio."""
import inspect
from pathlib import Path
import sys
import time


def save_screenshot(app, path, settle):
    """Save the open popup, or the app window when no popup is open."""
    from PIL import ImageGrab

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    start = time.monotonic()
    settle(app, lambda: time.monotonic() - start > .3)
    popup = getattr(app, 'popup', None)
    target = popup if popup is not None and popup.winfo_exists() else app

    if sys.platform == 'win32':
        if 'window' not in inspect.signature(ImageGrab.grab).parameters:
            raise RuntimeError('Windows GUI screenshots need Pillow with ImageGrab.grab(window=...) support.')
        import ctypes
        from ctypes import wintypes

        get_root = ctypes.windll.user32.GetAncestor
        get_root.argtypes = (wintypes.HWND, wintypes.UINT)
        get_root.restype = wintypes.HWND
        # Capture this window even when another application covers it. Never
        # save unrelated desktop content in Windows test artifacts.
        shot = ImageGrab.grab(window=get_root(target.winfo_id(), 2))
    else:
        target.lift()
        target.update()
        x, y = target.winfo_rootx(), target.winfo_rooty()
        shot = ImageGrab.grab(bbox=(x, y, x + target.winfo_width(), y + target.winfo_height()))

    shot.save(path)
