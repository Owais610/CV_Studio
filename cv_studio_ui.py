"""Shared desktop interface for the personal and starter editions of CV Studio.

Uses only Tk plus the existing ReportLab/PyMuPDF engine. No UI framework install.
The engine is injected by each launcher; UI appearance never affects PDF colours.
"""
import base64
import io
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import gc
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk, font as tkfont, filedialog, messagebox
import weakref

from cv_studio_richtext import Format, NORMAL, parse, plain, runs, serialize, normalize_url
from cv_studio_templates import DEFAULT_TEMPLATE, TEMPLATES
from cv_studio_reorder import ReorderController, LineHandles, can_scroll_view
from cv_studio_photo import PhotoCropDialog, import_photo, normalize_crop, decode_photo, crop_image
from cv_studio_sections import is_custom, new_section_key, ENTRY_TYPES, ENTRY_CHOICES, entry_type, empty_entry, ENTRY_LAYOUTS, entry_layout
from cv_studio_appearance import (BUTTON_THEMES, DEFAULT_UI_THEME, DEFAULT_UI_MODE, DEFAULT_UI_STYLE, UI_STYLES,
                                  normalize_ui_theme, normalize_ui_style, theme_palette,
                                  minimal_palette, navigation_material)


PALETTES = {
    'Light': dict(bg='#EDF1F6', surface='#FBFCFE', field='#F3F6FA', text='#202B3D',
                  muted='#617087', line='#DEE5EF', hover='#E5EBF4', accent='#3468D4',
                  pressed='#2855B1', tint='#E9EFFC', accent_text='#FFFFFF',
                  canvas='#E7E9ED', shadow='#CDD1D8', thumb='#B6BFCC', good='#23764E',
                  warning='#996016', danger='#B83E46', rail='#E8EEF6',
                  softshadow='#DFE5EF', rim='#FFFFFF', focus_line='#A6BDEB'),
    'Dark': dict(bg='#171A20', surface='#20242C', field='#292E38', text='#EEF0F5',
                 muted='#ADB6C6', line='#363D49', hover='#303744', accent='#8CABFF',
                 pressed='#ABC0FF', tint='#2B3C60', accent_text='#142241',
                 canvas='#12151A', shadow='#080A0D', thumb='#576172', good='#81CBA1',
                 warning='#E5BD77', danger='#FF9FA5', rail='#1C222D',
                 softshadow='#12161E', rim='#38414F', focus_line='#597AB8'),
}
MINIMAL_PALETTES = {
    'Light': dict(bg='#F7F7F5', surface='#FFFFFF', field='#FAFAF9', text='#27272A',
                  muted='#666A70', line='#E4E4E1', hover='#F1F1EF', accent='#27272A',
                  pressed='#3F3F46', tint='#EEEEEB', accent_text='#FFFFFF',
                  canvas='#ECEDEB', shadow='#D5D7D5', thumb='#B9BDBB', good='#24714C',
                  warning='#946318', danger='#A83F45', rail='#F7F7F5',
                  softshadow='#E9EAE8', rim='#FFFFFF', focus_line='#71717A'),
    'Dark': dict(bg='#181818', surface='#202020', field='#262626', text='#F3F3F2',
                 muted='#B3B3B0', line='#363636', hover='#303030', accent='#F3F3F2',
                 pressed='#D8D8D6', tint='#353535', accent_text='#181818',
                 canvas='#141414', shadow='#0B0B0B', thumb='#6B6B69', good='#87CDA4',
                 warning='#E3BC74', danger='#F5A3A5', rail='#1B1B1B',
                 softshadow='#111111', rim='#424242', focus_line='#D0D0CE'),
}
NAVIGATION = [('header', 'Contact', 'Your name, headline, and contact details.'),
              ('profile', 'Profile', 'A concise introduction to your experience and strengths.'),
              ('projects', 'Projects', 'Showcase your work, research, and achievements.'),
              ('skills', 'Skills', 'Organise your expertise into focused categories.'),
              ('experience', 'Experience', 'Tell the story of your professional contribution.'),
              ('education', 'Education', 'Qualifications, distinctions, and relevant study.'),
              ('layout', 'Design', 'Fine-tune your document and your workspace.')]


class Appearance:
    def __init__(self, root):
        self.root, self.mode, self.listeners = root, DEFAULT_UI_MODE, []
        self.theme = DEFAULT_UI_THEME
        self.style = DEFAULT_UI_STYLE
        families = set(tkfont.families(root))
        self.family = next((f for f in ('Segoe UI', 'Inter', 'Helvetica Neue', 'DejaVu Sans') if f in families), 'Arial')
        self.fonts = {}
        for name, size, weight, slant in [('body', 10, 'normal', 'roman'), ('small', 9, 'normal', 'roman'),
                ('label', 9, 'bold', 'roman'), ('title', 21, 'bold', 'roman'), ('heading', 12, 'bold', 'roman'),
                ('bold', 10, 'bold', 'roman'), ('italic', 10, 'normal', 'italic'), ('both', 10, 'bold', 'italic')]:
            self.fonts[name] = tkfont.Font(root=root, family=self.family, size=size, weight=weight, slant=slant)
        self.apply(DEFAULT_UI_MODE)

    def __getitem__(self, key):
        return self.palette[key]

    def watch(self, widget, callback):
        # Bound methods must not retain destroyed cards and their text histories.
        self.listeners.append((weakref.ref(widget), weakref.WeakMethod(callback) if hasattr(callback, '__self__') else callback))
        callback()

    def apply(self, mode, theme=None, style=None):
        self.mode = mode if mode in PALETTES else DEFAULT_UI_MODE
        if theme is not None:
            self.theme = normalize_ui_theme(theme)
        if style is not None:
            self.style = normalize_ui_style(style)
        self.palette = (minimal_palette(MINIMAL_PALETTES[self.mode],self.mode)
                        if self.style == 'Minimal' else
                        theme_palette(PALETTES[self.mode],self.mode,self.theme))
        s = ttk.Style(self.root)
        s.theme_use('clam')
        s.configure('.', background=self['surface'], foreground=self['text'], font=self.fonts['body'])
        s.configure('TEntry', fieldbackground=self['field'], foreground=self['text'], insertcolor=self['text'],
                    padding=8, borderwidth=1, bordercolor=self['line'], lightcolor=self['line'], darkcolor=self['line'])
        s.map('TEntry', bordercolor=[('focus', self['accent'])], lightcolor=[('focus', self['accent'])],
              darkcolor=[('focus', self['accent'])], selectbackground=[('!disabled', self['tint'])],
              selectforeground=[('!disabled', self['text'])])
        s.configure('TPanedwindow', background=self['line'], sashwidth=5)
        for orient in ('Vertical', 'Horizontal'):
            s.layout(orient + '.TScrollbar', [(orient + '.Scrollbar.trough', {'sticky': 'nswe', 'children': [
                (orient + '.Scrollbar.thumb', {'expand': '1', 'sticky': 'nswe'})]})])
            s.configure(orient + '.TScrollbar', background=self['thumb'], troughcolor=self['bg'],
                        bordercolor=self['bg'], lightcolor=self['thumb'], darkcolor=self['thumb'],
                        borderwidth=0, arrowsize=10, width=10, gripcount=0)
            s.map(orient + '.TScrollbar', background=[('active', self['muted']), ('pressed', self['accent'])])
        s.configure('Horizontal.TScale', background=self['surface'], troughcolor=self['line'],
                    borderwidth=0, sliderlength=18, sliderthickness=14)
        self.root.configure(bg=self['bg'])
        keep = []
        for ref, handler in self.listeners:
            widget = ref()
            callback = handler() if isinstance(handler, weakref.WeakMethod) else handler
            if widget is not None and callback and widget.winfo_exists():
                callback()
                keep.append((ref, handler))
        self.listeners = keep


class Frame(tk.Frame):
    def __init__(self, parent, ui, role='surface', **kwargs):
        self.ui, self.role = ui, role
        # Set an explicit normal cursor on content frames.  On Windows/Tk the
        # PanedWindow sash cursor can otherwise appear to remain active after
        # crossing directly from the sash into a child with an inherited cursor.
        kwargs.setdefault('cursor', 'arrow')
        super().__init__(parent, bd=0, **kwargs)
        ui.watch(self, self.retheme)

    def retheme(self):
        self.configure(bg=self.ui[self.role])


class Label(tk.Label):
    def __init__(self, parent, ui, text='', font='body', fg='text', bg='surface', **kwargs):
        self.ui, self.fg_role, self.bg_role = ui, fg, bg
        kwargs.setdefault('anchor', 'w')
        super().__init__(parent, text=text, font=ui.fonts[font], bd=0, **kwargs)
        ui.watch(self, self.retheme)

    def retheme(self):
        self.configure(bg=self.ui[self.bg_role], fg=self.ui[self.fg_role])


def rounded(canvas, x, y, w, h, r, **kwargs):
    points = [x+r,y, x+w-r,y, x+w,y, x+w,y+r, x+w,y+h-r, x+w,y+h,
              x+w-r,y+h, x+r,y+h, x,y+h, x,y+h-r, x,y+r, x,y]
    return canvas.create_polygon(points, smooth=True, splinesteps=20, **kwargs)


class Button(tk.Canvas):
    """Consistent rounded buttons with keyboard focus, selected and disabled states."""
    def __init__(self, parent, ui, text, command, kind='secondary', width=None, compact=False,
                 bg='surface', font='body', anchor='center'):
        self.ui, self.text, self.command, self.kind = ui, text, command, kind
        self.bg_role, self.font, self.anchor = bg, ui.fonts[font], anchor
        self.selected = self.hover = self.pressed = self.focused = False
        self.enabled = True
        height = 30 if compact else 36
        super().__init__(parent, width=width or self.font.measure(text) + 26, height=height,
                         highlightthickness=0, bd=0, takefocus=1, cursor='hand2')
        self.bind('<Configure>', lambda e: self.draw())
        self.bind('<Enter>', lambda e: self._state('hover', True))
        self.bind('<Leave>', lambda e: self._state('hover', False))
        self.bind('<ButtonPress-1>', lambda e: self._state('pressed', True))
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<FocusIn>', lambda e: self._state('focused', True))
        self.bind('<FocusOut>', lambda e: self._state('focused', False))
        self.bind('<space>', lambda e: self.invoke())
        self.bind('<Return>', lambda e: self.invoke())
        ui.watch(self, self.draw)

    def _state(self, name, value):
        setattr(self, name, value)
        self.draw()

    def _release(self, event):
        self.pressed = False
        self.draw()
        if 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height():
            self.invoke()

    def invoke(self):
        if self.enabled:
            self.command()
        return 'break'

    def draw(self):
        p = self.ui
        self.configure(bg=p[self.bg_role])
        self.delete('all')
        w, h = max(self.winfo_width(), int(self.cget('width'))), int(self.cget('height'))
        if p.style == 'Minimal':
            fill, fg = p['button_face'], p['button_ink']
            if self.kind == 'primary':
                fill, fg = (p['pressed'] if self.hover or self.pressed else p['accent']), p['accent_text']
            elif self.selected:
                fill = p['tint']
            elif self.kind in ('ghost', 'nav'):
                fill = p[self.bg_role]
            if self.kind != 'primary' and (self.hover or self.pressed):
                fill = p['tint'] if self.pressed else p['hover']
            if self.kind == 'danger':
                fg = p['danger']
            if not self.enabled:
                fg = p['muted']
            border = (p['focus_line'] if self.focused else
                      p['button_line'] if self.kind == 'secondary' and not self.selected else fill)
            rounded(self, 1, 1, w-2, h-2, 6, fill=fill, outline=border, width=1)
            self.create_text(13 if self.anchor == 'w' else w/2, h/2, text=self.text,
                             fill=fg, font=self.font, anchor=self.anchor)
            if getattr(self,'shortcut',''):
                self.create_text(w-12,h/2,text=self.shortcut,fill=p['muted'],font=p.fonts['small'],anchor='e')
            return
        fill, fg = p['button_face'], p['button_ink']
        if self.kind == 'primary':
            fill, fg = p['accent'], p['accent_text']
            if self.hover or self.pressed:
                fill = p['pressed']
        elif self.selected:
            fill, fg = p['tint'], p['selection_ink']
        elif self.kind in ('ghost', 'nav'):
            fill = p[self.bg_role]
        if self.kind != 'primary' and (self.hover or self.pressed):
            fill = p['tint'] if self.pressed else p['hover']
        if self.kind == 'danger':
            fg = p['danger']
        if not self.enabled:
            fg = p['muted']
        raised = self.kind in ('primary', 'secondary') and not self.pressed
        if raised:
            rounded(self, 1, 3, w-2, h-4, 8, fill=p['softshadow'], outline='')
        border = p['accent'] if self.focused else p['button_line'] if self.kind=='secondary' else fill
        rounded(self, 1, 1, w-2, h-4, 8, fill=fill, outline=border, width=1)
        self.create_text(13 if self.anchor == 'w' else w/2, h/2+(1 if self.pressed else -1), text=self.text,
                         fill=fg, font=self.font, anchor=self.anchor)
        if getattr(self,'shortcut',''):
            self.create_text(w-12,h/2,text=self.shortcut,fill=p['muted'],font=p.fonts['small'],anchor='e')


