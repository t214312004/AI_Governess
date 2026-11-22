# 共用臉部 rig v5

2026-11-13 補記：v5 閉眼與 v6 視線已由使用者接受，模型與來源已備份，見 [GAZE.md](GAZE.md)。最新 v7 嘴型精修見 [SPEECH.md](SPEECH.md)；以下保留 v5 與早期版本的製作紀錄。

更新：2026-11-12。這是可組合控制的候選，**不是完整角色或通過質感驗收的成品**。

## v5：眼皮與睫毛同步

使用者指出半閉眼時皮膚先蓋下來，與黑色睫毛分離。量測確認舊版以各個 mesh 自己的 bounds 縮放，實際閉合中心不同：右側睫毛與遮罩相差約 7.20 個來源像素，左側約 14.38。兩者雖讀同一個開合參數，路徑仍不相同。

現在同側睫毛與眼睛遮罩共用 `SharedLidR`／`SharedLidL` Warp；虹膜圖像留在外面，只由遮罩決定可見範圍。Core 量測的平均閉合中心差已縮至約 0.15／0.18 個來源像素。這個量測反映幾何取樣，不等同完整輪廓的逐像素誤差。

接近全閉時，閉眼睫毛先以對齊的細線接入，再漸變至原圖厚度，減少整片閉眼圖淡入造成的灰色重影。閉眼皮膚陰影另外清掉誤帶的黑色睫毛像素，避免形變後露出另一條邊線。

同時修正嘴角與開口透明度的控制衝突：原本 `ParamMouthForm=0.35`、開口為 0 時，張嘴 mesh 的透明度仍會變成 0.35。現在完整填寫嘴形 × 開口的透明度 keyforms，閉嘴時改嘴角不再漏出張嘴細線。

`npm.cmd run test:blink` 檢查 10 個開合值；在 25%、50%、75% 開眼時，左右眼各 3 個取樣欄位沒有量到睫毛與遮罩之間的膚色帶。結果及範圍見 `reports/g2/blink-continuity-results.json`。`test:shared` 另檢查 5 個嘴形值在完全閉口／開口時的 mesh 透明度。這些都是針對缺陷的回歸檢查，並非全模型質感驗收。

最新 [慢速眨眼錄影](../reports/g2/shared-slow-blink-v5.webm) 為無聲、固定頭部的檢查。頭部角度、獨立視線與完整手勢仍待製作。

## v4 精修與原圖對照

眼皮抽取現在以原畫內的定位點保留連通部件，排除原本誤選的髮際碎片。左右睫毛各保留一個主要連通區域，左右閉眼陰影各保留兩個主要區域（上眼皮明暗與較低的粉色陰影）。來源分析見 `reports/g2/shared-source-integrity.json`。

預覽新增「慢速眨眼檢查」，一個往返約 8 秒，可在中途暫停；「與原圖校對」可選待機張眼、待機閉眼、說話張嘴三張原圖，檢視原圖、50% 疊加與差異 ×4。所有比較保持相同來源座標，沒有額外拉伸或移動參考圖。

原圖閉眼時眉毛也改變位置；既有自動 rig 向下行程不足，因此補了局部眉毛 keyform，再以既有 8 個控制校準來源端點。候選參數存於 `shared-reference-poses.json`，不需切換模型或整頭圖。校準過程固定 moc3，紀錄在 `reports/g2/reference-fit-candidate.json`；尚未完成全表情校準。

| 閉眼原圖的比較區域 | 只閉眼、眉毛停在待機 | 校準後 RGB 平均差／255 |
|---|---|---|
| 右眉矩形區域 | 31.77 | 17.73 |
| 左眉矩形區域 | 22.99 | 14.04 |
| 完整臉部視窗 | 15.44 | 14.69 |

矩形區域包含周圍皮膚與部分髮際，數值不代表眉毛部件單獨誤差。說話原圖的左右眼區域仍約 26.93／25.42，眼型、視線與頭部形狀差異尚未解決，不能用局部改善宣告完整還原合格。

[慢速閉眼往返錄影](../reports/g2/shared-slow-blink-v4.webm) 是無聲、固定頭部的檢查錄影；模型 hash 與錄影範圍見 `reports/g2/shared-blink-recording.json`。它不包含手勢或音畫延遲驗收。

## 結構

`models/shared-face/model.model3.json` 指向單一 moc3，17 個 ArtMesh。一個 `SharedSkinContinuous` 保留原圖髮型、下巴、耳朵與鼻子；只有指定臉部皮膚區域使用 imagegen 補畫。該區域外 981,447 個像素的 RGBA 最大差為 0，見 `reports/g2/shared-source-integrity.json`。這是來源邊界檢查，不代表生成區域與原畫完全一致。

左右眉各一層；左右眼各包含眼睛可見範圍遮罩、保留原始虹膜／眼白的內部圖、睫毛、閉眼睫毛、張眼摺線與閉眼陰影；嘴部包含閉嘴與張嘴局部部件。眼睛內部圖目前仍把虹膜與眼白放在同一層，尚未支援獨立視線。

