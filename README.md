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

⏰ **主動提醒**
待機時會定期巡檢，該提醒的事情用語音告訴你。附近沒人時，提醒會安靜地留在畫面上，不會一直唸。

🧠 **記得你的家庭大小事**
家庭成員的稱呼、偏好、作息習慣、常用的規矩——全部寫在你自己電腦裡的記憶檔案中。換了電腦也能帶走，不怕雲端服務關閉。

🔧 **不只聊天，還能動手做事**
這是愛管家最特別的地方。背後的 AI 不是只會回答問題——它能**真正操作你的電腦**：讀檔案、查資料、執行腳本、整理筆記。這就像請了一個數位管家，不只會說話，還會動手幫你處理事情。

🔒 **你的隱私，你自己掌握**
所有對話記錄、家庭記憶、語音錄音、設定檔，全部留在你自己的電腦上。GitHub 上只有程式碼，沒有你的任何個人資料。

---

## 📸 畫面預覽

![AI Governess UI screenshot](docs/images/ui-screenshot.png)

---

## 🤔 跟 Siri、Google 助理有什麼不同？

| | Siri / Google 助理 | 愛管家 |
|---|---|---|
| **住在哪裡** | 雲端伺服器 | 你家的 Windows 電腦 |
| **AI 等級** | 功能受限的語音指令 | 最新 LLM（跟 ChatGPT 同等級） |
| **能做什麼** | 回答問題、設鬧鐘 | 回答問題、讀寫檔案、執行程式、主動提醒 |
| **記憶** | 存在別人的伺服器 | 存在你自己的電腦，隨時可帶走 |
| **隱私** | 語音上傳到雲端 | 所有資料留在本機 |
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

AI 大腦可以選擇不同的後端：Antigravity CLI（public default）、OpenCode CLI、OpenAI 的 Codex CLI、Anthropic 的 Claude Code，或自架的 OpenClaw。

---

## 🚀 安裝

需求：

- Windows 10 / 11
- Python 3.11+ 建議
- Git
- Antigravity CLI（`agy`），預設 LLM backend `antigravity_cli` 會用到
- Node.js 18+ / npm，若使用需要透過 npm 安裝的 CLI backend 才會用到
- microphone / speaker
- 若改用其他 CLI backend，需自行安裝並登入對應工具，例如 `opencode`、`codex` 或 `claude`

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
.\scripts\download_models.ps1
```

建立自己的 local config：

```powershell
copy ai_voice_assistant\config.example.json ai_voice_assistant\config.local.json
```

## Antigravity CLI 安裝

本專案的 public default backend 是 `antigravity_cli`。因為 Gemini CLI 已停止支援，預設改用本機的 Antigravity CLI（`agy`）執行 LLM 回覆流程。

`start.bat` 和 `debug.bat` 已經包含 Antigravity CLI 的 preflight 流程：當 `llm.active_backend` 是 `antigravity_cli` 時，啟動腳本會先檢查 `agy` 指令是否存在；如果找不到，會提示安裝 Google Antigravity 或執行：

```powershell
agy install
```

建議你先手動確認，錯誤訊息會比較清楚：

1. 安裝 Google Antigravity，並確認 `agy` 已加入 PATH。
2. 重新開啟 PowerShell。
3. 確認 CLI 可用：

```powershell
agy --help
```

4. 若 CLI component 尚未完成安裝，依畫面提示或手動執行：

```powershell
agy install
```

5. 第一次使用前，先完成 Antigravity 的登入或授權流程，再回到本專案執行 `.\start.bat`。

`antigravity_cli` 預設使用 `ai_voice_assistant/agent_workspace/` 作為工作目錄；需要調整時請覆寫 `config.local.json` 的 `llm.antigravity_cli.project_dir`。

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

- `llm.active_backend`：預設 `antigravity_cli`；也可改成 `opencode_cli`、`codex_cli`、`claude_code` 或 `openclaw`
- `whisper.model_size`：Whisper model size
- `whisper.device`：`cpu` 或 `cuda`
- `tts.voice`：Edge TTS voice
- `speaker_recognition.enabled`：是否啟用說話者辨識
- `whisper_audio_archive.enabled`：是否保存送進 Whisper 的語音
- `heartbeat.enabled`：是否啟用待機巡檢

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
- `ai_voice_assistant/agent_workspace/*.md`
- `ai_voice_assistant/voice_profiles/`
- `ai_voice_assistant/whisper_audio_archive/`
- `ai_voice_assistant/logs/`
- downloaded models under `ai_voice_assistant/models/`
- local `venv/`

這樣你可以保留自己的家庭記憶、聲音樣本、錄音、LLM 設定與 logs，同時仍然能跟別人共享 bugfix 和功能改進。

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
.\scripts\pre_git_audit.ps1
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

公開 repo 不包含 speaker centroid `.pt`、prompt WAV、reference WAV 或真實語音樣本。啟用步驟請看：

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
