# 開源 rigging 工具選型

查核日期：2026-11-11。以下為原始專案文件的能力核對，尚未安裝或以愛管家素材執行測試；「優先試驗」不等同於品質已獲驗證。

## 建議

第一順位試驗 **PSD2Live**，以標準 Cubism 模型為交付格式。製作工具選開源，不必連 runtime 一起換掉；保留 Cubism Editor 精修的路徑。

這也修正了前次僅以影片流程為主的評估：目前已有宣稱可直接匯出標準模型的開源工具，值得實測，不必預設所有 rigging 都從官方編輯器手工開始。但七種手勢的素材、遮擋與中間動作仍需個別製作。

## 候選比較

| 工具 | 可重用能力 | 標準 Live2D 交付 | 本案定位 |
|---|---|---|---|
| PSD2Live | PSD 自動網格、變形器、參數、物理、動作、骨架／IK、編輯與 MCP | 官方專案宣稱可匯出 moc3 / cmo3，須在目標 runtime 實測 | 首選製作工具試驗 |
| Anime2.5DRig | PSD 自動 rig、頭眼嘴微動、頭髮物理，瀏覽器預覽方便 | 使用自有 WebGL 系統；不作 moc3 交付路徑 | 快速外觀對照 |
| StandRig | MCP 操作 mesh、deformer、keyform，獨立服務與可嵌入 runtime | 官方明確不支援 cmo3 / moc3 建立、轉換或播放 | 接受自有格式時的研究備案 |
| See-through | 單圖語意拆層與遮擋區域補全 | 不提供完整 rigging | 前處理助手 |

上游依據：[PSD2Live](https://github.com/tsunehimatoi/psd2live/blob/master/docs/en/README.md)、[Anime2.5DRig](https://github.com/852wa/Anime2.5DRig)、[StandRig](https://github.com/sayaka-aiart/StandRig)、[See-through](https://github.com/shitagaki-lab/see-through)。

## PSD2Live 的採用邊界

實測更新：3.6.7 已成功將 tml 樣本與愛管家 See-through PSD 匯出為 moc3；兩者均通過官方 Cubism Core 載入，愛管家嘴型參數可動。尚未完成 Cubism Editor 回編及七手勢驗證，因此目前只確認基礎相容性，仍未作全案採用結論。詳見 [G1 紀錄](reports/g1/STATUS.md)。

它最接近本案需求，因為同時涵蓋自動生成、後續編輯和標準格式匯出。上游說明提供 Windows 便攜版；製作階段可以放在獨立工具目錄。保留 `.psd2live` 源工程，再輸出可回到 Cubism 的 `.cmo3`，降低只剩不可編輯成品的風險。

骨架、IK 與模擬可能須烘焙成 Cubism 支援的資料；不能假設工具內看到的每個效果都可無損交付。每次匯出保留 loss report，對照官方 runtime 檢查嘴、遮擋、物理和動作。上游也要求使用目標編輯器與 runtime 驗證輸出。

授權紀錄：編輯器為 GPL-3.0，專案另列 p2lrt runtime 為 MIT，實作時按實際使用的子目錄與固定版本確認。本案先將 PSD2Live 作獨立製作工具，viewer 使用 Cubism SDK，不將不同部分的授權混為一談。[README 授權資訊](https://github.com/tsunehimatoi/psd2live/blob/master/docs/en/README.md)、[LICENSE](https://github.com/tsunehimatoi/psd2live/blob/master/LICENSE)

## 2–4 人日的 G1 試驗

1. 固定 release／commit，記錄來源、作業系統與工具版本。先以可合法使用的分層樣本驗證完整匯出及重新開啟工程。
2. 準備愛管家的最小可動 PSD：頭、眼、嘴、上身，以及托腮／舉食指所需手臂差分。未完成這份素材前，只能驗證工具相容性，不能判定角色適用性。
3. 自動生成基礎 rig，校正錯誤部件分類與關節；保存未修整與修整後版本，記錄人工耗時。
4. 在同一模型內建立托腮、舉食指和過渡姿態。以正常速度、0.25 倍速和參數極值檢查手穿臉、袖口裂縫與雙手重影。
5. 匯出 moc3 與 cmo3；在官方 runtime 播放，在 Cubism Editor 開啟並檢查可編輯性。記錄 exporter、目標格式與 SDK 版本。
6. 以相同音檔測試嘴型，確認模型嘴參數可獨立控制；禁止用已烘焙整段嘴巴動作假裝即時同步。

**採用條件：**模型可讀、可回編、重要輸出未遺失，高風險姿勢可修到合格，且工作量確實低於手工重建的估算。樣本成功、API 有回應或匯出沒有報錯，均不足以判定採用。

**退出條件：**G1 內仍無法穩定匯出／回編、重要遮擋或手勢遺失，或修復生成 rig 比重建更費工。保留 PSD、標記與可用部件，轉 Cubism Editor 精修；不因工具限制縮減七種姿勢。

## 其他候選的限制

Anime2.5DRig 適合快速確認拆件與微動效果；要完整重現七姿勢，仍可能需要較多自訂 rig 與 runtime 工作。不要把其頭部自動微動展示，當成複雜手勢已經解決。

StandRig 適合讓 agent 操作建模資料。其 Cubism Bridge 連線不代表模型可轉成 moc3；本體文件清楚說明目前的格式限制。因此除非使用者另行接受改用自有格式，本案不以它取代標準 Live2D 交付。

影片列出的 [live2d-automation](https://github.com/J621111/live2d-automation#export-notes) 目前記載 mock 中介輸出，不列為正式交付工具。See-through 只負責拆件，不能替代上述任一完整 rigging 工具。

本次選型不以 star 數作為品質證據；最終以愛管家的七姿勢、20 轉場及官方 runtime 表現決定。
