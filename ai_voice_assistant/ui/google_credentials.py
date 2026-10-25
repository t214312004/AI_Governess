"""Credential entry never pre-fills or displays the existing secret."""
import customtkinter as ctk

from ui.components import FONT, INK, LINE, NAV, MUTED, label, button
from utils.google_credentials import google_key_status


class GoogleCredentialsEditor(ctk.CTkFrame):
    def __init__(self, parent, settings, save_key, changed):
        super().__init__(parent, fg_color="transparent")
        self.settings, self.save_key, self.changed = settings, save_key, changed
        self.key = ctk.StringVar(value="")
        self.entry = ctk.CTkEntry(self, textvariable=self.key, show="•", height=44,
            placeholder_text="輸入新的 Google API key", font=(FONT, 14),
            fg_color=NAV, text_color=INK, border_color=LINE)
        self.entry.pack(fill="x", pady=(8, 10))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x")
        button(row, "儲存 key", self.save, width=100).pack(side="left", padx=(0, 8))
        button(row, "刪除本機 key", self.delete, width=130).pack(side="left", padx=(0, 8))
        self.visible = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(self, text="顯示輸入", variable=self.visible, width=110,
            command=self.toggle_visibility, text_color=INK).pack(anchor="w", pady=(12, 0))
        self.status = label(self, google_key_status(settings), 12, color=MUTED,
            anchor="w", wraplength=300)
        self.status.pack(fill="x", pady=(12, 0))
        label(self, "儲存與刪除立即生效；只寫入本機 config.local.json。",
              12, color=MUTED, anchor="w", wraplength=300).pack(fill="x", pady=(6, 0))

    def toggle_visibility(self):
        self.entry.configure(show="" if self.visible.get() else "•")

    def save(self):
        if not self.key.get().strip():
            self.status.configure(text="請輸入 key；清除已儲存的 key 請按「刪除本機 key」。")
            return
        self._persist(self.key.get())

    def delete(self):
        self._persist("")

    def _persist(self, value):
        if self.save_key is None:
            self.status.configure(text="此預覽未連接本機設定，無法儲存。")
            return
        try:
            self.save_key(value)
        except Exception:
            # Do not surface an exception containing a credential or private body.
            self.status.configure(text="無法寫入本機設定，原有 key 保持不變。")
            return
        self.settings.setdefault("gemini", {})["api_key"] = value.strip()
        self.changed(value.strip())
        self.key.set("")
        self.visible.set(False)
        self.toggle_visibility()
        self.status.configure(text=google_key_status(self.settings))
