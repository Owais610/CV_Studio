"""Flow based PDF templates shared by the two CV Studio editions.

The existing CVBuilder owns text conversion, styles, links and source regions.
Templates only decide how those same flowables are arranged and styled.
"""
import io
import re
from dataclasses import dataclass, replace

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import Flowable, HRFlowable, Image, SimpleDocTemplate, Spacer, Table, TableStyle

from cv_studio_pdf import SourceParagraph
from cv_studio_richtext import plain, parse, serialize, normalize_url
from cv_studio_sections import ENTRY_TYPES, entry_type, entry_layout
from cv_studio_photo import crop_image, decode_photo


@dataclass(frozen=True)
class Template:
    name: str
    description: str
    layout: str = 'classic'
    side_margin: int = 17
    gap: int = 5
    photo: bool = False


TEMPLATES = {
    t.name: t for t in (
        Template('Modern Professional', 'Original CV Studio layout.'),
        Template('Minimal / ATS-friendly', 'Quiet monochrome typography, fine rules and a clear single reading column.',
                 layout='minimal',side_margin=19,gap=7),
        Template('Executive', 'A confident colour masthead, editorial section labels and structured experience.',
                 layout='executive',side_margin=17,gap=8),
        Template('Two-Column', 'A numbered section rail, delicate separators and a generous main column.',
                 layout='rail',side_margin=13,gap=6),
        Template('Academic / Research', 'Serif typography, a centered masthead and numbered research entries.',
                 layout='academic',side_margin=18,gap=7),
        Template('Creative / Photo CV', 'A tailored portrait sidebar, timeline details and bold typographic hierarchy.',
                 layout='photo_rail',side_margin=12,gap=7,photo=True),
    )
}
DEFAULT_TEMPLATE = 'Modern Professional'


def polish_classic_styles(styles, scale):
    """Keep the original layout while refining its spacing and section hierarchy."""
    for key, after in (('name',3),('role',3),('contact',2)):
        styles[key].spaceAfter = after*scale
    styles['section'].spaceBefore = 10*scale
    styles['section'].spaceAfter = 7*scale
    styles['section'].keepWithNext = True
    return styles


