# Build only the Generic edition; no Personal documents or test artifacts.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, copy_metadata

root = Path(SPECPATH).parent
data = [(str(root/'assets'/'fonts'),'fonts'),
        (str(root/'assets'/'icon.png'),'assets'),
        (str(root/'assets'/'icon.ico'),'assets'),
        (str(root/'LICENSE'),'licenses'),
        (str(root/'packaging'/'THIRD_PARTY_NOTICES.txt'),'licenses'),
        (str(root/'assets'/'licenses'),'licenses/third-party')]
data += collect_data_files('reportlab',includes=['fonts/*.ttf'])
for distribution in ('reportlab','PyMuPDF','Pillow'):
    data += copy_metadata(distribution)

a = Analysis([str(root/'cv_studio_app.py')],pathex=[str(root)],
             binaries=collect_dynamic_libs('pymupdf'),datas=data,
             hiddenimports=[],hookspath=[],runtime_hooks=[],
             excludes=['matplotlib','pytest','tests'],noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz,a.scripts,a.binaries,a.datas,[],name='CV Studio',debug=False,
          bootloader_ignore_signals=False,strip=False,upx=False,console=False,
          disable_windowed_traceback=False,
          icon=str(root/'assets'/'icon.ico'),
          version=str(root/'packaging'/'windows_version.txt'))
