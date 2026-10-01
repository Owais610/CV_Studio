# CV Studio

A structured desktop CV editor for creating, maintaining, and exporting polished CVs without fighting document formatting.

CV Studio separates your **content** from your **layout**, so you can update your experience, projects, education, or skills without breaking the design of the document.

Built with Python, Tkinter, ReportLab, and PyMuPDF.

---

## Why CV Studio?

Editing CVs in Word or Canva can become frustrating very quickly.

A small content change can:

- push sections onto another page
- break spacing or alignment
- move headings unexpectedly
- make older versions difficult to maintain
- require repeated manual formatting

CV Studio approaches the problem differently.

Your CV content is stored as structured data, while the application handles layout, formatting, previewing, and PDF generation.

Update the content once. Let the renderer handle the document.

---

## Features

### Structured CV Editing

Edit your CV through dedicated sections for:

- Contact information
- Profile
- Projects and achievements
- Skills
- Experience
- Education
- Custom sections

Sections can be reordered, renamed, hidden, and managed independently.

### Live PDF Preview

See the generated CV while you edit.

The preview supports:

- live PDF rendering
- zoom controls
- page fitting
- scrolling
- clickable source regions for editing
- automatic layout refresh

PyMuPDF is used for the live preview pane. :chatgpt-content-reference{index="3"}

### Rich Text Editing

CV Studio includes lightweight rich-text formatting.

Supported formatting includes:

- **Bold**
- *Italic*
- ***Bold + Italic***
- Hyperlinks
- Automatic URL detection

Keyboard shortcuts include:

- `Ctrl+B` — Bold
- `Ctrl+I` — Italic
- `Ctrl+K` — Link

Existing Markdown-style CV data remains compatible. :chatgpt-content-reference{index="4"}

### Multiple CV Templates

CV Studio currently includes:

- Modern Professional
- Minimal / ATS-friendly
- Executive
- Two-Column
- Academic / Research
- Creative / Photo CV

Templates control presentation while keeping the underlying CV content unchanged. :chatgpt-content-reference{index="5"}

### Photo CV Support

The photo editor supports:

- PNG and JPEG images
- drag-to-position cropping
- zoom control
- keyboard nudging
- non-destructive crop settings
- circular and rectangular presentation depending on template

:chatgpt-content-reference{index="6"}

### Drag and Drop Reordering

Sections and supported content cards can be reordered interactively.

The reorder system preserves editable widgets and commits changes only after the drop operation. :chatgpt-content-reference{index="7"}

### Light and Dark Interface

CV Studio includes both light and dark workspace themes with consistent styling for:

- buttons
- fields
- scrollbars
- panels
- navigation
- focus and hover states

The application UI theme does not affect the colors of the generated PDF. :chatgpt-content-reference{index="8"}

### Custom Sections

Additional CV sections can be created without modifying the application source.

Custom sections use stable internal identifiers, allowing their titles and content to be changed independently. :chatgpt-content-reference{index="9"}

---


## Requirements

- Python 3
- ReportLab
- PyMuPDF
- Pillow

Install the dependencies with:

```bash
pip install reportlab pymupdf Pillow