class RuledHeading(SourceParagraph):
    """A rule follows the text without putting it inside a rigid table."""
    def __init__(self,*args,rule_color=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.rule_color = rule_color

    def draw(self):
        super().draw()
        if getattr(self,'rule_color',None):
            self.canv.saveState()
            self.canv.setStrokeColor(colors.HexColor(self.rule_color))
            self.canv.setLineWidth(.7)
            self.canv.line(0,-3,self.width,-3)
            self.canv.restoreState()


class TimelineParagraph(SourceParagraph):
    """Decoration follows paragraph fragments instead of absolute text positions."""
    def draw(self):
        super().draw()
        self.canv.saveState()
        self.canv.setStrokeColor(self.style.textColor)
        self.canv.setLineWidth(.55)
        self.canv.line(-9,-self.getSpaceAfter(),-9,self.height+2)
        if getattr(self,'timeline_dot',False):
            self.canv.setFillColor(colors.white)
            self.canv.circle(-9,self.height-self.style.leading/2,2.4,stroke=1,fill=1)
        self.canv.restoreState()


class Monogram(Flowable):
    """An intentional identity mark when the optional portrait is absent."""
    def __init__(self,name,builder):
        super().__init__()
        self.width=self.height=20*mm
        self.name=''.join(word[0] for word in name.split()[:2]).upper()
        self.color=builder.C['blue']

    def draw(self):
        self.canv.setStrokeColor(colors.Color(1,1,1,.5))
        self.canv.setLineWidth(.8)
        self.canv.circle(self.width/2,self.height/2,self.width/2-1,fill=0,stroke=1)
        self.canv.setFillColor(colors.white)
        self.canv.setFont('CV-Bold',18)
        self.canv.drawCentredString(self.width/2,self.height/2-6,self.name)


def _portrait(encoded, circle=False, size=31, crop=None):
    """Use an embedded image; crop without stretching either axis."""
    if not encoded:
        return None
    try:
        image = crop_image(decode_photo(encoded),crop,size=900,circle=circle)
        output = io.BytesIO()
        image.save(output,format='PNG' if circle else 'JPEG')
        output.seek(0)
        return Image(output, width=size*mm, height=size*mm, mask='auto')
    except (ValueError, OSError, ImportError):
        return None


def _styles(builder, template):
    s, k, t = builder.S, builder.k, builder.t
    mode = template.layout
    name_size = {'minimal':27,'executive':28,'rail':28,'academic':26,'photo_rail':29}.get(mode,22)
    heading_size = {'minimal':9.5,'executive':10.5,'rail':9.3,'academic':10,'photo_rail':9.8}.get(mode,10)
    heading_color = t['text'] if mode=='minimal' else t['navy']
    s['name'] = ParagraphStyle('template_name', parent=s['name'], fontSize=name_size*k,
                               leading=(name_size+3)*k,
                               textColor=colors.HexColor(t['text']) if mode in ('minimal','academic') else colors.HexColor(t['navy']),
                               alignment=TA_CENTER if mode=='academic' else TA_LEFT,
                               spaceAfter=6*k)
    s['role'] = ParagraphStyle('template_role', parent=s['role'],
                               alignment=TA_CENTER if mode=='academic' else TA_LEFT,
                               spaceAfter=8*k, fontSize=(10 if mode=='minimal' else 11.5)*k)
    s['contact'] = ParagraphStyle('template_contact', parent=s['contact'],
                                  alignment=TA_CENTER if mode=='academic' else TA_LEFT)
    s['section'] = ParagraphStyle('template_section', parent=s['section'],
                                   fontSize=heading_size*k, leading=(heading_size+3)*k,
                                   textColor=colors.HexColor(heading_color),
                                   spaceBefore=14*k, spaceAfter=9*k, keepWithNext=1)
    for key in ('body','small','bullet','skilltext'):
        s[key] = ParagraphStyle(mode+'_'+key,parent=s[key],alignment=TA_LEFT,
                                fontSize=(8.6 if key in ('body','bullet') else 8.2)*k,
                                leading=(12.2 if key in ('body','bullet') else 11.6)*k,
                                spaceAfter=3*k)
    for key in ('project','edu'):
        s[key] = ParagraphStyle(mode+'_'+key,parent=s[key],fontSize=10*k,leading=13*k,spaceAfter=3*k)
    for key in ('meta','edumeta'):
        s[key] = ParagraphStyle(mode+'_'+key,parent=s[key],fontName='CV',leading=11*k,spaceAfter=4*k)
    s['skillhead'] = ParagraphStyle(mode+'_skillhead',parent=s['skillhead'],fontSize=8.5*k,leading=11*k,spaceAfter=3*k)
    if mode=='minimal':
        ink = colors.HexColor('#24272C')
        for key in ('role','contact','section','project','meta','skillhead','skilltext','edumeta','distinction'):
            s[key] = ParagraphStyle('minimal_'+key,parent=s[key],textColor=ink)
    elif mode=='academic':
        for key in ('name','body','small','bullet','project','edu','skilltext','distinction'):
            bold = key in ('name','project','edu','distinction')
            s[key] = ParagraphStyle('academic_'+key,parent=s[key],fontName='Times-Bold' if bold else 'Times-Roman')
        s['body'] = ParagraphStyle('academic_body',parent=s['body'],fontSize=10*k,leading=14*k)
        s['small'] = ParagraphStyle('academic_small',parent=s['small'],fontSize=9.4*k,leading=13*k)
        s['bullet'] = ParagraphStyle('academic_bullet',parent=s['bullet'],fontSize=9.4*k,leading=13*k)
        s['meta'] = ParagraphStyle('academic_meta',parent=s['meta'],fontName='Times-Italic',fontSize=9*k,leading=12*k)


def _header(builder, template, intro=None):
    d, s, regions = builder.d, builder.S, builder.source_regions
    mode = template.layout
    header = []
    name = d['personal']['name'].strip()
    if name:
        header.append(SourceParagraph(builder.esc(builder.clean_glyphs(name)), s['name'],
                                      source=('personal','name'), regions=regions))
    role = d['personal']['role'].strip()
    if role:
        header.append(SourceParagraph(builder.esc(builder.clean_glyphs(role)), s['role'],
                                      source=('personal','role'), regions=regions))
    contact = builder.contact_line()
    if mode in ('photo_rail','rail'):
        if intro:
            header.extend(_section(builder,'profile',intro['title'],template))
        rail_width = 45*mm if mode=='photo_rail' else 34*mm
        page_width = A4[0]-2*template.side_margin*mm-12
        side_style = ParagraphStyle('side_contact',parent=s['contact'],
                 fontSize=7.5*builder.k,leading=11*builder.k,spaceAfter=7*builder.k,
                 textColor=colors.white if mode=='photo_rail' else colors.HexColor(builder.t['text']))
        side = []
        if mode=='photo_rail':
            portrait = _portrait(d['settings'].get('photo',''),circle=True,size=34,
                                  crop=d['settings'].get('photo_crop'))
            if portrait:
                side.extend([portrait,Spacer(1,15*builder.k)])
            elif name:
                side.extend([Monogram(name,builder),Spacer(1,15*builder.k)])
        if mode=='rail':
            side.append(SourceParagraph('CONTACT',ParagraphStyle('contact_label',parent=s['skillhead'],
                                          spaceAfter=8*builder.k),source=('contacts',),regions=regions))
        if contact:
            for piece in contact.split(' &nbsp;&nbsp;·&nbsp;&nbsp; '):
                if mode=='photo_rail':
                    piece = piece.replace(builder.t['mid'],'#FFFFFF')
                side.append(SourceParagraph(piece,side_style,source=('contacts',),regions=regions))
        if not side:
            side = [Spacer(1,1)]
        table = Table([[side,header or Spacer(1,1)]],
                      colWidths=[rail_width,page_width-rail_width],splitInRow=1)
        table.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('BACKGROUND',(0,0),(0,0),colors.HexColor(builder.t['navy'] if mode=='photo_rail' else builder.t['light'])),
            ('LEFTPADDING',(0,0),(0,0),10),('RIGHTPADDING',(0,0),(0,0),8),
            ('LEFTPADDING',(1,0),(1,0),21),('RIGHTPADDING',(1,0),(1,0),3),
            ('TOPPADDING',(0,0),(-1,-1),12),('BOTTOMPADDING',(0,0),(-1,-1),10),
        ]))
        return [table, builder.sp(12)]
    contact_para = None
    if contact:
        contact_markup = contact.replace(builder.t['mid'],'#FFFFFF') if mode=='executive' else contact
        contact_style = (ParagraphStyle('banner_contact',parent=s['contact'],
                         textColor=colors.white,fontSize=7.8*builder.k,leading=11*builder.k)
                         if mode=='executive' else s['contact'])
        contact_para = SourceParagraph(contact_markup,contact_style,source=('contacts',),regions=regions)
    if mode=='executive':
        left_style = ParagraphStyle('banner_name',parent=s['name'],textColor=colors.white)
        role_style = ParagraphStyle('banner_role',parent=s['role'],textColor=colors.white)
        left = []
        if name:
            left.append(SourceParagraph(builder.esc(builder.clean_glyphs(name)),left_style,
                                        source=('personal','name'),regions=regions))
        if d['personal']['role'].strip():
            left.append(SourceParagraph(builder.esc(builder.clean_glyphs(d['personal']['role'])),role_style,
                                        source=('personal','role'),regions=regions))
        usable = A4[0]-2*template.side_margin*mm-12
        table = Table([[left or Spacer(1,1), contact_para or Spacer(1,1)]],
                      colWidths=[usable*.62,usable*.38],splitInRow=1)
        table.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,-1),colors.HexColor(builder.t['navy'])),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('LEFTPADDING',(0,0),(-1,-1),13),('RIGHTPADDING',(0,0),(-1,-1),12),
            ('TOPPADDING',(0,0),(-1,-1),16),('BOTTOMPADDING',(0,0),(-1,-1),15),
        ]))
        return [table,builder.sp(12)]
    if contact_para:
        header.append(contact_para)
    header.append(builder.sp(7))
    header.append(HRFlowable(width='100%',thickness=.65 if mode=='minimal' else 1,
                            color=colors.HexColor('#555B65' if mode=='minimal' else builder.t['navy'])))
    return header+[builder.sp(4)]


