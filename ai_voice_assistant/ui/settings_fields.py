"""Schema-backed startup fields shared by basic and advanced pages."""
import json
from tkinter import filedialog

import customtkinter as ctk

from core.session_settings import parse_field
from core.settings_schema import field_spec, SettingsError
from ui.components import FONT, INK, MUTED, NAV, LINE, OwnedComboBox, label, button


class TextValue:
    def __init__(self, widget):
        self.widget = widget

    def get(self):
        return self.widget.get('1.0', 'end-1c')

    def set(self, value):
        self.widget.delete('1.0', 'end')
        self.widget.insert('1.0', value)


class ListValue:
    def __init__(self, owner, values):
        self.owner = owner
        self.set(json.dumps(values, ensure_ascii=False))

    def get(self):
        return json.dumps([var.get() for var, _ in self.rows], ensure_ascii=False)

    def set(self, value):
        values = json.loads(value)
        for child in self.owner.winfo_children(): child.destroy()
        self.rows = []
        for item in values: self.add(item)
        button(self.owner, '＋ 新增項目', self.add, height=32, width=110).pack(anchor='w', pady=4)

    def add(self, text=''):
        row = ctk.CTkFrame(self.owner, fg_color='transparent')
        # Insert before the add button when it already exists.
        children = self.owner.pack_slaves()
        row.pack(fill='x', pady=3, **({'before':children[-1]} if children and isinstance(children[-1],ctk.CTkButton) else {}))
        row.grid_columnconfigure(0, weight=1)
        var = ctk.StringVar(value=text)
        ctk.CTkEntry(row, textvariable=var, height=38).grid(row=0,column=0,sticky='ew')
        def remove():
            self.rows.remove((var,row))
            row.destroy()
            self.owner.master.changed()
        button(row, '移除', remove, width=56, height=32).grid(row=0,column=1,padx=(6,0))
        self.rows.append((var,row))
        var.trace_add('write',lambda *_:self.owner.master.changed())


class SettingsField(ctk.CTkFrame):
    def __init__(self, parent, path, value, title, *, changed=None, options=None, readonly=None):
        super().__init__(parent, fg_color='transparent', height=1)
        self.path, self.original = tuple(path), value
        self.changed = changed or (lambda: None)
        self.spec = field_spec(path, value)
        label(self,title,13,color=MUTED,anchor='w',wraplength=300).pack(fill='x',pady=(12,5))
        options = self.spec.options if options is None else options
        if self.spec.kind == 'bool':
            self.variable = ctk.BooleanVar(value=value)
            self.widget = ctk.CTkSwitch(self,text='',variable=self.variable,command=self.changed)
        elif self.spec.kind == 'list' and isinstance(value,list) and all(isinstance(x,str) for x in value):
            self.widget = ctk.CTkFrame(self,fg_color='transparent',height=1)
            self.variable = ListValue(self.widget,value)
        elif self.spec.kind in ('multiline','list','json_list'):
            self.widget = ctk.CTkTextbox(self,height=92,fg_color=NAV,text_color=INK,font=(FONT,14))
            self.variable = TextValue(self.widget)
            self.variable.set(json.dumps(value,ensure_ascii=False) if self.spec.kind in ('list','json_list') else '' if value is None else str(value))
            self.widget.bind('<KeyRelease>',lambda event=None:self.changed())
        else:
            text = '' if value is None else str(value)
            self.variable = ctk.StringVar(value=text)
            if options:
                self.widget = OwnedComboBox(self,variable=self.variable,values=[str(x) for x in options],
                    state='readonly' if (readonly if readonly is not None else self.path != ('whisper','model_size')) else 'normal')
            else:
                self.widget = ctk.CTkEntry(self,textvariable=self.variable,height=42,fg_color=NAV,
                    text_color=INK,border_color=LINE,show='•' if self.spec.kind=='secret' else '')
        self.widget.pack(fill='x')
        if isinstance(self.variable,(ctk.StringVar,ctk.BooleanVar)):
            self.variable.trace_add('write',lambda *_:self.changed())
        if self.spec.kind in ('file','directory'):
            button(self,'瀏覽…',self.browse,width=90,height=32).pack(anchor='w',pady=4)
        if self.spec.kind=='nullable_int':
            button(self,'使用隨機值',lambda:self.variable.set(''),width=120,height=32).pack(anchor='w',pady=4)
        if self.spec.kind=='secret':
            visible=ctk.BooleanVar(value=False)
            ctk.CTkCheckBox(self,text='顯示金鑰',variable=visible,
                command=lambda:self.widget.configure(show='' if visible.get() else '•')).pack(anchor='w',pady=6)
        if self.spec.help:
            label(self,self.spec.help,12,color=MUTED,anchor='w',wraplength=300).pack(fill='x',pady=(5,0))
        self.error = label(self,'',12,color='#9B342E',anchor='w',wraplength=300)

    def browse(self):
        picker=filedialog.askdirectory if self.spec.kind=='directory' else filedialog.askopenfilename
        value=picker(parent=self.winfo_toplevel(),title='選擇'+('資料夾' if self.spec.kind=='directory' else '檔案'))
        if value: self.variable.set(value)

    def parse(self):
        self.error.pack_forget()
        try:
            return parse_field(self.variable.get(),self.original,self.path)
        except (ValueError,TypeError) as exc:
            # Never echo a raw value, especially credentials, in a parse error.
            message='請填有效的整數' if type(self.spec.default) is int else '格式不正確，請依欄位說明填寫'
            if isinstance(exc,SettingsError): message=exc.message
            self.show_error(message)
            raise SettingsError(self.path,message) from None

    def show_error(self, message):
        self.error.configure(text=message)
        self.error.pack(fill='x',pady=(5,0))

    def focus_field(self):
        self.widget.focus_set()
