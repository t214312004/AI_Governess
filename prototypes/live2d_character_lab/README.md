# 愛管家單一 Live2D 模型實驗室

**v11 已完成原生工程與展示頁。** v5 閉眼、v6 視線、v7 嘴型、v8.1 眉毛修正與 v9 頭頸側傾已獲使用者確認。v11 涵蓋髮緣與日常聆聽，完整手勢與整體質感仍待驗收。更新日期為 2026-11-18。

目標是在此獨立資料夾，以同一個標準 Live2D 模型支援現有五種狀態、七種主要姿勢及播放音訊嘴型同步。先完成獨立展示與使用者質感驗收，再另行評估整合。

- [完整規劃書](PLAN.md)：範圍、素材、單模型設計、架構、時程、風險與決策門檻。
- [開源 rigging 工具評估](OPEN_SOURCE_RIGGING.md)：PSD2Live 優先試驗，其他工具的用途與限制。
- [驗收清單](ACCEPTANCE.md)：測試案例、量測方法、主觀評分與簽核紀錄。
- [現有素材總覽](references/current_states.jpg)：30 張原始影格的縮圖，僅供比對。
- [素材清冊](references/inventory.json)：原始路徑、尺寸、SHA-256 與盤點版本。

## 本機啟動

目前這台電腦的工具、模型與 npm dependencies 已備妥。雙擊 `start-lab.bat`，再開啟 <http://127.0.0.1:5187/>。或在此資料夾執行 `npm.cmd run dev`。伺服器只綁定 localhost。

