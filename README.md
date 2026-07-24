# AI Governess — 愛管家

### 住在你家電腦裡的 AI 語音管家

愛管家是一個可以**用說的**跟它互動的桌面 AI 助手。它不需要手機、不需要智慧音箱，只要家裡有一台 Windows 電腦、一組麥克風和喇叭，就能成為你的家庭好幫手。

> 💡 **跟 ChatGPT 打字聊天不一樣，愛管家能聽你說話、用語音回答你，還能主動提醒你該做的事。**

---

## ✨ 它能幫你做什麼？

🗣️ **用說的就好**
不用打字，不用看螢幕。像跟家人講話一樣，說「愛管家，明天早上七點提醒我」就行了。

🧒 **陪孩子互動**
幫孩子回答功課問題、一起講故事、聊天解悶。每個家庭可以建立自己的故事世界觀，讓 AI 記住角色和劇情。

⏰ **主動提醒與排程**
待機時會定期巡檢，該提醒的事情用語音告訴你。也可以建立一次性、每日或每週排程，讓它到時間自己整理天氣、待辦、學習重點或其他家庭報告；附近沒人時，提醒會安靜地留在畫面上，不會一直唸。

🧠 **記得你的家庭大小事**
家庭成員的稱呼、偏好、作息習慣、常用的規矩——全部寫在你自己電腦裡的記憶檔案中。換了電腦也能帶走，不怕雲端服務關閉。

🧾 **把重點留在白板上**
有些內容用念的不夠清楚：清單、表格、讀書重點、食譜步驟、今天行程。愛管家可以把整理好的文字或圖片放到畫面左側的白板，讓內容留著給家人慢慢看，對話也可以繼續。

🔧 **不只聊天，還能動手做事**
這是愛管家最特別的地方。背後的 AI 不是只會回答問題——它能**真正操作你的電腦**：讀檔案、查資料、執行腳本、整理筆記。這就像請了一個數位管家，不只會說話，還會動手幫你處理事情。

🔒 **你的隱私，你自己掌握**
家庭記憶、語音封存、排程資料、白板內容、設定檔與 logs 都保存在自己的電腦並排除於 Git；但選用 cloud-backed LLM、Groq STT、Edge TTS 或 web search 時，完成請求所需的文字、音訊或查詢仍會送到對應服務。

---

## 📸 畫面預覽

![AI Governess UI screenshot](docs/images/ui-screenshot.png)

---

## 🤔 跟 Siri、Google 助理有什麼不同？

| | Siri / Google 助理 | 愛管家 |
|---|---|---|
| **住在哪裡** | 雲端伺服器 | 你家的 Windows 電腦 |
| **AI 等級** | 功能受限的語音指令 | 最新 LLM（跟 ChatGPT 同等級） |
| **能做什麼** | 回答問題、設鬧鐘 | 回答問題、讀寫檔案、執行程式、排程任務、白板展示 |
| **記憶** | 存在別人的伺服器 | 存在你自己的電腦，隨時可帶走 |
| **隱私** | 由服務商管理 | runtime state 留在本機；依所選 backend 傳送必要資料 |
| **費用** | 綁定特定裝置 / 服務 | 免費、開源，你可以自己改 |
| **語言** | 多語但中文體驗一般 | 繁體中文優先設計 |

> 🔑 **關鍵差異：** 傳統語音助理只能執行預設好的指令（「明天天氣如何」）。愛管家背後的 AI 可以像真人助手一樣**理解你的需求並自己想辦法完成**，包括讀檔案、寫筆記、跑指令——這就是 LLM CLI Agent 的威力。

---

## 🧩 它怎麼運作的？

簡單來說：

> **你說話 → 電腦聽到 → 轉成文字 → AI 思考並回覆 → 念給你聽**

背後的技術流程：

```text
麥克風收音
  → 偵測是不是有人在說話（VAD）
  → 聽到喚醒詞「愛管家」
  → 語音轉文字（Whisper）
  → AI 大腦思考回覆（LLM）
  → 文字轉語音（TTS）
  → 喇叭播放
```

AI 大腦可以選擇不同的後端：Antigravity CLI（public default）、Grok Build、OpenCode CLI、OpenAI 的 Codex CLI，或 Anthropic 的 Claude Code。

除了即時語音對話，愛管家也會透過待機巡檢檢查到期的排程。排程可以只是單純提醒，也可以請 AI 到時間整理一份報告，等合適的家人回來時再顯示或朗讀。白板則讓 AI 把較適合閱讀的內容留在畫面上，而不是全部硬塞進語音回答裡。