## 控制與修正

| 控制 | 行為 |
|---|---|
| `ParamEyeROpen` / `ParamEyeLOpen` | 遮罩與睫毛控制開合；虹膜圖像不跟著壓縮 |
| `ParamBrowRY` / `ParamBrowLY` | 左右眉獨立高低 |
| `ParamBrowRAngle` / `ParamBrowLAngle` | 左右眉獨立角度，模型端 authored keyforms |
| `ParamMouthForm` | 實際嘴角形變；已修正自動匯出只有參數、沒有可見作用的問題 |
| `ParamMouthOpenY` | 上唇附近固定開口位置；播放音訊時由 WebAudio RMS 驅動 |

張眼摺線隨閉眼下移、變平，開合值 0.5 時透明度 0.7，0.15 以下為 0。原始 `idle_listen_4` 的閉眼圖仍有較低的粉色眼皮陰影，以及上眼皮的局部明暗；因此保留這些局部原畫，在接近閉眼時接入，而不是把張眼摺線固定在原位。左右分別綁定同側開合參數。

曾出現的半閉眼重影，原因是自動 rig 把完整眼睛當睫毛變形，又疊入閉眼圖。v3 改為裁切可見範圍，虹膜幾何不變。嘴部也修正了閉嘴細線殘留與開口時兩個嘴型同時可見的問題。這些修正仍需慢速動畫與原圖端點視覺評估。

`expression-sequence.json` 定義連續表情目標，viewer 平滑插值並疊加眨眼；不需攝影機。音訊優先控制開口，其他表情可同時運行。操作任一滑桿或選擇 preset 會停止自動表情展示；手動開口會暫停音訊。此處音訊是音量包絡，不是逐音素嘴型。

## 驗證

`npm.cmd run test:shared` 使用官方 Cubism Core 與 headless Edge，檢查：

- 五組單獨控制不影響指定的無關部件。
- 八個控制各五個取樣值皆產生不同、有限的幾何結果。
- 左右摺線會移動、淡化，完全閉眼時為透明；眼內部幾何不被眨眼壓縮，且使用同側眼睛遮罩。
- 左右眉在高度與角度同時使用時，兩個控制仍各自改變幾何；慢速眨眼可暫停。
- 十一組表情／中間形狀、連續展示、實際音訊開口與手動接管。
- 三張原圖的同座標量測與疊圖／差異畫面；不把非零誤差誤標為視覺合格。
- 全程只載入一次 moc3；測試前後模型 hash 不變。

結果見 `reports/g2/shared-face-results.json`。其中 `structuralPassed` 只代表上述功能，`qualityAccepted` 仍為 false。未用此測試取代完整 E01–E07、30 張原圖還原、手勢與效能驗收。

## 來源與重建

基準：`idle_listen_1.png`；閉眼局部：`idle_listen_4.png`；張嘴局部：`speaking_1.png`。工作畫布為來源 x=600、y=0、1024×1024 的原尺寸裁切。imagegen 產物與使用限制記錄於 `IMAGEGEN.md`。

在 lab 專用 PSD2Live headless workspace 已啟動、素材工程存在時，可從 repo 根目錄依序執行：

```powershell
.\ai_voice_assistant\venv\Scripts\python.exe prototypes/live2d_character_lab/tools/isolate-feature-masks.py
.\ai_voice_assistant\venv\Scripts\python.exe prototypes/live2d_character_lab/tools/split-eye-geometry.py
.\ai_voice_assistant\venv\Scripts\python.exe prototypes/live2d_character_lab/tools/rig-shared-face.py
.\ai_voice_assistant\venv\Scripts\python.exe prototypes/live2d_character_lab/tools/verify-shared-face.py
```

前兩步由原圖分析遮罩，實際部件抽取、遮罩、綁定與匯出均在 PSD2Live 進行。Python 不另畫替代五官。最新可編輯工程：`authoring/shared-face/shared-face-rig-v5.psd2live` 與同名 PSD。再於 lab 執行 `npm.cmd run prepare:assets` 更新預覽資產。

局部參數候選可用 `node tools/fit-shared-reference.mjs` 重算；它只產生候選報告，不自動覆寫預覽的參數檔。先檢查疊圖再採用，不把降低平均誤差當作主觀品質通過。錄影由 `node tools/record-shared-blink.mjs` 產生；所需 Playwright FFmpeg 固定於 lab 的 `.cache/playwright/`，未更動主程式環境。

## 尚待完成

眼皮陰影邊緣仍有裁切感，閉眼睫毛與局部明暗需要更細緻的原圖比對；嘴唇、牙齒、舌頭尚未完整分層，只有基礎開合與嘴角形變。頭髮、耳朵、頭頸還未從這個共用底層進一步分離，因此此版固定頭部方向，不能宣稱轉頭已合格。

仍需完成 30 張原圖端點的還原校正、獨立眼球／眼白、頭頸與身體、七姿勢、腕部／肩肘過渡及拇指遮擋。手部原畫目前保留於獨立校對模型，未合入本頁。主程式未整合。
