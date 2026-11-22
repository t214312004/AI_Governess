# 獨立視線候選 v6

更新：2026-11-13。使用者繼 v5 閉眼後，明確確認 **v6 視線通過**。接受版保存在 `authoring/checkpoints/gaze-v6/`，62 份檔案清冊見 `reports/g2/gaze-v6-accepted.json`。接受範圍不擴大為全表情、嘴型、手勢或整合。以下保留當時的製作與測試紀錄。

## 預覽

- [視線候選](http://127.0.0.1:5187/shared-face.html?gaze=1)：19 個 ArtMesh、10 個控制。可用左右視線按鈕、上下／左右滑桿，或「播放連續表情與視線」。音訊嘴型可同時運作。
- [已通過閉眼的 v5](http://127.0.0.1:5187/shared-face.html)：17 個 ArtMesh、原有 8 個控制。預設入口繼續讀取這份模型。
- [無聲視線與眨眼錄影](../reports/g2/gaze-v6.webm)：程式插值控制，沒有人體追蹤。

候選在單頁內只有一個模型實例，不因方向或表情更換 moc3。兩個獨立版本僅用於比較與回退；最終目標仍是一份能演繹全部動作的模型。

## 部件與綁定

原本 `InteriorR/L` 同時包含眼白和虹膜。候選將它們拆成固定的 `ScleraR/L` 與可移動的 `IrisR/L`；虹膜以 `face_detail` 匯入，避免自動生成器額外套用未知眼球行為。

`ParamEyeBallX/Y` 現在有實際 keyforms，設計行程為來源座標左右約 6 px、上下約 4 px。兩眼共用視線方向，左右眼開合仍獨立。虹膜和眼白均受對應 `EyeWindowR/L` 裁切；虹膜不隨閉眼被壓扁。

已接受的 `SharedLidR/L` Warp、睫毛接替、摺線淡出、閉眼陰影維持原來邏輯。虹膜在視線 X × Y × 眼開合的完整 keyform 網格上設定透明度，避免斜看時提前淡出或閉眼漏出虹膜。

## 圖像來源與修正

原圖可見的瞳孔、單一高光與虹膜主要色彩仍由 `head-original.png` 抽取。imagegen 只供應被上睫毛遮住的上方深色補片；最終只使用生成圖 `[450,165,400,100]` 的無高光區域，不把生成圖的另一個高光疊回眼睛。

原生 `material_crop`、`material_peel`、SVG 遮罩與 material folder 合成負責部件製作。Python 僅分析原圖、建立遮罩幾何與檢查輸出。SVG 內嵌 PNG 在此工具版本沒有正常顯示，已改成原生圖層合成，並加入輸出非空及 1024 × 1024 尺寸檢查。

已修掉早期候選的雙重高光、雙重外框和向下看時一起移動的黑色上睫毛殘留。完整的虹膜邊緣、下眼緣、極端視線相似度仍列為視覺檢查項目，不能只靠平均差異宣稱完成。

生成素材：[iris-complete-v1.png](../authoring/shared-face/iris-complete-v1.png)。完整 prompt：[iris-completion-prompt.txt](iris-completion-prompt.txt)。細節見 [IMAGEGEN.md](IMAGEGEN.md)。

## 驗證範圍

`npm.cmd run test:gaze` 驗證兩個視線軸各 5 個位置、9 種視線方向 × 8 個開合值，共 72 組；另外在非零視線下掃描原有 8 個臉部控制，確認虹膜不被眼眉嘴形變拉動。也檢查程式視線序列、播放音訊開口、停止閉嘴與單次模型載入。

視線組合檢查沿用閉眼共同軌跡門檻：眼皮遮罩和睫毛的推算閉合中心差低於 0.35 個來源像素。全閉畫面與接受版 v5 的 RGB 最大通道差為 2/255，平均差約 0.00046/255；沒有超過 8/255 的差異像素。

正視畫面與 v5 在眼部區域的 RGB 平均差約為右眼 1.37/255、左眼 1.20/255。這是相對上一版的回歸量測，**不是與全部原圖一致的證明**；局部最大差仍可能很大。眼部 ROI 固定在來源座標，沒有另外縮放或配準。

報告：[功能測試](../reports/g2/gaze-face-results.json)、[來源與眼部差異](../reports/g2/gaze-asset-integrity.json)。42 份已接受模型與既有臉部素材的 hash 保持不變；30 張原始影格未改寫。v5 原有 `test:shared` 與 `test:blink` 亦通過。

## 保存與重建

- 原生工程：`authoring/shared-face/shared-face-rig-v6-gaze.psd2live`，同名 PSD。
- 材料工程：`authoring/shared-face/materials-irises-v1.psd2live`。
- 候選模型：`models/gaze-face/`；對照 `design/gaze-face-runtime-map.json`。
- 接受版備份：`authoring/checkpoints/blink-v5/`，清冊 `reports/g2/blink-v5-accepted.json`。

於 lab 的 PSD2Live service 啟動後，從 repo 根目錄執行：

```powershell
.\ai_voice_assistant\venv\Scripts\python.exe prototypes/live2d_character_lab/tools/split-irises.py
.\ai_voice_assistant\venv\Scripts\python.exe prototypes/live2d_character_lab/tools/rig-shared-face.py --gaze
```

再於 lab 執行 `npm.cmd run build`、`npm.cmd run test:gaze`；來源檢查用 `tools/verify-gaze-assets.py`。重建候選必須帶 `--gaze`，避免覆蓋預設 v5 匯出。

下一步仍是原圖各表情的眼型與嘴角校準，以及頭頸／手臂接入。手勢、手指與拇指尚未合併進這份共用臉部候選，不能宣稱已支援七姿勢。
