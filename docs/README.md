# 文件索引

目前正式入口是 `start.bat`／`debug.bat` → `main.py` → 五步初始設定 → 全螢幕 session。
操作說明以現行指南及程式為準；歷史 audit 保留當時的驗證結果。

## 安裝與使用

- [初始設定指南](startup_setup_guide.md)：AI 登入與查詢、聲音裝置、服務、喚醒詞／聲紋、進階搜尋與儲存。

- [根目錄 README](../README.md)：安裝、CLI backend、啟動、隱私與設定。
- [主程式 README](../ai_voice_assistant/README.md)：使用方式、設定與架構。
- [UI README](../ai_voice_assistant/ui/README.md)：初始設定、固定 session、輸入／輸出、白板與原生測試。
- [HTML 互動白板](html_whiteboard.md)：app 製作、hide／restore、每日額度、tool 狀態、網路限制與故障排除。
- [排程指南](schedule.md)：獨立 poller、trigger、payload、確認／undo 與報告邊界。
- [BlueMagpie TTS](bluemagpie_tts_setup.md)：選用的 local worker、模型與語音素材。
- [Gemini 語音設定](gemini_audio_setup.md)：初始 UI、Google key 儲存／刪除、STT／TTS、音色試聽與完整調整參數。

## 開發與模組

- [2026-10-24 Antigravity 官方 ACP 遷移評估](antigravity_acp_migration_plan_2026-10-24.md)：Google AI Pro 真實登入、模型／工具實測、能力差異與完整切換條件。
- [Gemini-only 能力與反應時間補充](antigravity_acp_capabilities_latency_2026-10-24.md)：現有 PTY client 與 ACP 同模型多輪比較、cold start，以及跨 workspace 讀檔差異。
- [Gemini 語音功能規劃](gemini_audio_plan.md)、[2026-10-18 API 實測](gemini_audio_benchmark_2026-10-18.md)：已實作的設計契約、STT／TTS 多輪比較與量測限制。
- [Contributing](../CONTRIBUTING.md)、[Security](../SECURITY.md)、[Third-party notices](../THIRD_PARTY_NOTICES.md)、[Asset license](../ASSET_LICENSE.md)、[Code of conduct](../CODE_OF_CONDUCT.md)。
- [Core](../ai_voice_assistant/core/README.md)、[LLM](../ai_voice_assistant/llm/README.md)、[TTS](../ai_voice_assistant/tts/README.md)、[Utils](../ai_voice_assistant/utils/README.md)。
- 本機資料 placeholder：[Models](../ai_voice_assistant/models/README.md)、[Voice profiles](../ai_voice_assistant/voice_profiles/README.md)、[Audio archive](../ai_voice_assistant/whisper_audio_archive/README.md)、[Schedule state](../ai_voice_assistant/schedule_state/README.md)、[Whiteboard state](../ai_voice_assistant/whiteboard_state/README.md)。

## Sophia 提示詞

- 公開 [AGENTS.md](../ai_voice_assistant/agent_workspace_template/AGENTS.md)：人格、家庭互動、目前 UI、巡檢與記憶規則。
- 公開 [TOOLS.md](../ai_voice_assistant/agent_workspace_template/TOOLS.md)：工具能力、payload、成功／失敗結果及授權。
- 公開 [Camera README](../ai_voice_assistant/agent_workspace_template/tools/camera/README.md) 與 [HTML apps README](../ai_voice_assistant/agent_workspace_template/apps/README.md)。
- 執行時使用 `agent_workspace/` 的 private 版本；bootstrap 只補缺少檔案。更新 template 不會自動覆寫已存在的家庭記憶、提示詞或工具，維護時要同步相關契約。

## Audit 紀錄

- [2026-10-25 提交前 audit](pre_submit_audit_2026-10-25.md)：本批變更審查、取消／設定修補、dependency 安全檢查與驗證限制。

- [2026-10-20 初始 UI audit](startup_ui_audit_2026-10-20.md) 與 [改善／驗證紀錄](startup_ui_changes_2026-10-20.md)。

- [2026-10-06 日誌檢查與修補](log_audit_2026-10-06.md)。
- [2026-10-05 文件與 Sophia 提示詞核對](documentation_audit_2026-10-05.md)。
- [2026-10-05 正式 UI 整合快照](ui-integration-audit.md)。
- [2026-10-03 module audit](audit_2026-10-03.md)。

歷史文件的模型數量、CLI 登入狀態及測試數字只代表記錄當時，不能當成目前設備或服務可用的保證。