class NavigationButton(Button):
    """Soft navigation cards. Motion is paint-only, never a moving hit target."""
    MATERIALS = {
        'Light': dict(face='#F1F5FA', hover='#FAFCFF', active='#D9E5F7',
                      edge='#E2E9F3', active_edge='#C3D2E8', shadow='#CED9E8',
                      well='#BDCCE1', rim='#FFFFFF', ink='#264E87'),
        'Dark': dict(face='#272E3A', hover='#323D4C', active='#334867',
                     edge='#303A48', active_edge='#415B7C', shadow='#111823',
                     well='#182433', rim='#465365', ink='#D7E6FF'),
    }

    def __init__(self,*args,**kwargs):
        self.rename_entry=None
        self.reorderable=False
        self._nav_job=None
        self._motion_target=None
        self._motion_value=(0.,0.,0.)
        self._title_layout=None
        super().__init__(*args,**kwargs)
        self.bind('<Map>',lambda e:self.draw(),add='+')
        self.bind('<Unmap>',self.stop_animation,add='+')
        self.bind('<Destroy>',self.stop_animation,add='+')

    @staticmethod
    def blend(first, second, amount):
        amount=max(0.,min(1.,amount))
        return '#'+''.join(f'{round(int(first[i:i+2],16)*(1-amount)+int(second[i:i+2],16)*amount):02x}'
                           for i in (1,3,5))

    @staticmethod
    def shape(canvas,x,y,w,h,radius,**kwargs):
        """Circular corners, rather than the generic control's tighter spline."""
        width,height=w,h
        radius=min(radius,width/2,height/2)
        points=[]
        for cx,cy,start in ((x+width-radius,y+radius,-90),
                            (x+width-radius,y+height-radius,0),
                            (x+radius,y+height-radius,90),(x+radius,y+radius,180)):
            for angle in range(start,start+91,15):
                theta=math.radians(angle)
                points.extend((cx+radius*math.cos(theta),cy+radius*math.sin(theta)))
        return canvas.create_polygon(points,smooth=True,splinesteps=8,**kwargs)

    def stop_animation(self,event=None):
        if event is not None and event.widget is not self:
            return
        if self._nav_job is not None:
            self.ui.root.after_cancel(self._nav_job)
            self._nav_job=None

    def animate(self):
        self._nav_job=None
        self.draw()

    def title_layout(self,width):
        # Measure every state with the stronger font: selection, hover and the
        # drag proxy all keep identical line breaks and row height.
        font=self.ui.fonts['bold']
        available=max(32,width-48)
        cache_key=(self.text,available,font.metrics('linespace'),font.measure('MW'),self.ui.style)
        if self._title_layout and self._title_layout[0]==cache_key:
            return self._title_layout[1]
        lines=[]
        line=''
        for word in self.text.split():
            candidate=(line+word).strip()
            if line and font.measure(candidate)>available:
                lines.append(line)
                line=''
            # Long uninterrupted names/URLs wrap too; never hide them in an ellipsis.
            for char in word:
                if line and font.measure(line+char)>available:
                    lines.append(line)
                    line=''
                line+=char
            line+=' '
        if line.strip():
            lines.append(line.strip())
        lines=[text.rstrip() for text in lines] or ['']
        vertical_padding = 18 if self.ui.style == 'Minimal' else 24
        result=('\n'.join(lines),max(40 if self.ui.style == 'Minimal' else 48,
                                     len(lines)*font.metrics('linespace')+vertical_padding))
        self._title_layout=(cache_key,result)
        return result

    def paint_material(self,canvas,width,height,hover,selected,pressed,focused=False,editing=False,lifted=False):
        p=self.ui
        canvas.delete('all')
        canvas.configure(bg=p[self.bg_role])
        if p.style == 'Minimal':
            face = self.blend(p[self.bg_role],p['hover'],hover)
            face = self.blend(face,p['tint'],max(selected,pressed))
            if editing:
                face = p['tint']
            edge = p['focus_line'] if focused or editing else face
            self.shape(canvas,2,2,width-4,height-4,7,fill=face,outline=edge,
                       width=1,tags='nav_face')
            if self.reorderable and not editing and (hover>.02 or focused or lifted):
                for dx in (0,4):
                    for dy in (-4,0,4):
                        x,cy=width-16+dx,height/2+dy
                        canvas.create_oval(x,cy,x+1,cy+1,fill=p['muted'],outline='',tags='nav_grip')
            return face,2
        m=navigation_material(self.MATERIALS[p.mode],p.palette,p.mode)
        depth=max(selected,pressed)
        face=self.blend(self.blend(m['face'],m['hover'],hover),m['active'],selected)
        if editing:
            face=m['active']
        y=3-1.5*hover*(1-depth)+2*depth
        if lifted:
            y=1
            face=m['hover']
        # A shallow surrounding well is exposed above the selected face. Normal
        # and hovered cards instead carry their shadow below the face.
        if depth>.01 and not lifted:
            self.shape(canvas,2,2,width-4,height-5,12,
                    fill=self.blend(p[self.bg_role],m['well'],depth),outline='',tags='nav_well')
        else:
            self.shape(canvas,3,y+3+(1 if lifted else hover),width-6,height-8,12,
                    fill=self.blend(p[self.bg_role],m['shadow'],.65 if lifted else .35+.3*hover),
                    outline='',tags='nav_shadow')
        edge=m['active_edge'] if editing else self.blend(m['edge'],m['active_edge'],selected)
        self.shape(canvas,2,y,width-4,height-8,12,fill=face,outline=edge,width=1,tags='nav_face')
        canvas.create_line(16,y+1,width-16,y+1,
            fill=self.blend(m['rim'],m['well'],depth*.75),tags='nav_rim')
        if focused or editing:
            self.shape(canvas,2,y,width-4,height-8,12,fill='',outline=p['focus_line'],width=1,tags='nav_focus')
        if selected>.01 or editing:
            self.shape(canvas,10,y+(height-8)/2-9,3,18,2,
                    fill=self.blend(face,p['accent'],1 if editing else selected),outline='',tags='nav_indicator')
        if self.reorderable and not editing and (hover>.02 or focused or lifted):
            color=self.blend(face,p['muted'],.7 if focused or lifted else hover*.7)
            for dx in (0,4):
                for dy in (-4,0,4):
                    x,cy=width-16+dx,y+(height-8)/2+dy
                    canvas.create_oval(x,cy,x+1,cy+1,fill=color,outline='',tags='nav_grip')
        return face,y

    def paint_drag_preview(self,canvas,width):
        title,height=self.title_layout(width)
        self.paint_material(canvas,width,height,1.,0.,0.,lifted=True)
        canvas.create_text(18 if self.ui.style == 'Minimal' else 24,(height-8)/2+1,
                           text=title,anchor='w',justify='left',
                           font=self.ui.fonts['bold'],fill=self.ui['text'],tags='nav_title')
        return width,height

    def draw(self):
        p=self.ui
        if getattr(p.root,'closing',False):
            self.stop_animation()
            return
        width=self.winfo_width() if self.winfo_width()>1 else int(self.cget('width'))
        title,height=self.title_layout(width)
        if int(self.cget('height'))!=height:
            self.configure(height=height)
        editing=bool(self.rename_entry)
        target=(float(self.hover),float(self.selected or editing),float(self.pressed))
        now=time.monotonic()
        if target!=self._motion_target:
            self._motion_from=self._motion_value
            self._motion_target=target
            self._motion_start=now
        progress=min(1.,(now-self._motion_start)/(.08 if self.pressed else .14))
        if editing or not self.winfo_viewable() or getattr(self,'_paint_mode',None)!=(p.mode,p.theme,p.style):
            progress=1.
        self._paint_mode=(p.mode,p.theme,p.style)
        ease=1-(1-progress)**3
        self._motion_value=tuple(start+(end-start)*ease for start,end in zip(self._motion_from,target))
        fill,y=self.paint_material(self,width,height,*self._motion_value,focused=self.focused,editing=editing)
        material=navigation_material(self.MATERIALS[p.mode],p.palette,p.mode)
        fg=p['muted'] if getattr(self,'hidden',False) else (
            p['text'] if p.style == 'Minimal' else material['ink'] if self.selected else p['text'])
        if not editing:
            self.create_text(18 if p.style == 'Minimal' else 24,y+(height-8)/2,
                             text=title,anchor='w',justify='left',
                             font=p.fonts['bold'] if self.selected else self.font,fill=fg,tags='nav_title')
        if self.rename_entry and self.rename_entry.winfo_exists():
            self.rename_entry.configure(bg=fill,fg=p['text'],insertbackground=p['text'],
                selectbackground=p['accent'],selectforeground=p['accent_text'])
        if progress<1 and self._nav_job is None:
            # The application owns/cancels timer commands during shutdown. Use
            # that same owner so a mid-transition close cannot delete a child's
            # registered Tcl callback twice.
            self._nav_job=p.root.after(16,self.animate)
        elif progress>=1:
            self.stop_animation()


class Surface(Frame):
    """Lightweight rounded inset surface; native editable children stay untouched.

    A handful of Canvas shapes emulate a frosted material, without screenshots,
    transparency, blur, or periodic redraws. The backing never takes focus.
    """
    def __init__(self, parent, ui, role='surface', outer='bg', radius=12, shadow=True, **kwargs):
        self.surface_role, self.radius, self.shadow = role, radius, shadow
        self.focused = self.hovered = False
        super().__init__(parent, ui, outer, **kwargs)
        self.backing = tk.Canvas(self, bd=0, highlightthickness=0, takefocus=0, cursor='arrow')
        # Ignore the frame's content padding: the material must extend behind
        # the padded children, all the way to the real outside edges.
        self.backing.place(x=0, y=0, relwidth=1, relheight=1, bordermode='ignore')
        self.backing.tk.call('lower', self.backing._w)
        self.bind('<Configure>', lambda e:self.paint())
        ui.watch(self, self.paint)

    def paint(self):
        p, canvas = self.ui, self.backing
        canvas.configure(bg=p[self.role])
        canvas.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w<8 or h<8:
            return
        if p.style == 'Minimal':
            edge = p['focus_line'] if self.focused else p['line']
            rounded(canvas,1,1,w-2,h-2,8,fill=p[self.surface_role],outline=edge,width=1)
            return
        inset = 4 if self.shadow else 2
        if self.shadow:
            rounded(canvas, 2, 4, w-4, h-5, self.radius, fill=p['softshadow'], outline='')
        edge = p['focus_line'] if self.focused else p['thumb'] if self.hovered else p['line']
        rounded(canvas, 1, 1, w-inset, h-inset, self.radius,
                fill=p[self.surface_role], outline=edge, width=1)
        if self.shadow:
            canvas.create_line(self.radius+2, 2, w-self.radius-3, 2, fill=p['rim'])

    def set_focus(self, focused):
        if self.focused != focused:
            self.focused = focused
            self.paint()


class Tooltip:
    def __init__(self, widget, text):
        self.widget, self.text, self.job, self.window = widget, text, None, None
        self.scheduler=widget.nametowidget('.')
        widget.bind('<Enter>', self.schedule, add='+')
        widget.bind('<Leave>', self.hide, add='+')
        widget.bind('<ButtonPress>', self.hide, add='+')
        widget.bind('<Destroy>', self.hide, add='+')

    def schedule(self, _=None):
        self.hide()
        if not getattr(self.scheduler,'closing',False):
            self.job = self.scheduler.after(650, self.show)

    def show(self):
        self.job = None
        if getattr(self.scheduler,'closing',False) or not self.widget.winfo_viewable():
            return
        self.window = tk.Toplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.attributes('-topmost', True)
        tk.Label(self.window, text=self.text, bg='#242B36', fg='white', padx=10, pady=6,
                 font=self.widget.ui.fonts['small']).pack()
        self.window.update_idletasks()
        x = min(self.widget.winfo_rootx(), self.widget.winfo_screenwidth()-self.window.winfo_reqwidth()-8)
        self.window.geometry(f'+{max(0,x)}+{self.widget.winfo_rooty()+self.widget.winfo_height()+5}')

    def hide(self, _=None):
        if self.job:
            self.scheduler.after_cancel(self.job)
            self.job = None
        if self.window:
            self.window.destroy()
            self.window = None


class PopupMenu(tk.Toplevel):
    """Application-drawn menus so Windows native menu styling cannot override us."""
    def __init__(self, app, anchor, items, *, width=320, compact=False, font='body'):
        if app.popup and app.popup.winfo_exists():
            app.popup.close()
        super().__init__(app)
        self.withdraw()
        self.app, self.anchor, self.previous_focus, self.buttons = app, anchor, app.focus_get(), []
        app.popup = self
        self.overrideredirect(True)
        self.transient(app)
        self.attributes('-topmost', True)
        self.configure(bg=app.ui['bg'])
        body = Surface(self, app.ui, padx=7, pady=8, radius=12)
        body.pack(fill='both', expand=True)
        for item in items:
            if item is None:
                Frame(body, app.ui, 'line', height=1).pack(fill='x', padx=10, pady=5)
                continue
            label, shortcut, fn, *rest = item
            enabled = rest[0] if rest else True
            row = Frame(body, app.ui)
            row.pack(fill='x', padx=5, pady=1)
            b = Button(row, app.ui, label, lambda f=fn: self.choose(f),
                       kind='danger' if label.startswith('Remove ') else 'ghost',
                       width=width, compact=compact, font=font, anchor='w')
            b.pack(fill='x')
            b.enabled = enabled
            b.shortcut = shortcut
            b.draw()
            self.buttons.append(b)
        self.update_idletasks()
        x = min(anchor.winfo_rootx(), app.winfo_screenwidth()-self.winfo_reqwidth()-8)
        y = min(anchor.winfo_rooty()+anchor.winfo_height()+4, app.winfo_screenheight()-self.winfo_reqheight()-8)
        self.geometry(f'{self.winfo_reqwidth()}x{self.winfo_reqheight()}+{max(0,x)}+{max(0,y)}')
        self.deiconify()
        self.lift()
        self.update_idletasks()
        self.bind('<Escape>', lambda e: self.close())
        self.bind('<Down>', lambda e: self.step(1))
        self.bind('<Up>', lambda e: self.step(-1))
        self.bind('<ButtonPress-1>', self.outside, add='+')
        self.bind('<FocusOut>', lambda e: self.app.after(80,self.check_focus))
        # Do not grab the application.  A local grab redirects the first click
        # intended for an editor back to this popup; restoring the old focus on
        # close then makes the editor look frozen.  Let the click reach its real
        # target and close the popup from the root binding instead.
        self._root_click_id = app.bind('<ButtonPress-1>', self.root_click, add='+')
        # The popup is opened by a click in the already-active application.
        # Using focus_force() here can leave Windows/Tk with its keyboard focus
        # attached to this temporary toplevel after it is destroyed.  A normal
        # Tk focus transfer is sufficient and keeps the main editor recoverable.
        self.focus_set()
        if self.buttons:
            self.buttons[0].focus_set()

    def step(self, delta):
        active = self.focus_get()
        i = self.buttons.index(active) if active in self.buttons else 0
        self.buttons[(i+delta) % len(self.buttons)].focus_set()
        return 'break'

    def check_focus(self):
        if self.winfo_exists():
            focus = self.focus_get()
            if focus is None or not str(focus).startswith(str(self)):
                self.close(restore_focus=False)

    def root_click(self, event):
        # Clicks in the main window should close the popup without undoing the
        # focus/caret placement performed by the clicked widget.
        if self.winfo_exists():
            self.close(restore_focus=False)

    def outside(self, event):
        if not (self.winfo_rootx() <= event.x_root < self.winfo_rootx()+self.winfo_width()
                and self.winfo_rooty() <= event.y_root < self.winfo_rooty()+self.winfo_height()):
            self.close(restore_focus=False)

    def choose(self, fn):
        # Do not restore focus to the control that happened to be focused before
        # the popup opened: it may be a Text widget on a page that is now hidden.
        # First destroy the temporary toplevel, run the selection callback, then
        # explicitly return *OS* keyboard focus to the visible main-window anchor.
        # On Windows this prevents focus_get() becoming None after a theme menu.
        anchor = self.anchor
        self.close(restore_focus=False)

        def finish_choice():
            fn()
            if anchor is not None and anchor.winfo_exists() and anchor.winfo_viewable():
                anchor.focus_force()
            elif self.app.winfo_exists():
                self.app.focus_force()

        self.app.after_idle(finish_choice)

    def close(self, restore_focus=True):
        if getattr(self, '_root_click_id', None):
            try:
                self.app.unbind('<ButtonPress-1>', self._root_click_id)
            except tk.TclError:
                pass
            self._root_click_id = None
        if self.winfo_exists():
            # Be defensive if a popup created by an older code path still owns a grab.
            try:
                if self.grab_current() is self:
                    self.grab_release()
            except tk.TclError:
                pass
            self.destroy()
        self.app.popup = None
        if restore_focus and self.previous_focus and self.previous_focus.winfo_exists():
            self.previous_focus.focus_set()


class Choice(Button):
    def __init__(self, parent, app, variable, values, command=None, width=170, *, compact=False, fit_menu=False, font='body'):
        self.app, self.variable, self.values, self.on_change = app, variable, values, command
        self.compact, self.fit_menu = compact, fit_menu
        self.choice_font = font
        if width is None:
            # Fit the longest option once, so changing themes never shifts the control.
            width = max(app.ui.fonts[font].measure(str(v)+'   ▾') for v in values)+26
        super().__init__(parent, app.ui, '', self.open, width=width, compact=compact, font=font, anchor='w')
        self.trace = variable.trace_add('write', self.update_text)
        self.bind('<Destroy>', lambda e: variable.trace_remove('write', self.trace) if e.widget is self else None)
        self.update_text()

    def update_text(self, *_):
        self.text = self.variable.get() + '   ▾'
        self.draw()

    def open(self):
        items = [(('✓  ' if v == self.variable.get() else '    ')+str(v), '',
                  lambda x=v: self.choose(x)) for v in self.values]
        options = {}
        if self.fit_menu:
            # Account for the popup's 24px horizontal padding; keep checkmarks
            # and labels readable without the standard full-width menu.
            row_width = max(self.font.measure('✓  '+str(v))+26 for v in self.values)
            options = dict(width=max(self.winfo_width()-24,row_width),compact=self.compact,font=self.choice_font)
        PopupMenu(self.app, self, items, **options)

    def choose(self, value):
        self.variable.set(value)
        if self.on_change:
            self.on_change()


