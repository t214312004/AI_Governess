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

AI 大腦可以選擇不同的後端：Google 的 Gemini CLI（免費入門）、OpenAI 的 Codex CLI、Anthropic 的 Claude Code，或自架的 OpenClaw。

---

## 🚀 安裝

需求：

- Windows 10 / 11
- Python 3.11+ 建議
- Git
- Node.js 18+ / npm，預設 LLM backend `gemini_cli` 會用到
- microphone / speaker
- 若改用其他 CLI backend，需自行安裝並登入對應工具，例如 `codex` 或 `claude`

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

## Gemini CLI 安裝

本專案的 public default backend 是 `gemini_cli`。選擇 Gemini CLI 的原因是：對多數台灣使用者來說，它通常比其他 LLM CLI backend 更容易開始，不一定需要先準備額外付費 API key。

`start.bat` 和 `debug.bat` 已經包含 Gemini CLI 的 preflight 流程：當 `llm.active_backend` 是 `gemini_cli` 時，啟動腳本會先檢查 `gemini` 指令是否存在；如果找不到，會嘗試執行：

```powershell
npm install -g @google/gemini-cli
```

不過仍建議你先手動安裝，錯誤訊息會比較清楚：

1. 安裝 Node.js LTS：到 [nodejs.org](https://nodejs.org/) 下載 Windows installer。
2. 重新開啟 PowerShell。
3. 確認 npm 可用：

```powershell
node --version
npm --version
```

4. 安裝官方 Gemini CLI package：

```powershell
npm install -g @google/gemini-cli
```

5. 第一次登入：

```powershell
gemini
```

依照 Gemini CLI 畫面提示登入 Google 帳號。登入完成後，可以輸入 `/quit` 離開，再回到本專案執行 `.\start.bat`。

安全提醒：請確認 package name 是完整的 `@google/gemini-cli`，不要安裝來路不明或名稱相似的 npm package。

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

`start.bat` 和 `debug.bat` 會讀取 layered config 裡的 `llm.active_backend`，再做對應 backend 的 preflight check。預設是 `gemini_cli`，因此第一次啟動時會檢查 Gemini CLI 是否已安裝與登入。

## 設定檔

設定採 layered config：

- `ai_voice_assistant/config.default.json`：public 預設值，會提交到 Git。
- `ai_voice_assistant/config.example.json`：給新使用者參考與複製。
- `ai_voice_assistant/config.local.json`：每台機器自己的設定，不會提交到 Git。

建議新使用者只改 `config.local.json`。

常見設定：

- `llm.active_backend`：預設 `gemini_cli`；也可改成 `codex_cli`、`claude_code` 或 `openclaw`
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
ai_voice_assistant/voice_profiles/Thomas/sample_01.wav
ai_voice_assistant/voice_profiles/ViVi/sample_01.wav
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

GUI 使用 `customtkinter`，角色狀態動畫放在 `ai_voice_assistant/assets/states/`。

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

## 安全提醒

這個專案可能會使用 microphone、speaker、keyboard/mouse activity、LLM CLI 和本機工具。若你把 LLM backend 設成高權限模式，例如 `danger-full-access`、`approval_policy=never`、`--yolo` 或 `bypassPermissions`，請確認 workspace 內沒有你不希望 LLM 工具讀取或修改的檔案。

public default config 採用較保守的設定；你可以在自己的 `config.local.json` 裡調整。

## 授權

Source code 使用 MIT License。模型、語音、圖片與 generated assets 可能有不同授權或來源限制，請參考：

- `LICENSE`
- `ASSET_LICENSE.md`
- `THIRD_PARTY_NOTICES.md`
- `SECURITY.md`

---

> AI Governess 的核心理念是：**AI 助手可以開源，但你的家庭記憶、聲音與日常資料應該留在你自己的電腦裡。**
