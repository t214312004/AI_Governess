# 頭頸側傾 v9

2026-11-14。v8.1 眉毛修正已獲使用者確認，本輪延續同一模型，加入小角度頭頸側傾。**v9 頭頸側傾已獲使用者確認，接受版另存 37 份檔案於 `authoring/checkpoints/head-v9/`。** 主程式尚未整合。

## 預覽與範圍

開啟 [頭頸預覽](http://127.0.0.1:5187/shared-face.html?head=1)，按「頭頸慢速檢查」觀看一個 16 秒往返；再按一次可停在中間角度。也可用「向畫面左側傾」「向畫面右側傾」「側傾說話」、既有表情序列及音訊播放檢查。

- 同一份 `models/head-face/original.moc3`、20 個 ArtMesh、16 個控制；未增加整頭差分或重載模型。
- 新增 `ParamHeadTilt`，範圍 −6° 至 +6°，0 為原中立姿勢。這是畫面平面內的側傾，尚不包含左右轉面或俯仰。
- 延續既有眨眼、視線、眉毛及音訊嘴型；可在側傾時改變表情。音訊控制嘴開合，未使用攝影機追蹤。
- 頭頸仍使用同一連續皮膚底層；本輪沒有把下巴切開再疊回。
- 放大視野會看見原有髮緣少量綠／白背景殘色，尚待原生素材清理。頭髮仍未完整獨立分層；全身、七手勢與原圖全表情還原亦未完成。

## 製作方式

在已接受 v8.1 工程的 `DeformHeadContainer` 外加入原生 Rotation Deformer `HeadNeckTilt`，轉軸在 1024 px 頭部來源畫布的 `(512,750)`。既有五官變形器保留，共用上層側傾。

原自動綁定會把肩部一起帶動。本輪對既有 `ArtMeshFace` 的下半部加入反向補償：來源 y≤620 保持頭部轉動，620–800 以 smoothstep 過渡，y≥800 的頸根／肩部頂點固定。使用 9 個角度 key：−6、−4.5、−3、−1.5、0、1.5、3、4.5、6。先建立全部中立 key，再設定變形，避免從已變形端點插值後重複套用。

原生局部座標和匯出 Core 的畫布座標並不完全一致。先用小幅 x/y 位移量測每個頂點的局部換算，再逐點設定反向位移，最後以匯出幾何進行兩輪誤差修正。所有變形寫回原生 keyforms，runtime 只設定參數，不在瀏覽器額外拉扯頂點。

## 檢查結果

來源像素座標的量測見 [head-neck-results.json](../reports/g2/head-neck-results.json)。

| 項目 | 結果 |
|---|---|
| 中立角度與已接受 v8.1 比較 | 27 組眼型／開合／嘴型組合；最大差 0.0108 px |
| 表情 × 側傾 | 135 組，含 −3.75°／3.75° 非 key 角度 |
| 密集角度掃描 | −6° 至 6°，間距 0.25°，49 組 |
| 五官及上頭部跟隨轉軸誤差 | 最大 0.0113 px |
| 頸根／肩部位移 | 最大 0.0835 px；門檻 0.15 px |
| 頸部三角形 | 未翻折；面積比例約 0.817–1.185 |
| 拓撲、遮罩、透明度 | 與既有模型對應一致 |
| 暫停、音訊疊加、連續表情 | 通過；單次模型載入，無瀏覽器例外 |
| 工程重新開啟匯出 | moc3 與三張 atlas hash 完全相同 |

新增父層後，半閉眼的摺線／睫毛匯出座標有最多約 0.011 px 的微差，因此回歸門檻為 0.02 px，沒有宣稱逐頂點完全相等。肩部門檻仍維持 0.15 px，沒有為了通過測試放寬到可見位移。測試數字只證明本輪幾何與操作行為，不代替使用者對自然度的判斷。

既有眉尾 125 組與表情 22 組回歸／63 組組合亦重新通過；已接受 v5、v6、v7、v8.1 的模型及備份獨立保護。

## 檔案與重建

- 原生工程：`authoring/head-v9/shared-face-rig-v9-head.psd2live`；同目錄另有 PSD。
- 模型：`models/head-face/`；已接受眉毛模型仍在 `models/expression-face/`。
- 基礎作者工具：`tools/rig-head-neck.py`；校準資料：`design/head-neck-calibration.json`。
- 匯出幾何修正：`tools/capture-head-geometry.mjs` 與 `tools/refine-head-neck.py`。執行基礎作者工具後，先 `node tools/prepare-assets.mjs`，再依序 capture → refine → prepare，執行兩輪。
- 校準資料只適用目前固定來源模型。換來源時，`tools/calibrate-head-neck.py` → prepare → `tools/capture-head-calibration.mjs` 可重測；它暫時將 `head-face` 換成量測版本，必須接著重建正式候選並重跑檢查，不可直接交付量測模型。
- 驗證：`npm.cmd run test:head`、`tools/verify-head-roundtrip.py`、`tools/verify-head-assets.py`。
- [無聲錄影](../reports/g2/head-neck-v9.webm)：側傾往返、側傾時眨眼，以及連續表情與音訊驅動嘴型。錄影不含聲音，不能當作聲畫延遲量測。

## 範本的重用

通用結構已由 PSD2Live 生成，再累積角色專屬校準；不是每個表情重新建一副骨架。Cubism 官方也提供模型範本套用功能，但仍需將部件正確對應並調整形狀。見 [官方範本套用說明](https://docs.live2d.com/en/cubism-editor-manual/applying-the-model-template/) 與 [PSD2Live 說明](https://github.com/tsunehimatoi/psd2live/blob/master/docs/en/README.md)。本輪繼續使用本機固定的 PSD2Live 3.6.7，未因上游版本更新更換工具。

對同一角色新增動作，優先組合既有參數；超過已驗證角度、手掌視角或遮擋範圍時，才擴充局部素材與 rig，並回歸已接受版本。