class ModernScrollbar(tk.Canvas):
    """Quiet rounded thumb; an unnecessary scrollbar draws no track or thumb."""
    def __init__(self,parent,ui,command,orient='vertical',bg='bg'):
        self.ui,self.command,self.orient,self.bg_role = ui,command,orient,bg
        self.first,self.last,self.hover,self.drag = 0.,1.,False,None
        super().__init__(parent,width=12 if orient=='vertical' else 1,
                         height=12 if orient=='horizontal' else 1,bd=0,highlightthickness=0)
        self.bind('<Configure>',lambda e:self.draw())
        self.bind('<Enter>',lambda e:self.over(True))
        self.bind('<Leave>',lambda e:self.over(False))
        self.bind('<Button-1>',self.press)
        self.bind('<B1-Motion>',self.motion)
        self.bind('<ButtonRelease-1>',self.release)
        ui.watch(self,self.draw)

    def set(self,first,last):
        self.first,self.last=float(first),float(last)
        self.draw()

    def over(self,value):
        self.hover=value
        self.draw()

    def dimensions(self):
        length=self.winfo_height() if self.orient=='vertical' else self.winfo_width()
        span=self.last-self.first
        size=max(28,(length-8)*span)
        start=4+(length-8-size)*self.first/max(.0001,1-span)
        return length,size,start

    def draw(self):
        self.configure(bg=self.ui[self.bg_role])
        self.delete('all')
        if self.last-self.first>=.999:
            return
        length,size,start=self.dimensions()
        color=self.ui['muted'] if self.hover or self.drag else self.ui['thumb']
        width=8 if self.hover or self.drag else 5
        if self.orient=='vertical':
            self.create_line(6,start+3,6,start+size-3,width=width,fill=color,capstyle='round')
        else:
            self.create_line(start+3,6,start+size-3,6,width=width,fill=color,capstyle='round')

    def press(self,event):
        position=event.y if self.orient=='vertical' else event.x
        length,size,start=self.dimensions()
        if not start<=position<=start+size:
            self.command('moveto',max(0,min(1,position/max(1,length)-(self.last-self.first)/2)))
        self.drag=(position,self.first)
        self.draw()

    def motion(self,event):
        if self.drag:
            position=event.y if self.orient=='vertical' else event.x
            length,size,start=self.dimensions()
            movement=(position-self.drag[0])/max(1,length-8-size)*(1-self.last+self.first)
            self.command('moveto',max(0,min(1,self.drag[1]+movement)))

    def release(self,event):
        self.drag=None
        self.draw()


class SplitPane(tk.PanedWindow):
    def __init__(self,parent,ui):
        self.ui=ui
        super().__init__(parent,orient='horizontal',bd=0,sashwidth=5,sashpad=0,sashrelief='flat',
                         showhandle=False,opaqueresize=True,sashcursor='sb_h_double_arrow')
        ui.watch(self,self.retheme)

    def retheme(self):
        self.configure(bg=self.ui['line'])

    def add(self,widget,weight=1):
        super().add(widget,stretch='always',padx=0,pady=0)

    def sashpos(self,index,position=None):
        if position is not None:
            self.sash_place(index,int(position),0)
        return self.sash_coord(index)[0]


class SidebarDivider(tk.Canvas):
    """A narrow, keyboard-accessible resize handle with a generous hit area."""
    def __init__(self,parent,app):
        self.app,self.ui,self.drag,self.hover=app,app.ui,None,False
        super().__init__(parent,width=6,bd=0,highlightthickness=0,cursor='sb_h_double_arrow',takefocus=1)
        self.bind('<Configure>',lambda e:self.draw())
        self.bind('<Enter>',lambda e:self.over(True))
        self.bind('<Leave>',lambda e:self.over(False))
        self.bind('<FocusIn>',lambda e:self.draw())
        self.bind('<FocusOut>',lambda e:self.draw())
        self.bind('<ButtonPress-1>',self.start)
        self.bind('<B1-Motion>',self.move)
        self.bind('<ButtonRelease-1>',self.end)
        self.bind('<Left>',lambda e:self.step(-12))
        self.bind('<Right>',lambda e:self.step(12))
        self.bind('<Escape>',self.cancel)
        app.ui.watch(self,self.draw)

    def draw(self):
        self.configure(bg=self.ui['surface'])
        self.delete('all')
        active=self.drag or self.hover or self.focus_get() is self
        self.create_line(3,0,3,self.winfo_height(),width=2 if active else 1,
                         fill=self.ui['accent'] if active else self.ui['line'])

    def over(self,value):
        self.hover=value
        self.draw()

    def start(self,event):
        if getattr(self.app,'active_drag',None):
            self.app.active_drag.cancel()
        self.app.finish_section_rename()
        self.focus_set()
        self.drag=(event.x_root,self.app.sidebar.winfo_width(),self.app.sidebar_width)
        self.grab_set()
        self.draw()
        return 'break'

    def move(self,event):
        if self.drag:
            self.app.set_sidebar_width(self.drag[1]+event.x_root-self.drag[0])
        return 'break'

    def end(self,event=None):
        if self.drag:
            self.drag=None
            if self.grab_current() is self:
                self.grab_release()
            self.app.changed(render=False)
            self.draw()
        return 'break'

    def cancel(self,event=None):
        if self.drag:
            self.app.set_sidebar_width(self.drag[2])
            self.end()
        return 'break'

    def step(self,delta):
        self.app.set_sidebar_width(self.app.sidebar.winfo_width()+delta)
        self.app.changed(render=False)
        return 'break'


class Slider(tk.Canvas):
    def __init__(self,parent,ui,variable,minimum,maximum,command):
        self.ui,self.variable,self.minimum,self.maximum,self.command=ui,variable,minimum,maximum,command
        self.focused=False
        super().__init__(parent,height=30,width=150,bd=0,highlightthickness=0,takefocus=1,cursor='hand2')
        self.bind('<Configure>',lambda e:self.draw())
        self.bind('<Button-1>',self.move)
        self.bind('<B1-Motion>',self.move)
        for key,step in [('Left',-1),('Right',1),('Down',-1),('Up',1)]:
            self.bind('<'+key+'>',lambda e,n=step:self.set_value(self.variable.get()+n))
        self.bind('<FocusIn>',lambda e:self.focus(True))
        self.bind('<FocusOut>',lambda e:self.focus(False))
        ui.watch(self,self.draw)
        self.trace=variable.trace_add('write',lambda *_:self.draw())
        self.bind('<Destroy>',lambda e:variable.trace_remove('write',self.trace) if e.widget is self else None)

    def focus(self,value):
        self.focused=value
        self.draw()

    def draw(self):
        self.configure(bg=self.ui['surface'])
        self.delete('all')
        w=max(30,self.winfo_width())
        fraction=(self.variable.get()-self.minimum)/(self.maximum-self.minimum)
        x=10+(w-20)*max(0,min(1,fraction))
        self.create_line(10,15,w-10,15,fill=self.ui['line'],width=4,capstyle='round')
        self.create_line(10,15,x,15,fill=self.ui['accent'],width=4,capstyle='round')
        if self.focused:
            self.create_oval(x-10,5,x+10,25,outline=self.ui['accent'],width=1)
        self.create_oval(x-7,8,x+7,22,fill=self.ui['accent'],outline='')

    def set_value(self,value):
        self.variable.set(max(self.minimum,min(self.maximum,round(value))))
        self.command()
        return 'break'

    def move(self,event):
        self.focus_set()
        return self.set_value(self.minimum+(self.maximum-self.minimum)*(event.x-10)/max(1,self.winfo_width()-20))


class ScrollArea(Frame):
    def __init__(self, parent, app):
        super().__init__(parent, app.ui, 'bg')
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0, yscrollincrement=1, cursor='arrow')
        self.bar = ModernScrollbar(self, app.ui, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.bar.pack(side='right', fill='y', padx=(0, 3))
        self.canvas.pack(side='left', fill='both', expand=True)
        self.inner = Frame(self.canvas, app.ui, 'bg')
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor='nw')
        self.inner.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self.window, width=e.width))
        self.canvas.scroll_target = self.canvas
        app.ui.watch(self.canvas, self.retheme_canvas)

    def retheme_canvas(self):
        self.canvas.configure(bg=self.ui['bg'])

    def reveal(self, widget):
        self.update_idletasks()
        y = widget.winfo_rooty()-self.inner.winfo_rooty()
        height = self.canvas.winfo_height()
        top = self.canvas.canvasy(0)
        if y < top+16 or y+min(widget.winfo_height(), height-32) > top+height-16:
            self.canvas.yview_moveto(max(0, y-22)/max(1, self.inner.winfo_height()))


class InspectorGroup(Surface):
    def __init__(self, parent, app, title, description=''):
        super().__init__(parent, app.ui, padx=20, pady=18)
        self.pack(fill='x', padx=20, pady=(0, 14))
        Label(self, app.ui, title, font='heading').pack(anchor='w', pady=(0, 4 if description else 12))
        if description:
            hint = Label(self, app.ui, description, font='small', fg='muted', justify='left')
            hint.pack(fill='x', pady=(0, 14))
            hint.bind('<Configure>', lambda e: hint.configure(wraplength=max(120,e.width)))


