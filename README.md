# CV Studio

A desktop CV editor with visual rich text, live PDF preview, six layouts, photo cropping, and reusable custom sections. The starter document contains placeholders, not personal CV data.

## Windows app

[**Download CV Studio for Windows**](https://github.com/Owais610/CV_Studio/releases/latest)
— get `CV Studio-Windows.zip`, extract it, and double-click `CV Studio.exe`.
Releases also include `SHA256SUMS.txt` to verify downloaded files.

The Generic edition can run as a standalone **CV Studio.exe**. Double-click it to
open the editor; Python and a terminal are not required. The Windows build includes
the preview libraries, application icon and PDF fonts.

After building, double-click the **CV Studio** shortcut in the repository folder,
or run `dist/CV Studio.exe` directly. `dist/CV Studio-Windows.zip`
contains the executable and its readme/license notices for sharing. Save editable
CVs as JSON and export finished documents as PDF using the existing file dialogs.
You can move the executable to another folder without moving your documents.

### Build the Windows app

On a 64-bit Windows desktop with Python 3.10+ and Tcl/Tk, run from the repository:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows.ps1
```

The script creates an isolated `.build-venv`, installs the tested build dependencies,
and packages **only the Generic edition**. It then checks the actual executable
from another working directory without Python on its PATH: all six PDF layouts,
preview images, photo cropping, JSON saves and PDF export. A failed check stops
the build. `build/`, `dist/` and the build environment are ignored by Git.

The execution-policy setting applies only to this build command. Later builds can
use `-SkipInstall` when the build environment is already prepared. The executable
is built with [PyInstaller](https://pyinstaller.org/en/stable/usage.html), which
bundles the runtime and libraries into the app. This build targets Windows; builds
for other operating systems need to be produced on those systems.

App errors are logged locally in `%LOCALAPPDATA%\CV Studio\app.log`.

## Run from source

Use **Python 3.10 or newer with Tkinter** on a Windows, macOS, or Linux desktop. Download/clone the whole repository, then open a terminal in its folder. Keep all `cv_studio_*.py` modules beside `CV_Studio_Generic.py`, including `cv_studio_appearance.py` and `cv_studio_data.py`; no sibling application or parent folder is required.

### Windows

Install Python with Tcl/Tk support, then run:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe CV_Studio_Generic.py
```

If `py` is unavailable, use your Python installation's `python` command for the first line. No virtual-environment activation or PowerShell execution-policy change is needed.

### macOS / Linux

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python CV_Studio_Generic.py
```

Check Tk support with `python3 -m tkinter`. On Debian/Ubuntu, install the matching `python3-tk` and `python3-venv` system packages if needed. Other distributions and Homebrew Python require the Tk package matching their Python installation; the python.org macOS installer is another option. Tkinter is **not** installed with pip.

A graphical desktop/display is required; this is not a browser app. Headless GUI tests require a virtual display.

PDF fonts are discovered relative to the application and in platform font folders. ReportLab's bundled Bitstream Vera family is the fallback, so fonts from the author's computer are not required. Optionally put `DejaVuSans.ttf`, `DejaVuSans-Bold.ttf`, `DejaVuSans-Oblique.ttf`, and `DejaVuSans-BoldOblique.ttf` in a `fonts/` directory beside the launcher.

## CV layouts

Each layout uses the same editable document, live links, and click-to-edit preview:

| Layout | Design |
| --- | --- |
| Modern Professional | The original shaded summary panel, skills grid, structured experience columns, and GPA panel. |
| Minimal / ATS-friendly | Restrained monochrome typography and a straightforward reading order. |
| Executive | The original split masthead and editorial section labels beside the content. |
| Academic / Research | A centered identity, serif body text, and flowing research and publication entries. |
| Two-Column | The original continuous section rail, delicate separators, and generous main column. |
| Creative / Photo CV | The original portrait sidebar, dark section rail, and timeline details. |

Body paragraphs and wrapped bullet text use full justification, with the final line left aligned. Headings, dates, contact entries, and short labels keep their natural alignment. Contact entries wrap together; separators appear only between entries on the same line. Long URLs retain their full clickable target.

**Prefer one page** adjusts vertical gaps and line spacing before reducing text. It keeps useful spacing improvements that reduce overflow even when a longer CV still needs multiple pages. Text is reduced only when it saves a page, with a maximum reduction of 8%; manually reduced text is not shrunk further. CVs that already fit one page remain unchanged. Your margins, template design and content stay intact. Turning the option off preserves the selected layout exactly.

## Flexible custom sections

1. Choose **+ Add Section** in the Document sidebar and name it in place.
2. Choose **+ Add entry ▾** and select **Education, Publication, Project, Experience, Referee / Reference, Certification, Award, Skills, Bullet List, or Free Text**.
3. Mix any of these types in the same section. Each card shows its type and the relevant fields; empty optional fields are omitted from the PDF.

Publication entries accept bare DOIs or links. References support email and phone links. Rich fields support combined bold/italic, labelled links, and clear formatting. Drag card headers or use the **…** menu to reorder, duplicate, or remove entries. Existing untyped custom entries retain their original title/details/content/bullets form.

Double-click a section name to rename it; drag the row to reorder it. **Right-click a category → Show on CV** toggles its visibility: a checkmark means it is included. Hidden categories remain editable in the sidebar and retain all their content; toggling the option again restores them to preview/export. Section titles, visibility, entry types, and order are saved in JSON. Built-in categories retain their existing forms. Contact and Design are fixed navigation pages, not hideable document categories.

### Side-by-side entries

Each custom section has a **PDF layout** selector above its entries:

- **Automatic** pairs consecutive short entries of the same type: references, certifications, awards, skills, or education. For example, two referees appear side by side, with a subtle divider. The Minimal / ATS-friendly template stays single-column in this mode.
- **Single column** keeps every entry full-width.
- **Two columns** requests pairs of neighbouring entries, including projects, publications, and other types. This explicitly overrides the ATS template's single-column default for that section.

Pairs are measured against the actual space available in the chosen template. Long entries, narrow columns, or pairs that would waste vertical space fall back to a full-width stack. An unpaired final entry uses the full width. Reading order remains left-to-right, then top-to-bottom, following the editor's existing order; entries are never regrouped across other content. This controls PDF preview/export, not the editor card layout. The setting is saved with the section, and links and double-click navigation work in either column.

## Editing and export

- **Ctrl+B / Ctrl+I / Ctrl+K**: bold, italic, and links in rich-text fields.
- **Ctrl+N / Ctrl+0**: create a new CV and fit the preview to the page.
- **Ctrl+S / Ctrl+Shift+S / Ctrl+O**: save, save as, and open CV data.
- **Profile** shows a live summary word count. The editor and preview keep usable minimum widths when resizing the window; photo controls also fit compact windows.
- **Ctrl+E**: export PDF. Double-click preview text to reveal its editor field; double-click a section heading to rename it directly in the sidebar.
- **Design → Workspace → Interface style**: New CVs open in Dark mode with Minimal style, using flat controls, neutral surfaces, and quiet section buttons. Select Vibrant for the previous colourful, raised design. Older documents saved with the name Original open as Vibrant. Sidebar categories no longer show hover popups.
- **Design → Workspace → Button theme** appears only with Vibrant selected: Ocean, Teal, Forest, Violet, Rose, or Graphite. These colours work in light and dark mode, update immediately without recreating editors or rebuilding the PDF, and are saved as `settings.ui_theme`. Minimal keeps neutral controls regardless of this saved setting.
- **Design** also contains PDF layout, PDF colour theme, text scale, margins, and AutoFit. The PDF colour theme, document layout and workspace button theme are independent. Section management lives in the sidebar, not a duplicate Design panel.
- **Creative / Photo CV**: upload PNG/JPEG, crop/zoom/reposition, replace, or remove a portrait. Images and crop settings are embedded in JSON, not saved as machine-specific source paths.

The application can be launched from any working directory. Save/open/export locations are chosen through file dialogs; JSON files can be moved to another computer. JSON saves and PDF exports replace the destination only after the new file is written successfully. Legacy CV JSON files remain readable, including highlights stored as multiline text. Invalid file shapes are reported before replacing your open CV; empty fields and unsupported design settings are normalized. Keep private CV data outside the source repository; the included ignore rules cover PDF exports and files named `my_cv*.json`, not every possible JSON filename.

## Tests

Use the virtual environment's Python for these commands:

```sh
python -m unittest discover -s tests -v
python tests/test_entries.py --gui
python tests/test_entry_layouts.py --gui
python tests/test_appearance.py --gui
python tests/test_workflows.py --gui
```

The unit suite checks mixed-entry migration, compact layout geometry, ordering, all PDF layouts, long content, links, source locations, theme text contrast, PDF independence from workspace colours, and a relocated copy with bundled fonts. The optional GUI suites open a window to check themes, sidebar visibility, pickers, fields, focus, rich text, reordering, two-column preview navigation, save/reopen, and export. Add `--screenshots` to write review images into the ignored `test_artifacts/` directory.

The native GUI has been exercised on Windows. Paths and platform-specific operations are portable, but native macOS/Linux GUI testing is still recommended; those operating systems have not been validated in this workspace.
