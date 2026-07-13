# Camera Tool

這個工具提供給本地 AI agent 透過 Windows DirectShow 拍照。

從 `ai_voice_assistant\agent_workspace` 執行：

```powershell
.\tools\camera\camera.cmd list-devices
.\tools\camera\camera.cmd list-resolutions --device "ASUS FHD webcam"
.\tools\camera\camera.cmd capture --resolution 1280x720 --timeout-seconds 15
```

- `--resolution` 接受 `WIDTHxHEIGHT`、`auto`、`high`、`medium`、`low`、`fhd`、`hd`、`vga`。
- 預設 `--fallback nearest`；可改成 `--fallback error`。
- 預設略過最初 6 幀，可用 `--settle-frames` 調整。
- 預設最長等待 15 秒，可用 `--timeout-seconds` 調整。
- 未指定 `--output` 時會建立帶微秒與隨機尾碼的唯一檔名。
- 只有在 Thomas 或 ViVi 明確授權時才可觸發拍照。