class RichTextEditor(Frame):
    """Text plus independent bold/italic/link attributes and formatting-aware undo.

    A Tcl widget proxy catches typing, paste, cut, IME and native edit commands.
    This is important: Tk's built-in undo alone does not undo changes to tags.
    """
    def __init__(self, parent, app, label, value='', rich=True, lines=2, hint='', on_change=None, reorder_lines=False):
        super().__init__(parent, app.ui)
        self.app, self.rich, self.label = app, rich, label
        self.on_change = on_change or app.changed
        self.attrs, self.pending, self.busy = [], None, False
        self.history, self.history_pos, self.last_edit, self.last_kind = [], 0, 0, ''
        self.min_lines, self.max_lines = lines, max(lines, 12 if lines>2 else 4)
        self.pack(fill='x', pady=(0, 16))
        Label(self, app.ui, label, font='label').pack(anchor='w', pady=(0, 7))
        self.box = Surface(self, app.ui, 'field', outer='surface', radius=8, shadow=False, padx=5, pady=5)
        self.box.pack(fill='x')
        self.toolbar = None
        self.buttons = {}
        if rich:
            self.toolbar = Frame(self.box, app.ui, 'field', padx=7, pady=4)
            self.toolbar.pack(fill='x')
            for text, key, fn, width, font, tooltip in [
                ('B', 'bold', lambda: self.toggle('bold'), 30, 'bold', 'Bold · Ctrl+B'),
                ('I', 'italic', lambda: self.toggle('italic'), 30, 'italic', 'Italic · Ctrl+I'),
                ('Link', 'link', self.edit_link, 49, 'small', 'Add or edit link · Ctrl+K'),
                ('Clear', 'clear', self.clear_formatting, 52, 'small', 'Remove formatting'),
            ]:
                b = Button(self.toolbar, app.ui, text, fn, kind='ghost', width=width, compact=True, bg='field', font=font)
                b.pack(side='left', padx=(0, 2))
                self.buttons[key] = b
                Tooltip(b, tooltip)
        self.text_row = Frame(self.box, app.ui, 'field')
        self.text_row.pack(fill='x')
        self.input = tk.Text(self.text_row, height=lines, width=1, wrap='word', undo=False, bd=0,
                             highlightthickness=0, padx=11, pady=10, exportselection=False,
                             takefocus=True, cursor='xterm',
                             font=app.ui.fonts['body'], spacing1=1, spacing3=3, tabs=('24p',))
        self.input.pack(side='left', fill='both', expand=True)
        self.line_handles = LineHandles(self, self.text_row) if reorder_lines else None
        if self.line_handles:
            Tooltip(self.line_handles.gutter, 'Drag to reorder lines · Alt+↑ / Alt+↓ · Ctrl+Z to undo')
        if hint:
            self.hint = Label(self, app.ui, hint, font='small', fg='muted', justify='left')
            self.hint.pack(fill='x', pady=(6, 0))
            self.hint.bind('<Configure>', lambda e: self.hint.configure(wraplength=max(e.width, 120)))
        # Preserve native Tk text bindings; observe changes at the widget command.
        self.original = self.input._w + '_original'
        self.tk.call('rename', self.input._w, self.original)
        self.tk.createcommand(self.input._w, self._proxy)
        self.input.bind('<Destroy>', self._destroy_proxy, add='+')
        self.input.bind('<KeyRelease>', self.cursor_changed)
        # Explicitly focus on mouse-down before the native Text class binding runs.
        # This preserves normal click/drag selection while preventing a stale popup
        # or platform focus quirk from leaving the field without an insertion caret.
        self.input.bind('<ButtonPress-1>', self.mouse_focus, add='+')
        self.input.bind('<ButtonRelease-1>', self.cursor_changed)
        self.input.bind('<FocusIn>', self.focus_in)
        self.input.bind('<FocusOut>', lambda e: self.retheme())
        self.input.bind('<Configure>', lambda e: self.autosize())
        self.input.bind('<Tab>', lambda e: self.traverse(1))
        self.input.bind('<Shift-Tab>', lambda e: self.traverse(-1))
        self.input.bind('<Control-a>', lambda e: self.select_all())
        self.input.bind('<Control-z>', lambda e: self.undo())
        self.input.bind('<Control-y>', lambda e: self.redo())
        self.input.bind('<Control-Shift-Z>', lambda e: self.redo())
        self.input.bind('<MouseWheel>', app.wheel)
        if rich:
            for key, fn in [('b', lambda: self.toggle('bold')), ('i', lambda: self.toggle('italic')), ('k', self.edit_link)]:
                self.input.bind('<Control-'+key+'>', lambda e, f=fn: (f(), 'break')[1])
        self.input.bind('<Button-3>', self.context_menu)
        app.ui.watch(self, self.retheme)
        self.set(value)

    def _destroy_proxy(self, event):
        if event.widget is self.input:
            self.tk.deletecommand(self.input._w)

    def _call(self, *args):
        return self.tk.call(self.original, *args)

    def _offset(self, index):
        return len(self._call('get', '1.0', index))

    def _idx(self, offset):
        # Tcl/Tk 8.6 counts supplementary Unicode characters as two units.
        prefix = self.visible()[:offset]
        return '1.0+%dc' % self.tk.call('string', 'length', prefix)

    def visible(self):
        return self._call('get', '1.0', 'end-1c')

    def selection(self):
        selected = self.input.tag_ranges('sel')
        if selected:
            return self._offset(selected[0]), self._offset(selected[1])
        pos = min(len(self.attrs), self._offset('insert'))
        return pos, pos

    def cursor_style(self):
        if self.pending is not None:
            return self.pending
        start, end = self.selection()
        if not self.attrs:
            return NORMAL
        return self.attrs[start if start < end else max(0, start-1)]

    def _proxy(self, command, *args):
        if self.busy or command not in ('insert', 'delete', 'replace'):
            return self._call(command, *args)
        old = self.visible()
        start = min(len(old), self._offset(args[0]))
        end, inserted = start, ''
        if command in ('delete', 'replace'):
            end = min(len(old), self._offset(args[1])) if len(args)>1 else min(start+1, len(old))
        if command == 'insert':
            inserted = ''.join(str(s) for s in args[1::2])
        elif command == 'replace':
            inserted = ''.join(str(s) for s in args[2::2])
        style = self.cursor_style() if self.rich else NORMAL
        selected_start, selected_end = self.selection()
        if command=='delete' and selected_start==start and selected_end==end and start<end:
            self.pending = style
        result = self._call(command, *args)
        self.attrs[start:end] = [style] * len(inserted)
        # Tk can clip indices; guard the model on all platform-native operations.
        actual = len(self.visible())
        self.attrs = (self.attrs + [style]*max(0,actual-len(self.attrs)))[:actual]
        if old != self.visible():
            self.paint()
            self.remember('typing')
            self.on_change()
        return result

    def set(self, value):
        text, attrs = parse(value) if self.rich else (str(value or ''), [NORMAL]*len(str(value or '')))
        self.restore((text, tuple(attrs), 0))
        self.history = [self.snapshot()]
        self.history_pos = 0
        self.last_kind = ''

    def get(self):
        text = self.visible()
        return (serialize(text, self.attrs) if self.rich else text).strip()

    def snapshot(self):
        return self.visible(), tuple(self.attrs), min(len(self.attrs), self._offset('insert'))

    def restore(self, snapshot):
        text, attrs, cursor = snapshot
        self.busy = True
        self._call('delete', '1.0', 'end')
        self._call('insert', '1.0', text)
        self.attrs = list(attrs)
        self.input.mark_set('insert', self._idx(cursor))
        self.pending = None
        self.busy = False
        self.paint()

    def remember(self, kind):
        snap = self.snapshot()
        if self.history and snap[:2] == self.history[self.history_pos][:2]:
            return
        now = time.monotonic()
        self.history = self.history[:self.history_pos+1]
        if kind == 'typing' and self.last_kind == kind and now-self.last_edit < .65 and self.history_pos>0:
            self.history[-1] = snap
        else:
            self.history.append(snap)
        if len(self.history)>150:
            self.history.pop(0)
        self.history_pos = len(self.history)-1
        self.last_kind, self.last_edit = kind, now

    def undo(self):
        if self.history_pos:
            self.history_pos -= 1
            self.restore(self.history[self.history_pos])
            self.last_kind = ''
            self.on_change()
        return 'break'

    def redo(self):
        if self.history_pos+1 < len(self.history):
            self.history_pos += 1
            self.restore(self.history[self.history_pos])
            self.last_kind = ''
            self.on_change()
        return 'break'

    def toggle(self, attribute):
        start, end = self.selection()
        if start == end:
            self.pending = replace(self.cursor_style(), **{attribute: not getattr(self.cursor_style(), attribute)})
        else:
            value = not all(getattr(a, attribute) for a in self.attrs[start:end])
            self.attrs[start:end] = [replace(a, **{attribute: value}) for a in self.attrs[start:end]]
            self.pending = None
            self.paint()
            self.remember('format')
            self.on_change()
        self.input.focus_set()
        self.update_toolbar()

    def clear_formatting(self):
        start, end = self.selection()
        if start == end:
            self.pending = Format(no_link=True)
        else:
            self.attrs[start:end] = [Format(no_link=True)]*(end-start)
            self.pending = None
            self.paint()
            self.remember('format')
            self.on_change()
        self.input.focus_set()
        self.update_toolbar()

    def apply_link(self, start, end, label, url):
        url = normalize_url(url)
        self.busy = True
        if self.visible()[start:end] != label:
            style = self.attrs[start] if start < len(self.attrs) else self.cursor_style()
            self._call('delete', self._idx(start), self._idx(end))
            self._call('insert', self._idx(start), label)
            self.attrs[start:end] = [style]*len(label)
            end = start+len(label)
        self.attrs[start:end] = [replace(a, link=url, no_link=not bool(url)) for a in self.attrs[start:end]]
        self.busy = False
        self.input.tag_remove('sel', '1.0', 'end')
        self.input.tag_add('sel', self._idx(start), self._idx(end))
        self.input.mark_set('insert', self._idx(end))
        self.paint()
        self.remember('format')
        self.on_change()
        self.input.focus_set()

    def edit_link(self):
        start, end = self.selection()
        link = self.cursor_style().link
        if start == end and link:
            start = max(0, start-1)
            while start>0 and self.attrs[start-1].link == link:
                start -= 1
            while end<len(self.attrs) and self.attrs[end].link == link:
                end += 1
        dialog = tk.Toplevel(self.app)
        dialog.title('Edit link' if link else 'Insert link')
        dialog.transient(self.app)
        dialog.resizable(False, False)
        body = Frame(dialog, self.ui, padx=24, pady=22)
        body.pack(fill='both', expand=True)
        Label(body, self.ui, 'Link', font='heading').pack(anchor='w', pady=(0,16))
        Label(body, self.ui, 'Display text', font='label').pack(anchor='w', pady=(0,6))
        name_var = tk.StringVar(value=self.visible()[start:end])
        url_var = tk.StringVar(value=link)
        name = ttk.Entry(body, textvariable=name_var, width=42, cursor='xterm')
        name.pack(fill='x', pady=(0,14))
        Label(body, self.ui, 'Web address or email', font='label').pack(anchor='w', pady=(0,6))
        address = ttk.Entry(body, textvariable=url_var, width=42, cursor='xterm')
        address.pack(fill='x', pady=(0,20))
        actions = Frame(body, self.ui)
        actions.pack(fill='x')
        def commit(remove=False):
            url = '' if remove else url_var.get().strip()
            label = name_var.get().strip() or url
            if not label:
                name.focus_set()
                return
            self.apply_link(start, end, label, url)
            dialog.destroy()
        if link:
            Button(actions, self.ui, 'Remove link', lambda: commit(True), kind='ghost').pack(side='left')
        Button(actions, self.ui, 'Apply', commit, kind='primary').pack(side='right')
        Button(actions, self.ui, 'Cancel', dialog.destroy, kind='ghost').pack(side='right', padx=8)
        dialog.bind('<Escape>', lambda e: dialog.destroy())
        dialog.bind('<Return>', lambda e: commit())
        self.app.center_dialog(dialog)
        dialog.grab_set()
        address.focus_set()

    def paint(self):
        self.attrs = [NORMAL if ch == '\n' else state for ch, state in zip(self.visible(), self.attrs)]
        for tag in ('bold', 'italic', 'both', 'hyperlink'):
            self.input.tag_remove(tag, '1.0', 'end')
        offset = 0
        for content, state in runs(self.visible(), self.attrs):
            a, b = self._idx(offset), self._idx(offset+len(content))
            tag = 'both' if state.bold and state.italic else 'bold' if state.bold else 'italic' if state.italic else ''
            if tag:
                self.input.tag_add(tag, a, b)
            if state.link:
                self.input.tag_add('hyperlink', a, b)
            offset += len(content)
        self.input.tag_raise('sel')
        self.autosize()
        self.update_toolbar()
        if getattr(self, 'line_handles', None):
            self.line_handles.draw()

    def autosize(self):
        if self.input.winfo_width()<20:
            return
        count = self.input.count('1.0', 'end-1c', 'displaylines')
        height = max(self.min_lines, min(self.max_lines, (count[0] if count else 0)+1))
        if int(self.input.cget('height')) != height:
            self.input.configure(height=height)

    def retheme(self):
        p = self.ui
        self.configure(bg=p['surface'])
        if not hasattr(self, 'input'):
            return
        self.input.configure(bg=p['field'], fg=p['text'], insertbackground=p['text'],
                             selectbackground=p['tint'], selectforeground=p['text'], inactiveselectbackground=p['tint'])
        self.box.set_focus(self.app.focus_get() is self.input)
        for tag, font in [('bold','bold'), ('italic','italic'), ('both','both')]:
            self.input.tag_configure(tag, font=p.fonts[font])
        self.input.tag_configure('hyperlink', foreground=p['accent'], underline=True)

    def mouse_focus(self, event=None):
        if self.input.winfo_exists():
            # A Design popup (theme/colour selector) is a temporary Toplevel.
            # On Windows, destroying such a popup can occasionally leave the app
            # without a keyboard-focus owner.  focus_set() only moves Tk's logical
            # focus and may then fail to bring the insertion caret back.  Because
            # this handler runs only after the user actually clicks the editor,
            # focus_force() is appropriate: it explicitly re-activates the clicked
            # Text widget and restores its insertion caret.
            self.input.focus_force()
            self.app.active_editor = self
            # Reassert once the current mouse event (and any popup-close binding)
            # has completed.  This is what makes the first click after Design work.
            self.app.after_idle(self.ensure_mouse_focus)
        # No 'break': Tk's native Text binding still places/extends the selection.

    def ensure_mouse_focus(self):
        if self.input.winfo_exists() and self.input.winfo_viewable():
            self.input.focus_force()
            self.retheme()

    def focus_in(self, event):
        self.app.active_editor = self
        self.retheme()
        self.update_toolbar()
        area = self.app.pages.get(self.app.current_section)
        if area:
            self.app.after_idle(lambda:area.reveal(self) if self.winfo_exists() else None)

    def cursor_changed(self, event=None):
        if event and (event.type == tk.EventType.ButtonRelease or event.keysym in ('Left','Right','Up','Down','Home','End')):
            self.pending = None
            self.last_kind = ''
        self.update_toolbar()

    def update_toolbar(self):
        if not self.rich or not hasattr(self, 'input'):
            return
        start, end = self.selection()
        attrs = self.attrs[start:end] if start<end else [self.cursor_style()]
        for key in ('bold', 'italic', 'link'):
            self.buttons[key].selected = bool(attrs) and all(bool(getattr(a,key)) for a in attrs)
            self.buttons[key].draw()

    def traverse(self, direction):
        target = self.input.tk_focusNext() if direction>0 else self.input.tk_focusPrev()
        target.focus_set()
        return 'break'

    def select_all(self):
        self.input.tag_add('sel', '1.0', 'end-1c')
        self.update_toolbar()
        return 'break'

    def context_menu(self, event):
        self.app.active_editor = self
        PopupMenu(self.app, self.input, self.app.edit_menu())
        return 'break'


# key, label, rich text, minimum lines, helper text
FIELDS = {
    'contacts': [('text','Display text',False,1,''), ('url','Link',False,1,'Optional. Email addresses link automatically.')],
    'projects': [('title','Project title',False,1,''), ('meta','Details & links',True,2,'Organisation, venue, dates, or publication link.'),
                 ('bullets','Highlights',True,4,'One achievement per line. Each line becomes a bullet in your CV.')],
    'skills': [('category','Category',False,1,''), ('items','Skills',True,2,'Separate skills with commas or a middle dot.')],
    'experience': [('title','Position',False,1,''), ('company','Company & location',False,1,''),
                   ('dates','Dates',False,1,''), ('description','Contribution & achievements',True,4,'One paragraph per line.')],
    'education': [('degree','Degree or qualification',False,1,''), ('institution','Institution',False,1,''),
                  ('dates','Dates',False,1,''), ('gpa','GPA / grade',False,1,'Leave empty to hide.'),
                  ('distinction','Distinction',False,1,''), ('coursework','Relevant coursework',True,2,'Optional.')],
    'custom': [('title','Entry title',False,1,'Optional. Leave empty for a simple text section.'),
               ('meta','Details & links',True,2,'Optional dates, organisation, or website.'),
               ('description','Content',True,4,'Write freely. Use the toolbar for emphasis and links.'),
               ('bullets','Highlights',True,3,'Optional. Each line becomes a bullet in your CV.')],
}
ENTRY_NAMES = {'contacts':'contact', 'projects':'project', 'skills':'category', 'experience':'position', 'education':'qualification', 'custom':'entry'}
TITLE_KEYS = {'contacts':'text', 'projects':'title', 'skills':'category', 'experience':'title', 'education':'degree', 'custom':'title'}


class SectionCard(Surface):
    def __init__(self, owner, data, expanded=False):
        self.owner, self.app, self.expanded, self.fields = owner, owner.app, expanded, {}
        self.entry_kind = entry_type(data) if owner.kind=='custom' else None
        self.entry_spec = ENTRY_TYPES[self.entry_kind] if self.entry_kind else None
        form = [field.form() for field in self.entry_spec.fields] if self.entry_spec else FIELDS[owner.kind]
        form_keys = {field[0] for field in form}
        self.saved_extras = deepcopy({k:v for k,v in data.items() if k not in form_keys}) if self.entry_spec else {}
        super().__init__(owner.holder, owner.app.ui, padx=18, pady=16)
        self.header = Frame(self, self.ui)
        self.header.pack(fill='x')
        self.grip = Button(self.header, self.ui, '⋮', lambda:None, kind='ghost', width=24, compact=True)
        self.grip.configure(cursor='fleur')
        self.grip.pack(side='left', anchor='n')
        Tooltip(self.grip, 'Drag this header to reorder · Alt+↑ / Alt+↓')
        self.chevron = Button(self.header, self.ui, '▾' if expanded else '▸', self.toggle,
                               kind='ghost', width=28, compact=True)
        self.chevron.pack(side='left', anchor='n', padx=(0,7))
        self.copy = Frame(self.header, self.ui)
        self.copy.pack(side='left', fill='x', expand=True, pady=4)
        self.type_label = None
        if self.entry_spec:
            self.type_label = Label(self.copy,self.ui,self.entry_spec.label.upper(),font='label',fg='accent',cursor='hand2')
            self.type_label.pack(anchor='w',pady=(0,4))
        self.title_label = Label(self.copy, self.ui, '', font='bold', cursor='hand2', justify='left')
        self.title_label.pack(fill='x')
        self.subtitle = Label(self.copy, self.ui, '', font='small', fg='muted', cursor='hand2', justify='left')
        self.subtitle.pack(fill='x', pady=(4,0))
        for label in (self.title_label, self.subtitle):
            label.bind('<Configure>', lambda e, w=label: w.configure(wraplength=max(80,e.width)))
        self.more = Button(self.header, self.ui, '⋯', self.open_menu, kind='ghost', width=32, compact=True)
        self.more.pack(side='right', anchor='n', padx=(8,0))
        self.copy.pack_forget()
        self.copy.pack(side='left', fill='x', expand=True, pady=4)
        Tooltip(self.more, 'Move, duplicate, or remove this entry')
        for widget in (self.header, self.copy, self.title_label, self.subtitle, self.grip, self.chevron) + ((self.type_label,) if self.type_label else ()):
            self.owner.reorder.bind(widget, self, self.toggle if widget is not self.grip else None)
            widget.bind('<Enter>', lambda e: self.header_hover(True), add='+')
            widget.bind('<Leave>', lambda e: self.header_hover(False), add='+')
        self.body = Frame(self, self.ui)
        if expanded:
            self.body.pack(fill='x', pady=(18,0))
        for key, label, rich, lines, hint in form:
            value = data.get(key, '')
            if key == 'bullets':
                value = '\n'.join(value or [])
            self.fields[key] = RichTextEditor(self.body, self.app, label, value, rich, lines, hint, self.changed,
                                              reorder_lines=key in ('bullets','description','coursework','items'))
        self.refresh()

    def header_hover(self, active):
        self.hovered = active
        self.paint()
        role = 'field' if active else 'surface'
        for widget in (self.header, self.copy, self.title_label, self.subtitle) + ((self.type_label,) if self.type_label else ()):
            if isinstance(widget, Label):
                widget.bg_role = role
            else:
                widget.role = role
            widget.retheme()
        for widget in (self.grip, self.chevron, self.more):
            widget.bg_role = role
            widget.draw()

    def get(self):
        result = deepcopy(self.saved_extras)
        result.update({key: field.get() for key, field in self.fields.items()})
        if 'bullets' in self.fields:
            result['bullets'] = [line for line in result['bullets'].splitlines() if plain(line).strip()]
        return result

    def refresh(self):
        data = self.get()
        title_key = self.entry_spec.title_key if self.entry_spec else TITLE_KEYS[self.owner.kind]
        type_name = self.entry_spec.label.lower() if self.entry_spec else ENTRY_NAMES[self.owner.kind]
        title = plain(data.get(title_key, '')) or 'Untitled '+type_name
        self.title_label.configure(text=title[:100]+('…' if len(title)>100 else ''))
        second = next((plain(data[k]) for k in ('meta','company','institution','authors','venue','organisation','issuer','role','items','url','description') if data.get(k)), '')
        if not second:
            second = 'Click to edit' if not self.expanded else 'Entry '+str(self.owner.cards.index(self)+1 if self in self.owner.cards else len(self.owner.cards)+1)
        self.subtitle.configure(text=second[:85]+('…' if len(second)>85 else ''))

    def changed(self):
        self.refresh()
        self.app.changed()

    def toggle(self):
        self.set_expanded(not self.expanded)

    def set_expanded(self, value):
        self.expanded = value
        if value:
            self.body.pack(fill='x', pady=(18,0))
        else:
            self.body.pack_forget()
        self.chevron.text = '▾' if value else '▸'
        self.chevron.draw()
        self.refresh()

    def open_menu(self):
        i = self.owner.cards.index(self)
        PopupMenu(self.app, self.more, [
            ('Move up','',lambda: self.owner.move(self,-1),i>0),
            ('Move down','',lambda: self.owner.move(self,1),i<len(self.owner.cards)-1), None,
            ('Duplicate','',lambda: self.owner.duplicate(self)),
            ('Remove entry…','',lambda: self.owner.remove(self)),
        ])

