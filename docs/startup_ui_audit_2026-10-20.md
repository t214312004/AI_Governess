# 初始設定 UI audit（2026-10-20）

> 此為修改前的 audit 快照。A01–A11 的後續實作與驗證見 [初始 UI 改善紀錄](startup_ui_changes_2026-10-20.md)，現行操作見 [初始設定指南](startup_setup_guide.md)。

## 結論

**現有初始 UI 的設定入口覆蓋率高，但尚不足以讓第一次使用的人直覺、可靠地完成設定。**

- **設定方式：部分通過。** Backend／模型、輸入輸出模式、Google key、語音試聽與額度已有專用控制；多數其他選項仍是依 JSON 結構展開的表單。
- **排版與導覽：未通過。** 實際 Tk 量測重現隱藏區域仍佔高度、切頁沿用舊捲動位置，以及小視窗的錯誤文字擠壓導覽按鈕。
- **設定完整性：設定值有入口，使用者任務仍有缺口。** 麥克風／喇叭選擇、喚醒詞內容編輯、聲紋建立與初次安裝／登入引導，未形成可在初始 UI 完成的流程。BlueMagpie 選擇與實際啟用不同步，nullable seed 也有無法還原的問題。

應優先修正「選了卻不生效」和「接受不支援的設定」，再處理空白、捲動與錯誤回復，最後調整資訊架構。單純增加更多欄位無法解決上述問題。

## 範圍、方法與限制

- 基準：working tree 當下內容，HEAD `fcd1407`，包含既有未提交修改及新增的 Gemini audio 模組；並非只檢查 HEAD。
- 追查 `main.py → StartupWindow → StartupView → session_snapshot → Config.apply_snapshot → VoiceAssistant.prepare_for_gui`，核對 public defaults、所有進階分類、STT／TTS factory 及設定驗證。
- 以 public `config.default.json` 建立隔離的 Tk fixture，模型目錄使用 stub；測量控制項尺寸與捲動範圍，重現設定保存及錯誤情境。未呼叫真實語音服務、錄音或更新 CLI，未變更家庭 private config。
- 執行相關回歸及選定 native Tk 測試，結果見文末。
- Windows 畫面擷取失敗：`CreateForMonitor ... 0x80070057`；重新選取視窗後，桌面存取亦回報 `GetCursorPos ... 0x80070005`。因此**本報告沒有完成像素畫面目視、色彩對比、screen reader 或真人可用性驗證**。排版問題以實際 Tk geometry／mapping 狀態及程式碼為證據，不將它們冒充 screenshot review。
- 測量 DPI 為 125%；fixture 分別指定 logical `1160×640`、`640×480`，實際 client area 為 `1450×800`、`800×600`。數值不代表所有螢幕或正式視窗定位後的尺寸。
- 本次只新增 audit 文件，沒有修正產品程式或改動既有修改。

## 已做得好的部分

1. 五步驟、左側導覽、上／下一步及確認頁，建立了清楚的基本流程。較窄時自動隱藏側邊摘要，中央表單支援捲動。見 `ui/startup.py:70–125`。
2. 語音輸入、語音輸出可獨立選擇，STT／TTS 也可交叉搭配；有草稿音檔辨識、5 秒錄音、試聽與停止入口。見 `ui/startup.py:241`、`ui/audio_settings.py:33`。
3. 草稿使用完整設定副本，包含未知本機 keys；設定原子寫入，準備失敗嘗試 rollback，準備期間凍結控制。這些行為有回歸測試支持。見 `config.py:173`、`ui/startup_window.py:48`、`ui/startup.py:485`。
4. Google key 有遮罩、不預填舊 key、顯示新輸入、儲存／刪除與環境變數來源提示；立即生效的保存方式有明確說明。見 `ui/google_credentials.py:8`、`utils/google_credentials.py:15`。
5. LLM 模型與 effort 向 CLI 查詢能力，避免純手動輸入不相容組合；全螢幕 Alt+F4 政策也有提示。這些設計應保留。

