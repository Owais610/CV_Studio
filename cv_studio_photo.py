"""Portable, non-destructive portrait crops shared by the editor and PDF renderer."""
import base64
import io
import math
from pathlib import Path
import tkinter as tk


def normalize_crop(value=None):
    value = value if isinstance(value, dict) else {}
    def number(key, default, lo, hi):
        try:
            n = float(value.get(key, default))
            return max(lo,min(hi,n)) if math.isfinite(n) else default
        except (TypeError,ValueError):
            return default
    return dict(x=number('x',.5,0,1), y=number('y',.5,0,1), zoom=number('zoom',1,1,4))


def decode_photo(encoded):
    from PIL import Image, ImageOps
    raw = base64.b64decode(encoded.split(',',1)[-1], validate=True)
    if len(raw)>20*1024*1024:
        raise ValueError('Choose an image smaller than 20 MB.')
    with Image.open(io.BytesIO(raw)) as source:
        rgba = ImageOps.exif_transpose(source).convert('RGBA')
        opaque = Image.new('RGB',rgba.size,'white')
        opaque.paste(rgba,mask=rgba.getchannel('A'))
        return opaque


def import_photo(path):
    from PIL import Image, ImageOps
    if Path(path).stat().st_size>20*1024*1024:
        raise ValueError('Choose an image smaller than 20 MB.')
    with Image.open(path) as source:
        if source.format not in ('PNG','JPEG'):
            raise ValueError('Please choose a PNG or JPEG image.')
        rgba = ImageOps.exif_transpose(source).convert('RGBA')
        rgba.thumbnail((2400,2400),Image.Resampling.LANCZOS)
        opaque = Image.new('RGB',rgba.size,'white')
        opaque.paste(rgba,mask=rgba.getchannel('A'))
        output = io.BytesIO()
        opaque.save(output,format='JPEG',quality=95,optimize=True)
    return 'data:image/jpeg;base64,'+base64.b64encode(output.getvalue()).decode('ascii')


def crop_box(size, crop=None):
    width, height = size
    crop = normalize_crop(crop)
    edge = min(width,height)/crop['zoom']
    x = max(edge/2,min(width-edge/2,crop['x']*width))
    y = max(edge/2,min(height-edge/2,crop['y']*height))
    return x-edge/2,y-edge/2,x+edge/2,y+edge/2


def crop_image(source, crop=None, size=720, circle=False):
    from PIL import Image, ImageDraw
    # Resize the original region directly, never a succession of previous crops.
    result = source.resize((size,size),Image.Resampling.LANCZOS,box=crop_box(source.size,crop))
    if circle:
        mask = Image.new('L',(size,size),0)
        ImageDraw.Draw(mask).ellipse((0,0,size-1,size-1),fill=255)
        result = result.convert('RGBA')
        result.putalpha(mask)
    return result