class ItemList(Frame):
    def __init__(self, parent, app, key, items, layout='auto'):
        super().__init__(parent, app.ui, 'bg')
        self.app, self.key, self.cards = app, key, []
        self.kind = 'custom' if is_custom(key) else key
        self.pack(fill='x')
        if self.kind=='custom':
            arrangement = Frame(self,app.ui,'bg')
            arrangement.pack(fill='x',padx=22,pady=(0,16))
            row = Frame(arrangement,app.ui,'bg')
            row.pack(fill='x')
            Label(row,app.ui,'PDF layout',font='label',fg='muted',bg='bg').pack(side='left',padx=(0,12))
            self.layout_variable = tk.StringVar(value=ENTRY_LAYOUTS[entry_layout(layout)])
            self.layout_choice = Choice(row,app,self.layout_variable,list(ENTRY_LAYOUTS.values()),self.layout_changed,width=190)
            self.layout_choice.bg_role = 'bg'
            self.layout_choice.pack(side='left')
            self.layout_hint = Label(arrangement,app.ui,'',font='small',fg='muted',bg='bg',justify='left')
            self.layout_hint.pack(fill='x',pady=(7,0))
            self.layout_hint.bind('<Configure>',lambda e:self.layout_hint.configure(wraplength=max(120,e.width)))
            self.layout_changed(render=False)
        bar = Frame(self, app.ui, 'bg')
        bar.pack(fill='x', padx=20, pady=(0,14))
        self.count = Label(bar, app.ui, '', font='small', fg='muted', bg='bg')
        self.count.pack(side='left')
        self.add_button = Button(bar, app.ui, '+ Add entry  ▾' if self.kind=='custom' else '+ Add '+ENTRY_NAMES[self.kind],
                                 self.add_new, compact=True, bg='bg')
        self.add_button.pack(side='right')
        if self.kind=='custom':
            Tooltip(self.add_button,'Choose an entry type. Different types can share the same section.')
        collapse = Button(bar, app.ui, 'Collapse all', lambda: self.expand_all(False), kind='ghost', compact=True, bg='bg', font='small')
        collapse.pack(side='right', padx=8)
        self.holder = Frame(self, app.ui, 'bg')
        self.holder.pack(fill='x')
        area = app.pages['header' if key=='contacts' else key]
        self.reorder = ReorderController(app, self.holder,
            lambda: ReorderController.widget_rows([(card,card) for card in self.cards]),
            self.reorder_to, viewport=area.canvas,
            scroll=lambda pixels: area.canvas.yview_scroll(pixels,'units'), label=ENTRY_NAMES[self.kind],
            can_scroll=lambda direction: can_scroll_view(area.canvas,direction),
            widgets=lambda:[(card,card) for card in self.cards],on_layout_end=self.repack,
            describe=lambda card:(card.title_label.cget('text'),card.subtitle.cget('text')))
        self.empty = Label(self.holder, app.ui, 'No entries yet. Add one when you’re ready.', fg='muted', bg='bg', justify='left')
        if self.kind=='custom':
            self.empty.configure(text='Choose a type with + Add entry. Mix education, publications, projects, and more in this section.')
            self.empty.bind('<Configure>',lambda e:self.empty.configure(wraplength=max(120,e.width)))
        for i, item in enumerate(items):
            self.add(item, expanded=(i==0))
        self.repack()

    def get_layout(self):
        return next((key for key,label in ENTRY_LAYOUTS.items() if label==self.layout_variable.get()), 'auto')

    def layout_changed(self, render=True):
        hints = {'auto':'Pair similar, compact entries when there is room. ATS stays single-column.',
                 'single':'Each entry uses the full available width in the PDF.',
                 'columns':'Pair neighbouring entries in the PDF. Long entries use the full width.'}
        self.layout_hint.configure(text=hints[self.get_layout()])
        if render:
            self.app.changed()

    def add(self, data=None, expanded=True):
        data = data or {key: [] if key=='bullets' else '' for key,*_ in FIELDS[self.kind]}
        card = SectionCard(self, data, expanded)
        self.cards.append(card)
        self.repack()
        return card

    def add_new(self):
        if self.kind=='custom':
            return PopupMenu(self.app,self.add_button,
                [(ENTRY_TYPES[kind].label,'',lambda k=kind:self.create_entry(k)) for kind in ENTRY_CHOICES])
        return self.create_entry()

    def create_entry(self, kind=None):
        card = self.add(empty_entry(kind or 'text') if self.kind=='custom' else None)
        self.app.changed()
        self.app.after_idle(lambda: self.app.reveal_field(next(iter(card.fields.values())), card) if card.winfo_exists() else None)
        return card

    def repack(self):
        self.empty.pack_forget()
        for card in self.cards:
            card.pack_forget()
        for card in self.cards:
            card.pack(fill='x', padx=20, pady=(0,12))
            card.refresh()
        n = len(self.cards)
        self.count.configure(text=f'{n} '+('entry' if n==1 else 'entries'))
        if not n:
            self.empty.pack(fill='x', padx=22, pady=18)

    def get_items(self):
        return [card.get() for card in self.cards]

    def move(self, card, delta):
        i = self.cards.index(card)
        j = i+delta
        if 0<=j<len(self.cards):
            self.reorder_to(i,j)

    def reorder_to(self, old, new):
        self.cards.insert(new,self.cards.pop(old))
        if not self.reorder.layout:
            self.repack()
        self.app.changed()
        self.app.status.set(ENTRY_NAMES[self.kind].title()+' order updated')

    def duplicate(self, card):
        copy = self.add(deepcopy(card.get()))
        self.cards.remove(copy)
        self.cards.insert(self.cards.index(card)+1, copy)
        self.repack()
        self.app.changed()
        return copy

    def remove(self, card):
        if messagebox.askyesno('Remove entry', 'Remove “'+card.title_label.cget('text')+'”?', parent=self.app):
            self.cards.remove(card)
            card.destroy()
            self.repack()
            self.app.changed()

    def expand_all(self, expanded):
        for card in self.cards:
            card.set_expanded(expanded)


class Toggle(Button):
    def __init__(self, parent, app, variable, text, command=None):
        self.variable, self.on_change = variable, command
        super().__init__(parent, app.ui, text, self.flip, kind='ghost', anchor='w')
        self.selected = bool(variable.get())
        self.trace = variable.trace_add('write', self.refresh)
        self.bind('<Destroy>', lambda e: variable.trace_remove('write', self.trace) if e.widget is self else None)
        self.refresh()

    def flip(self):
        self.variable.set(not self.variable.get())
        if self.on_change:
            self.on_change()

    def refresh(self, *_):
        self.selected = bool(self.variable.get())
        self.draw()


class SectionState:
    """Section data shared by sidebar editing, ordering and visibility; no duplicate form."""
    def __init__(self, app, sections):
        self.app, self.rows = app, []
        for section in sections:
            self.add(section)

    def add(self, section):
        app = self.app
        visible = tk.BooleanVar(master=app,value=section['visible'])
        title = tk.StringVar(master=app,value=section['title'])
        item = dict(key=section['key'], visible=visible, title=title)
        item['traces'] = [(variable,variable.trace_add('write',self.changed)) for variable in (title,visible)]
        self.rows.append(item)
        return item

    def changed(self, *_):
        self.app.refresh_section_labels()
        self.app.changed()

    def remove(self, row):
        for variable,trace in row['traces']:
            variable.trace_remove('write',trace)
        self.rows.remove(row)

    def dispose(self):
        for row in list(self.rows):
            self.remove(row)

    def get(self):
        sections = []
        for row in self.rows:
            section = dict(key=row['key'], title=row['title'].get(), visible=row['visible'].get())
            if is_custom(row['key']):
                layout = self.app.lists[row['key']].get_layout()
                if layout!='auto':
                    section['entry_layout'] = layout
            sections.append(section)
        return sections


PDF_LOCK = threading.Lock()