---

## 🚀 安裝

需求：

- Windows 10 / 11
- Python 3.11+ 建議
- Git
- Antigravity CLI（`agy`），預設 LLM backend `antigravity_cli` 會用到
- Node.js 18+ / npm，若使用需要透過 npm 安裝的 CLI backend 才會用到
- microphone / speaker
- 若改用其他 CLI backend，需自行安裝並登入對應工具，例如 `grok`、`opencode`、`codex` 或 `claude`

建立 Python virtual environment：

```powershell
cd ai_voice_assistant
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

若你有 NVIDIA GPU 並想使用 CUDA 加速 Whisper，可改裝 CUDA 版本：

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements-cuda.txt
```

CPU-only 使用者只需安裝 `requirements.txt`，不需要額外的 CUDA 套件。

下載 wake-word model：

```powershell
cd ..
powershell -ExecutionPolicy Bypass -File .\scripts\download_models.ps1
```

建立自己的 local config：

```powershell
copy ai_voice_assistant\config.example.json ai_voice_assistant\config.local.json
```

## 建議的語音設定

日常使用建議優先選：

- 語音辨識 STT：`groq`。它使用 Groq 的 Whisper transcription endpoint，速度快，不需要本機 GPU；但語音會送到 Groq API。若你要完全離線或不想把語音送出本機，才改用 local `faster-whisper`。
- 文字轉語音 TTS：`edge`（`edge-tts`）。這是目前最適合日常使用的預設選項，速度和穩定性都比 experimental local TTS 更適合家庭互動；合成文字會傳送至 Microsoft 的線上語音服務。若需要離線 TTS，請使用 experimental `bluemagpie`。

Groq API key 申請與設定：

