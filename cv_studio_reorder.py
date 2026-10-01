"""Insertion-based dragging shared by navigation, cards and rich-text lines.

Hit testing uses stable slots while real widgets animate around a lifted preview.
The data changes only on drop. No editable widgets are rebuilt or reparented.
"""
import tkinter as tk
import time


def can_scroll_view(widget, direction):
    """Tk canvases can accept scroll calls even when their content already fits."""
    if isinstance(widget,tk.Canvas):
        region = widget.cget('scrollregion')
        if not region:
            return False
        _,y0,_,y1 = map(float,widget.tk.splitlist(region))
        if y1-y0 <= widget.winfo_height()+1:
            return False
    first,last = widget.yview()
    return first>1e-5 if direction<0 else last<1-1e-5


def round_rect(canvas,x,y,w,h,r,**kwargs):
    points=[x+r,y,x+w-r,y,x+w,y,x+w,y+r,x+w,y+h-r,
            x+w,y+h,x+w-r,y+h,x+r,y+h,x,y+h,x,y+h-r,x,y+r,x,y]
    return canvas.create_polygon(points,smooth=True,splinesteps=24,**kwargs)


class PackedListMotion:
    """Temporarily place existing packed widgets, preserving focus and list height.

    Collision slots never depend on animated positions, so a moving neighbour
    cannot change the selected target or cause back-and-forth oscillation.
    """
    def __init__(self, host, widgets, source, on_restore, ui):
        self.host,self.widgets,self.source,self.on_restore,self.ui=host,widgets,source,on_restore,ui
        self.active=True
        self.original_height=host.cget('height')
        self.propagate=host.pack_propagate()
        self.padx=int(host.cget('padx'))
        self.pady=int(host.cget('pady'))
        self.packed=[(w,w.pack_info(),w.winfo_x(),w.winfo_y(),w.winfo_width(),w.winfo_height())
                     for w in host.pack_slaves()]
        self.slots=[(key,w.winfo_x(),w.winfo_y(),w.winfo_width(),w.winfo_height()) for key,w in widgets]
        self.old=next(i for i,row in enumerate(self.slots) if row[0]==source)
        self.target=self.old
        self.current={key:y for key,_,y,_,_ in self.slots}
        self.positions=dict(self.current)
        self.start_positions=dict(self.current)
        self.started=time.monotonic()
        host.configure(height=host.winfo_height())
        host.pack_propagate(False)
        source_widget=dict(widgets)[source]
        for widget,_,x,y,width,height in self.packed:
            widget.pack_forget()
            if widget is not source_widget:
                widget.place(x=x-self.padx,y=y-self.pady,width=width,height=height)
        self.slot=tk.Canvas(host,bd=0,highlightthickness=0,cursor='fleur',bg=ui[getattr(host,'role','bg')])
        self.draw_slot()

    def rows(self):
        x,y=self.host.winfo_rootx(),self.host.winfo_rooty()
        return [(key,x+rx,y+ry,w,h) for key,rx,ry,w,h in self.slots]

    def target_rect(self):
        _,x,_,w,h=self.slots[self.old]
        return (self.host.winfo_rootx()+x,self.host.winfo_rooty()+self.positions[self.source],w,h)

    def set_target(self,target):
        if target==self.target:
            return
        self.target=target
        self.start_positions=dict(self.current)
        self.started=time.monotonic()
        order=[r[0] for r in self.slots]
        order.insert(target,order.pop(self.old))
        heights={key:h for key,_,_,_,h in self.slots}
        gap=(self.slots[1][2]-self.slots[0][2]-self.slots[0][4]) if len(self.slots)>1 else 0
        y=self.slots[0][2]
        for key in order:
            self.positions[key]=y
            y+=heights[key]+gap
        self.draw_slot()

    def draw_slot(self):
        x,y,w,h=self.target_rect()
        self.slot.place(x=x-self.host.winfo_rootx()-self.padx,
                        y=y-self.host.winfo_rooty()-self.pady,width=w,height=h)
        self.slot.delete('all')
        round_rect(self.slot,2,2,w-4,h-4,12,fill=self.ui['tint'],outline=self.ui['line'],width=1)
        self.slot.create_line(12,3,w-12,3,fill=self.ui['accent'],width=2)
        # Use Tk's window stacking operation, not Canvas.lower (which lowers items).
        self.slot.tk.call('lower',self.slot._w)

    def tick(self):
        progress=min(1,(time.monotonic()-self.started)/.16)
        ease=1-(1-progress)**3
        sizes={key:(x,w,h) for key,x,_,w,h in self.slots}
        for key,widget in self.widgets:
            self.current[key]=self.start_positions[key]+(self.positions[key]-self.start_positions[key])*ease
            if key!=self.source:
                x,w,h=sizes[key]
                widget.place_configure(x=x-self.padx,y=round(self.current[key])-self.pady,width=w,height=h)

    def restore(self):
        if not self.active:
            return
        self.active=False
        self.slot.destroy()
        for widget,info,*_ in self.packed:
            if widget.winfo_exists():
                widget.place_forget()
                widget.pack(**info)
        self.host.configure(height=self.original_height)
        self.host.pack_propagate(self.propagate)
        if self.on_restore:
            self.on_restore()


