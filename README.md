# CV Studio — Generic edition

Run `CV_Studio_Generic.py` to open the editor with a placeholder CV anyone can personalise.

From this folder:

```powershell
python .\CV_Studio_Generic.py
```

This folder is self-contained and can be shared on its own. Keep all seven `cv_studio_*.py` support files beside the launcher. It does not depend on the Personal edition or the parent folder.

Requirements: Python, `reportlab`, `pymupdf` for live preview, and `Pillow` for photo editing. The existing Python environment already has these installed.

`CV_Studio_Generic_BACKUP.py` is the unchanged pre-overhaul backup, not the current launcher. Existing JSON files can be opened using File → Open.