**目前精修入口：[共用臉部 rig](http://127.0.0.1:5187/shared-face.html)。** 提供左右眼、左右眉高低／角度、嘴形與開口共 8 個控制，可播放連續表情與眨眼，並同時播放測試語音。雙眼皮摺線隨上眼皮下移、淡出；閉眼陰影取自原圖。此頁使用一個臉底、同一份 moc3，沒有切換整頭或 `ParamReferenceFrame`。結構與限制見 [共用臉部製作紀錄](design/SHARED_FACE.md)。

**2026-11-18 美感複查**　[髮緣與日常聆聽 v11](http://127.0.0.1:5187/shared-face.html?polish=1) 沿用 v10 小角度控制。按「播放日常聆聽」觀看視線先移動、頭稍後跟上，以及一次輕點頭。可同時播放語音。深淺底 [髮緣對照](reports/g2/polish-comparison.png) 與 [原速聆聽錄影](reports/g2/listening-v11.webm) 供質感驗收。一般尺寸下髮尾黃綠殘色已減少，右側細髮的線條仍偏硬。

v11 的髮緣修正已存進 [可編輯工程](authoring/polish-v11/shared-face-rig-v11-polish.psd2live)。展示直接載入 `models/polish-face/` 的原生匯出。髮緣素材使用原貼圖在來源畫布的 727 × 901 範圍，讓五官與頭髮維持對位。聆聽動作由 `viewer/listening-pose.ts` 控制，可與音訊嘴型一起播放。

**[G2a 托腮到舉食指](http://127.0.0.1:5187/shared-face.html?gesture=1) 待質感驗收。** 單一 Live2D 模型結合 v11 頭臉、獨立肘腕和三個手型。中間手型與袖口取自 ImageGen 的姿勢參考，端點以托腮及說話原圖校對。暫停或拖曳進度可檢查手肘外框和手掌比例。「與原圖校對」可套用對應端點並疊加 50% 原圖。[連拍](reports/g2/g2a/gesture-silhouettes.png) · [端點疊圖](reports/g2/g2a/endpoint-overlays.png) · [可編輯工程](authoring/gesture-g2a/governess-g2a.psd2live)

G2a 用一個連續網格支撐肩峰到手肘的袖側外框。下放與抬臂時以肘腕旋轉帶動袖口，維持掌指大小，前臂沿長軸少量調整投影。抬臂期間保持收指，腕線接近定位後才伸出食指。

舉食指前，袖片與露出的前臂沿肘腕路徑逐步變形。袖片外框依說話原圖校對，並在手型切換前到位。左右兩側都逐幀檢查從收指到伸指時袖口、前臂的頂點與透明度。[舉食指前後的袖口對照](reports/g2/g2a/point-arm-continuity.png)

下放與抬起共用手掌與袖片，並在 45° 內共用肘腕路徑。整段使用依肩寬換算的肘腕長度。前臂採 ANSUR II 女性樣本的第 75 百分位（251 mm），以配合原圖托腮的接觸點。托腮時移動肘點及支撐手，使彎曲的指節接觸下巴。抬臂越過 45° 後腕點沿固定肘點走等半徑圓弧。左右兩側都逐幀量測上臂投影、肘腕距離和掌長。[比例與托腮對照](reports/g2/g2a/forearm-proportion-and-chin-contact.png) · [ANSUR II 第 8、67 項](https://dacowits.defense.gov/LinkClick.aspx?fileticket=EbsKcm6A10U%3D&portalid=48)

手部校正以原圖的肩峰、解剖腕點與掌指關節作為標記。掌寬取同一掌部區間三條橫切線的平均。兩種手型共用以人體資料換算的尺寸下限，縱向調整作用在掌部，末端食指仍採原圖的長度。人體資料中的平放手掌與插畫手勢的量測方向有差異，因此換算值作為比對參考。 [ANSUR II 原始報告](https://dacowits.defense.gov/LinkClick.aspx?fileticket=EbsKcm6A10U%3D&portalid=48) · [女性消防員手部量測](https://pmc.ncbi.nlm.nih.gov/articles/PMC4681492/#T2) · [原圖與校正尺寸](authoring/gesture-g2a/palm-fit.json)

前臂接近 45° 時，以 ImageGen 姿勢圖上可見的肘側曲線校對袖片。下放與抬臂各有一個局部修形關鍵幀。[參考圖與修整前後](reports/g2/g2a/elbow-45-comparison.png)

G2a 素材由 `node tools/prepare-gesture-g2a.mjs` 產生。用 WSL2 執行 `python3 -B tools/rig-gesture-g2a.py`，以 PSD2Live 3.6.7 產生 `.cache` 內的工程與匯出候選。瀏覽器驗證使用 `npm.cmd run test:gesture`，涵蓋原有臉部網格、袖側外框、端點疊圖及語音與手勢同時播放。[測試結果](reports/g2/g2a/results.json) · [中間姿勢參考](authoring/gesture-g2a/inbetween-pose-reference.png) · [ImageGen 提示詞](authoring/gesture-g2a/inbetween-prompt.txt)

**[G2b 手靠胸前](http://127.0.0.1:5187/shared-face.html?gesture=1&pose=chest&revision=g2b-seams) 待質感驗收。** 預覽用「說話手勢」在舉食指與靠胸之間切換，兩種動作共用同一份模型。靠胸手型擷取自 `speaking_3`，保留拇指輪廓與指縫，依同一肩寬基準校正掌部。抬手時保持肘腕長度，腕點到位後切換手型，再局部展開手指。左右側的托肘掌面留在袖子後方，包住手肘的指尖在袖子前方，兩個部件一起跟隨手肘。為維持肘腕比例，靠胸腕點比原圖約高 28 px、向胸口中央移動 16 px（900 px 預覽）。[原圖與左右側對照](reports/g2/g2b/hand-on-chest-comparison.png) · [過渡修整前後對照](reports/g2/g2b/seams-and-occlusion.png) · [G2b 可編輯工程](authoring/gesture-g2a/governess-g2b.psd2live) · [G2a 備份](authoring/checkpoints/gesture-g2a/governess-g2a.psd2live)

**轉頭版本：[小角度轉頭／俯仰 v10](http://127.0.0.1:5187/shared-face.html?turn=1)。** 沿用同一模型，轉頭參數限制 ±6、俯仰限制 ±4；可與側傾、眉眼、視線及音訊嘴型組合。「慢速轉頭檢查」「慢速俯仰檢查」可暫停。頸根／肩部固定，眉尾會隨轉頭保留髮際接合。見 [製作與檢查](design/HEAD_TURN.md)、[無聲錄影](reports/g2/head-turn-v10.webm)。

**已通過：[頭頸側傾 v9](http://127.0.0.1:5187/shared-face.html?head=1)。** 同一模型新增 ±6° 頭頸側傾；頸部平滑過渡，肩部固定，既有眉眼／嘴型及音訊可同時使用。「頭頸慢速檢查」可暫停。這一版不含左右轉面、俯仰或完整手勢，髮緣少量背景殘色仍待清理。見 [製作與測試](design/HEAD_NECK.md)、[無聲錄影](reports/g2/head-neck-v9.webm)。

**已通過：[眉尾修正 v8.1](http://127.0.0.1:5187/shared-face.html?expression=1)。** 清掉畫面左側眉尾的髮絲碎片及底圖殘影，新增眉尾局部接合形變，仍為同一臉底、20 個 ArtMesh、15 個控制。「雙眉慢速檢查」可暫停檢查左右眉毛；125 組高度／角度／眉形測試中，另一側眉毛及其餘五官幾何與 v8 完全一致。兩側保留原圖本身的遮擋及弧度差異，疑問預設會刻意抬起單眉。見 [本輪製作紀錄](design/BROW_HAIRLINE.md)、[無聲錄影](reports/g2/brow-v8-1.webm)。

v8 的眼型、眉形控制與說話校準仍保留，完整原圖還原尚未完成；背景與數值範圍見 [眉眼製作紀錄](design/EXPRESSION.md)。

[已通過嘴型的 v7](http://127.0.0.1:5187/shared-face.html?speech=1)：下唇獨立、隨開口移動並保留厚度；有嘴寬控制、可暫停的「慢速嘴型檢查」與「說話表情校對」。63 組嘴型及 21 組眼部回歸通過，已保存 68 份驗收備份。見 [製作紀錄](design/SPEECH.md)、[無聲錄影](reports/g2/speech-v7.webm)。

[已通過視線的 v6](http://127.0.0.1:5187/shared-face.html?gaze=1) 有 10 個控制，可播放連續表情、視線與語音。v5、v6 的模型與驗收備份均保留；通過範圍不擴大到全表情或手勢。見 [視線製作與驗證紀錄](design/GAZE.md)。

v5 修正了半閉眼時眼皮與睫毛分離，以及改嘴角時漏出張嘴細線的問題。預覽提供可暫停的慢速眨眼，以及三張原圖的疊圖／差異校對：展開「與原圖校對」，選參考影格後按「套用目前對應表情」即可比較。[無聲慢速錄影](reports/g2/shared-slow-blink-v5.webm) 可檢查眼皮過渡；目前仍未通過完整原圖還原。

展示包含單一 `.moc3`、五狀態頭身／表情控制、眨眼、呼吸，以及跟隨實際播放音訊的嘴型。可選擇本機音檔，或播放預設的新生成測試語音；暫停、靜音、停止時閉嘴。五個狀態的**七種手勢尚未製作**，按鈕旁會顯示待補件項目。

另有 <http://127.0.0.1:5187/arms.html> 手臂工程試驗，能拖曳檢查「手靠下巴 → 放下 → 抬手」。它只驗證分段骨架，尚未與可動眼嘴合併，也尚未補上托腮／食指差分。換電腦時同時移交 `models/arm-spike-clean/`。

- [G1 實測紀錄](reports/g1/STATUS.md)
- [G2 精修紀錄與方向修正](reports/g2/STATUS.md)
- [五官疊圖校對](http://127.0.0.1:5187/fidelity.html)／[手勢與拇指校對](http://127.0.0.1:5187/hands.html)：兩頁共用 `face-fidelity/original.moc3`，目前僅驗證素材端點；正式方向是共用頭部底圖配合乾淨拆件與連續形變。
- [imagegen 草稿與補件規則](design/IMAGEGEN.md)
- [第三方來源與版本](THIRD_PARTY.md)

## 驗證與重建

### WSL2 試匯出

2026-11-18 在 Ubuntu 24.04.5 LTS（WSL2）用 PSD2Live 3.6.7 Linux x64 開啟 v10 工程副本。v10 和 v11 工程均已重新開啟並匯出，moc3 與三張 atlas 的 SHA-256 全數相符。[v10 驗證](reports/g2/v10-linux-roundtrip.json) · [v11 驗證](reports/g2/v11-linux-roundtrip.json)

從此資料夾執行以下 PowerShell 指令可重跑。套件快取位於 `.cache/psd2live-linux-v3.6.7/`，清除快取後需從 [v3.6.7 官方 Releases](https://github.com/tsunehimatoi/psd2live/releases/tag/v3.6.7) 重新下載 `PSD2Live-3.6.7-linux-x64.tar.gz`。

```powershell
wsl.exe -d Ubuntu-24.04 --user nobody --exec python3 -B tools/verify-turn-wsl.py --polish
```

### 瀏覽器與模型測試

```powershell
npm.cmd ci
npm.cmd run build
npm.cmd test
# 另一個終端已啟動 npm.cmd run dev 時：
npm.cmd run test:browser
npm.cmd run test:fidelity
npm.cmd run test:shared
npm.cmd run test:blink
npm.cmd run test:gaze
npm.cmd run test:speech
npm.cmd run test:expression
npm.cmd run test:brow
npm.cmd run test:head
npm.cmd run test:turn
npm.cmd run test:turn-blink
npm.cmd run test:gesture
node tools/head-turn-test.mjs --polish
node tools/head-turn-blink-test.mjs --polish
node tools/review-polish.mjs
```

瀏覽器測試使用本機 Edge 的獨立 headless instance，不操作日常瀏覽器。結果在 `reports/g1/browser-results.json`；截圖留在同資料夾，未加入 Git。

在新的 checkout 執行 `powershell.exe -ExecutionPolicy Bypass -File tools/setup-tools.ps1` 安裝固定版本工具。請移交本機 `models/` 的匯出與 `authoring/shared-face/head-original.png`，再執行 `npm.cmd run dev` 或 `npm.cmd run build`。眉毛測試另外需要 `models/expression-face-v8/` 的基準版本，手部原圖比對需要 `authoring/source-parts/` 的圖片。這些資產由本機工程產生，Git 僅保存原始碼、設計資料及文字報告。可從保存的分層 PSD 重建主角，使用 `powershell.exe -ExecutionPolicy Bypass -File tools/export-model.ps1 -InputPsd <PSD路徑> -Model governess`。viewer 預期主角使用 `seethrough_output.model3.json`，相容性案例使用 `tml.model3.json`。

可用 `tools/make-demo-audio.ps1` 重建本機語音；執行後再啟動 dev，將音檔複製到展示資產。所有 authoring 工作與 SDK 保持在此 lab，不需要更動主程式的 Python 環境。

本資料夾可先獨立開發。展示程式不得 import 主程式、讀取 config.local.json、使用正式語音樣本或改寫原始素材。外部製作工具只是 authoring dependencies，最終展示以驗證過的 Cubism 模型與 SDK 為基準。