def _heading(builder,key,title,template):
    if template.layout in ('minimal','executive','academic'):
        return RuledHeading(builder.esc(builder.clean_glyphs(title)),builder.S['section'],
                             source=('section',key),regions=builder.source_regions,
                             rule_color=builder.t['blue'] if template.layout=='executive' else '#CCD0D6')
    return builder.heading(title,key)


def _entry_link(value, mode):
    """Link bare DOI/email/website fields without losing visual formatting."""
    text, attrs = parse(value)
    label = text.strip()
    if not label or any(a.link or a.no_link for a in attrs):
        return value
    target = ''
    doi = re.fullmatch(r'(?:doi:\s*)?(10\.\d{4,9}/\S+)', label, re.I)
    if mode == 'phone':
        number = re.sub(r'[^\d+]', '', label)
        if re.fullmatch(r'[+\d() .-]+', label) and len(re.sub(r'\D','',number)) >= 5:
            target = 'tel:' + number
    elif doi:
        target = 'https://doi.org/' + doi.group(1)
    elif re.fullmatch(r'[^\s<>]+\.[^\s<>]+', label):
        target = normalize_url(label)
    return serialize(text, [replace(a, link=target) for a in attrs]) if target else value


class CompactEntryPair(Flowable):
    """Two source-aware entries measured against the actual containing column.

    Short pairs stay together; long/narrow pairs fall back to a splittable,
    full-width stack. Neither text nor PDF links are flattened into images.
    """
    def __init__(self, left, right, builder):
        super().__init__()
        self.entries = (left, right)
        self.gutter = 20 * builder.k
        self.min_column = 46 * mm * builder.k
        page_height = A4[1] - 2 * builder.d['settings']['margin_mm'] * mm - 12
        self.max_height = min(190 * builder.k, page_height * .28)
        self.color = builder.C['line']
        self.gap = 7 * builder.af
        self.table = None

    @staticmethod
    def _plain_table(rows, widths, split=True):
        table = Table(rows, colWidths=widths, hAlign='LEFT', splitInRow=int(split))
        table.setStyle(TableStyle([
            ('VALIGN',(0,0),(-1,-1),'TOP'),
            ('LEFTPADDING',(0,0),(-1,-1),0),('RIGHTPADDING',(0,0),(-1,-1),0),
            ('TOPPADDING',(0,0),(-1,-1),0),('BOTTOMPADDING',(0,0),(-1,-1),0),
        ]))
        return table

    def wrap(self, availWidth, availHeight):
        # Table cells may measure/split their contents without a bound canvas.
        canvas = getattr(self,'canv',None)
        column = (availWidth-self.gutter)/2
        compact = column >= self.min_column
        if compact:
            heights = [self._plain_table([[entry]], [column]).wrapOn(canvas,column,1e6)[1]
                       for entry in self.entries]
            # Do not create tall, cramped columns, or pairs that cost more
            # height than simply stacking their original full-width content.
            full_heights = [self._plain_table([[entry]], [availWidth]).wrapOn(canvas,availWidth,1e6)[1]
                            for entry in self.entries]
            compact = max(heights) <= self.max_height and max(heights) < sum(full_heights)+self.gap
        if compact:
            self.table = self._plain_table([[self.entries[0],self.entries[1]]], [availWidth/2]*2, split=False)
            self.table.setStyle(TableStyle([
                ('RIGHTPADDING',(0,0),(0,0),self.gutter/2),
                ('LEFTPADDING',(1,0),(1,0),self.gutter/2),
                ('LINEAFTER',(0,0),(0,0),.35,self.color),
            ]))
        else:
            self.table = self._plain_table([[entry] for entry in self.entries], [availWidth])
            self.table.setStyle(TableStyle([('BOTTOMPADDING',(0,0),(0,0),self.gap)]))
        self.width, self.height = self.table.wrapOn(canvas,availWidth,availHeight)
        return self.width, self.height

    def split(self, availWidth, availHeight):
        # ReportLab's parent Table passes its unpadded cell width to split(),
        # after wrapping at the narrower content width. Keep that measured
        # width, or continuation tables would expand into the right gutter.
        if self.table is not None:
            availWidth = min(availWidth,self.width)
        self.wrap(availWidth,availHeight)
        return self.table.splitOn(getattr(self,'canv',None),availWidth,availHeight)

    def draw(self):
        self.table.drawOn(self.canv,0,0)