1. 到 [Groq Console](https://console.groq.com/) 建立或登入帳號。
2. 打開 [API Keys](https://console.groq.com/keys)，按 `Create API Key` 建立 key。Groq 文件也建議把 key 放在環境變數，避免不小心寫進 codebase。
3. 在 Windows PowerShell 設定使用者環境變數：

```powershell
[Environment]::SetEnvironmentVariable("GROQ_API_KEY", "gsk_your_key_here", "User")
```

4. 關掉 PowerShell 視窗再重新開啟，確認目前 session 讀得到：

```powershell
$env:GROQ_API_KEY
```

5. 編輯 `ai_voice_assistant/config.local.json`，把 STT 切到 `groq`，TTS 保持 `edge`：

```json
{
  "whisper": {
    "backend": "groq",
    "groq": {
      "api_key": "",
      "api_key_env": "GROQ_API_KEY",
      "model": "whisper-large-v3"
    }
  },
  "tts": {
    "backend": "edge",
    "voice": "zh-TW-HsiaoChenNeural",
    "rate": "+0%",
    "volume": "+0%"
  }
}
```

`whisper.groq.api_key` 建議保持空字串，讓程式從 `GROQ_API_KEY` 環境變數讀 key。真的需要只針對這個專案設定時，也可以把 key 放在 `config.local.json` 的 `whisper.groq.api_key`；但不要放進 `config.default.json`、`config.example.json`、README 或任何會提交到 Git 的檔案。

目前預設模型是 `whisper-large-v3`，Groq 官方文件把它定位為高準確度、多語言的 speech-to-text model；若未來更重視成本或速度，可以再評估 `whisper-large-v3-turbo`。本專案目前的 public config 先保守使用 `whisper-large-v3`。

## Antigravity CLI 安裝

本專案的 public default backend 是 `antigravity_cli`，使用本機的 Antigravity CLI（`agy`）執行 LLM 回覆流程。

`start.bat` 和 `debug.bat` 已經包含 Antigravity CLI 的 preflight 流程：當 `llm.active_backend` 是 `antigravity_cli` 時，啟動腳本會先檢查 `agy` 指令是否存在。這個檢查只負責擋下缺少 CLI 的情況，不會自動安裝。

建議先在 PowerShell 手動安裝並確認，錯誤訊息會比較清楚：

1. 安裝 Antigravity CLI：

```powershell
Invoke-RestMethod https://antigravity.google/cli/install.ps1 | Invoke-Expression
```

2. 重新開啟 PowerShell，讓 PATH 更新生效。
3. 確認 CLI 可用：

```powershell
agy --help
```

4. 如果 `agy --help` 可以執行，但 CLI 提示還需要設定 shell / PATH，再依畫面提示執行：

```powershell
agy install
```

5. 第一次使用前，建議先在 PowerShell 跑一次簡短請求，讓 Antigravity 完成登入或授權流程：

```powershell
agy -p "請只回答 ready"
```

6. 回到本專案根目錄執行 `.\start.bat`。如果啟動腳本仍然顯示找不到 `agy`，通常是 PowerShell 還沒重新讀取 PATH，請關掉視窗後再開一次。

`antigravity_cli` 預設使用 `ai_voice_assistant/agent_workspace/` 作為工作目錄；需要調整時請覆寫 `config.local.json` 的 `llm.antigravity_cli.project_dir`。

## Codex CLI backend

`codex_cli` 使用 `codex app-server --listen stdio://` 維持長連線 thread，支援 streaming、session refresh 與 `turn/interrupt`。啟動 script 會在 Codex 被選為 active backend 時執行 `codex update`，確保使用已安裝管道的最新版 CLI。

public default 使用 `sandbox: "danger-full-access"` 與 `approval_policy: "never"`。這等同本機 full-trust / YOLO 模式：Codex 不會等待互動式 approval，並可在作業系統帳號權限範圍內執行工具。請只在你信任的電腦、workspace 與語音輸入環境使用。

## OpenCode CLI backend

本專案也支援 `opencode_cli`。它使用 `opencode acp --cwd <agent_workspace>` 的長連線 ACP 模式，不使用單次 `opencode run`，因此可以串流回覆、保留連續對話、支援 cancel 與 tool call keepalive。

在 `config.local.json` 切換：

```json
{
  "llm": {
    "active_backend": "opencode_cli",
    "opencode_cli": {
      "project_dir": "./agent_workspace",
      "model": "",
      "mode": "",
      "permission_mode": "yolo",
      "auto_approve": true,
      "enable_web_search": true
    }
  }
}
```

`model` 與 `mode` 預設空字串，代表沿用 OpenCode 自己的 default。只有明確填入非空值時，程式才會透過 ACP `session/set_config_option` 設定，並先驗證 OpenCode 回傳的 `configOptions`。

`permission_mode: "yolo"` 會用 `OPENCODE_CONFIG_CONTENT` 對 OpenCode subprocess 注入 `permission: "allow"`，並自動回覆 ACP permission request。這是本機 full-trust 模式，不是 sandbox；請只在你信任的電腦與 workspace 使用。

`enable_web_search: true` 會對 OpenCode subprocess 設定 `OPENCODE_ENABLE_EXA=1`，讓 OpenCode 的 `websearch` tool 透過 Exa AI hosted MCP service 查詢網路。這不需要 Exa API key，但代表查詢內容會送到外部服務；如需完全離線或避免外部搜尋，請在 `config.local.json` 改成 `false`。

## 資料傳送與本機 logs

- `local` Whisper、BlueMagpie TTS、排程、白板及 private memory 可在本機處理；它們的 runtime files 會被 Git 排除。
- `groq` STT 會把錄音傳至 Groq；`edge` TTS 會把待合成文字傳至 Microsoft。
- Antigravity、Grok、OpenCode、Codex 與 Claude Code 是本機啟動的 CLI，但模型服務通常在雲端，prompt、private context 與工具結果可能由其供應商處理。實際 retention 依各 CLI／服務帳號政策為準。
- OpenCode Exa、Grok web/X search 或其他網路工具會把搜尋字詞及必要 context 傳至外部服務。
- `logs/llm_io-YYYY-MM-DD.log` 預設以 plaintext 保存完整 LLM input/output，保留 5 天；一般 debug log 位於 `logs/ai_voice_assistant-YYYY-MM-DD.log`。不要分享或提交這些檔案。

## Grok Build backend

`grok_cli` 使用 Grok Build 的 `grok agent stdio` ACP v1 長連線，支援連續 session、cancel、tool permission、web search 與 X search。請先依 [xAI Grok Build 文件](https://docs.x.ai/build/overview) 安裝，然後執行：

```powershell
grok login
grok models
```

若剛安裝後目前的 PowerShell 還找不到 `grok`，程式也會檢查 `%USERPROFILE%\.grok\bin\grok.exe`。

在 `config.local.json` 切換：

```json
{
  "llm": {
    "active_backend": "grok_cli",
    "grok_cli": {
      "project_dir": "./agent_workspace",
      "model": "",
      "reasoning_effort": "",
      "auto_approve": true,
      "auto_approve_scope": "once",
      "enable_web_search": true,
      "enable_subagents": false
    }
  }
}
```

Grok Build 會略過被 Git ignore 的 instruction files，因此 client 會在啟動時把 private `agent_workspace/AGENTS.md` 與 `MEMORY.md` 組成 temporary agent profile，完成 ACP session setup 後立即刪除。Grok 自己仍會把 session 保存在 `%USERPROFILE%\.grok\sessions`，內容也會送到 xAI model；請把這視為使用 cloud LLM backend 的資料邊界。

Grok 在 tool call 前可能先輸出操作旁白。為避免 UI / TTS 念出「我現在要搜尋」等中間過程，`grok_cli` 會保留 keepalive，但只把 turn 結束時最後一段 assistant message 交給上層。

第一次啟動時，程式會自動建立下列 private folders：

- `ai_voice_assistant/agent_workspace/`
- `ai_voice_assistant/voice_profiles/`
- `ai_voice_assistant/whisper_audio_archive/`

如果 `agent_workspace/` 裡缺少初始檔案，程式會從 `agent_workspace_template/` 複製一份乾淨模板。

## 啟動

一般啟動：

```powershell
.\start.bat
```

Debug 啟動：

```powershell
.\debug.bat
```

`start.bat` 和 `debug.bat` 會讀取 layered config 裡的 `llm.active_backend`，再做對應 backend 的 preflight check。預設是 `antigravity_cli`，因此第一次啟動時會檢查 Antigravity CLI 的 `agy` 指令是否可用。

## 設定檔

設定採 layered config：

- `ai_voice_assistant/config.default.json`：public 預設值，會提交到 Git。
- `ai_voice_assistant/config.example.json`：給新使用者參考與複製。
- `ai_voice_assistant/config.local.json`：每台機器自己的設定，不會提交到 Git。

建議新使用者只改 `config.local.json`。

常見設定：

- `llm.active_backend`：預設 `antigravity_cli`；也可改成 `grok_cli`、`opencode_cli`、`codex_cli` 或 `claude_code`
- `whisper.backend`：建議日常使用 `groq`；若要完全離線則使用 `local`
- `whisper.groq.api_key_env`：預設 `GROQ_API_KEY`，用來讀取 Groq API key
- `whisper.model_size`：Whisper model size
- `whisper.device`：`cpu` 或 `cuda`
- `tts.backend`：建議日常使用 `edge`
- `tts.voice`：Edge TTS voice
- `speaker_recognition.enabled`：是否啟用說話者辨識
- `whisper_audio_archive.enabled`：是否保存送進 Whisper 的語音
- `heartbeat.enabled`：是否啟用待機巡檢
- `schedule.enabled`：是否啟用本機排程管理
- `whiteboard.enabled`：是否啟用畫面白板

## 建立自己的記憶

每個使用者都應該擁有自己的 private memory，而不是使用別人的。

第一次啟動後，可以編輯：

- `ai_voice_assistant/agent_workspace/MEMORY.md`
- `ai_voice_assistant/agent_workspace/ARCHIVE.md`
- `ai_voice_assistant/agent_workspace/STORIES.md`
- `ai_voice_assistant/agent_workspace/TOOLS.md`

這些檔案已被 `.gitignore` 排除。你可以在裡面寫自己的家庭規則、稱呼、偏好、故事設定與本機工具說明。

## 說話者辨識

如果你想讓系統知道「可能是誰在說話」，可以在 `voice_profiles/` 建立資料夾：

```text
ai_voice_assistant/voice_profiles/PersonA/sample_01.wav
ai_voice_assistant/voice_profiles/PersonB/sample_01.wav
```

`voice_profiles/` 是 private data，不會提交到 GitHub。

---

## 技術架構

以下內容主要面向開發者與 AI agent。

### Pipeline

```text
sounddevice 錄音
  -> silero-vad 判斷語音起訖
  -> sherpa-onnx 偵測喚醒詞
  -> faster-whisper 轉文字
  -> LLM backend 串流回覆
  -> edge-tts 合成語音
  -> sounddevice 播放
```

GUI 使用 `customtkinter`，角色狀態動畫的 runtime layered assets 放在 `ai_voice_assistant/assets/states/layers/`。

主要程式位於 `ai_voice_assistant/`。

### Schedule 與白板

Schedule 是本機狀態，不依賴外部行事曆服務。`ScheduleManager` 負責 `ai_voice_assistant/schedule_state/` 裡的 schedules、runs、drafts 與 pending reports；到期執行由 heartbeat 巡檢驅動。LLM 不直接改 JSON，而是透過 `ai_voice_assistant/agent_workspace/tools/schedule_tool.py` 建立、確認、編輯、停用或刪除排程，payload 放在 `agent_workspace/tool_payloads/schedule/`。

白板由 `WhiteboardManager` 管理，durable state 和 materialized assets 放在 `ai_voice_assistant/whiteboard_state/`。LLM 透過 `ai_voice_assistant/agent_workspace/tools/whiteboard_tool.py` 顯示 Markdown 或單張圖片、查詢狀態或關閉白板；UI 會輪詢目前 active state，並把內容覆蓋顯示在左側 Sophia 舞台上。白板是 display-only，適合清單、表格、步驟與學習筆記，不把 raw HTML、外部連結或互動表單當成可操作內容。

### Public Source vs Private Data

這個 repo 採用「source code 可開源、private runtime state 留在本機」的設計。

會提交到 GitHub 的內容：

- source code：`core/`、`llm/`、`tts/`、`ui/`、`utils/`
- tests：`tests/`
- public config：`config.default.json`、`config.example.json`
- private memory template：`agent_workspace_template/`
- 文件、授權、啟動腳本

不會提交到 GitHub 的內容：

- `ai_voice_assistant/config.local.json`
- `ai_voice_assistant/agent_workspace/`
- `ai_voice_assistant/schedule_state/`
- `ai_voice_assistant/whiteboard_state/`
- `ai_voice_assistant/voice_profiles/`
- `ai_voice_assistant/whisper_audio_archive/`
- `ai_voice_assistant/logs/`
- downloaded models under `ai_voice_assistant/models/`
- local `venv/`

這樣你可以保留自己的家庭記憶、排程、白板內容、聲音樣本、錄音、LLM 設定與 logs，同時仍然能跟別人共享 bugfix 和功能改進。

### 開發與測試

安裝開發 dependencies：

```powershell
cd ai_voice_assistant
.\venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

執行測試：

```powershell
.\venv\Scripts\python.exe -m pytest -q
```

開源前檢查 private paths：

```powershell
cd ..
powershell -ExecutionPolicy Bypass -File .\scripts\pre_git_audit.ps1
```

### GitHub 發布前流程

如果你要直接在目前資料夾初始化 Git，建議順序如下：

```powershell
git init
git add .
.\scripts\pre_git_audit.ps1
git status --short
git commit -m "Initial public source release"
```

請確認 `git status --short` 裡沒有：

- `config.local.json`
- `logs/`
- `whisper_audio_archive/`
- `voice_profiles/`
- `agent_workspace/*.md`
- `models/` 內下載的模型
- `venv/`
- `.venv-bluemagpie/`
- `tts_eval_outputs/`

## BlueMagpie TTS（選用）

預設 TTS backend 仍是 `edge-tts`。BlueMagpie TTS 已整合為可選的 experimental local backend，但需要另外建立 `ai_voice_assistant/.venv-bluemagpie`，並自行準備或下載模型與 voice conditioning assets。

目前 BlueMagpie local TTS 生成速度明顯慢於 `edge-tts`，不適合作為公開專案的預設或日常主力 TTS。建議只把它當作 offline/local fallback：例如網路 TTS 不可用、需要測試本機模型、或可以接受較長延遲時使用。

公開 repo 不包含 speaker centroid `.pt`、prompt WAV、reference WAV 或真實語音樣本。啟用 BlueMagpie、製作自己的 `.pt`、準備語音提示 prompt WAV 的步驟請看：

- `docs/bluemagpie_tts_setup.md`

## 安全提醒

這個專案可能會使用 microphone、speaker、keyboard/mouse activity、LLM CLI 和本機工具。若你把 LLM backend 設成高權限模式，例如 OpenCode `permission_mode: "yolo"`、`danger-full-access`、`approval_policy=never`、`--yolo` 或 `bypassPermissions`，請確認 workspace 內沒有你不希望 LLM 工具讀取或修改的檔案。

public default config 會盡量避免提交本機 private 資料；你可以在自己的 `config.local.json` 裡調整 backend 權限、網路搜尋與本機工具行為。

## 授權

Source code 使用 MIT License。模型、語音、圖片與 generated assets 可能有不同授權或來源限制，請參考：

- `LICENSE`
- `ASSET_LICENSE.md`
- `THIRD_PARTY_NOTICES.md`
- `SECURITY.md`

---

> AI Governess 的核心理念是：**AI 助手可以開源，但你的家庭記憶、聲音與日常資料應該留在你自己的電腦裡。**