class ReorderController:
    def __init__(self, app, host, rows, commit, viewport=None, scroll=None, label='item',
                 can_scroll=None, widgets=None, on_layout_end=None, describe=None, ghost_painter=None):
        self.app, self.host = app, host
        self.rows, self.commit = rows, commit  # [(identity, x, y, width, height)] in screen coordinates
        self.viewport, self.scroll, self.label = viewport or host, scroll, label
        self.can_scroll = can_scroll or (lambda direction: can_scroll_view(self.viewport,direction))
        self.widgets,self.on_layout_end,self.describe=widgets,on_layout_end,describe
        self.ghost_painter=ghost_painter
        self.layout=None
        self.animation=None
        self.cursor_states=[]
        self.capture_bindings=[]
        self.state = None
        self.job = self.escape_binding = None
        self.marker = tk.Frame(app, height=3, bd=0)
        self.ghost=tk.Canvas(app,bd=0,highlightthickness=0,cursor='fleur',takefocus=0)
        host.bind('<Destroy>', self.destroy, add='+')

    @staticmethod
    def widget_rows(items):
        return [(key, widget.winfo_rootx(), widget.winfo_rooty(),
                 widget.winfo_width(), widget.winfo_height()) for key, widget in items]

    def bind(self, widget, key, click=None):
        # Replace mouse handlers only. Native editable Text widgets never use this binding.
        widget.bind('<ButtonPress-1>', lambda e: self.start(key, e, widget, click),add='+')
        widget.bind('<B1-Motion>', self.motion)
        widget.bind('<ButtonRelease-1>', self.end)
        widget.bind('<Alt-Up>', lambda e: self.step(key, -1))
        widget.bind('<Alt-Down>', lambda e: self.step(key, 1))

    def start(self, key, event, widget=None, click=None):
        active = getattr(self.app, 'active_drag', None)
        if active:
            active.cancel()
        self.app.finish_section_rename()
        self.app.active_drag = self
        self.state = dict(key=key, x=event.x_root, y=event.y_root, moved=False,
                          target=None, widget=widget, click=click, settling=False,
                          previous_status=self.app.status.get())
        self.escape_binding = self.app.bind('<Escape>', self.cancel, add='+')
        if widget is not None:
            widget.grab_set()
            if hasattr(widget, '_state'):
                widget._state('pressed', True)
        return 'break'

    def motion(self, event):
        state = self.state
        if not state or state['settling']:
            return 'break'
        if not state['moved'] and max(abs(event.x_root-state['x']), abs(event.y_root-state['y'])) < 6:
            return 'break'
        if not state['moved']:
            self.lift()
            state['moved'] = True
        state['pointer'] = (event.x_root, event.y_root)
        self.feedback(*state['pointer'])
        if self.scroll and self.job is None:
            self.job = self.app.after(24, self.autoscroll)
        return 'break'

    def lift(self):
        state=self.state
        row=next(r for r in self.rows() if r[0]==state['key'])
        _,x,y,w,h=row
        state['offset']=(state['x']-x,min(state['y']-y,55))
        p=self.app.ui
        if self.ghost_painter:
            gw,gh=self.ghost_painter(self.ghost,state['key'],w)
            state['ghost_size']=(gw,gh)
            self.ghost.configure(width=gw,height=gh)
        else:
            title,subtitle=(self.describe(state['key']) if self.describe else (self.label.title(),''))
            height=84 if subtitle else max(34,min(48,h))
            state['ghost_size']=(w+12,height+12)
            self.ghost.configure(width=w+12,height=height+12,bg=p['bg'])
            self.ghost.delete('all')
            round_rect(self.ghost,5,7,w+2,height+2,11,fill=p['line'],outline='')
            round_rect(self.ghost,3,4,w+2,height+2,10,fill=p['shadow'],outline='')
            round_rect(self.ghost,1,1,w,height,9,fill=p['surface'],outline=p['accent'],width=1)
            title_y=24 if subtitle else height/2
            self.ghost.create_text(13,title_y,text='⠿',font=p.fonts['small'],fill=p['accent'],anchor='w')
            def fit(text,font):
                while len(text)>2 and font.measure(text)>w-45:
                    text=text[:-2]+'…'
                return text
            title_font=p.fonts['bold' if subtitle else 'body']
            self.ghost.create_text(29,title_y,text=fit(title,title_font),font=title_font,fill=p['text'],anchor='w')
            if subtitle:
                self.ghost.create_text(29,53,text=fit(subtitle,p.fonts['small']),font=p.fonts['small'],fill=p['muted'],anchor='w')
        if self.widgets:
            self.layout=PackedListMotion(self.host,self.widgets(),state['key'],self.on_layout_end,p)
        # The real source may be temporarily unmapped. Capture at the toplevel
        # so dragging also continues over padding, sibling widgets and outside.
        self.app.grab_set()
        for sequence,callback in (('<B1-Motion>',self.motion),('<ButtonRelease-1>',self.end)):
            self.capture_bindings.append((sequence,self.app.bind(sequence,callback,add='+')))
        # Some children explicitly use arrow/xterm/hand2. An inherited cursor on
        # the source alone cannot cover their right padding or the scrollbar.
        pending=[self.app]
        while pending:
            widget=pending.pop()
            pending.extend(widget.winfo_children())
            if 'cursor' in widget.keys():
                self.cursor_states.append((widget,widget.cget('cursor')))
                widget.configure(cursor='fleur')
        self.animation=self.app.after(16,self.animate)

    def drag_rows(self):
        return self.layout.rows() if self.layout and self.layout.active else self.rows()

    def place_ghost(self,x,y):
        self.state['ghost_at']=(x,y)
        self.ghost.place(x=round(x-self.app.winfo_rootx()),y=round(y-self.app.winfo_rooty()))
        self.ghost.tk.call('raise',self.ghost._w)

    def animate(self):
        self.animation=None
        if not self.state:
            return
        if self.layout:
            self.layout.tick()
        if self.state['settling']:
            start=self.state['settle_at']
            destination=self.layout.target_rect()[:2] if self.layout else self.state['destination']
            t=min(1,(time.monotonic()-self.state['settle_started'])/.16)
            ease=1-(1-t)**3
            self.place_ghost(start[0]+(destination[0]-start[0])*ease,start[1]+(destination[1]-start[1])*ease)
            if t>=1:
                self.cancel()
                return
        self.animation=self.app.after(16,self.animate)

    def bounds(self):
        w = self.viewport
        x, y = w.winfo_rootx(), w.winfo_rooty()
        right, bottom = x+w.winfo_width(), y+w.winfo_height()
        parent = w.master
        while parent is not None:
            if isinstance(parent,tk.Canvas) and hasattr(parent,'scroll_target'):
                x, y = max(x,parent.winfo_rootx()), max(y,parent.winfo_rooty())
                right = min(right,parent.winfo_rootx()+parent.winfo_width())
                bottom = min(bottom,parent.winfo_rooty()+parent.winfo_height())
            parent = parent.master
        return x, y, right, bottom

    def feedback(self, x, y):
        rows = self.drag_rows()
        left, top, right, bottom = self.bounds()
        state = self.state
        dx,dy=state['offset']
        gw,gh=state['ghost_size']
        self.place_ghost(max(left+2,min(right-gw,x-dx+5)),max(top+2,min(bottom-gh,y-dy-4)))
        if not rows or not (left-12 <= x <= right+12 and top-24 <= y <= bottom+24):
            state['target'] = None
            self.marker.place_forget()
            self.app.status.set('Release to cancel the move · Esc to cancel')
            if self.layout:
                self.layout.set_target(self.layout.old)
            return
        target = next((i for i, (_, _, ry, _, h) in enumerate(rows) if y < ry+h/2), len(rows))
        state['target'] = target
        old = next(i for i, row in enumerate(rows) if row[0] == state['key'])
        position = target - (target > old)
        if target == 0:
            boundary = rows[0][2]-3
        elif target == len(rows):
            boundary = rows[-1][2]+rows[-1][4]+3
        else:
            boundary = (rows[target-1][2]+rows[target-1][4]+rows[target][2])/2
        rx, _, width, _ = rows[min(target, len(rows)-1)][1:]
        if self.layout:
            self.layout.set_target(position)
            rx,boundary,width,_=self.layout.target_rect()
        marker_left, marker_right = max(left+2, rx), min(right-2, rx+width)
        if top-4 <= boundary <= bottom+4:
            self.marker.configure(bg=self.app.ui['accent'])
            self.marker.place(x=marker_left-self.app.winfo_rootx(),
                              y=max(top, min(bottom-3, boundary))-self.app.winfo_rooty(),
                              width=max(5, marker_right-marker_left), height=3)
            self.marker.lift()
        else:
            self.marker.place_forget()
        self.app.status.set(f'Moving {self.label} · Position {position+1} of {len(rows)} · Esc to cancel')
        self.ghost.tk.call('raise',self.ghost._w)

    def autoscroll(self):
        self.job = None
        if not self.state or not self.state['moved'] or self.state['settling']:
            return
        x, y = self.state['pointer']
        left, top, right, bottom = self.bounds()
        if left-12 <= x <= right+12 and top-24 <= y <= bottom+24:
            edge = 40
            delta = -min(16, max(0, (top+edge-y)/3)) if y<top+edge else min(16,max(0,(y-bottom+edge)/3))
            if delta and self.can_scroll(delta):
                self.scroll(round(delta))
                self.host.update_idletasks()
                self.feedback(x, y)
        self.job = self.app.after(24, self.autoscroll)

    def end(self, event):
        state = self.state
        if not state or state['settling']:
            return 'break'
        if state['moved']:
            # Recompute once on release, including a final mouse move without a motion event.
            self.feedback(event.x_root, event.y_root)
        target, moved, key, click = state['target'], state['moved'], state['key'], state['click']
        keys = [row[0] for row in self.drag_rows()]
        inside = True
        widget = state['widget']
        if widget is not None:
            inside = (widget.winfo_rootx() <= event.x_root <= widget.winfo_rootx()+widget.winfo_width()
                      and widget.winfo_rooty() <= event.y_root <= widget.winfo_rooty()+widget.winfo_height())
        if moved and target is not None and key in keys:
            old = keys.index(key)
            new = target-(target>old)
            # Persist immediately, then settle the existing widgets visually.
            # Saving during the animation therefore saves the dropped order.
            if old != new:
                self.commit(old, new)
            state['settling']=True
            state['settle_at']=state['ghost_at']
            state['settle_started']=time.monotonic()
            state['destination']=self.drag_rows()[new][1:3]
            self.marker.place_forget()
            if old==new:
                self.app.status.set(state['previous_status'])
            self.release_pointer()
        elif not moved and inside and click:
            self.cancel()
            click()
        else:
            self.cancel()
        return 'break'

    def step(self, key, delta):
        keys = [row[0] for row in self.rows()]
        if key in keys:
            old = keys.index(key)
            if 0 <= old+delta < len(keys):
                self.commit(old, old+delta)
        return 'break'

    def cancel(self, event=None):
        if self.job is not None:
            self.app.after_cancel(self.job)
            self.job = None
        if self.escape_binding:
            self.app.unbind('<Escape>', self.escape_binding)
            self.escape_binding = None
        if self.animation is not None:
            self.app.after_cancel(self.animation)
            self.animation=None
        self.release_pointer()
        if self.layout:
            self.layout.restore()
            self.layout=None
        if self.state and not self.state['settling']:
            self.app.status.set(self.state['previous_status'])
        self.state = None
        if getattr(self.app, 'active_drag', None) is self:
            self.app.active_drag = None
        self.marker.place_forget()
        self.ghost.place_forget()
        return 'break'

    def release_pointer(self):
        for sequence,binding in self.capture_bindings:
            self.app.unbind(sequence,binding)
        self.capture_bindings=[]
        if self.app.grab_current() is self.app:
            self.app.grab_release()
        for widget,cursor in self.cursor_states:
            if widget.winfo_exists():
                widget.configure(cursor=cursor)
        self.cursor_states=[]
        if self.state:
            widget = self.state['widget']
            if widget is not None and widget.winfo_exists():
                if self.app.grab_current() is widget:
                    widget.grab_release()
                if hasattr(widget, '_state'):
                    widget._state('pressed', False)

    def destroy(self, event):
        if event.widget is self.host:
            self.cancel()
            self.marker.destroy()
            self.ghost.destroy()


