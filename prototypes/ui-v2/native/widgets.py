"""Shared visual components. Icons use vector drawing, not platform emoji."""
import customtkinter as ctk
import tkinter as tk
from functools import lru_cache
import math
from PIL import Image, ImageDraw

BG = '#F3F5F8'
PANEL = '#FFFFFF'
INK = '#243449'
MUTED = '#748196'
GREEN = '#315E91'  # primary action color; retained name for existing callers
SOFT = '#EDF3FA'
LINE = '#E1E7EF'
NAV = '#F8FAFC'
GOLD = '#B88A4A'
FONT = 'Microsoft JhengHei UI'

class OwnedComboBox(ctk.CTkComboBox):
    def __init__(self, parent, **kwargs):
        self._popup=None
        self._popup_bindings=[]
        self._menu_rows=[]
        self._menu_values=()
        self._menu_index=0
        self._menu_start=0
        defaults=dict(height=46,corner_radius=11,border_width=1,border_color=LINE,
            fg_color=NAV,button_color=NAV,button_hover_color=SOFT,text_color=INK,
            text_color_disabled='#9BA7B6',font=(FONT,15),dropdown_font=(FONT,15),
            dropdown_fg_color=PANEL,dropdown_hover_color=SOFT,dropdown_text_color=INK)
        defaults.update(kwargs)
        super().__init__(parent,**defaults)
        self._rest_border=defaults['border_color']
        self._arrow=ctk.CTkLabel(self,text='',width=24,height=26,
            fg_color=self.cget('fg_color'),image=icon_image('chevron',size=18))
        self._arrow.place(relx=1,rely=.5,x=-23,anchor='center')
        self._arrow.bind('<Button-1>',self._open_dropdown_menu)
        self.bind('<FocusIn>',self._focus_in)
        self.bind('<FocusOut>',self._focus_out)
        self.bind('<Button-1>',self._open_dropdown_menu)
        self.bind('<Down>',lambda event:self._move_selection(1))
        self.bind('<Up>',lambda event:self._move_selection(-1))
        self.bind('<Return>',self._accept_selection)
        self.bind('<Escape>',self._dismiss_selection)
        self.bind('<Alt-Down>',self._open_dropdown_menu)
        self._draw()

    def _draw(self,*args,**kwargs):
        super()._draw(*args,**kwargs)
        # Replace the font-glyph arrow with the same crisp icon grid as the UI.
        self._canvas.itemconfigure('dropdown_arrow',state='hidden')
        arrow=getattr(self,'_arrow',None)
        if arrow:
            arrow.configure(image=icon_image('chevron',color='#9BA7B6' if self.cget('state')=='disabled' else GREEN,size=18),
                            fg_color=self.cget('fg_color'))

    def configure(self,**kwargs):
        if 'values' in kwargs or 'state' in kwargs: self._close_popup()
        super().configure(**kwargs)

    def _focus_in(self,event=None):
        if self.cget('state')!='disabled': self.configure(border_color='#94B0D0')

    def _focus_out(self,event=None):
        self._close_popup()
        self.configure(border_color=self._rest_border)

    @staticmethod
    def _inside(widget,owner):
        while widget is not None:
            if widget is owner: return True
            widget=getattr(widget,'master',None)
        return False

    def _open_dropdown_menu(self,event=None):
        if self.cget('state')=='disabled' or not self.cget('values'): return 'break'
        if self._popup:
            self._close_popup();return 'break'
        root=self.winfo_toplevel()
        previous=getattr(root,'_open_combo',None)
        if previous and previous is not self: previous._close_popup()
        self.focus_set()
        self.update_idletasks()
        scale=self._get_widget_scaling()
        width=min(self.winfo_width()/scale,max(1,root.winfo_width()/scale-24))
        x=(self.winfo_rootx()-root.winfo_rootx())/scale
        top=(self.winfo_rooty()-root.winfo_rooty())/scale
        bottom=top+self.winfo_height()/scale
        below=root.winfo_height()/scale-bottom-12
        above=top-12
        height=min(len(self.cget('values'))*44+16,368,max(44,below,above))
        y=bottom+6 if below>=height else top-height-6
        x=max(12,min(x,root.winfo_width()/scale-width-12))
        popup=ctk.CTkFrame(root,fg_color=PANEL,corner_radius=12,border_width=1,
                          border_color='#D3DDE9',width=width,height=height)
        self._popup=popup
        root._open_combo=self
        popup.grid_propagate(False)
        popup.place(x=x,y=max(6,y))
        popup.grid_rowconfigure(0,weight=1);popup.grid_columnconfigure(0,weight=1)
        canvas=tk.Canvas(popup,bg=PANEL,highlightthickness=0,bd=0,
                         yscrollincrement=round(44*scale))
        canvas.grid(row=0,column=0,sticky='nsew',padx=8,pady=8)
        self._menu_canvas=canvas
        inner=ctk.CTkFrame(canvas,fg_color=PANEL,corner_radius=0)
        self._menu_window=canvas.create_window(0,0,window=inner,anchor='nw')
        self._menu_values=tuple(self.cget('values'))
        self._menu_row_height=44*scale
        self._menu_scrollbar=None
        self._menu_start=0
        if len(self._menu_values)*44+16>height:
            scrollbar=ctk.CTkScrollbar(popup,width=9,fg_color=PANEL,
                button_color='#CCD7E5',button_hover_color='#ABC0D9',command=canvas.yview)
            scrollbar.grid(row=0,column=1,sticky='ns',padx=(0,6),pady=12)
            self._menu_scrollbar=scrollbar
        current=self.get()
        self._menu_index=self._menu_values.index(current) if current in self._menu_values else 0
        self._check_icon=icon_image('check',size=17)
        # Render only the viewport plus two rows, even for a 500-model catalog.
        # The canvas retains the full scroll range without thousands of HWNDs.
        count=min(len(self._menu_values),math.ceil(height/44)+2)
        for slot in range(count):
            row=ctk.CTkFrame(inner,fg_color=PANEL,corner_radius=8,height=40)
            row.pack(fill='x',pady=2);row.pack_propagate(False)
            text=ctk.CTkLabel(row,text='',font=self.cget('dropdown_font'),text_color=INK,
                            anchor='w',width=1)
            text.pack(side='left',fill='both',expand=True,padx=(12,8))
            check=ctk.CTkLabel(row,text='',width=24)
            check.pack(side='right',padx=(0,9))
            for widget in (row,text,check):
                # Labels have no deferred button click animation to outlive a
                # selection that rebuilds or destroys the startup form.
                widget.bind('<Button-1>',lambda event,s=slot:self._choose(self._menu_start+s))
                widget.bind('<Enter>',lambda event,s=slot:self._highlight(self._menu_start+s))
            self._menu_rows.append((row,text,check))
        canvas.bind('<Configure>',self._canvas_changed)
        canvas.configure(yscrollcommand=self._menu_scrolled,
            scrollregion=(0,0,1,len(self._menu_values)*self._menu_row_height))
        self._paint_rows()
        for sequence,callback in (('<Button-1>',self._outside_click),
                ('<MouseWheel>',self._wheel),('<Configure>',self._root_changed),
                ('<Unmap>',self._root_changed)):
            self._popup_bindings.append((root,sequence,root.bind(sequence,callback,add='+')))
        popup.update_idletasks()
        if self._popup is not popup: return 'break'
        # Use the measured row pitch, including native pixel rounding at DPI
        # scales such as 175%, for both scrolling and virtual row placement.
        if len(self._menu_rows)>1:
            self._menu_row_height=self._menu_rows[1][0].winfo_y()-self._menu_rows[0][0].winfo_y()
        canvas.configure(yscrollincrement=self._menu_row_height,
            scrollregion=(0,0,canvas.winfo_width(),len(self._menu_values)*self._menu_row_height))
        popup.lift()
        self._highlight(self._menu_index)
        self._reveal_selection()
        return 'break'

    def _highlight(self,index):
        if not self._popup: return
        self._menu_index=index
        self._paint_rows()

    def _paint_rows(self):
        current=self.get()
        for slot,(row,text,check) in enumerate(self._menu_rows):
            index=self._menu_start+slot
            value=self._menu_values[index]
            row.configure(fg_color=SOFT if index==self._menu_index else PANEL)
            text.configure(text=value,text_color=GREEN if index==self._menu_index else INK)
            check.configure(image=self._check_icon if value==current else None)

    def _canvas_changed(self,event):
        if not self._popup: return
        canvas=self._menu_canvas
        canvas.itemconfigure(self._menu_window,width=event.width)
        canvas.configure(scrollregion=(0,0,event.width,len(self._menu_values)*self._menu_row_height))

    def _menu_scrolled(self,first,last):
        if not self._popup or not self._menu_rows: return
        if self._menu_scrollbar: self._menu_scrollbar.set(first,last)
        start=int(max(0,self._menu_canvas.canvasy(0))/self._menu_row_height)
        start=min(start,len(self._menu_values)-len(self._menu_rows))
        if start!=self._menu_start:
            self._menu_start=start
            self._menu_canvas.coords(self._menu_window,0,start*self._menu_row_height)
            self._paint_rows()

    def _reveal_selection(self):
        if not self._popup: return
        canvas=self._menu_canvas
        top=self._menu_index*self._menu_row_height
        bottom=top+self._menu_row_height
        visible=canvas.canvasy(0);height=canvas.winfo_height()
        total=max(1,len(self._menu_values)*self._menu_row_height)
        if top<visible: canvas.yview_moveto(top/total)
        elif bottom>visible+height: canvas.yview_moveto((bottom-height)/total)

    def _move_selection(self,step):
        if not self._popup: return self._open_dropdown_menu()
        index=max(0,min(len(self._menu_values)-1,self._menu_index+step))
        self._highlight(index);self._reveal_selection()
        return 'break'

    def _accept_selection(self,event=None):
        if self._popup: return self._choose(self._menu_index)

    def _dismiss_selection(self,event=None):
        if self._popup:
            self._close_popup();return 'break'

    def _choose(self,index):
        if not self._popup or not 0<=index<len(self._menu_values): return 'break'
        value=self._menu_values[index]
        self._close_popup()
        self._dropdown_callback(value)
        return 'break'

    def _outside_click(self,event):
        if self._popup and not self._inside(event.widget,self._popup) and not self._inside(event.widget,self):
            self._close_popup()

    def _root_changed(self,event):
        if event.widget is self.winfo_toplevel(): self._close_popup()

    def _wheel(self,event):
        if not self._popup: return
        if not self._inside(event.widget,self._popup):
            self._close_popup();return
        if event.delta:
            steps=-round(event.delta/120) or (-1 if event.delta>0 else 1)
            self._menu_canvas.yview_scroll(steps*3,'units')
        return 'break'

    def _close_popup(self):
        popup=self._popup
        if popup is None: return
        self._popup=None
        bindings,self._popup_bindings=self._popup_bindings,[]
        for root,sequence,command in bindings:
            root.unbind(sequence,command)
        root=popup.master
        if getattr(root,'_open_combo',None) is self: root._open_combo=None
        popup.destroy()
        self._menu_rows=[]
        self._menu_values=()
        self._menu_scrollbar=None

    def destroy(self):
        self._close_popup()
        # Installed CTk DropdownMenu.destroy omits scaling deregistration.
        # Remove only our menu's callback while its root still exists.
        menu=self._dropdown_menu
        ctk.ScalingTracker.remove_widget(menu._set_scaling,menu)
        super().destroy()