## 設定覆蓋盤點

對 public defaults 的 **206 個 leaf values** 逐一比對實際產生的編輯控制及跳過規則：

| 入口類型 | 數量 | 說明 |
| --- | ---: | --- |
| 進階通用表單 | 177 | 約 86%；bool 使用 switch，其他多為單行 entry |
| 第二步語音專用欄位 | 14 | STT／TTS、Edge、Gemini 與 streaming TTS |
| 其他專用控制 | 7 | active backend、Google key、輸入／輸出／更新 CLI、HTML 額度、對話字級 |
| 隨選定 LLM backend 編輯的模型／effort | 6 | 計算 defaults 中已存在的 leaves；部分 backend 的值會在選擇後新增 |
| 刻意固定的政策 | 2 | fullscreen exit／enter shortcuts；啟動時固定為 Alt+F4／空清單 |
| 未能對應入口或固定政策 | **0** | 僅限本次 public defaults 的 leaf 盤點 |

**204 個值有控制入口，不代表 204 個值都能完整操作或一定生效。** Seed 還原、BlueMagpie 啟用、取樣率限制是本次已重現的反例。兩個 fullscreen shortcut 是既定政策，不列為遺漏。

| 分類 | defaults leaves | 進階控制數 |
| --- | ---: | ---: |
| audio | 4 | 4 |
| pipeline_v2_5 | 13 | 12 |
| vad | 8 | 8 |
| gemini | 2 | 1 |
| whisper | 31 | 26 |
| wake_word | 2 | 2 |
| semantic_chunker | 2 | 2 |
| tts | 45 | 37 |
| whisper_audio_archive | 3 | 3 |
| speaker_recognition | 5 | 5 |
| presence_detection | 4 | 4 |
| hot_listen | 2 | 2 |
| llm | 46 | 39 |
| user_activity_prompt | 4 | 4 |
| heartbeat | 2 | 2 |
| schedule | 10 | 10 |
| whiteboard | 15 | 14 |
| ui | 5 | 2 |
| interaction | 3 | 0 |

進階控制較少的分類，多數由專用控制接管，並非漏欄位。判定依據：`ui/startup.py:23`、`:290`、`ui/audio_settings.py:13`、`core/session_settings.py:99`。

這份數量不包含外部 CLI 認證、檔案內容、Windows 裝置設定，或由環境變數管理的 logging directory／level／retention；這些不能據此宣稱也已涵蓋。

## 依優先順序的問題

以下 P1 表示應先修的設定行為問題；P2 表示明顯影響設定效率、理解或錯誤回復；P3 為較小的一致性問題。

### A01 · P1：選擇 BlueMagpie 不會啟用 BlueMagpie

**重現：** 使用 public defaults，第二步將「語音輸出服務」改成 `bluemagpie`，收集草稿。結果為：

```json
{"tts.backend": "bluemagpie", "tts.bluemagpie.enabled": false}
```

`collect()` 成功，但 engine 的 `speak_stream()` 遇到 `enabled=false` 直接回傳 `played=false, reason=disabled`。使用者必須另到進階設定，在長表單中找到第二個啟用開關。第二步沒有提示這個相依條件。

**依據：** `ui/audio_settings.py:55`、`:136`；`config.default.json:108`；`tts/factory.py:81`；`tts/bluemagpie_tts_engine.py:217`。

**建議／驗收：** 選擇服務後明確處理啟用狀態；未安裝或未完成 worker 設定時顯示具體缺項。不得出現 UI 顯示已選用、engine 卻因另一個隱藏開關停用的情況。試聽錯誤應保留 `disabled` 等實際原因，不能一律變成 `empty_audio`。

### A02 · P1：驗證與 runtime 支援範圍不一致

**重現：** 在進階音訊設定輸入 `input_sample_rate=22050`，`validate_settings()` 接受；但語音模式建構 VAD 時，`VADIterator` 立即拒絕：