def custom_section(builder, key, title, template=None):
    """Shared flowing custom content for both classic and alternate layouts."""
    entries = []
    for i, item in enumerate(builder.d.get('custom_sections', {}).get(key, [])):
        spec = ENTRY_TYPES[entry_type(item)]
        paragraphs, identities = [], []
        for field in spec.fields:
            value = item.get(field.key) or ([] if field.mode=='bullets' else '')
            if field.mode in ('link','phone'):
                value = _entry_link(value, field.mode)
            lines = value if field.mode=='bullets' else value.splitlines() if field.mode=='paragraphs' else [value]
            for n, line in enumerate(lines):
                if not plain(line).strip():
                    continue
                source = (key, i, field.key) + ((n,) if field.mode in ('paragraphs','bullets') else ())
                prefix = field.prefix if field.mode!='paragraphs' or n==0 else ''
                paragraphs.append(builder.para(line, builder.S[field.style], source=source, prefix=prefix))
                identities.append(field.mode not in ('paragraphs','bullets'))
        if not paragraphs:
            continue
        for paragraph, identity in zip(paragraphs[:-1], identities):
            if not identity or len(paragraph.getPlainText()) >= 220:
                break
            paragraph.keepWithNext = True
        paragraphs[-1].keepWithNext = False
        entries.append((entry_type(item), paragraphs))
    if not entries:
        return []
    section = next((s for s in builder.d['settings']['sections'] if s['key']==key), {})
    layout = entry_layout(section.get('entry_layout'))
    if layout=='auto' and template and template.layout=='minimal':
        layout = 'single'
    out = [_heading(builder, key, title, template) if template else builder.heading(title, key)]
    index = 0
    while index < len(entries):
        kind, paragraphs = entries[index]
        pair = index+1 < len(entries) and (layout=='columns' or
                (layout=='auto' and ENTRY_TYPES[kind].compact and entries[index+1][0]==kind))
        if pair:
            out.append(CompactEntryPair(paragraphs,entries[index+1][1],builder))
            index += 2
        else:
            out.extend(paragraphs)
            index += 1
        out.append(builder.sp(template.gap if template else 6))
    return out