def label(parent, text, size=15, **kwargs):
    weight=kwargs.pop('weight','normal')
    color=kwargs.pop('color',INK)
    return ctk.CTkLabel(parent, text=text, text_color=color,
                        font=ctk.CTkFont(family=FONT,size=size,weight=weight), **kwargs)

def button(parent, text, command, primary=False, **kwargs):
    defaults=dict(height=40,font=ctk.CTkFont(family=FONT,size=14,weight='bold'),
        fg_color=GREEN if primary else PANEL,hover_color='#274E7A' if primary else SOFT,
        text_color='white' if primary else INK,text_color_disabled='#9BA7B6',
        corner_radius=11,border_width=0 if primary else 1,border_color=LINE)
    defaults.update(kwargs)
    return ctk.CTkButton(parent,text=text,command=command,**defaults)

@lru_cache(maxsize=96)
def _icon_art(kind, muted, locked, color):
    # One 24-unit grid, round caps and high-resolution strokes for every icon.
    # Cache PIL artwork only: Tk images must belong to their own interpreter.
    scale = 4
    im = Image.new('RGBA', (24*scale,24*scale))
    d = ImageDraw.Draw(im)
    def line(points, fill=color, width=1.7):
        pixels=[(x*scale,y*scale) for x,y in points]
        d.line(pixels,fill=fill,width=round(width*scale),joint='curve')
        radius=width*scale/2
        for x,y in (pixels[0],pixels[-1]):
            d.ellipse((x-radius,y-radius,x+radius,y+radius),fill=fill)
    def arc(box,start,end,width=1.7):
        d.arc(tuple(v*scale for v in box),start,end,fill=color,width=round(width*scale))
        cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
        rx,ry=(box[2]-box[0])/2,(box[3]-box[1])/2
        for angle in (start,end):
            theta=math.radians(angle)
            x,y=(cx+rx*math.cos(theta))*scale,(cy+ry*math.sin(theta))*scale
            radius=width*scale/2
            d.ellipse((x-radius,y-radius,x+radius,y+radius),fill=color)
    if kind == 'mic':
        d.rounded_rectangle((9*scale,3*scale,15*scale,15*scale),radius=3*scale,
                            outline=color,width=round(1.7*scale))
        arc((5.5,7,18.5,19),0,180)
        line([(5.5,10),(5.5,13)]);line([(18.5,10),(18.5,13)])
        line([(12,19),(12,22)]);line([(8.5,22),(15.5,22)])
        if muted:
            # A transparent cut keeps the slash distinct from the microphone.
            line([(3.5,3.5),(20.5,20.5)],fill=(0,0,0,0),width=4)
            line([(3.5,3.5),(20.5,20.5)])
    elif kind == 'speaker':
        line([(3,9),(7,9),(12,5),(12,19),(7,15),(3,15),(3,9)])
        if muted:
            line([(17,9),(22,15)]);line([(22,9),(17,15)])
        else:
            arc((9,7.5,19,16.5),-55,55)
            arc((8,4,23,20),-52,52)
    elif kind == 'send':
        line([(3,4),(21,12),(3,20),(6,12),(3,4)])
        line([(6,12),(15,12)])
    elif kind == 'hide':
        line([(6,12),(18,12)])
    elif kind == 'close':
        line([(7,7),(17,17)]);line([(17,7),(7,17)])
    elif kind == 'board':
        d.rounded_rectangle((3*scale,4*scale,21*scale,17*scale),radius=2*scale,
                            outline=color,width=round(1.7*scale))
        line([(12,17),(12,21)]);line([(8,21),(16,21)])
        line([(7,8),(17,8)],width=1.4);line([(7,12),(13,12)],width=1.4)
    elif kind == 'chat':
        line([(5,18),(4,22),(10,19)])
        d.rounded_rectangle((3*scale,3*scale,21*scale,19*scale),radius=4*scale,
                            outline=color,width=round(1.7*scale))
        for x in (7.5,12,16.5):
            d.ellipse(((x-.8)*scale,10.2*scale,(x+.8)*scale,11.8*scale),fill=color)
    elif kind == 'settings':
        for y,x in ((5,8),(12,16),(19,10)):
            line([(3,y),(x-2.5,y)]);line([(x+2.5,y),(21,y)])
            d.ellipse(((x-2.5)*scale,(y-2.5)*scale,(x+2.5)*scale,(y+2.5)*scale),
                      outline=color,width=round(1.7*scale))
    elif kind == 'backend':
        for y in (4,14):
            d.rounded_rectangle((3*scale,y*scale,21*scale,(y+6)*scale),radius=2*scale,
                                outline=color,width=round(1.7*scale))
            line([(7,y+3),(7.1,y+3)],width=2)
            line([(15,y+3),(17,y+3)],width=1.4)
    elif kind == 'check':
        line([(5,12),(10,17),(19,7)])
    elif kind == 'chevron':
        line([(7,10),(12,15),(17,10)],width=1.8)
    else:
        raise ValueError(f'Unknown icon: {kind}')
    if locked:
        d.ellipse((14*scale,14*scale,24*scale,24*scale),fill=NAV)
        d.rounded_rectangle((16.5*scale,18.5*scale,22*scale,23*scale),radius=scale,
                            outline=color,width=round(1.3*scale))
        d.arc((17.5*scale,15.5*scale,21*scale,21*scale),180,360,
              fill=color,width=round(1.3*scale))
    return im