```text
UI validation accepted input_sample_rate=22050
ValueError: VADIterator supports only 8000 or 16000 Hz
```

通用驗證目前偏重型別、有限數值、少數正值／範圍與 Gemini 設定。`whisper.model_size=nonsense`、`whisper.device=nonsense`、`tts.rate=fast`、負的停頓毫秒數等，也能通過這層驗證。後果依欄位而異：可能在 runtime 失敗、異常運作或被默默改用 fallback；例如 Edge rate 將無法解析的文字改成 `+0%`。

**依據：** `core/session_settings.py:38–95`；`core/vad.py:40`；`core/assistant.py:185`；`tts/rate_limits.py:24`。

**建議／驗收：** 共用欄位 schema，定義 enum、nullable、單位、界限與跨欄位條件。收音取樣率僅提供當前 pipeline 支援的選項；在送出前於對應欄位顯示錯誤。保留 Gemini 已有的細部驗證，補齊其他服務。

### A03 · P2：隱藏語音設定後，外層仍保留大片空白

**重現／量測：** public defaults 的 Local STT＋Edge TTS，兩個 Gemini details 都是 `winfo_ismapped=false`，但其外層 slot 高度分別仍是 **632 px、642 px**。合計約 **1,274 px** 空白。

第二步總內容高 **3,834 px**；在較大 fixture 的中央 viewport 高 576 px，約為 6.7 個 viewport；最小 fixture 高 376 px，約為 10.2 個 viewport。Google key 區標題相對內容頂端約在 **y=3,234 px**，字級區約在 y=3,623 px。

**原因：** 只 `pack_forget()` 內層 details；已被內容撐大的外層 slot 沒有一起移除或重設高度。

**依據：** `ui/audio_settings.py:44–79`、`:147–155`。

**建議／驗收：** 顯示／隱藏整個服務區塊，或同步收合外層 slot。Local＋Edge 不應留下 Gemini 高度；切換三種 STT／TTS 後逐一檢查內容高度。Key 應放在需要它的服務選擇附近，先完成金鑰再執行測試。

### A04 · P2：錯誤訊息會擠掉導覽按鈕

**重現／量測：** logical `640×480`、125% DPI，footer 顯示既有數字解析錯誤：

```text
請檢查欄位：invalid literal for int() with base 10: 'abc'
```

狀態 label 佔 367 px；「下一步」實際只剩 **80 px**，requested width 為 156 px；「上一步」則 **不再 mapped**。錯誤愈長，導覽區愈難使用。

**依據：** `ui/startup.py:100–108`，status 先向左 pack，沒有可換行、限寬且與按鈕獨立的區域。

**建議／驗收：** 按鈕固定在獨立 grid column；錯誤訊息放上方或表單內，可換行並限制高度。在最小尺寸注入解析錯誤及較長的服務錯誤，導覽按鈕仍須完整可見。

### A05 · P2：切頁與分類沿用舊捲動位置

**重現／量測：** 第二步 Gemini 設定捲到底，再由導覽切至進階設定，fixture 的 yview 起點仍在約 **0.728**，沒有回到 0。進階 TTS 捲到底後，直接呼叫分類切換至 Whisper，控制確已更換為 26 個 Whisper editors，但 yview 起點仍約 **0.871**。

前者可透過左側導覽重現；後者為控制 callback 層的測試，並非宣稱人在頁底一定能直接點到頁頂的分類選單。

**依據：** `ui/startup.py:169–179`、`:198–201`、`:290–325`，重建內容後未明確設定新頁的 scroll origin。

**建議／驗收：** 新頁／新分類完成 layout 後回到頂端；若要保存各頁位置，則以頁面／分類分別儲存，不能共用前一頁的比例。驗證要等待 Tk layout 收斂。

### A06 · P2：nullable seed 填過數字後無法還原「隨機」

**重現：** 進階 TTS 的 BlueMagpie seed 原為 `null`，欄位標示空白表示隨機。填入 `42`，離開後再回來，清空；`collect()` 回報 `invalid literal for int() ... ''`，也不能用 `null` 還原。