def _section(builder, key, title, template):
    """Paragraph based sections split safely between pages and narrow columns."""
    d, s = builder.d, builder.S
    if key in d.get('custom_sections', {}):
        return custom_section(builder, key, title, template)
    out = []
    heading = _heading(builder,key,title,template)
    def begin():
        if not out:
            out.append(heading)
    def add(text, style, source, prefix=''):
        if str(text or '').strip():
            paragraph = builder.para(text, style, prefix=prefix, source=source)
            if template.layout=='photo_rail' and key in ('experience','education'):
                paragraph.__class__ = TimelineParagraph
                paragraph.timeline_dot = source[-1] in ('title','degree')
            out.append(paragraph)
    def finish_entry(start, gap=None):
        # Keep short identity lines with the first content line. Never lock an
        # entire user entry in a table/KeepTogether: long entries must split.
        for p in out[start:-1]:
            if isinstance(p,SourceParagraph) and p.source and p.source[-1] in ('items','coursework'):
                break
            if isinstance(p,SourceParagraph) and p.source and any(k in p.source for k in ('bullets','description')):
                break
            if isinstance(p,SourceParagraph) and len(p.getPlainText())<220:
                p.keepWithNext = True
            else:
                break
        if out[start:]:
            out[-1].keepWithNext = False
        out.append(builder.sp(template.gap if gap is None else gap))
    if key == 'profile':
        if plain(d['profile']).strip():
            begin()
            add(d['profile'], s['body'], ('profile',))
    elif key == 'projects':
        for i, item in enumerate(d['projects']):
            if not any(plain(str(v)).strip() for v in (item['title'], item['meta'], *item['bullets'])):
                continue
            begin()
            start = len(out)
            add(item['title'], s['project'], ('projects',i,'title'),
                prefix=f'{i+1:02d}   ' if template.layout=='academic' else '')
            add(item['meta'], s['meta'], ('projects',i,'meta'))
            for n, line in enumerate(item['bullets']):
                add(line, s['bullet'], ('projects',i,'bullets',n), prefix='• ')
            finish_entry(start)
    elif key == 'skills':
        for i, item in enumerate(d['skills']):
            if not (plain(item['category']).strip() or plain(item['items']).strip()):
                continue
            begin()
            start = len(out)
            add(item['category'], s['skillhead'], ('skills',i,'category'))
            add(item['items'], s['skilltext'], ('skills',i,'items'))
            finish_entry(start,5)
    elif key == 'experience':
        for i, item in enumerate(d['experience']):
            if not any(plain(item[k]).strip() for k in ('title','company','dates','description')):
                continue
            begin()
            start = len(out)
            for k, style in (('title','project'),('company','meta'),('dates','meta')):
                add(item[k], s[style], ('experience',i,k))
            for n,line in enumerate(item['description'].splitlines()):
                add(line, s['small'], ('experience',i,'description',n))
            finish_entry(start)
    elif key == 'education':
        for i, item in enumerate(d['education']):
            if not any(plain(str(v)).strip() for v in item.values()):
                continue
            begin()
            start = len(out)
            for k,style in (('degree','edu'),('institution','edumeta'),('dates','edumeta'),
                            ('gpa','distinction'),('distinction','distinction'),('coursework','small')):
                add(item[k], s[style], ('education',i,k))
            finish_entry(start)
    return out