def icon_image(kind, muted=False, locked=False, *, color=None, size=24):
    color=color or ('#96A1B0' if locked else GREEN)
    im=_icon_art(kind,muted,locked,color)
    return ctk.CTkImage(im,im,size=(size,size))

class IconButton(ctk.CTkButton):
    def __init__(self, parent, kind, command, tip='', **kwargs):
        self.kind = kind
        self.tip = tip
        self._tooltip = None
        self._tip_job = None
        self._status=None
        quiet=kind in ('hide','close')
        primary=kind=='send'
        defaults=dict(width=44,height=44,corner_radius=14,
            fg_color=GREEN if primary else 'transparent' if quiet else PANEL,
            hover_color='#274E7A' if primary else '#E8EFF7',
            border_width=0 if primary or quiet else 1,border_color=LINE)
        defaults.update(kwargs)
        super().__init__(parent,text='',image=icon_image(kind,color='white' if primary else GREEN),
                         command=command,**defaults)
        self.bind('<Enter>', self._enter)
        self.bind('<Leave>', self._leave)

    def set_status(self, muted=False, locked=False, tip=''):
        if self._status==(muted,locked) and self.tip==tip: return
        self._leave()
        self.tip = tip
        self._status=(muted,locked)
        color='#96A1B0' if locked else '#A26645' if muted else GREEN
        self.configure(image=icon_image(self.kind,muted,locked,color=color),
            fg_color=NAV if locked else '#FBF2EC' if muted else SOFT,
            border_color=LINE if locked else '#ECDACE' if muted else '#D4E2F3',
            hover_color='#EEF1F5' if locked else '#F5E5DB' if muted else '#DDEAF8')

    def _enter(self, event=None):
        self._leave()
        self._tip_job = self.after(600, self._show_tip)

    def _show_tip(self):
        self._tip_job = None
        if not self.tip or not self.winfo_exists():
            return
        root = self.winfo_toplevel()
        # A child panel keeps keyboard focus and window controls in the app.
        self._tooltip = ctk.CTkFrame(root,fg_color=INK,corner_radius=9)
        label(self._tooltip,self.tip,12,color='white').pack(padx=12,pady=7)
        self._tooltip.update_idletasks()
        scale=self._tooltip._get_widget_scaling()
        x=(self.winfo_rootx()-root.winfo_rootx())/scale
        y=(self.winfo_rooty()-root.winfo_rooty()-self._tooltip.winfo_reqheight())/scale-8
        x=max(8,min(x,(root.winfo_width()-self._tooltip.winfo_reqwidth())/scale-8))
        self._tooltip.place(x=x, y=max(8,y))
        self._tooltip.lift()

    def _leave(self, event=None):
        if self._tip_job:
            self.after_cancel(self._tip_job)
            self._tip_job = None
        if self._tooltip:
            self._tooltip.destroy()
            self._tooltip = None

    def destroy(self):
        self._leave()
        super().destroy()

def card(parent, **kwargs):
    return ctk.CTkFrame(parent,fg_color=PANEL,corner_radius=18,
                       border_width=1,border_color=LINE,**kwargs)

def pill(parent,text,color=GREEN,bg=SOFT):
    frame=ctk.CTkFrame(parent,fg_color=bg,corner_radius=12)
    label(frame,text,12,color=color).pack(padx=12,pady=4)
    return frame

def divider(parent):
    return ctk.CTkFrame(parent,fg_color=LINE,height=1,corner_radius=0)