class LineHandles:
    """A separate gutter reorders logical lines, leaving Text's selection/focus intact."""
    def __init__(self, editor, parent):
        self.editor, self.text, self.hover = editor, editor.input, None
        self.gutter = tk.Canvas(parent, width=25, height=1, bd=0, highlightthickness=0, cursor='fleur', takefocus=1)
        self.gutter.pack(side='left', fill='y', before=self.text)
        self.controller = ReorderController(editor.app, self.gutter, self.rows, self.commit,
            viewport=self.text,scroll=self.scroll,can_scroll=self.can_scroll,label='line',
            describe=lambda key:(editor.visible().split('\n')[key],''))
        self.gutter.bind('<ButtonPress-1>', self.start)
        self.gutter.bind('<B1-Motion>', self.controller.motion)
        self.gutter.bind('<ButtonRelease-1>', self.controller.end)
        self.gutter.bind('<Motion>', self.motion)
        self.gutter.bind('<Leave>', lambda e: self.highlight(None))
        self.text.bind('<Configure>', lambda e: self.draw(), add='+')
        self.text.configure(yscrollcommand=lambda *args:self.draw())
        self.gutter.bind('<Alt-Up>', lambda e:self.move_current(-1))
        self.gutter.bind('<Alt-Down>', lambda e:self.move_current(1))
        self.text.bind('<Alt-Up>', lambda e:self.move_current(-1))
        self.text.bind('<Alt-Down>', lambda e:self.move_current(1))
        editor.ui.watch(self.gutter, self.draw)

    def rows(self):
        t = self.text
        count = int(t.index('end-1c').split('.')[0])
        # Tk's display-line count handles wrapping, including off-screen paragraphs.
        heights = []
        line_height = max(1, self.editor.ui.fonts['body'].metrics('linespace')+4)
        for n in range(1, count+1):
            start, end = f'{n}.0', f'{n+1}.0' if n<count else 'end'
            height = t.count(start, end, 'ypixels')
            heights.append(max(line_height, height[0] if height else 0))
        visible = int(t.index('@0,0').split('.')[0])-1
        info = t.dlineinfo(f'{visible+1}.0')
        if info:
            y = t.winfo_rooty()+info[1]-sum(heights[:visible])
        else:
            # The first visible paragraph may begin above the viewport.
            index = t.index('@0,0')
            info = t.dlineinfo(index)
            above = t.count(f'{visible+1}.0', index, 'ypixels')
            y = t.winfo_rooty()+(info[1] if info else 0)-(above[0] if above else 0)-sum(heights[:visible])
        rows = []
        for i, height in enumerate(heights):
            rows.append((i, self.gutter.winfo_rootx(), y, t.winfo_width()+25, height))
            y += height
        return rows

    def draw(self):
        if not self.text.winfo_exists():
            return
        p = self.editor.ui
        self.gutter.configure(bg=p['field'])
        self.gutter.delete('all')
        for i, _, y, _, height in self.rows():
            yy = y-self.gutter.winfo_rooty()
            if -height < yy < self.gutter.winfo_height():
                if i == self.hover:
                    self.gutter.create_rectangle(3,yy,23,yy+min(height,24),fill=p['tint'],outline='')
                self.gutter.create_text(13,yy+10,text='⠿',fill=p['accent'] if i==self.hover else p['muted'],
                                        font=p.fonts['small'])

    def line_at(self, y):
        rows = self.rows()
        return next((i for i,_,ry,_,h in rows if ry <= y < ry+h), None)

    def highlight(self, line):
        if line != self.hover:
            self.hover = line
            self.draw()

    def motion(self, event):
        self.highlight(self.line_at(event.y_root))

    def start(self, event):
        line = self.line_at(event.y_root)
        if line is not None:
            # Include the gutter in the drop viewport as well as the text.
            self.controller.viewport = self.gutter.master
            self.controller.start(line, event, self.gutter)
        return 'break'

    def scroll(self, pixels):
        if can_scroll_view(self.text,pixels):
            self.text.yview_scroll(-1 if pixels<0 else 1, 'units')
        else:
            area = self.editor.app.pages[self.editor.app.current_section]
            if self.can_scroll(pixels):
                area.canvas.yview_scroll(pixels, 'units')

    def can_scroll(self,direction):
        if can_scroll_view(self.text,direction):
            return True
        area=self.editor.app.pages[self.editor.app.current_section]
        state=self.controller.state
        if not state:
            return False
        y=state.get('pointer',(0,0))[1]
        edge=area.canvas.winfo_rooty() if direction<0 else area.canvas.winfo_rooty()+area.canvas.winfo_height()
        return abs(y-edge)<40 and can_scroll_view(area.canvas,direction)

    def move_current(self, delta):
        return self.controller.step(int(self.text.index('insert').split('.')[0])-1, delta)

    def commit(self, old, new):
        editor = self.editor
        text, attrs, cursor = editor.snapshot()
        lines, offset = [], 0
        for line in text.split('\n'):
            lines.append((line, attrs[offset:offset+len(line)]))
            offset += len(line)+1
        lines.insert(new, lines.pop(old))
        from cv_studio_richtext import NORMAL
        ordered_attrs = []
        for n, (line, styles) in enumerate(lines):
            if n:
                ordered_attrs.append(NORMAL)
            ordered_attrs.extend(styles)
        position = sum(len(line)+1 for line,_ in lines[:new])
        editor.restore(('\n'.join(line for line,_ in lines), tuple(ordered_attrs), position))
        editor.remember('reorder')
        editor.on_change()
        editor.input.see('insert')
        self.highlight(new)
        editor.app.status.set('Line order updated · Ctrl+Z to undo')