def build(builder, target, template_name):
    """Assemble a selected layout from the same source-aware paragraph helpers."""
    template = TEMPLATES.get(template_name, TEMPLATES[DEFAULT_TEMPLATE])
    _styles(builder, template)
    d, st = builder.d, builder.d['settings']
    margin = st['margin_mm']*mm
    side = template.side_margin*mm
    name = d['personal']['name'].strip()
    meta = dict(pagesize=A4, title=f'{name.title()} - Curriculum Vitae' if name else 'Curriculum Vitae',
                author=name.title(), subject='Curriculum Vitae', creator='CV Studio')
    def decorate(canvas, doc):
        canvas.saveState()
        if template.layout=='photo_rail':
            canvas.setFillColor(colors.HexColor(builder.t['navy']))
            canvas.rect(0,0,side+45*mm+6,A4[1],stroke=0,fill=1)
        elif template.layout=='rail':
            canvas.setFillColor(colors.HexColor(builder.t['light']))
            canvas.rect(side,margin,34*mm+6,A4[1]-2*margin,stroke=0,fill=1)
            canvas.setStrokeColor(colors.HexColor(builder.t['line']))
            canvas.setLineWidth(.6)
            canvas.line(side+34*mm+6,margin,side+34*mm+6,A4[1]-margin)
        elif template.layout=='executive':
            canvas.setFillColor(colors.HexColor(builder.t['blue']))
            canvas.rect(side+6,A4[1]-margin+3*mm,A4[0]-2*side-12,1.3*mm,stroke=0,fill=1)
        if template.layout=='academic':
            canvas.setStrokeColor(colors.HexColor(builder.t['line']))
            canvas.line(side,margin-5*mm,A4[0]-side,margin-5*mm)
        if doc.page>1 or template.layout=='academic':
            canvas.setFont('CV',6.5*builder.k)
            canvas.setFillColor(colors.HexColor(builder.t['mid']))
            canvas.drawRightString(A4[0]-side,max(7,margin-9*mm),str(doc.page))
        canvas.restoreState()
    doc = SimpleDocTemplate(target, leftMargin=side, rightMargin=side,
                            topMargin=margin, bottomMargin=margin, **meta)
    visible_sections = [section for section in st['sections'] if section.get('visible',True)]
    intro = (visible_sections[0] if visible_sections and visible_sections[0]['key']=='profile'
             and plain(d['profile']).strip() and template.layout in ('rail','photo_rail') else None)
    story = _header(builder, template, intro)
    rail = template.layout in ('rail','photo_rail','executive')
    page_width = A4[0]-2*side-12
    rail_width = (45 if template.layout=='photo_rail' else 34 if template.layout=='rail' else 32)*mm
    rail_style = ParagraphStyle('rail_heading',parent=builder.S['section'],
                     fontSize=(9.5 if template.layout=='photo_rail' else 9.1)*builder.k,
                     leading=13*builder.k,spaceBefore=0,spaceAfter=7*builder.k,
                     textColor=colors.white if template.layout=='photo_rail'
                                             else colors.HexColor(builder.t['navy'])) if rail else None
    section_number = 0
    for sec in st['sections']:
        if not sec.get('visible',True):
            continue
        if intro is sec:
            continue
        title = sec['title'].strip()
        flows = _section(builder,sec['key'],title,template)
        if not flows:
            continue
        section_number += 1
        if rail:
            longest = max((stringWidth(word,rail_style.fontName,rail_style.fontSize) for word in title.split()),default=1)
            available = rail_width-(8 if template.layout=='executive' else 18)
            label_style = ParagraphStyle('fitted_rail_label',parent=rail_style,
                fontSize=max(7*builder.k,rail_style.fontSize*min(1,available/max(1,longest))))
            label = RuledHeading(builder.esc(builder.clean_glyphs(title)),label_style,
                                    rule_color=builder.t['line'] if template.layout=='photo_rail' else None,
                                    source=('section',sec['key']),regions=builder.source_regions)
            labels = [label]
            if template.layout=='rail':
                number_style = ParagraphStyle('section_number',parent=rail_style,fontName='CV',
                                               fontSize=8*builder.k,textColor=builder.C['mid'])
                labels.insert(0,SourceParagraph(f'{section_number:02d}',number_style))
            table = Table([[labels,flows[1:] or Spacer(1,1)]],
                          colWidths=[rail_width,page_width-rail_width],splitInRow=1)
            table.setStyle(TableStyle([
                ('VALIGN',(0,0),(-1,-1),'TOP'),
                ('LINEABOVE',(0 if template.layout=='executive' else 1,0),(-1,0),
                 .8 if template.layout=='executive' else .4,colors.HexColor(builder.t['blue'] if template.layout=='executive' else builder.t['line'])),
                ('LEFTPADDING',(0,0),(0,0),0 if template.layout=='executive' else 10),('RIGHTPADDING',(0,0),(0,0),8),
                ('LEFTPADDING',(1,0),(1,0),21 if template.layout=='photo_rail' else 16),('RIGHTPADDING',(1,0),(1,0),3),
                ('TOPPADDING',(0,0),(-1,-1),11),('BOTTOMPADDING',(0,0),(-1,-1),10),
            ]))
            story.append(table)
        else:
            story.extend(flows)
    doc.build(story,onFirstPage=decorate,onLaterPages=decorate)
    return doc.page
