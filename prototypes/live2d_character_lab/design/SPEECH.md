# 嘴型與下唇精修 v7

更新：2026-11-13。使用者回覆「好 通過，繼續下個步驟吧」，v7 嘴型已通過；連同 v5 閉眼與 v6 視線保留為局部驗收基準。v7 的 68 份備份見 `authoring/checkpoints/speech-v7/`，hash 見 `reports/g2/speech-v7-accepted.json`。仍只在獨立 lab 開發，未整合主程式；全臉與手勢不在此通過範圍。

## 預覽與操作

[嘴型精修預覽](http://127.0.0.1:5187/shared-face.html?speech=1) 使用單一 `speech-face/model.moc3`，20 個 ArtMesh、11 個控制。

- 「慢速嘴型檢查」約 8 秒完成一次閉嘴、張嘴、閉嘴，可暫停檢查中間形狀。
- 「說話表情校對」套用目前局部參數；可展開「與原圖校對」，選說話原圖及疊圖／差異檢視。
- 嘴寬滑桿可與嘴角、開口、視線、眼眉組合，也可在播放音訊時調整。
- [無聲錄影](../reports/g2/speech-v7.webm) 展示慢速開合及嘴寬變化；即時音訊嘴型請在預覽播放測試音訊。

此版本不切換整頭、不重新載入模型，也不使用攝影機或真人動作追蹤。

## 問題與修改

v6 的張嘴部件沿用較小的嘴部遮罩，說話原圖的下唇陰影延伸到約 y=607，但舊部件在 y=600 附近已被截斷。口腔和殘缺下唇又共用縮放，開口較小時會一起被壓扁。

v7 將嘴部改成閉嘴主輪廓、張嘴口腔、共用下唇三個部件。閉嘴原件只在透明間隔處拆成上下兩部分，兩部分的 alpha 與可見 RGBA 合起來等於原件。張嘴口腔保留原本來源像素，下方殘缺陰影由完整共用下唇替代。

共用下唇使用待機原圖的完整下唇像素，閉嘴時維持原樣，張嘴時依說話原圖量測的位置與比例移動、縮放。全程保持可見，不以透明度交叉淡入兩片下唇。張嘴時約下移 13 個來源像素，保留約 11 個來源像素的厚度；這是幾何範圍，不等同每個可見像素的精確對位。

`ParamMouthWidth` 同時控制口腔與下唇各自的寬度 Warp，範圍約為中立寬度的 82%–118%。它獨立於 `ParamMouthOpenY`，因此音訊仍只控制開口。

曾嘗試重新切緊口腔外框，視覺上減少淺色碎邊，但固定原圖 ROI 的誤差反而增加，因此沒有採用該口腔版本。當前保留原口腔，集中修正完整下唇及動作；口腔邊緣仍屬後續視覺檢查範圍。

本輪沒有生成新圖。`tools/split-speech-mouth.py` 使用原生材料抽取與遮罩，Python 只分析來源像素及遮罩幾何。拆件不透明區域的 RGB 與各自原圖最大差為 0。

## 驗證

`npm.cmd run test:speech` 已通過：

- 3 個嘴寬 × 3 個嘴角 × 7 個開口，共 63 組；下唇保持可見、移動連續、厚度不塌陷，口腔／閉嘴透明度正確。
- 3 個斜向視線 × 7 個眼開合，共 21 組；虹膜遮罩、閉眼隱藏、眼皮與睫毛共同閉合軌跡維持原邏輯。
- 嘴部以外的幾何與 v6 對照，來源座標差低於 0.01 px。
- 慢速嘴型暫停、音訊與嘴寬同時操作、停止閉嘴、單次模型載入及瀏覽器無例外。

固定來源座標的診斷如下，數值越低表示在該範圍的 RGB 平均差越小：

| 檢查範圍 | v6 | v7 | 解讀 |
|---|---:|---:|---|
| 閉嘴完整嘴部 ROI | 1.5985 | 1.5992 | 保持原外觀，差異主要在輸出取樣 |
| 說話完整嘴部 ROI | 10.2585 | 10.1599 | 小幅改善；周圍皮膚仍與說話原圖不同 |
| 張嘴口腔較小 ROI | 2.2644 | 2.2618 | 保留原口腔保真程度 |
| 張嘴下唇較小 ROI | 6.8298 | 5.6087 | 差異約減少 17.9%，未宣稱完全一致 |

前兩項來自瀏覽器固定 ROI；後兩項用相同來源裁切與 bilinear 檢查縮放，不另做影像配準。指標只用於定位問題，不能取代質感驗收，也不代表全臉還原。

報告：[功能測試](../reports/g2/speech-face-results.json)、[來源及接受版保護](../reports/g2/speech-asset-integrity.json)、[拆件清冊](../reports/g2/speech-mouth-parts.json)。v5 的 46 份備份、v6 的 62 份備份皆驗證 hash；現行兩個已接受模型的全部檔案保持不變。

## 原圖表情仍待處理

本輪先量測原有控制的說話表情擬合，結果見 `reports/g2/gaze-reference-fit-candidate.json`。只調眼開合、眉毛與嘴角，仍無法還原來源的虹膜比例、眼尾、眉形，以及臉部明暗和鼻形變化。因此沒有把這一輪標記為整張說話表情完成；眼型、眉形與其餘表情仍需後續製作。頭頸與七手勢也尚未接入。

## 重建

於 PSD2Live service 啟動後，從 repo 根目錄執行：

```powershell
.\ai_voice_assistant\venv\Scripts\python.exe prototypes/live2d_character_lab/tools/split-speech-mouth.py
.\ai_voice_assistant\venv\Scripts\python.exe prototypes/live2d_character_lab/tools/rig-shared-face.py --speech
```

再於 lab 執行 `npm.cmd run build`、`npm.cmd run test:speech`。來源檢查為 `tools/verify-speech-assets.py`，錄影工具為 `tools/record-speech.mjs`。

- 模型：`models/speech-face/`。
- 原生模型工程及 PSD：`authoring/shared-face/shared-face-rig-v7-speech.*`。
- 獨立嘴部材料：`authoring/speech-face/`。
- 語意名稱對照：`design/speech-face-runtime-map.json`。

重建必須帶 `--speech`；v5 與 v6 的輸出維持分開保存。
