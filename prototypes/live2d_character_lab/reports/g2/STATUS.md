# G2 原圖五官與手部校對

更新日期為 2026-11-18。**v5 閉眼、v6 視線、v7 嘴型、v8.1 眉毛修正與 v9 頭頸側傾已通過使用者確認；v11 髮緣與日常聆聽已完成原生工程，G2 全模型質感待驗收。主程式及 30 張原圖未修改。**

## 髮緣與日常聆聽 v11

2026-11-18 已完成 v11 原生工程。將已比對的髮緣修正依原貼圖範圍套入 `SharedSkinContinuous`，保留同一個模型與五官定位。v11 的 moc3 與 v10 完全相同，原生貼圖含髮緣修正。重開工程再匯出可重現全部四個檔案的 SHA-256。[WSL2 重匯出](v11-linux-roundtrip.json)

在中立、半閉眼轉頭與閉眼轉頭三個姿勢比較先前的貼圖補丁與 v11 原生匯出。深淺背景各三張影像，最大像素差為 1 個 8-bit 色階。675 組頭部／表情與 90 組閉眼測試通過。聆聽測試涵蓋視線先到、眨眼、輕點頭、暫停續播與音訊嘴型。[外觀比對](v11-native-appearance.json) · [頭部測試](v11-head-turn-results.json) · [閉眼測試](v11-head-turn-blink-results.json) · [聆聽測試](v11-listening-results.json)