class StudioApp(tk.Tk):
    def __init__(self, engine, edition='Starter'):
        super().__init__()
        self.engine, self.edition = engine, edition
        self.loading, self.dirty, self.closing = True, False, False
        self.json_path = self.last_pdf = None
        self.last_dir = str(Path(engine.__file__).resolve().parent)
        self.popup = self.active_editor = None
        self.ui = Appearance(self)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='cv-preview')
        self.render_future = self.raster_future = None
        self.revision, self.raster_revision = 0, 0
        self._job = self._resize_job = None
        self._pdf = None
        self._displayed_pdf = None
        self._photos, self._preview_pages, self._source_map = [], [], []
        self._zoom, self.zoom_mode, self._effective_scale = 1.0, 'page', 1.0
        self.current_section = 'header'
        self.sidebar_width = 248
        self.section_rename = None
        self._focused_surfaces = set()
        self.status = tk.StringVar(value='Ready')
        self.document_name = tk.StringVar(value='Untitled CV')
        self.save_state = tk.StringVar(value='Starter document')
        self.preview_state = tk.StringVar(value='Preparing preview…')
        self.document_stats = tk.StringVar(value='A4 document')
        self.zoom_text = tk.StringVar(value='Fit page')
        self.geometry(f'{min(1480,int(self.winfo_screenwidth()*.91))}x{min(960,int(self.winfo_screenheight()*.86))}')
        self.minsize(1040, 660)
        self.build_chrome()
        self.load(deepcopy(engine.DEFAULT_DATA))
        self.loading = False
        self.bind('<MouseWheel>', self.wheel)
        self.bind('<FocusIn>', self.surface_focus_changed, add='+')
        self.bind('<FocusOut>', self.surface_focus_changed, add='+')
        self.bind('<Button-4>', lambda e: self.wheel(e,-1))
        self.bind('<Button-5>', lambda e: self.wheel(e,1))
        for key, fn in [('<Control-s>',self.save),('<Control-Shift-S>',self.save_as),
                        ('<Control-o>',self.open_file),('<Control-e>',self.export_pdf)]:
            self.bind(key, lambda e,f=fn:(f(),'break')[1])
        for key, name in [('<Alt-f>','File'),('<Alt-e>','Edit'),('<Alt-v>','View'),('<F1>','Help')]:
            self.bind(key, lambda e,n=name:self.open_app_menu(n))
        self.protocol('WM_DELETE_WINDOW', self.on_close)
        self.after(50, self.poll_worker)
        self.schedule_preview()

    def build_chrome(self):
        menus = Frame(self, self.ui, padx=18, pady=5)
        menus.pack(fill='x')
        Label(menus, self.ui, 'CV STUDIO', font='label', fg='muted').pack(side='left', padx=(5,24))
        self.menu_buttons = {}
        for text in ('File','Edit','View','Help'):
            b = Button(menus, self.ui, text, lambda n=text:self.open_app_menu(n), kind='ghost', compact=True)
            b.pack(side='left', padx=1)
            self.menu_buttons[text] = b
        Label(menus, self.ui, self.edition+' edition', font='small', fg='muted').pack(side='right', padx=8)
        Frame(self, self.ui, 'line', height=1).pack(fill='x')
        toolbar = Frame(self, self.ui, padx=22, pady=14)
        toolbar.pack(fill='x')
        doc = Frame(toolbar, self.ui)
        doc.pack(side='left', fill='x', expand=True)
        self.file_label = Label(doc, self.ui, font='heading', textvariable=self.document_name)
        self.file_label.pack(anchor='w')
        Label(doc, self.ui, font='small', fg='muted', textvariable=self.save_state).pack(anchor='w', pady=(4,0))
        Button(toolbar, self.ui, 'Export PDF', self.export_pdf, kind='primary', font='bold').pack(side='right')
        Button(toolbar, self.ui, 'Save', self.save).pack(side='right', padx=(8,10))
        Button(toolbar, self.ui, 'Open', self.open_file, kind='ghost').pack(side='right')
        Frame(self, self.ui, 'line', height=1).pack(fill='x')

        footer = Frame(self, self.ui, padx=20, pady=7)
        footer.pack(side='bottom', fill='x')
        Label(footer, self.ui, textvariable=self.status, font='small', fg='muted').pack(side='left')
        Label(footer, self.ui, 'Double-click PDF text to edit', font='small', fg='muted').pack(side='right')
        workspace = Frame(self, self.ui, 'bg')
        workspace.pack(fill='both', expand=True)
        self.workspace=workspace
        self.sidebar = Frame(workspace, self.ui, 'rail', width=self.sidebar_width)
        self.sidebar.pack(side='left', fill='y')
        self.sidebar.pack_propagate(False)
        self.nav_canvas=tk.Canvas(self.sidebar,bd=0,highlightthickness=0,yscrollincrement=1,cursor='arrow')
        self.nav_canvas.scroll_target=self.nav_canvas
        self.nav_scrollbar=ModernScrollbar(self.sidebar,self.ui,command=self.nav_canvas.yview,bg='rail')
        self.nav_scrollbar.pack(side='right',fill='y')
        self.nav_canvas.pack(side='left',fill='both',expand=True)
        self.nav_canvas.configure(yscrollcommand=self.nav_scrollbar.set)
        self.ui.watch(self.nav_canvas,self.theme_sidebar)
        sidebar = Frame(self.nav_canvas, self.ui, 'rail', padx=10, pady=20)
        self.nav_body=sidebar
        nav_window=self.nav_canvas.create_window(0,0,window=sidebar,anchor='nw')
        sidebar.bind('<Configure>',lambda e:self.nav_canvas.configure(scrollregion=self.nav_canvas.bbox('all')))
        self.nav_canvas.bind('<Configure>',lambda e:self.nav_canvas.itemconfigure(nav_window,width=e.width))
        self.sidebar_reorder = ReorderController(self,sidebar,
            lambda: ReorderController.widget_rows([(row['key'],self.nav[row['key']]) for row in self.sections.rows]),
            self.reorder_sections,label='section',
            viewport=self.nav_canvas,scroll=lambda pixels:self.nav_canvas.yview_scroll(pixels,'units'),
            widgets=lambda:[(row['key'],self.nav[row['key']]) for row in self.sections.rows],
            on_layout_end=self.refresh_section_labels,describe=lambda key:(self.nav[key].text,''),
            ghost_painter=lambda canvas,key,width:self.nav[key].paint_drag_preview(canvas,width))
        Label(sidebar, self.ui, 'DOCUMENT', font='label', fg='muted', bg='rail').pack(anchor='w', padx=12, pady=(0,14))
        self.nav = {}
        for key, title, _ in NAVIGATION:
            if key == 'layout':
                self.design_separator = Frame(sidebar, self.ui, 'line', height=1)
                self.design_separator.pack(fill='x', padx=16, pady=(18,14))
                self.add_section_button = NavigationButton(sidebar, self.ui, '+ Add Section', self.add_custom_section,
                                                           kind='nav', anchor='w', bg='rail', width=self.sidebar_width-20)
                self.add_section_button.pack(fill='x', pady=4)
            self.add_navigation(key, title)
        self.sidebar_drop_line = self.sidebar_reorder.marker
        self.sidebar_divider=SidebarDivider(workspace,self)
        self.sidebar_divider.pack(side='left',fill='y')
        self.paned = SplitPane(workspace, self.ui)
        self.paned.pack(fill='both', expand=True)
        self.editor_host = Frame(self.paned, self.ui, 'bg')
        self.preview_host = Frame(self.paned, self.ui, 'canvas')
        self.paned.add(self.editor_host, weight=1)
        self.paned.add(self.preview_host, weight=1)
        self.split_initialized = False
        self.paned.bind('<Configure>', self.place_split)
        self.paned.bind('<ButtonRelease-1>', self.clamp_split)
        self.build_preview()
        workspace.bind('<Configure>',self.sidebar_workspace_resize)

    def theme_sidebar(self):
        self.nav_canvas.configure(bg=self.ui['rail'])

    def surface_focus_changed(self, event=None):
        # Observe focus only; never transfer it. Repaint just the old/new ancestor
        # surfaces, not every card or editor, even in a very long document.
        current = set()
        widget = self.focus_get()
        while widget is not None:
            if isinstance(widget, Surface):
                current.add(widget)
            widget = getattr(widget, 'master', None)
        for surface in self._focused_surfaces | current:
            if surface.winfo_exists():
                surface.set_focus(surface in current)
        self._focused_surfaces = current

    def reveal_sidebar(self,button):
        if not button.winfo_exists() or not self.nav_canvas.winfo_exists():
            return
        self.update_idletasks()
        y=button.winfo_rooty()-self.nav_body.winfo_rooty()
        top=self.nav_canvas.canvasy(0)
        height=self.nav_canvas.winfo_height()
        bottom=y+button.winfo_height()
        if y<top or bottom>top+height:
            destination=y-8 if y<top else bottom-height+8
            self.nav_canvas.yview_moveto(max(0,destination)/max(1,self.nav_body.winfo_height()))

    def sidebar_limits(self):
        width=self.workspace.winfo_width()
        # Reserve the existing 405px editor, 340px preview and their sash.
        return 184,max(184,min(384,width-756 if width>1 else 384))

    def set_sidebar_width(self,value,remember=True):
        minimum,maximum=self.sidebar_limits()
        requested=self.number(value,248,184,384)
        if remember:
            self.sidebar_width=requested
        actual=max(minimum,min(maximum,requested))
        if int(self.sidebar.cget('width'))!=actual:
            if getattr(self,'active_drag',None):
                self.active_drag.cancel()
            self.sidebar.configure(width=actual)

    def sidebar_workspace_resize(self,event=None):
        self.set_sidebar_width(self.sidebar_width,remember=False)

    def sidebar_activate(self, key):
        self.navigate(key)

    def reorder_sections(self, old, new):
        rows = self.sections.rows
        rows.insert(new,rows.pop(old))
        if not self.sidebar_reorder.layout:
            self.refresh_section_labels()
        self.changed()
        self.status.set('Section order updated')

    def add_navigation(self, key, title):
        button = NavigationButton(self.nav_body, self.ui, title, lambda k=key:self.sidebar_activate(k),
                                  kind='nav', anchor='w', bg='rail', width=self.sidebar_width-20)
        button.pack(fill='x', pady=4)
        self.nav[key] = button
        if key not in ('header','layout'):
            button.reorderable=True
            self.sidebar_reorder.bind(button,key,lambda k=key:self.navigate(k))
            button.bind('<Double-Button-1>',lambda e,k=key:self.rename_section(k))
            button.bind('<Button-3>',lambda e,k=key:self.sidebar_menu(k),add='+')
            button.bind('<F2>',lambda e,k=key:self.rename_section(k),add='+')

    def add_custom_section(self):
        if getattr(self, 'active_drag', None):
            self.active_drag.cancel()
        self.finish_section_rename()
        key = new_section_key()
        existing = {row['title'].get() for row in self.sections.rows}
        title, number = 'New section', 2
        while title in existing:
            title = f'New section {number}'
            number += 1
        self.add_navigation(key, title)
        self.create_page(key, title, 'Your own space for awards, certifications, volunteering, or anything else.')
        self.lists[key] = ItemList(self.pages[key].inner, self, key, [])
        self.sections.add(dict(key=key, title=title, visible=True))
        self.refresh_section_labels()
        self.navigate(key)
        self.changed()
        self.rename_section(key)
        return key

    def remove_custom_section(self, key):
        if not is_custom(key) or key not in self.lists:
            return
        if getattr(self, 'active_drag', None):
            self.active_drag.cancel()
        self.finish_section_rename()
        row = next(r for r in self.sections.rows if r['key'] == key)
        if not messagebox.askyesno('Remove section',
                f'Remove “{row["title"].get()}” and all its entries?\n\nOther sections will not be changed.', parent=self):
            return
        if self.current_section == key:
            self.navigate('header')
        if self.active_editor and str(self.active_editor).startswith(str(self.pages[key]) + '.'):
            self.active_editor = None
        self.nav.pop(key).destroy()
        self.pages.pop(key).destroy()
        self.page_titles.pop(key)
        self.lists.pop(key)
        self.sections.remove(row)
        self.refresh_section_labels()
        self.changed()
        self.status.set('Custom section removed')

    def sidebar_menu(self,key,anchor=None):
        row = next(r for r in self.sections.rows if r['key']==key)
        visible = row['visible'].get()
        items = [('Rename section…','F2',lambda:self.rename_section(key)),
                 ('✓  Show on CV' if visible else '    Show on CV','',lambda:self.toggle_section(key))]
        if is_custom(key):
            items.extend([None, ('Remove section…', '', lambda:self.remove_custom_section(key))])
        PopupMenu(self,anchor or self.nav[key],items)
        return 'break'

    def rename_section(self,key):
        if getattr(self,'active_drag',None):
            self.active_drag.cancel()
        if self.section_rename and self.section_rename['key']==key:
            self.section_rename['entry'].focus_set()
            return 'break'
        self.finish_section_rename()
        self.reveal_sidebar(self.nav[key])
        row = next(r for r in self.sections.rows if r['key']==key)
        button=self.nav[key]
        entry=tk.Entry(button,bd=0,highlightthickness=0,relief='flat',font=self.ui.fonts['body'],
                       cursor='xterm',exportselection=False)
        entry.insert(0,row['title'].get())
        button.rename_entry=entry
        self.section_rename=dict(key=key,row=row,entry=entry,previous_status=self.status.get())
        button.draw()
        entry.place(x=24,rely=.5,y=1,anchor='w',relwidth=1,width=-48,height=self.ui.fonts['body'].metrics('linespace')+6)
        entry.bind('<Return>',lambda e:self.finish_section_rename(focus=True))
        entry.bind('<KP_Enter>',lambda e:self.finish_section_rename(focus=True))
        entry.bind('<Escape>',lambda e:self.finish_section_rename(commit=False,focus=True))
        entry.bind('<FocusOut>',lambda e:self.after_idle(lambda:self.rename_focus_out(entry)))
        entry.bind('<Control-a>',lambda e:(entry.selection_range(0,'end'),'break')[1])
        entry.selection_range(0,'end')
        entry.icursor('end')
        entry.focus_force()
        # Context-menu callbacks restore focus to their anchor after returning.
        self.after_idle(lambda:entry.focus_force() if self.section_rename and self.section_rename['entry'] is entry else None)
        self.status.set('Rename section · Enter to save · Esc to cancel')
        return 'break'

    def rename_focus_out(self,entry):
        if self.section_rename and self.section_rename['entry'] is entry and self.focus_get() is not entry:
            self.finish_section_rename()

    def finish_section_rename(self,commit=True,focus=False):
        state=self.section_rename
        if not state:
            return 'break'
        title=state['entry'].get().strip()
        if commit and not title and focus:
            self.status.set('Enter a section name, or press Esc to cancel.')
            state['entry'].focus_set()
            return 'break'
        self.section_rename=None
        button=self.nav[state['key']]
        button.rename_entry=None
        state['entry'].destroy()
        changed=commit and title and title!=state['row']['title'].get()
        if changed:
            state['row']['title'].set(title)
        button.draw()
        self.status.set('Section renamed' if changed else state['previous_status'])
        if focus:
            button.focus_set()
        return 'break'

    def toggle_section(self,key):
        row = next(r for r in self.sections.rows if r['key']==key)
        row['visible'].set(not row['visible'].get())
        self.status.set('Section shown on CV' if row['visible'].get() else 'Section hidden from CV · content kept')

    def place_split(self, event=None):
        width = self.paned.winfo_width()
        if width>700 and not self.split_initialized:
            self.paned.sashpos(0, int(width*.50))
            self.split_initialized = True
        if width>700:
            self.clamp_split()

    def clamp_split(self, event=None):
        width = self.paned.winfo_width()
        if width>700:
            pos = self.paned.sashpos(0)
            self.paned.sashpos(0, max(405,min(width-340,pos)))

    def build_preview(self):
        bar = Frame(self.preview_host, self.ui, padx=18, pady=15)
        bar.pack(fill='x')
        copy = Frame(bar, self.ui)
        copy.pack(side='left', fill='x', expand=True)
        Label(copy, self.ui, 'Preview', font='heading').pack(anchor='w')
        Label(copy, self.ui, textvariable=self.preview_state, font='small', fg='muted').pack(anchor='w', pady=(3,0))
        controls = Frame(bar, self.ui)
        controls.pack(side='right')
        Button(controls,self.ui,'−',lambda:self.set_zoom(1/1.15),width=32,compact=True,kind='ghost').pack(side='left')
        self.zoom_button = Button(controls,self.ui,'Fit page',self.zoom_menu,width=90,compact=True)
        self.zoom_button.pack(side='left', padx=3)
        Button(controls,self.ui,'+',lambda:self.set_zoom(1.15),width=32,compact=True,kind='ghost').pack(side='left')
        stage = Frame(self.preview_host,self.ui,'canvas')
        stage.pack(fill='both',expand=True)
        self.pcanvas = tk.Canvas(stage,highlightthickness=0,bd=0,yscrollincrement=1,xscrollincrement=1)
        self.pcanvas.scroll_target = self.pcanvas
        vertical = ModernScrollbar(stage,self.ui,command=self.pcanvas.yview,bg='canvas')
        horizontal = ModernScrollbar(stage,self.ui,orient='horizontal',command=self.pcanvas.xview,bg='canvas')
        self.pcanvas.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        vertical.pack(side='right',fill='y',padx=(0,3))
        horizontal.pack(side='bottom',fill='x',pady=(0,3))
        self.pcanvas.pack(fill='both',expand=True)
        self.ui.watch(self.pcanvas,self.theme_preview)
        self.pcanvas.bind('<Configure>',self.preview_resize)
        self.pcanvas.bind('<Double-Button-1>',self.preview_double_click)
        self.pcanvas.bind('<Motion>',self.preview_pointer)
        bottom = Frame(self.preview_host,self.ui,'canvas',padx=20,pady=10)
        bottom.pack(fill='x')
        Label(bottom,self.ui,textvariable=self.document_stats,font='small',fg='muted',bg='canvas').pack(anchor='center')

    def theme_preview(self):
        self.pcanvas.configure(bg=self.ui['canvas'])
        self.pcanvas.itemconfigure('shadow',fill=self.ui['shadow'])

    def navigate(self, key):
        if getattr(self,'active_drag',None):
            self.active_drag.cancel()
        self.finish_section_rename()
        previous = getattr(self, 'current_section', None)
        self.current_section = key
        for name, page in self.pages.items():
            page.pack_forget()
            self.nav[name].selected = name==key
            self.nav[name].draw()
        self.pages[key].pack(fill='both',expand=True)
        # Never leave keyboard focus parked in a Text widget on a page that has
        # just been hidden.  This is especially important when entering Design,
        # whose temporary popup controls otherwise inherit a stale editor focus.
        # Programmatic callers that need a field (e.g. PDF double-click) focus it
        # immediately after navigate(), so this does not interfere with them.
        if previous != key and key in self.nav and self.nav[key].winfo_exists():
            self.nav[key].focus_set()
            self.after_idle(lambda:self.reveal_sidebar(self.nav[key]))

    def load(self, raw):
        if getattr(self,'active_drag',None):
            self.active_drag.cancel()
        self.finish_section_rename(commit=False)
        data = self.engine.migrate(raw)
        self.loading = True
        if hasattr(self,'sections'):
            self.sections.dispose()
        # A scrolled, long navigation canvas can leave its new shorter window
        # completely offscreen. Tk then defers its geometry, so width/wrapping
        # never catches up. Map the top before replacing section widgets.
        self.nav_canvas.yview_moveto(0)
        self.set_sidebar_width(data['settings'].get('sidebar_width',248))
        self.active_editor = None
        self._focused_surfaces.clear()
        self.revision += 1
        for widget in self.editor_host.winfo_children():
            widget.destroy()
        for key in list(self.nav):
            if is_custom(key):
                self.nav.pop(key).destroy()
        mode = data['settings'].get('ui_mode',DEFAULT_UI_MODE)
        self.v_ui_mode = tk.StringVar(value=mode if mode in PALETTES else DEFAULT_UI_MODE)
        self.v_button_theme = tk.StringVar(value=normalize_ui_theme(data['settings'].get('ui_theme')))
        self.v_ui_style = tk.StringVar(value=normalize_ui_style(data['settings'].get('ui_style')))
        self.ui.apply(self.v_ui_mode.get(),self.v_button_theme.get(),self.v_ui_style.get())
        self.pages, self.lists, self.fields, self.page_titles = {}, {}, {}, {}
        for key,title,description in NAVIGATION:
            self.create_page(key, title, description)
        for section in data['settings']['sections']:
            key = section['key']
            if is_custom(key):
                self.add_navigation(key, section['title'])
                self.create_page(key, section['title'], 'Your own space for awards, certifications, volunteering, or anything else.')
                self.lists[key] = ItemList(self.pages[key].inner,self,key,data['custom_sections'][key],section.get('entry_layout','auto'))
        group = InspectorGroup(self.pages['header'].inner,self,'Personal details')
        for key,label in [('name','Full name'),('role','Professional headline')]:
            self.fields[('personal',key)] = RichTextEditor(group,self,label,data['personal'][key],False,1)
        self.lists['contacts'] = ItemList(self.pages['header'].inner,self,'contacts',data['contacts'])
        group = InspectorGroup(self.pages['profile'].inner,self,'Professional summary')
        self.fields[('profile',)] = RichTextEditor(group,self,'Your introduction',data['profile'],True,8,
                                                  'Aim for a focused summary of roughly 60–100 words.',reorder_lines=True)
        for key in ('projects','skills','experience','education'):
            self.lists[key] = ItemList(self.pages[key].inner,self,key,data[key])
        self.sections = SectionState(self,data['settings']['sections'])
        self.build_settings(data['settings'])
        self.refresh_section_labels()
        self.navigate(self.current_section if self.current_section in self.pages else 'header')
        self.loading = False
        self.saved_data = self.collect()
        self.set_dirty(False)
        self.schedule_preview()
        # Retire variables owned by the previous inspector on Tk's thread.
        # Background PDF work may otherwise trigger their finalizers later.
        gc.collect()

    def create_page(self, key, title, description):
        area = ScrollArea(self.editor_host, self)
        self.pages[key] = area
        intro = Frame(area.inner, self.ui, 'bg', padx=22, pady=22)
        intro.pack(fill='x')
        heading = Label(intro, self.ui, title, font='title', bg='bg', justify='left')
        heading.pack(fill='x')
        heading.bind('<Configure>',lambda e,w=heading:w.configure(wraplength=max(160,e.width)))
        self.page_titles[key] = heading
        hint = Label(intro,self.ui,description,font='small',fg='muted',bg='bg',justify='left')
        hint.pack(fill='x',pady=(6,0))
        hint.bind('<Configure>',lambda e,w=hint:w.configure(wraplength=max(160,e.width)))
        if is_custom(key):
            options = Button(intro,self.ui,'Section options  ⋯',lambda: self.sidebar_menu(key,options),
                             kind='ghost',compact=True,bg='bg',font='small')
            options.pack(anchor='w',pady=(10,0))
            Tooltip(options,'Rename, hide, or remove this custom section')

    def build_settings(self, settings):
        host = self.pages['layout'].inner
        group = InspectorGroup(host,self,'Workspace','Choose the appearance of CV Studio.')
        row = Frame(group,self.ui)
        row.pack(fill='x')
        self.mode_buttons = {}
        for mode in ('Light','Dark'):
            b = Button(row,self.ui,mode,lambda m=mode:self.set_mode(m),width=96)
            b.selected = self.v_ui_mode.get()==mode
            b.draw()
            b.pack(side='left',padx=(0,8))
            self.mode_buttons[mode] = b
        Label(group,self.ui,'Interface style',font='label').pack(anchor='w',pady=(18,8))
        self.ui_style_choice = Choice(group,self,self.v_ui_style,list(UI_STYLES),
                                      lambda:self.set_ui_style(self.v_ui_style.get()),width=150)
        self.ui_style_choice.pack(anchor='w',pady=(0,6))
        style_hint = Label(group,self.ui,'Minimal keeps the workspace quiet. Vibrant uses colourful buttons and category cards.',
                           font='small',fg='muted',justify='left')
        style_hint.pack(fill='x',pady=(4,0))
        style_hint.bind('<Configure>',lambda e,w=style_hint:w.configure(wraplength=max(120,e.width)))
        self.button_theme_label = Label(group,self.ui,'Button theme',font='label')
        self.button_theme_choice = Choice(group,self,self.v_button_theme,list(BUTTON_THEMES),
                                          lambda:self.set_button_theme(self.v_button_theme.get()),
                                          width=None,compact=True,fit_menu=True,font='small')
        self.button_theme_choice.configure(height=max(28,self.button_theme_choice.font.metrics('linespace')+2))
        self.button_theme_hint = Label(group,self.ui,'Styles buttons, menus and selection highlights. Your PDF colours stay unchanged.',
                                       font='small',fg='muted',justify='left')
        self.button_theme_hint.bind('<Configure>',lambda e,w=self.button_theme_hint:w.configure(wraplength=max(120,e.width)))
        self.sync_button_theme_controls()
        group = InspectorGroup(host,self,'Document style','Colour and typography for the exported PDF.')
        self.v_template = tk.StringVar(value=settings.get('template',DEFAULT_TEMPLATE))
        self.v_photo = tk.StringVar(value=settings.get('photo',''))
        self.photo_crop = normalize_crop(settings.get('photo_crop'))
        self.v_theme = tk.StringVar(value=settings.get('theme','Navy Blue'))
        self.v_scale = tk.DoubleVar(value=settings.get('font_scale',100))
        self.v_margin = tk.StringVar(value=str(settings.get('margin_mm',13)))
        self.v_autofit = tk.BooleanVar(value=settings.get('autofit',True))
        Label(group,self.ui,'CV layout',font='label').pack(anchor='w',pady=(0,7))
        self.template_choice = Choice(group,self,self.v_template,list(TEMPLATES),self.template_changed,width=250)
        self.template_choice.pack(anchor='w',pady=(0,7))
        self.template_description = Label(group,self.ui,'',font='small',fg='muted',justify='left')
        self.template_description.pack(fill='x',pady=(0,16))
        self.template_description.bind('<Configure>',lambda e:self.template_description.configure(wraplength=max(120,e.width)))
        self.photo_panel = Frame(group,self.ui)
        self.photo_panel.pack(fill='x',pady=(0,16))
        photo_row = Frame(self.photo_panel,self.ui)
        photo_row.pack(fill='x')
        self.photo_thumb = tk.Canvas(photo_row,width=64,height=64,bd=0,highlightthickness=0)
        self.photo_thumb.pack(side='left',padx=(0,12))
        copy = Frame(photo_row,self.ui)
        copy.pack(side='left',fill='x',expand=True)
        Label(copy,self.ui,'Portrait',font='label').pack(anchor='w',pady=(6,4))
        self.photo_label = Label(copy,self.ui,'',font='small',fg='muted')
        self.photo_label.pack(anchor='w')
        actions = Frame(self.photo_panel,self.ui)
        actions.pack(fill='x',pady=(10,0))
        self.photo_choose = Button(actions,self.ui,'Upload photo…',self.choose_photo,compact=True)
        self.photo_choose.pack(side='left')
        self.photo_edit = Button(actions,self.ui,'Crop / Edit',self.edit_photo,compact=True,kind='ghost')
        self.photo_edit.pack(side='left',padx=4)
        self.photo_remove = Button(actions,self.ui,'Remove photo',self.remove_photo,kind='ghost',compact=True)
        self.photo_remove.pack(side='left')
        Label(group,self.ui,'Colour theme',font='label').pack(anchor='w',pady=(0,7))
        Choice(group,self,self.v_theme,list(self.engine.THEMES),self.changed).pack(anchor='w',pady=(0,18))
        Label(group,self.ui,'Text size',font='label').pack(anchor='w')
        row = Frame(group,self.ui)
        row.pack(fill='x',pady=(8,0))
        self.scale_label = Label(row,self.ui,f'{self.v_scale.get():.0f}%',font='small',width=5,anchor='e')
        self.scale_label.pack(side='right',padx=(10,0))
        Slider(row,self.ui,self.v_scale,80,115,self.scale_changed).pack(side='left',fill='x',expand=True)
        group = InspectorGroup(host,self,'Page layout')
        Label(group,self.ui,'Top & bottom margins',font='label').pack(anchor='w',pady=(0,8))
        row = Frame(group,self.ui)
        row.pack(fill='x',pady=(0,14))
        Button(row,self.ui,'−',lambda:self.step_margin(-1),width=32,compact=True,kind='ghost').pack(side='left')
        self.margin_entry = ttk.Entry(row,textvariable=self.v_margin,width=5,justify='center',cursor='xterm')
        self.margin_entry.pack(side='left',padx=6)
        Button(row,self.ui,'+',lambda:self.step_margin(1),width=32,compact=True,kind='ghost').pack(side='left')
        Label(row,self.ui,'mm',font='small',fg='muted').pack(side='left',padx=8)
        self.v_margin.trace_add('write',lambda *_:self.changed())
        self.margin_entry.bind('<FocusOut>',lambda e:self.v_margin.set(str(self.number(self.v_margin.get(),13,6,24))))
        Toggle(group,self,self.v_autofit,'Auto-fit to one page',self.changed).pack(anchor='w')
        hint = Label(group,self.ui,'Gently reduces text size when the CV needs more space.',font='small',fg='muted',justify='left')
        hint.pack(fill='x',pady=(6,0))
        hint.bind('<Configure>',lambda e:hint.configure(wraplength=max(120,e.width)))
        self.template_changed(render=False)

    def template_changed(self, render=True):
        template = TEMPLATES.get(self.v_template.get(),TEMPLATES[DEFAULT_TEMPLATE])
        self.template_description.configure(text=template.description)
        self.refresh_photo_controls()
        if template.photo:
            self.photo_panel.pack(fill='x',pady=(0,16),after=self.template_description)
        else:
            self.photo_panel.pack_forget()
        if render:
            self.changed()

    def choose_photo(self):
        path = filedialog.askopenfilename(parent=self,title='Choose a CV photo',initialdir=self.last_dir,
                     filetypes=[('Image files','*.png *.jpg *.jpeg'),('PNG image','*.png'),('JPEG image','*.jpg *.jpeg')])
        if not path:
            return
        try:
            encoded = import_photo(path)
            self.last_dir = str(Path(path).parent)
            self.photo_dialog = PhotoCropDialog(self,encoded,None,self.apply_photo)
        except (OSError,ValueError,ImportError) as error:
            messagebox.showerror('Could not use photo',str(error),parent=self)

    def edit_photo(self):
        if self.v_photo.get():
            try:
                self.photo_dialog = PhotoCropDialog(self,self.v_photo.get(),self.photo_crop,self.apply_photo)
            except (OSError,ValueError,ImportError) as error:
                messagebox.showerror('Could not edit photo',str(error),parent=self)

    def apply_photo(self, encoded, crop):
        self.v_photo.set(encoded)
        self.photo_crop = normalize_crop(crop)
        self.refresh_photo_controls()
        self.changed()

    def refresh_photo_controls(self):
        has_photo = bool(self.v_photo.get())
        self.photo_label.configure(text='Drag & zoom to adjust your portrait' if has_photo else 'Optional · the layout also works without one')
        self.photo_choose.text = 'Replace photo…' if has_photo else 'Upload photo…'
        self.photo_choose.draw()
        for button in (self.photo_edit,self.photo_remove):
            button.enabled = has_photo
            button.draw()
        self.photo_thumb.configure(bg=self.ui['surface'])
        self.photo_thumb.delete('all')
        if has_photo:
            try:
                from PIL import ImageTk
                thumbnail = crop_image(decode_photo(self.v_photo.get()),self.photo_crop,size=64,circle=True)
                self.photo_thumbnail = ImageTk.PhotoImage(thumbnail,master=self)
                self.photo_thumb.create_image(0,0,image=self.photo_thumbnail,anchor='nw')
                return
            except (OSError,ValueError,ImportError):
                self.photo_label.configure(text='Photo unavailable · replace it to continue')
        self.photo_thumb.create_oval(2,2,62,62,fill=self.ui['field'],outline=self.ui['line'])
        self.photo_thumb.create_text(32,32,text='+',font=self.ui.fonts['title'],fill=self.ui['muted'])

    def remove_photo(self):
        if self.v_photo.get():
            self.v_photo.set('')
            self.photo_crop = normalize_crop()
            self.refresh_photo_controls()
            self.changed()

    def refresh_section_labels(self):
        if not hasattr(self,'sections'):
            return
        for row in self.sections.rows:
            title = row['title'].get().strip() or row['key'].title()
            key = row['key']
            label = title.title() if title.isupper() else title
            if key in self.nav:
                button = self.nav[key]
                button.text = label
                button.hidden = not row['visible'].get()
                button.draw()
            if key in self.page_titles:
                self.page_titles[key].configure(text=title.title() if title.isupper() else title)
        for row in self.sections.rows:
            key = row['key']
            button = self.nav[key]
            button.pack_forget()
            button.pack(fill='x',pady=4,before=self.design_separator)

    def set_mode(self, mode):
        self.v_ui_mode.set(mode)
        self.ui.apply(mode)
        for name,b in self.mode_buttons.items():
            b.selected = name==mode
            b.draw()
        self.refresh_photo_controls()
        self.changed(render=False)

    def set_button_theme(self, theme):
        theme = normalize_ui_theme(theme)
        self.v_button_theme.set(theme)
        self.ui.apply(self.v_ui_mode.get(),theme)
        self.refresh_photo_controls()
        self.changed(render=False)
        self.status.set(theme+' button theme · PDF colours unchanged')

    def set_ui_style(self, style):
        style = normalize_ui_style(style)
        self.v_ui_style.set(style)
        self.ui.apply(self.v_ui_mode.get(),self.v_button_theme.get(),style)
        self.sync_button_theme_controls()
        self.refresh_photo_controls()
        self.changed(render=False)
        self.status.set(style+' interface style · PDF colours unchanged')

    def sync_button_theme_controls(self):
        if self.v_ui_style.get() == 'Vibrant':
            self.button_theme_label.pack(anchor='w',pady=(18,8))
            self.button_theme_choice.pack(anchor='w',pady=(0,6))
            self.button_theme_hint.pack(fill='x',pady=(4,0))
        else:
            for widget in (self.button_theme_label,self.button_theme_choice,self.button_theme_hint):
                widget.pack_forget()

    def scale_changed(self, value=None):
        self.scale_label.configure(text=f'{self.v_scale.get():.0f}%')
        self.changed()

    def step_margin(self, delta):
        self.v_margin.set(str(self.number(self.number(self.v_margin.get(),13,6,24)+delta,13,6,24)))

    @staticmethod
    def number(value,default,lo,hi):
        try:
            return max(lo,min(hi,round(float(value))))
        except (ValueError,TypeError):
            return default

    def collect(self):
        data = dict(version=2,personal={key:self.fields[('personal',key)].get() for key in ('name','role')},
                    profile=self.fields[('profile',)].get())
        data.update({key:items.get_items() for key,items in self.lists.items() if not is_custom(key)})
        data['custom_sections'] = {key:items.get_items() for key,items in self.lists.items() if is_custom(key)}
        data['settings'] = dict(theme=self.v_theme.get(),ui_mode=self.v_ui_mode.get(),ui_theme=self.v_button_theme.get(),
                                ui_style=self.v_ui_style.get(),
                                sidebar_width=self.sidebar_width,
                                template=self.v_template.get(),photo=self.v_photo.get(),
                                photo_crop=dict(self.photo_crop),
                                font_scale=self.number(self.v_scale.get(),100,80,115),
                                margin_mm=self.number(self.v_margin.get(),13,6,24),autofit=self.v_autofit.get(),
                                sections=self.sections.get())
        return data

    def set_dirty(self, value):
        self.dirty = value
        name = Path(self.json_path).stem.replace('_',' ') if self.json_path else 'Untitled CV'
        self.document_name.set(name[:60])
        self.save_state.set('●  Unsaved changes' if value else ('Saved on this device' if self.json_path else self.edition+' document · ready to personalise'))
        self.title(f'{"● " if value else ""}{name} — CV Studio')

    def changed(self, render=True):
        if self.loading or self.closing:
            return
        self.set_dirty(self.collect()!=self.saved_data)
        if render:
            self.revision += 1
            self.schedule_preview()

    def wheel(self, event, direction=None):
        widget = self.winfo_containing(event.x_root,event.y_root)
        horizontal = bool(event.state & 1)
        if direction is None:
            delta = event.delta
            amount = -int(delta/120*40) if sys.platform!='darwin' else -int(delta*2)
            if not amount and delta:
                amount = -1 if delta>0 else 1
        else:
            amount = direction*40
        if not amount:
            return 'break'
        # Long text scrolls internally until its edge; then the inspector scrolls.
        if isinstance(widget,tk.Text) and not horizontal:
            first,last = widget.yview()
            if (amount<0 and first>0) or (amount>0 and last<1):
                widget.yview_scroll(-2 if amount<0 else 2,'units')
                return 'break'
        while widget:
            canvas = getattr(widget,'scroll_target',None)
            if canvas is not None:
                if horizontal:
                    canvas.xview_scroll(amount,'units')
                else:
                    canvas.yview_scroll(amount,'units')
                return 'break'
            widget = widget.master
        return 'break'

    def open_app_menu(self, name):
        if name=='File':
            items = [('New from starter…','',self.reset_defaults), ('Open CV…','Ctrl+O',self.open_file),
                     ('Save','Ctrl+S',self.save), ('Save as…','Ctrl+Shift+S',self.save_as), None,
                     ('Export PDF…','Ctrl+E',self.export_pdf), ('Open exported PDF','',self.open_pdf,bool(self.last_pdf)),
                     None, ('Exit','',self.on_close)]
        elif name=='Edit':
            items = self.edit_menu()
        elif name=='View':
            items = [('Zoom in','',lambda:self.set_zoom(1.15)), ('Zoom out','',lambda:self.set_zoom(1/1.15)),
                     ('Fit page','',lambda:self.fit('page')), ('Fit width','',lambda:self.fit('width')), None,
                     (('✓  ' if self.ui.mode=='Light' else '')+'Light appearance','',lambda:self.set_mode('Light')),
                     (('✓  ' if self.ui.mode=='Dark' else '')+'Dark appearance','',lambda:self.set_mode('Dark'))]
        else:
            items = [('Formatting & shortcuts','F1',self.show_tips), ('About CV Studio','',self.show_about)]
        PopupMenu(self,self.menu_buttons[name],items)
        return 'break'

    def edit_menu(self):
        editor = self.active_editor
        exists = editor is not None and editor.winfo_exists()
        return [('Undo','Ctrl+Z',lambda:self.edit_action('undo'),exists and editor.history_pos>0),
                ('Redo','Ctrl+Y',lambda:self.edit_action('redo'),exists and editor.history_pos+1<len(editor.history)), None,
                ('Cut','Ctrl+X',lambda:self.edit_action('cut'),exists),
                ('Copy','Ctrl+C',lambda:self.edit_action('copy'),exists),
                ('Paste','Ctrl+V',lambda:self.edit_action('paste'),exists), None,
                ('Select all','Ctrl+A',lambda:self.edit_action('select_all'),exists)]

    def edit_action(self, action):
        editor = self.active_editor
        if editor and editor.winfo_exists():
            editor.input.focus_set()
            if action in ('cut','copy','paste'):
                editor.input.event_generate('<<'+action.title()+'>>')
            else:
                getattr(editor,action)()

    def zoom_menu(self):
        PopupMenu(self,self.zoom_button,[('Fit page','',lambda:self.fit('page')),('Fit width','',lambda:self.fit('width')),
                                        None,('100%','',lambda:self.zoom_to(1)),('150%','',lambda:self.zoom_to(1.5))])

    def set_zoom(self,factor):
        self.zoom_to(self._effective_scale*factor)

    def zoom_to(self,value):
        self._zoom = max(.3,min(3,value))
        self.zoom_mode = 'manual'
        self.request_raster()

    def fit(self,mode='page'):
        self.zoom_mode = mode
        self.request_raster()

    def preview_resize(self,event=None):
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(160,self.request_raster)

    def schedule_preview(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(420,self.refresh_preview)

    def refresh_preview(self):
        self._job = None
        if self.closing:
            return
        if self.render_future is not None:
            self.schedule_preview()
            return
        self.preview_state.set('Updating…')
        data, revision = deepcopy(self.collect()), self.revision
        self.render_future = self.executor.submit(self.render_document,data,revision)

    def render_document(self,data,revision):
        regions = []
        with PDF_LOCK:
            pdf,pages,links,af = self.engine.render_pdf(data,source_map=regions)
        return revision,data,pdf,pages,links,af,regions

    def request_raster(self):
        self._resize_job = None
        if not self._pdf or self.closing:
            return
        if self.engine.pymupdf is None:
            self.pcanvas.delete('all')
            self.pcanvas.create_text(32,40,anchor='nw',width=300,fill=self.ui['text'],font=self.ui.fonts['body'],
                                    text='Live preview needs PyMuPDF.\nInstall with: pip install pymupdf\n\nPDF export remains available.')
            return
        self.raster_revision += 1
        if self.raster_future is not None:
            return
        width,height = self.pcanvas.winfo_width(),self.pcanvas.winfo_height()
        if width<40 or height<40:
            return
        self.raster_future = self.executor.submit(self.rasterize,self._pdf,width,height,self._zoom,self.zoom_mode,self.raster_revision)

    def rasterize(self,pdf,width,height,zoom,mode,revision):
        fitz = self.engine.pymupdf
        images = []
        with fitz.open(stream=pdf,filetype='pdf') as document:
            for page in document:
                scale = zoom
                if mode in ('page','width'):
                    scale = max(.1,(width-64)/page.rect.width)
                    if mode=='page':
                        scale = min(scale,max(.1,(height-48)/page.rect.height))
                pix = page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
                images.append((pix.tobytes('png'),pix.width,pix.height,scale))
        return revision,images

    def poll_worker(self):
        if self.closing:
            return
        if self.render_future is not None and self.render_future.done():
            future,self.render_future = self.render_future,None
            try:
                rev,data,pdf,pages,links,af,regions = future.result()
                if rev==self.revision:
                    self._pdf,self._source_map,self.rendered_data = pdf,regions,data
                    self.preview_state.set('Live · Up to date')
                    self.document_stats.set(f'{pages} '+('page' if pages==1 else 'pages')+
                                            f'   ·   {links} links'+(f'   ·   Auto-fit {round(af*100)}%' if af<1 else '')+
                                            ('   ·   Consider trimming' if pages>1 else ''))
                    self.request_raster()
                else:
                    self.schedule_preview()
            except Exception as error:
                self.preview_state.set('Layout needs attention')
                self.status.set('Preview: '+str(error)[:180])
        if self.raster_future is not None and self.raster_future.done():
            future,self.raster_future = self.raster_future,None
            try:
                revision,images = future.result()
                if revision==self.raster_revision:
                    self.draw_preview(images)
                else:
                    self.request_raster()
            except Exception as error:
                self.status.set('Preview could not be displayed: '+str(error)[:160])
        self.after(50,self.poll_worker)

    def draw_preview(self,images):
        c = self.pcanvas
        top,left = c.yview()[0],c.xview()[0]
        # Construct every new PhotoImage before replacing the old canvas contents.
        photos = [tk.PhotoImage(master=self,data=base64.b64encode(png)) for png,_,_,_ in images]
        c.delete('all')
        self._photos,self._preview_pages = photos,[]
        self._displayed_pdf = self._pdf
        y,maxw,cw = 24,0,c.winfo_width()
        for number,((png,w,h,scale),photo) in enumerate(zip(images,photos)):
            x = max(24,(cw-w)//2)
            c.create_rectangle(x+3,y+4,x+w+3,y+h+4,fill=self.ui['shadow'],outline='',tags='shadow')
            c.create_image(x,y,image=photo,anchor='nw')
            self._preview_pages.append(dict(number=number,x=x,y=y,width=w,height=h,scale=scale))
            y += h+24
            maxw = max(maxw,x+w+24)
        c.configure(scrollregion=(0,0,max(cw,maxw),y))
        c.yview_moveto(top)
        c.xview_moveto(left)
        if images:
            self._effective_scale = images[0][3]
        self.zoom_button.text = {'page':'Fit page','width':'Fit width'}.get(self.zoom_mode,f'{round(self._effective_scale*100)}%')
        self.zoom_button.draw()

    def preview_hit(self,event):
        x,y = self.pcanvas.canvasx(event.x),self.pcanvas.canvasy(event.y)
        for page in self._preview_pages:
            if page['x']<=x<=page['x']+page['width'] and page['y']<=y<=page['y']+page['height']:
                px,py = (x-page['x'])/page['scale'],(y-page['y'])/page['scale']
                hits = [r for r in self._source_map if r['page']==page['number'] and
                        r['rect'][0]<=px<=r['rect'][2] and r['rect'][1]<=py<=r['rect'][3]]
                if hits:
                    region = min(hits,key=lambda r:(r['rect'][2]-r['rect'][0])*(r['rect'][3]-r['rect'][1]))
                    return region,page,px,py
        return None

    def preview_pointer(self,event):
        self.pcanvas.configure(cursor='hand2' if self.preview_hit(event) else '')

    def preview_double_click(self,event):
        # A stale preview can refer to an entry which has just moved or been removed.
        current, rendered = self.collect(), deepcopy(getattr(self,'rendered_data',None))
        if rendered:
            rendered['settings']['ui_mode'] = current['settings']['ui_mode']
            rendered['settings']['ui_theme'] = current['settings']['ui_theme']
            rendered['settings']['ui_style'] = current['settings']['ui_style']
            rendered['settings']['sidebar_width'] = current['settings']['sidebar_width']
        if not self._pdf or current!=rendered or self._displayed_pdf!=self._pdf:
            self.status.set('The preview is updating. Try again in a moment.')
            return
        hit = self.preview_hit(event)
        if not hit:
            return
        region,page,px,py = hit
        source = region['source']
        field = card = None
        if source[0]=='section':
            self.rename_section(source[1])
            return
        if source[0]=='personal':
            self.navigate('header')
            field = self.fields[tuple(source)]
        elif source[0]=='profile':
            self.navigate('profile')
            field = self.fields[('profile',)]
        else:
            key = source[0]
            self.navigate('header' if key=='contacts' else key)
            index = source[1] if len(source)>1 else 0
            field_key = source[2] if len(source)>2 else 'text'
            if key=='contacts' or field_key=='identity':
                # Combined PDF paragraphs are narrowed using their actual layout box.
                candidates = [(i,'text',c.get().get('text') or self.engine.display_url(c.get().get('url','')))
                              for i,c in enumerate(self.lists[key].cards)] if key=='contacts' else [
                                  (index,k,self.lists[key].cards[index].get()[k]) for k in ('title','company','dates')]
                best = None
                if self.engine.pymupdf:
                    with self.engine.pymupdf.open(stream=self._pdf,filetype='pdf') as doc:
                        for i,k,value in candidates:
                            for rect in doc[region['page']].search_for(plain(value)) if value else []:
                                if rect.x0<=px<=rect.x1 and rect.y0<=py<=rect.y1:
                                    best = i,k
                                    break
                if best:
                    index,field_key = best
                elif key=='experience':
                    field_key='title'
                elif key=='contacts':
                    return
            if index>=len(self.lists[key].cards):
                return
            card = self.lists[key].cards[index]
            field = card.fields[field_key]
        if field:
            self.reveal_field(field,card,line=source[3] if len(source)>3 else None)
            r = region['rect']
            c = self.pcanvas
            c.delete('edit-target')
            c.create_rectangle(page['x']+r[0]*page['scale'],page['y']+r[1]*page['scale'],
                               page['x']+r[2]*page['scale'],page['y']+r[3]*page['scale'],
                               outline=self.ui['accent'],width=2,tags='edit-target')
            self.after(900,lambda:c.delete('edit-target') if c.winfo_exists() else None)

    def reveal_field(self,field,card=None,line=None):
        if card:
            card.set_expanded(True)
        self.update_idletasks()
        self.pages[self.current_section].reveal(field)
        field.input.focus_set()
        if line is not None:
            field.input.mark_set('insert',f'{line+1}.0')
        field.input.see('insert')
        self.active_editor = field
        self.status.set('Editing '+field.label.lower())

    def confirm_replace(self):
        if not self.dirty:
            return True
        result = messagebox.askyesnocancel('Unsaved changes','Save your changes before continuing?',parent=self)
        return False if result is None else (self.save() if result else True)

    def _write_json(self,path):
        self.finish_section_rename()
        data = self.collect()
        # Replace only after the new document has been written successfully.
        target = Path(path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=target.parent,
                                             prefix=target.name+'.',suffix='.tmp',delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(data,stream,ensure_ascii=False,indent=2)
            os.replace(temporary,target)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()
        self.json_path,self.last_dir = str(target),str(target.parent)
        self.saved_data = data
        self.set_dirty(False)
        self.status.set('Saved '+target.name)

    def save(self):
        self.finish_section_rename()
        if not self.json_path:
            return self.save_as()
        try:
            self._write_json(self.json_path)
            return True
        except Exception as error:
            messagebox.showerror('Could not save',str(error),parent=self)
            return False

    def save_as(self):
        self.finish_section_rename()
        path = filedialog.asksaveasfilename(parent=self,title='Save CV data',defaultextension='.json',
                    initialdir=self.last_dir,initialfile=Path(self.json_path).name if self.json_path else 'my_cv_data.json',
                    filetypes=[('CV data','*.json')])
        if not path:
            return False
        try:
            self._write_json(path)
            return True
        except Exception as error:
            messagebox.showerror('Could not save',str(error),parent=self)
            return False

    def open_file(self):
        path = filedialog.askopenfilename(parent=self,title='Open CV data',initialdir=self.last_dir,filetypes=[('CV data','*.json')])
        if not path:
            return
        try:
            with open(path,encoding='utf-8') as stream:
                raw = json.load(stream)
            # Validate the PDF before replacing any of the user's current content.
            data = self.engine.migrate(raw)
            with PDF_LOCK:
                self.engine.render_pdf(data)
            if not self.confirm_replace():
                return
            self.json_path,self.last_dir = path,str(Path(path).parent)
            self.load(data)
            self.status.set('Opened '+Path(path).name)
        except Exception as error:
            messagebox.showerror('Could not open CV','The file could not be loaded.\n\n'+str(error),parent=self)

    def reset_defaults(self):
        if self.confirm_replace():
            self.json_path = None
            self.load(deepcopy(self.engine.DEFAULT_DATA))
            self.status.set('New '+self.edition.lower()+' CV')

    def default_pdf_name(self):
        name = re.sub(r'[^\w]+','_',self.fields[('personal','name')].get().title()).strip('_')
        return 'My_CV.pdf' if name in ('','Your_Name') else name+'_CV.pdf'

    def export_pdf(self):
        self.finish_section_rename()
        path = filedialog.asksaveasfilename(parent=self,title='Export PDF',initialdir=self.last_dir,
                    initialfile=self.default_pdf_name(),defaultextension='.pdf',filetypes=[('PDF document','*.pdf')])
        if not path:
            return
        try:
            with PDF_LOCK:
                pdf,pages,links,af = self.engine.render_pdf(self.collect())
            Path(path).write_bytes(pdf)
            self.last_pdf,self.last_dir = path,str(Path(path).parent)
            self.status.set(f'Exported {Path(path).name} · {pages} '+('page' if pages==1 else 'pages'))
            if pages>1:
                messagebox.showinfo('PDF exported',f'Your CV uses {pages} pages. You can trim content or adjust text size in Design.',parent=self)
        except Exception as error:
            messagebox.showerror('Could not export PDF',str(error),parent=self)

    def open_pdf(self):
        if not self.last_pdf or not Path(self.last_pdf).exists():
            self.status.set('Export a PDF first.')
            return
        try:
            if sys.platform=='win32':
                os.startfile(self.last_pdf)
            else:
                subprocess.Popen(['open' if sys.platform=='darwin' else 'xdg-open',self.last_pdf])
        except OSError as error:
            messagebox.showerror('Could not open PDF',str(error),parent=self)

    def center_dialog(self,dialog):
        dialog.update_idletasks()
        x=self.winfo_rootx()+(self.winfo_width()-dialog.winfo_reqwidth())//2
        y=self.winfo_rooty()+(self.winfo_height()-dialog.winfo_reqheight())//2
        dialog.geometry(f'+{max(0,x)}+{max(0,y)}')

    def info_dialog(self,title,text):
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        body=Frame(dialog,self.ui,padx=28,pady=24)
        body.pack(fill='both',expand=True)
        Label(body,self.ui,title,font='heading').pack(anchor='w',pady=(0,16))
        Label(body,self.ui,text,justify='left',wraplength=420).pack(anchor='w')
        Button(body,self.ui,'Done',dialog.destroy,kind='primary').pack(anchor='e',pady=(24,0))
        dialog.bind('<Escape>',lambda e:dialog.destroy())
        self.center_dialog(dialog)

    def show_tips(self):
        self.info_dialog('Formatting & shortcuts',
            'Select text, then use B, I, or Link in its toolbar. Bold and italic can be combined. '
            'Click Clear to remove formatting. With no selection, formatting applies to what you type next.\n\n'
            'Ctrl+B    Bold\nCtrl+I      Italic\nCtrl+K    Insert or edit link\nCtrl+Z / Ctrl+Y    Undo / redo\n\n'
            'Ctrl+S    Save\nCtrl+Shift+S    Save as\nCtrl+O    Open\nCtrl+E    Export PDF\n\n'
            '+ Add Section creates a custom category. Name it in the sidebar; Enter saves, Esc cancels. '
            'Drag to reorder, double-click or press F2 to rename. Right-click a category and toggle Show on CV to hide/show it without deleting content.\n\n'
            'Design → Workspace offers light/dark mode and button themes; PDF colours are separate.\n\n'
            'Double-click PDF text to jump to its field.\nDouble-click a Document sidebar section to rename it. Drag to reorder; right-click for options.\n'
            'Use each entry’s … menu to move, duplicate, or remove it.\n'
            'Hold Shift while scrolling to move horizontally in the preview.')

    def show_about(self):
        self.info_dialog('CV Studio','A focused workspace for a considered CV.\n\n'
                         'Visual text editing, a live document preview, and print-ready PDF export.\n\n'+self.edition+' edition')

    def on_close(self):
        if self.confirm_replace():
            self.destroy()

    def destroy(self):
        if self.closing:
            return
        self.finish_section_rename(commit=False)
        if getattr(self,'active_drag',None):
            self.active_drag.cancel()
        self.closing = True
        if hasattr(self,'sections'):
            self.sections.dispose()
        for job in self.tk.splitlist(self.tk.call('after','info')):
            self.after_cancel(job)
        self.executor.shutdown(wait=False,cancel_futures=True)
        super().destroy()
