"""Own callbacks/timers added by the reused Markdown widget without patching it."""
import customtkinter as ctk
from ui.main_window import WhiteboardMarkdownRenderer


class OwnedMarkdownRenderer(WhiteboardMarkdownRenderer):
    def __init__(self):
        super().__init__()
        self._owned_callbacks=[]

    def render(self,parent,text):
        self.clear()
        before={id(callback) for callback in ctk.AppearanceModeTracker.callback_list}
        try:
            super().render(parent,text)
        finally:
            self._owned_callbacks=[callback for callback in ctk.AppearanceModeTracker.callback_list if id(callback) not in before]

    def clear(self):
        widget=self.widget
        if widget is not None:
            commands=set()
            def collect(owner):
                commands.update(getattr(owner,'_tclCommands',None) or ())
                for child in owner.winfo_children(): collect(child)
            collect(widget)
            for job in widget.tk.call('after','info'):
                script,_kind=widget.tk.call('after','info',job)
                if script in commands:
                    widget.tk.call('after','cancel',job)
        try:
            super().clear()
        finally:
            for callback in self._owned_callbacks:
                if callback in ctk.AppearanceModeTracker.callback_list:
                    ctk.AppearanceModeTracker.remove(callback)
            self._owned_callbacks=[]