[互動預覽](http://127.0.0.1:5187/shared-face.html?polish=1) · [原速錄影](listening-v11.webm) · [深淺背景前後對照](polish-comparison.png)。右側細髮放大看仍略硬。完整手勢待綁定，v11 質感待使用者確認。

## 小角度轉頭／俯仰 v10

依使用者要求限制動作幅度：`ParamAngleX` ±6、`ParamAngleY` ±4；這是動畫參數範圍，不是實測人體角度。保留 20 個 ArtMesh，新增兩個可操作控制，共 18 個。81 個頭部組合 key 修正肩部連動，眉尾另有轉頭／俯仰的局部條件修正。

[預覽](http://127.0.0.1:5187/shared-face.html?turn=1)／[製作紀錄](../../design/HEAD_TURN.md)／[組合檢查](head-turn-results.json)／[閉眼檢查](head-turn-blink-results.json)／[無聲錄影](head-turn-v10.webm)。**v10 質感待使用者確認**；髮緣殘色與完整手勢仍未完成，未整合主程式。

## 已接受：頭頸側傾 v9

37 份接受版檔案與 hash 見 `head-v9-accepted.json`。

新增 ±6° 側傾與頸根固定，仍為 20 個 ArtMesh、同一連續皮膚底層。135 組表情／側傾與 49 個角度檢查通過；中立五官最大差 0.0108 px，側傾跟隨最大誤差 0.0113 px，肩部最大位移 0.0835 px，頸部三角形沒有翻折。可同時播放音訊、表情與眨眼。

[預覽](http://127.0.0.1:5187/shared-face.html?head=1)／[製作紀錄](../../design/HEAD_NECK.md)／[測試](head-neck-results.json)／[無聲錄影](head-neck-v9.webm)。**v9 側傾已獲使用者確認**；髮緣殘色、左右轉面、俯仰、全身與手勢未完成。

## 已接受：眉尾接合 v8.1

使用者已確認「好 通過，繼續吧」；74 份接受版備份及 hash 見 `brows-v8-1-accepted.json`。

修正使用者指出的畫面左側眉毛與髮際不連續：原拆件夾帶黑色髮絲，底圖又留下眉尾殘影。最終採用原生局部擦除／補色，加上既有右眉 ArtMesh 的 27 個高度 × 角度 × 眉形條件形變，讓乾淨眉尾持續接上髮際。沒有新增整頭、左右鏡像或另一側眉毛位移。

125 組含中間值的檢查通過；另一側眉毛與其他全部五官頂點相對 v8 最大差為 0，眉尾最大正向間隙約 0.309 px（原圖座標）。原有閉眼、視線、嘴型回歸通過。預覽新增可暫停的「雙眉慢速檢查」。見 [製作紀錄](../../design/BROW_HAIRLINE.md)、[眉尾測試](brow-hairline-results.json)、[無聲錄影](brow-v8-1.webm)。

## 前版：眉眼校準 v8

[眉眼校準預覽](http://127.0.0.1:5187/shared-face.html?expression=1) 沿用 v7 的 20 個 ArtMesh 與全部拆件，新增四個左右獨立眼型／眉形控制，共 15 個控制。眼皮、睫毛、虹膜、眼白及摺線在同側外層一起變形，保留原有開合、視線與嘴型；沒有新增整頭素材。

說話原圖固定 ROI 的右／左眼 RGB 平均差由 27.691／26.394 降至 19.870／18.185，約改善 28%／31%；眉毛小幅改善，嘴部維持 10.1599。22 組舊參數回歸、四個新軸獨立控制、63 組眼型／視線／開合與嘴型組合、音訊和單次載入檢查通過。閉眼量測先還原外層旋轉的座標，仍使用原有 0.35 px 路徑容許值。畫面及測量只是本輪局部證據，全臉明暗、鼻形、其餘原圖表情、頭身及七手勢未完成。

詳細範圍：[製作紀錄](../../design/EXPRESSION.md)、[功能檢查](expression-face-results.json)、[驗收版保護](expression-asset-integrity.json)、[無聲錄影](expression-v8.webm)。

## 已接受嘴型：v7

[嘴型預覽](http://127.0.0.1:5187/shared-face.html?speech=1) 提供獨立下唇、嘴寬、慢速嘴型檢查及說話表情校對。共 20 個 ArtMesh、11 個控制；既有眼眉、眨眼與視線仍可組合。閉嘴原件在透明間隔拆分，原口腔保留，完整下唇隨開口移動，避免舊下唇被裁短及壓扁。

63 組嘴型與 21 組眼部回歸、音訊／嘴寬同時運作及單次載入均通過；閉嘴外觀維持 v6。下唇局部原圖差異減少約 18%，未宣稱全臉或完整說話表情還原。詳細範圍：[製作紀錄](../../design/SPEECH.md)、[功能檢查](speech-face-results.json)、[來源與驗收版保護](speech-asset-integrity.json)、[無聲錄影](speech-v7.webm)。

## 已接受視線：v6

[候選預覽](http://127.0.0.1:5187/shared-face.html?gaze=1) 使用 19 個 ArtMesh、10 個控制，保留同一臉底，新增獨立虹膜和眼白。可用程式序列演繹視線、眉眼、嘴形與眨眼，並同時播放音訊。候選另外保存，預設入口仍為 v5。

72 組視線 × 開合、兩個視線軸連續取樣、非零視線下的 8 個臉部控制、音訊和單次載入均有功能檢查。全閉畫面與 v5 最大色差為 2/255；這些不等同視線質感或全原圖還原通過。詳細範圍見 [製作紀錄](../../design/GAZE.md)、[測試](gaze-face-results.json)、[來源保護](gaze-asset-integrity.json)、[錄影](gaze-v6.webm)。

## 已接受閉眼：共用臉部 rig v5

新增 [共用臉部預覽](http://127.0.0.1:5187/shared-face.html) 與 [製作紀錄](../../design/SHARED_FACE.md)。此模型有一個臉底、17 個 ArtMesh、8 個可用獨立控制；沒有 `ParamReferenceFrame`。可連續組合左右眼眉、嘴形與實際音訊開口。雙眼皮摺線已改成隨閉眼移動、淡出，閉眼局部陰影來自原圖；虹膜不再隨眼睛開合被壓扁。

官方 Core 功能測試見 [shared-face-results.json](shared-face-results.json)，來源保護範圍見 [shared-source-integrity.json](shared-source-integrity.json)。五組獨立控制、八組五點連續取樣、十一組形狀與音訊操作已加入測試；這些不是視覺通過標記。眼皮局部邊緣、全表情還原、頭身與七手勢仍未完成。

v5 修正了使用者指出的半閉眼膚色間隙：同側睫毛與遮罩改由同一個 Warp 變形，並調整最後一段閉眼睫毛的厚度與位置過渡。閉眼陰影不再混入黑色睫毛像素；嘴形與開口的透明度衝突也已修正。針對性檢查見 [blink-continuity-results.json](blink-continuity-results.json)，最新 [無聲往返錄影](shared-slow-blink-v5.webm)。

v4 已移除眼皮部件的髮際碎片、延伸眉毛向下行程並校準閉眼／說話的局部控制。預覽保留三張原圖的疊圖／差異檢查與可暫停的慢速眨眼。眉高與角度組合檢查通過；全臉與說話眼型仍不合格，量測與限制見製作紀錄。

目前專用工作區保存為 `authoring/shared-face/shared-face-rig-v5.psd2live`。以下 `reference-fidelity-v4` 舊校對頁仍保留作來源端點比較，不與新的語意控制模型混為一談。

## 最新方向修正

使用者確認：各表情應共用同一個頭部底圖，正確拆件、網格、變形器與遮罩應能避免下巴接縫。這是正式方向。

目前矩形五官差分帶入了來源影格的髮絲或下巴輪廓，與待機頭部疊加後產生接縫。這是拆件與組裝缺陷，不能歸咎於「共用頭部本來就會如此」。曾嘗試加入每個表情的頭部背景差分，已停止並否決；未匯出成目前展示模型。原生工作區已恢復 `authoring/reference-fidelity-v4.psd2live`。`rejected-head-context-checkpoint.psd2live` 僅保存失敗實驗，不可作正式素材。

下一輪正式結構：一個完整、連續的臉部皮膚底層；頭髮與耳朵獨立；眉毛、眼白、虹膜、眼線、上下眼皮、嘴唇／口腔分離；表情經共用臉部變形器及局部參數控制。五官素材不得夾帶另一張原圖的下巴或頭髮。只有確有必要的眼／嘴／手掌局部差分才切換，不以整頭替換達成相似度。

使用者進一步確認：現有表情與動作是模型能力的考驗，未來還需演繹更多內容。因此 `ParamReferenceFrame` 與目前 16 組貼片僅用於來源保真檢查，不是正式的可延伸表情架構。PLAN 已補入可重用控制要求，ACCEPTANCE 新增 E01–E07；須同時通過原圖還原與未見組合演繹。新的共用臉部模型開始驗證這項能力，完整角色尚未完成。

## 本輪已完成的可檢查成果

- [五官校對頁](http://127.0.0.1:5187/fidelity.html)：30 張原始影格按 SHA-256 對應 16 組來源。使用原始畫布座標，比較眼眉、鼻子與嘴部；有原圖、模型、疊加與差異 ×4。此頁保留問題以便追蹤，不能當作最終臉部 rig。
- [手勢校對頁](http://127.0.0.1:5187/hands.html)：舉食指與托腮手掌由原圖直接分割，修正外套殘邊、食指關節削角與彎曲指節切線。保留指尖、拇指尖／根／虎口、手腕的來源座標，沒有鏡像或重新擺手指。
- 五官與兩隻手部差分已在同一個 `models/face-fidelity/original.moc3`，目前 74 個 ArtMesh。手部檢查模式暫時隱藏其他 drawable；**不代表已接回骨架或完整身體**。
- 可編輯工程：`authoring/reference-fidelity-v4.psd2live`；手部來源：`authoring/source-parts/{index,chin}-hand-v2.png/.psd/.psd2live`。定位與輪廓修正保存在 `design/hand-source-landmarks.json`、`hand-contour-overrides.json`。

## 實測結果與適用範圍

來源與程式檢查見 [source-integrity.json](source-integrity.json)，官方 Core 畫面檢查見 [fidelity-results.json](fidelity-results.json)。

| 檢查 | v4 結果 | 可以證明的事 |
|---|---|---|
| 16 組四個五官區域 RGB 平均絕對差 | 各區約 0.12–0.64／255 | 原始五官像素能透過 atlas 與 Core 保真顯示 |
| 包含五官周圍的完整 440 × 440 原圖區域 | 約 0.47–31.14／255 | 多數表情仍有頭部不一致與接縫，**未合格** |
| 兩份裁切手部的完全不透明像素 | 與原圖 RGB 最大差為 0 | 可見部件內部沒有重畫或改色 |
| 手部 Core 畫面與裁切素材比較 | 舉食指約 0.58、托腮約 0.48／255 | 匯出後手部內部像素保真；不是完整輪廓／動畫驗收 |
| 拇指與手腕定位點 | 8 個點均仍在裁切 alpha 內 | 指定點未被裁掉；定位點不等同全部手指輪廓 |
| 表情切換、手勢檢查切換 | 每頁只載入一次 moc；兩頁指向同一檔 | 檢查過程不需更換模型 |
| 原始素材與 UTF-8 | 30 個來源 hash 均未變；文件 strict UTF-8 通過 | 沒有改寫主程式原圖 |

量測在 900 × 900 WebGL buffer、相同來源座標與相同底色上進行，正確處理 premultiplied alpha；未另外拉伸原圖來降低誤差。手部 alpha 差是相對於裁切後的素材，不是獨立人工標註的完美輪廓，因此不能拿它宣稱拆件已完美。

## 明確未完成

1. 矩形五官貼片尚需改成乾淨的局部部件；髮絲與下巴接縫未通過。
2. 16 個表情目前是來源端點檢查。連續眨眼、嘴型、表情變形與共同頭部輪廓尚未完成；此模型不是 G1 音訊嘴型模型的完成替代品。
3. 兩個手勢保留原圖姿勢，但腕部接縫、肩肘連動、遮擋及手指過渡尚未製作；其餘五姿勢仍待製作。
4. 最終單一模型同時包含全部表情、七姿勢、轉場及音訊嘴型，仍未完成。
5. 使用者質感驗收、長時間效能、聲畫延遲與 Cubism Editor 回編仍未執行。

## 驗證命令

在 lab 目錄執行 `npm.cmd run build`、`npm.cmd test`；dev server 運作時執行 `npm.cmd run test:browser` 與 `npm.cmd run test:fidelity`。來源像素與 hash 檢查從 repo 根目錄執行 `ai_voice_assistant\venv\Scripts\python.exe prototypes/live2d_character_lab/tools/verify-reference-assets.py`，只使用既有 interpreter，不修改其 dependencies。

G1 回歸的 3 個 controller 測試與 7 組 browser 功能檢查仍通過。G2 browser 測試目前驗證資產版本、16 組端點可載入、像素可量測、手部可見與模型不重載；尚未把整張臉的低色差列為通過條件，因為該缺陷仍待修復。

製作時也修正了預覽誤讀舊 `model.model3.json` 的問題；當前明確讀取 `original.model3.json`，測試會拒收缺少 `ParamReferenceFrame` 或部件數不足的舊模型。原生工具有些未生成 layer 的 split／rebuild 操作會失敗；失敗工程保留供查證，不當作完成檔。