class PhotoCropDialog(tk.Toplevel):
    def __init__(self, app, encoded, crop, on_apply):
        from cv_studio_ui import Frame, Label, Button, Slider
        self.source = decode_photo(encoded)
        super().__init__(app)
        self.app, self.encoded, self.on_apply = app, encoded, on_apply
        self.crop = normalize_crop(crop)
        self.pending_draw, self.start_pointer = None, None
        self.title('Edit portrait')
        self.transient(app)
        self.resizable(False,False)
        self.configure(bg=app.ui['surface'])
        body = Frame(self,app.ui,padx=24,pady=22)
        body.pack(fill='both',expand=True)
        Label(body,app.ui,'Frame your portrait',font='heading').pack(anchor='w')
        Label(body,app.ui,'Drag the image to reposition. Scroll or use the slider to zoom.',
              font='small',fg='muted').pack(anchor='w',pady=(6,16))
        self.canvas = tk.Canvas(body,width=440,height=350,bd=0,highlightthickness=1,
                                highlightbackground=app.ui['line'],cursor='fleur',takefocus=1)
        self.canvas.pack()
        self.canvas.bind('<ButtonPress-1>',self.start)
        self.canvas.bind('<B1-Motion>',self.drag)
        self.canvas.bind('<ButtonRelease-1>',lambda e:setattr(self,'start_pointer',None))
        self.canvas.bind('<MouseWheel>',self.wheel)
        for key,dx,dy in [('Left',-4,0),('Right',4,0),('Up',0,-4),('Down',0,4)]:
            self.canvas.bind('<'+key+'>',lambda e,x=dx,y=dy:self.nudge(x,y))
        self.zoom = tk.DoubleVar(self,value=self.crop['zoom']*100)
        row = Frame(body,app.ui)
        row.pack(fill='x',pady=(16,0))
        Label(row,app.ui,'Zoom',font='label').pack(side='left',padx=(0,12))
        self.zoom_label = Label(row,app.ui,'100%',font='small',width=5,anchor='e')
        self.zoom_label.pack(side='right')
        Slider(row,app.ui,self.zoom,100,400,self.zoom_changed).pack(side='left',fill='x',expand=True)
        Label(body,app.ui,'The circular frame matches your PDF. Your original image is kept.',
              font='small',fg='muted').pack(anchor='w',pady=(10,18))
        actions = Frame(body,app.ui)
        actions.pack(fill='x')
        Button(actions,app.ui,'Reset crop',self.reset,kind='ghost').pack(side='left')
        Button(actions,app.ui,'Apply photo',self.apply,kind='primary').pack(side='right')
        Button(actions,app.ui,'Cancel',self.destroy,kind='ghost').pack(side='right',padx=8)
        self.bind('<Escape>',lambda e:self.destroy())
        self.bind('<Return>',lambda e:self.apply())
        self.app.center_dialog(self)
        self.grab_set()
        self.canvas.focus_set()
        self.redraw()

    def clamp(self):
        box = crop_box(self.source.size,self.crop)
        self.crop['x'] = (box[0]+box[2])/2/self.source.width
        self.crop['y'] = (box[1]+box[3])/2/self.source.height

    def redraw(self):
        from PIL import Image, ImageDraw, ImageTk
        self.pending_draw = None
        self.clamp()
        width, height, diameter = 440,350,290
        self.scale = diameter/min(self.source.size)*self.crop['zoom']
        cx,cy = self.crop['x']*self.source.width,self.crop['y']*self.source.height
        box = (cx-width/2/self.scale,cy-height/2/self.scale,
               cx+width/2/self.scale,cy+height/2/self.scale)
        preview = self.source.transform((width,height),Image.Transform.EXTENT,box,
                                        Image.Resampling.BICUBIC,fillcolor='#202733').convert('RGBA')
        overlay = Image.new('RGBA',preview.size,(16,22,32,160))
        draw = ImageDraw.Draw(overlay)
        bounds = ((width-diameter)/2,(height-diameter)/2,(width+diameter)/2,(height+diameter)/2)
        draw.ellipse(bounds,fill=(0,0,0,0),outline=(255,255,255,245),width=2)
        preview = Image.alpha_composite(preview,overlay)
        self.preview = ImageTk.PhotoImage(preview,master=self)
        self.canvas.delete('all')
        self.canvas.create_image(0,0,image=self.preview,anchor='nw')
        self.zoom_label.configure(text=f'{self.zoom.get():.0f}%')

    def schedule(self):
        if self.pending_draw is None:
            self.pending_draw = self.after(16,self.redraw)

    def start(self,event):
        self.canvas.focus_set()
        self.start_pointer = event.x,event.y,self.crop['x'],self.crop['y']
        return 'break'

    def drag(self,event):
        if self.start_pointer:
            x,y,cx,cy = self.start_pointer
            self.crop['x'] = cx-(event.x-x)/self.scale/self.source.width
            self.crop['y'] = cy-(event.y-y)/self.scale/self.source.height
            self.clamp()
            self.schedule()
        return 'break'

    def nudge(self,dx,dy):
        self.crop['x'] -= dx/self.scale/self.source.width
        self.crop['y'] -= dy/self.scale/self.source.height
        self.clamp()
        self.schedule()
        return 'break'

    def zoom_changed(self):
        self.crop['zoom'] = self.zoom.get()/100
        self.clamp()
        self.schedule()

    def wheel(self,event):
        self.zoom.set(max(100,min(400,self.zoom.get()+(10 if event.delta>0 else -10))))
        self.zoom_changed()
        return 'break'

    def reset(self):
        self.crop = normalize_crop()
        self.zoom.set(100)
        self.schedule()

    def apply(self):
        self.clamp()
        self.on_apply(self.encoded,dict(self.crop))
        self.destroy()

    def destroy(self):
        if self.pending_draw is not None:
            self.after_cancel(self.pending_draw)
            self.pending_draw = None
        super().destroy()
        # Release Tk-owned resources on the UI thread before a worker can
        # trigger cyclic collection of an old, replaced dialog.
        self.zoom = self.preview = None
        if getattr(self.app,'photo_dialog',None) is self:
            self.app.photo_dialog = None
        if not self.app.closing:
            self.app.nav['layout'].focus_set()
