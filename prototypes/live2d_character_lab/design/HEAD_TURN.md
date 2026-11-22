# 小角度轉頭與俯仰 v10

2026-11-14。依使用者「轉頭與俯仰可以限制在小角度」的要求，以已接受 v9 為基準加入微幅轉頭和俯仰。**功能檢查已通過，v10 質感仍待使用者確認。** 所有工作保留在獨立 lab，未整合主程式。

## 操作與動作邊界

[開啟預覽](http://127.0.0.1:5187/shared-face.html?turn=1)。先看「慢速轉頭檢查」與「慢速俯仰檢查」，再按一次可暫停；也可選「轉頭說話」並播放音訊，或使用連續表情展示。

| 控制 | 範圍 | 用途 |
|---|---|---|
| `ParamAngleX` | −6 至 +6 | 小幅左右轉頭 |
| `ParamAngleY` | −4 至 +4 | 小幅低頭／抬頭 |
| `ParamHeadTilt` | −6° 至 +6° | 已通過的畫面平面內側傾 |

X/Y 是繪製形變的動畫參數，不能當成量測的人體三維角度。可用範圍同時設在模型參數與預覽滑桿，沒有只靠播放腳本限制。此版本只驗證小幅動作；不提供大角度側臉或大幅仰頭。

同一個模型包含原有 20 個 ArtMesh 與 18 個可操作控制。眨眼、視線、眉形、嘴型與音訊開合都可疊加，使用過程不換整頭或重載模型。髮緣原有綠／白殘色、頭髮完整分層、全身七手勢與各原圖表情保真仍未完成。

## 這輪的模型修改

沿用原生生成 rig 的 `ParamAngleX/Y` 小幅區間，保留既有五官透視。原始生成動作會連同肩部一起移動，左右轉頭時約 7.3 px，轉頭與俯仰組合約 7.9 px。

在既有連續皮膚 ArtMesh 上加入 3 個轉頭 × 3 個俯仰 × 9 個側傾，共 81 個條件 key。來源 y≤620 保持頭部形變，620–800 平滑過渡，y≥800 保留 v9 的頸根／肩部位置；各方向與中間值皆可組合。這些修正保存在模型，runtime 不額外改寫頂點。

轉頭也會讓既有眉尾與髮際相對移動，最大約 1.10 px。因此在右眉尾加入 27 組眉高／眉角／眉形 × 9 組轉頭／俯仰的局部修正，以同一連續皮膚網格上的定位點為目標。只補償眉尾及平滑鄰域，不改正面眉形，也不鏡像另一側眉毛。兩輪修正後，密集檢查的接合變化低於 0.092 px。

## 驗證結果

數字均為來源圖畫布像素；幾何及功能通過不等於自然度已獲使用者接受。

| 檢查 | 結果 |
|---|---|
| 正面／側傾與已接受 v9 比較 | 27 組表情及側傾，頂點最大差 0 px |
| 轉頭 × 俯仰 × 側傾 × 表情 | 675 組，含 X/Y 中間值；無非有限座標或皮膚三角形翻折 |
| 相對相同側傾的 v9 肩部額外位移 | 最大 0.0819 px，門檻 0.15 px |
| 皮膚三角形面積相對 v9 | 約 0.907–1.067 |
| 密集眉毛接合檢查 | 1,125 組，含眉高／眉角／眉形中間值；最大變化 0.0916 px |
| 轉頭／俯仰＋側傾時的閉眼 | 90 組，眼皮／睫毛閉合路徑差最大 0.2397 px，維持原 0.35 px 門檻 |
| 中立與組合姿勢的遮罩／透明度 | 保持對應；允許 Core 浮點透明度的 1e−5 數值誤差 |
| 暫停、音訊與連續動作 | 通過；單次載入，無瀏覽器例外 |
| 原生工程重新開啟匯出 | moc3 及三張 atlas hash 完全一致 |

閉眼量測先去除眼部的轉頭投影；局部 affine 擬合最大誤差約 0.1145 px。它是閉合路徑的診斷近似，仍另留實際渲染與連續錄影供質感檢查，沒有只用近似數字宣布畫面完美。已接受 v9 的原有側傾頁也重新跑回歸。

證據：`reports/g2/head-turn-results.json`、`head-turn-blink-results.json`、`head-turn-brow-dense.json`、`head-turn-roundtrip.json`、`head-turn-asset-integrity.json`。

[無聲錄影](../reports/g2/head-turn-v10.webm) 包含轉頭、俯仰、轉頭時眨眼及音訊驅動嘴型；不含聲音，不作聲畫延遲量測。

## 工程與重建

- 接受版 v9：`authoring/checkpoints/head-v9/`，37 份檔案；模型仍在 `models/head-face/`。
- v10 工程：`authoring/turn-v10/shared-face-rig-v10-turn.psd2live`，同目錄另有 PSD。
- v10 runtime：`models/turn-face/original.model3.json`、`original.moc3` 與三張 atlas。
- 81 個條件 key：`design/head-turn-keys.json`；連續皮膚目標：`design/head-turn-skin-targets.json`。
- 建立與修正：`tools/rig-head-turn.py` → `node tools/prepare-assets.mjs` → `tools/capture-head-turn.mjs` → `tools/refine-head-turn.py`。每輪 refine 後都須重新 prepare、capture，直到固定端達標。
- 眉尾修正：`tools/fit-turn-brow.mjs` 產出具模型 hash 的條件資料，再交給 `tools/rig-turn-brow.py`。後續修正需使用重新量測的資料，不得重用舊模型取樣。
- 驗證：`npm.cmd run test:turn`、`npm.cmd run test:turn-blink`、`tools/verify-turn-roundtrip.py`、`tools/verify-turn-assets.py`。

取樣與修正工具已加入 model hash 檢查，防止開發伺服器重新載入或匯出失敗後誤用前一版幾何。重建時每步命令失敗即停止，不可繼續套用舊資料。原圖與所有已接受版本保持獨立備份。