**原因：** 以目前值的 Python type 推斷欄位型別。原值變成 int 後，下一次重建 editor 便使用 `int(raw)`，失去 nullable 資訊。此時若要將已保存的 seed 恢復成 null，現有 UI 沒有正常途徑。

**依據：** `ui/startup.py:320–325`；`core/session_settings.py:38–56`；`config.default.json:120`。

**建議／驗收：** 型別與 nullable 來自穩定 schema。驗證 `null → 42 → 換頁 → 空白 → null`，並包括保存／重開後的還原。

### A07 · P2：關鍵初次設定仍仰賴外部操作或難找的進階欄位

| 使用者要完成的事 | 目前入口 | 判定與建議 |
| --- | --- | --- |
| 選 AI、模型、推理強度 | 第一步 | 有入口；需補服務名稱、用途與就緒狀態 |
| 選麥克風、喇叭／耳機 | 無；sounddevice 使用預設裝置 | 應有裝置選單、音量／收音指示與測試；不是增加 JSON 欄位就足夠，runtime 也須對接 |
| Local Whisper 模型、CPU／GPU、辨識語言 | 進階 → 語音辨識 | 可改但不易發現；將常用選項移到 Local 專屬區，給相容選項 |
| Groq key、模型、環境變數來源 | 進階 → 語音辨識 → Groq | 可填；第二步選 Groq 沒有相應 key／模型區塊，也沒有 Google 類似的來源提示 |
| Gemini key、模型、音色、風格 | 第二步 | 基本完整；key 太晚出現，詞彙清單仍要求 JSON |
| Edge 音色、語速、音量 | 第二步 | 有入口；語速／音量沒有格式範例或適當滑桿 |
| BlueMagpie worker、參考聲音、啟用 | 進階 → 語音合成 | 可改路徑；缺設定引導、檔案選擇與依賴檢查，另有 A01 |
| 改喚醒詞內容 | 只有 keywords 檔案路徑 | 不能在 UI 編輯內容或測試喚醒；須手動改檔 |
| 新增家人聲紋／名稱、錄製樣本 | 只有目錄、門檻等設定 | 須建立資料夾並放 WAV；5 秒 STT 測試不會建立聲紋 profile |
| 初次 CLI 安裝、登入 | 查詢失敗文字 | 沒有可跟隨的安裝／登入／重試流程；至少顯示正確步驟或文件入口及檢測結果 |
| 錄音保存、主動詢問、接續聆聽、定時關懷 | 進階中的不同分類 | 都有設定值；常用開關可集中成「互動與保存」 |
| 白板每日額度、對話字級 | 第三步／第二步 | 有入口；應補 0 分鐘的意義、重置時區與字級預覽 |
| 排程內容 | 主畫面排程管理 | 已有專用介面，不必為追求初始 UI 全包而搬進 wizard |
| 角色指令／私人記憶內容 | 外部 Markdown 檔 | 不在本次設定表單範圍；若納入 onboarding，應提供獨立編輯／開啟入口 |

**依據：** `core/audio_capture.py:65`、`core/audio_player.py:216`（均無指定 device）；`ui/audio_preview.py` 的錄音同樣使用預設裝置；`ui/audio_settings.py:43–82`；`ui/startup.py:290`；`core/wake_word.py:36`；`voice_profiles/README.md:3`；`llm/model_catalog.py:97–112`。

不必把 CLI 認證做成內嵌登入，也不必讓一般使用者編輯所有 runtime 參數；但至少要能在 UI 得知缺什麼、如何完成，以及如何驗證完成。

### A08 · P2：進階設定是資料結構導向，欄位缺乏操作語意

19 個分類依設定檔插入順序排列；LLM 同時展開多個 backend，TTS／Whisper 同時展開多服務。實際控制數分別為 **39、37、26**，即使只用其中一種服務仍須在長表單找設定。

