"""Visual helpers for Sophia's session and startup screens."""
from functools import lru_cache

import customtkinter as ctk
from PIL import Image, ImageDraw

from ui.components import FONT, IconButton, icon_image, label as shared_label
from ui.theme import (
    CANVAS, SURFACE, INK, MUTED, LINE, CHROME, CHROME_SOFT, PRIMARY,
    PRIMARY_HOVER, BLUE_SOFT, BLUE_LINE, WARM_SOFT, ROSE, GOLD, SAGE, SAGE_SOFT,
)


def label(parent, text, size=15, **kwargs):
    kwargs.setdefault('color', INK)
    return shared_label(parent, text, size, **kwargs)


def card(parent, **kwargs):
    defaults = dict(fg_color=SURFACE, corner_radius=20,
                    border_width=1, border_color=LINE)
    defaults.update(kwargs)
    return ctk.CTkFrame(parent, **defaults)


def button(parent, text, command, **kwargs):
    defaults = dict(height=40, font=(FONT, 14, 'bold'), fg_color=PRIMARY,
                    hover_color=PRIMARY_HOVER, text_color='white',
                    text_color_disabled='#AEA4A3', corner_radius=11,
                    border_width=0)
    defaults.update(kwargs)
    return ctk.CTkButton(parent, text=text, command=command, **defaults)


@lru_cache(maxsize=1)
def _identity_art():
    """A window/sun emblem echoes the existing room; no new image asset."""
    image = Image.new('RGBA', (160, 160))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((40, 28, 118, 128), radius=36, outline='#E8CC9E', width=6)
    draw.line((40, 88, 118, 88), fill='#E8CC9E', width=5)
    draw.line((80, 30, 80, 128), fill='#E8CC9E', width=5)
    draw.ellipse((92, 44, 108, 60), fill='#F2DDAC')
    draw.line((28, 138, 132, 138), fill='#B89276', width=4)
    return image


def identity_image(size=30):
    artwork = _identity_art()
    return ctk.CTkImage(artwork, artwork, size=(size, size))


class SessionIconButton(IconButton):
    """Reuse the established commands/tooltips, with session-local colors."""
    def __init__(self, parent, kind, command, tip='', **kwargs):
        primary = kind == 'send'
        quiet = kind in ('hide', 'close', 'calendar', 'reload')
        defaults = dict(corner_radius=12,
                        fg_color=PRIMARY if primary else 'transparent' if quiet else SURFACE,
                        hover_color=PRIMARY_HOVER if primary else '#EEE5DD',
                        border_width=0 if primary or quiet else 1, border_color=LINE)
        defaults.update(kwargs)
        super().__init__(parent, kind, command, tip, **defaults)
        self.configure(image=icon_image(kind, color='white' if primary else PRIMARY))

    def set_status(self, muted=False, locked=False, tip=''):
        if self._status == (muted, locked) and self.tip == tip:
            return
        self._leave()
        self.tip = tip
        self._status = (muted, locked)
        color = '#A69C9B' if locked else ROSE if muted else PRIMARY
        self.configure(image=icon_image(self.kind, muted, locked, color=color),
                       fg_color='#F1ECE7' if locked else '#F9EEE8' if muted else BLUE_SOFT,
                       border_color=LINE if locked else '#E8CFC4' if muted else BLUE_LINE,
                       hover_color='#EAE3DD' if locked else '#F1DDD2' if muted else '#DFEBF2')


def set_phase_style(widget, state):
    """Colors supplement the existing text, so state is never color-only."""
    from core.state_machine import State
    color, background = {
        State.IDLE_LISTEN: (SAGE, SAGE_SOFT),
        State.HOT_LISTEN: (PRIMARY, BLUE_SOFT),
        State.COLLECTING: (PRIMARY, BLUE_SOFT),
        State.SENDING: ('#886537', '#F7EEDC'),
        State.SPEAKING: ('#866275', '#F3EAF0'),
    }.get(state, (SAGE, SAGE_SOFT))
    widget.configure(text_color=color, fg_color=background)