非 bool 多為單行 entry，包含 enum、路徑、較長提示詞與 JSON list；沒有欄位搜尋、檔案選擇器、值域／範例、單位旁註或一般性的還原預設。數字解析錯誤沒有指出欄位，`navigate()` 又要求先通過全頁收集，所以錯誤會阻擋離開，使用者必須自行找出來源。

**依據：** `ui/startup.py:263–272`、`:181–194`、`:297–325`；`core/session_settings.py:38`。

**建議／驗收：** 依使用者任務分類，先顯示目前選用服務；提供搜尋與各區還原。Enum 用選單，nullable 有「自動／指定」控制，路徑可瀏覽，多行文字可展開，清單可逐項增刪。錯誤帶欄位名稱並捲到、聚焦該欄位。未選用服務的設定可收合保留。

### A09 · P2：確認頁的「已完成檢查」範圍不明，啟動失敗也難以自助排除

只要模型查詢讓 `ready=true`，確認頁便顯示「已完成檢查」，即使沒有測過 STT／TTS，也沒有確認麥克風、wake-word assets 或聲紋。此標章實際表示的是模型查詢狀態。

`StartupWindow._prepare()` 將各種例外統一變成「啟動失敗，請檢查設定與 backend 登入狀態；詳細原因見 logs」。即使原因是 Google key／模型、設定寫入或本機語音資源，也只得到這句文字，且沒有開啟診斷、返回對應頁或區分錯誤類型的按鈕。

**依據：** `ui/startup.py:274–288`；`ui/startup_window.py:58–74`；`ui/audio_preview.py` 的 `validate_google_selection()` 僅驗選用 Google 模型 metadata，不是完整語音端到端測試。

**建議／驗收：** 分別列出「模型已查詢」「金鑰已設定／連線已驗證」「裝置未測試」「語音試聽成功／未執行」。只對已測項目標示成功。啟動錯誤顯示經遮罩的具體原因及修正入口，不能只要求使用者自行翻 logs。

### A10 · P2：更新、查詢與設定保存綁得太緊

每次開啟新 wizard 都從 `ready=false` 開始；第一步「下一步」會先執行查詢。Public default 又開啟 `update_cli`，查詢先跑 CLI update／upgrade；失敗即無法取得模型，沒有 UI 上的獨立取消按鈕，且查詢中導覽會被阻擋。模型查詢有 180 秒上限與取消機制，但使用者只能等待或關閉整個視窗。

一般設定沒有「儲存設定，稍後啟動」。設定主要在啟動準備時寫入，準備失敗會 rollback；Google key 則立即保存且有註記。首次環境尚未就緒時，使用者不容易保存已完成的其他設定。

**依據：** `config.default.json:274`；`ui/startup.py:46–57`、`:358–400`、`:443–483`；`llm/model_catalog.py:64–68`；`ui/startup_window.py:54–74`。

**建議／驗收：** 把「檢查可用性／查詢模型」與「更新 CLI」區分，顯示目前階段並可取消查詢；提供保存草稿或已驗證設定的途徑。若保留每次必查模型的產品政策，應清楚說明，並讓更新失敗時仍能選擇只查詢。

### A11 · P3：文案、條件顯示與摘要的一致性不足

- 第一頁仍直接顯示 `codex_cli` 等 identifiers，`Backend / Model / Effort` 缺乏簡短解釋；語音服務也只顯示 `local / groq / gemini`，不利理解本機、雲端與金鑰需求。
- 固定文字輸入／輸出後，整個語音服務、金鑰與測試區仍會出現。可以保留顯示選項，但應標示本次不使用並預設收合。
- `interaction` 分類的三個值都由專用控制接管，進階選單仍列出這個未翻譯、沒有可編輯欄位的分類。
- 確認頁對 Local／Groq STT、Edge／BlueMagpie TTS 多只列 backend 名稱；看不到重要模型／音色／啟用狀態，無法從這一頁發現 A01。
- 字級專用選單只有 19／21／24，`SessionConfig` 接受 16–32；進階又跳過字級。若產品只提供三檔應明確定義，否則補完整控制與即時預覽。
- 額度 0–1440 的限制只在錯誤時出現；0 分鐘、每日重置時區等意義沒有在設定處完整說明。

**依據：** `ui/startup.py:19`、`:219–233`、`:241–281`、`:304–307`；`core/session_settings.py:25–28`；`ui/field_labels.json`。

## 建議的設定順序與驗收

保留五步框架，將內容調整為：

1. **AI 服務**：可辨識的服務名稱 → 安裝／登入狀態與處理入口 → 查詢模型 → 模型與推理強度。CLI 更新另列成明確動作。
2. **聲音與裝置**：先選輸入／輸出方式，再顯示需要的裝置、服務、金鑰、常用模型／音色及測試。以服務為單位收合，避免先測試才在頁底找到 key。
3. **互動與使用限制**：白板額度、字級預覽，以及常用的接續聆聽、主動詢問、保存選項；喚醒詞／聲紋提供管理入口。
4. **進階選項（可略過）**：預設只顯示選用的服務，提供搜尋、檔案選擇、型別合適的控制與還原。
5. **確認與啟動**：完整的有效設定摘要，以及分項的檢查／測試狀態；錯誤能返回正確欄位，提供保存途徑。

最低應完成以下情境驗收：

- 新使用者不開 JSON，完成「純文字」「Local＋Edge」「Groq＋Edge」「Gemini 語音」的必要設定；BlueMagpie 缺環境時能得到可操作的指引。
- 麥克風／輸出裝置能選擇且 preview 與正式 session 一致。
- 每個服務切換後無不明空白，切頁從合理位置開始；最小視窗在成功／錯誤狀態下都保有完整導覽按鈕。
- Seed 等 nullable 值能反覆設定與還原；不支援的取樣率、enum、格式在對應欄位被攔截。
- 查詢、試聽與準備失敗能看到具體修正方向；確認頁不將未測項目顯示為通過。
- 在可存取的 Windows desktop 補上 100／125／150／175% DPI 的 screenshot review、Tab／Shift+Tab／Enter／Escape 操作及真人首次設定測試。本次尚未驗證這些項目。

## 測試紀錄

1. 相關回歸：**86 passed、2 skipped，6.43 秒**。

```powershell
cd ai_voice_assistant
.\venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/test_config.py tests/test_session_integration.py tests/test_session_audit.py tests/test_audio_startup.py tests/test_google_credentials.py
```

2. 另外以 `AI_GOVERNESS_NATIVE_TESTS=1`、暫存 config，執行 **3 個 native Tk 測試，均 passed**：語音設定換頁／保存、準備期間凍結與重試、Google key 儲存／刪除。前一輪 skipped 的兩個 opt-in 測試已於此補跑；另外一個是 startup freeze 測試。這些是 native 控制測試，不等於完成畫面目視或真實音訊測試。

```powershell
$env:AI_GOVERNESS_NATIVE_TESTS='1'
$env:AI_GOVERNESS_CONFIG=Join-Path $env:TEMP 'startup-audit-unused-config.json'
.\venv\Scripts\python.exe -B -m pytest -q -s -p no:cacheprovider tests/test_audio_startup.py::test_native_audio_settings_round_trip_stop_and_catalog_preserve_voice tests/test_native_session.py::test_startup_draft_is_frozen_during_preparation tests/test_google_credentials.py::test_startup_key_editor_saves_deletes_and_survives_page_changes
```

3. 額外隔離 probes 重現 A01–A06、確認標章狀態，並盤點 206 個 leaves；probe 的 Tk callback exception list 為空。22050 Hz 的 runtime 拒絕是刻意的問題重現，不列為既有回歸測試失敗。

既有測試通過與上述問題可以同時成立：現有測試主要保護設定保存、生命週期及 callback 行為，尚未覆蓋這些使用者流程、控制項尺寸與欄位語意。
