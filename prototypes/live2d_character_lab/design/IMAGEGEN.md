# imagegen 補件紀錄

## shared-face skin-underpaint-v1（2026-11-12）

- 內建 imagegen，透明背景；輸入 `authoring/shared-face/head-original.png`，為 `idle_listen_1` 的 x=600、y=0、1024×1024 原尺寸裁切。
- 原始生成結果保存為 `authoring/shared-face/skin-underpaint-v1.png`，實際 1254×1254；由 PSD2Live material preview 正規化為 `skin-underpaint-normalized-v1.png`（1024×1024）。
- 補畫要求摘要（非逐字 prompt）：移除左右眉毛、左右眼睛與眼皮陰影、整個嘴部，以連續皮膚補滿；保留鼻子、髮型、耳朵、臉部外輪廓、衣服、原有位置與風格。
- 生成圖曾改變少量頭髮／臉形幾何，因此**沒有採用整張生成頭部**。只在臉部內側的限定遮罩取其皮膚，並挖孔保留原鼻子；原始髮型、耳朵與下巴沿用原圖。native material_peel 製成 `SharedSkinContinuous.png`。
- 遮罩外 981,447 個像素與原圖 RGBA 完全相同；證據為 `reports/g2/shared-source-integrity.json`。遮罩內仍須色調與明暗精修，不宣稱生成結果完全保真。
- 原始五官、閉眼睫毛／陰影與張嘴圖仍取自原始影格；imagegen 只補被移除五官遮住的皮膚。
- 完整 prompt 未在這份工作目錄持久化，此處不將摘要假稱逐字記錄。產物 hash 與尺寸已保存於上述來源完整性報告。

本輪結構與重建方式見 [SHARED_FACE.md](SHARED_FACE.md)。

## neutral_v1：拆件基準姿勢草稿

- 生成方式：內建 imagegen，transparent_background=true。
- 身分參考：`ai_voice_assistant/assets/states/layers/idle_listen_1.png`。
- 本機產物：`authoring/imagegen/neutral_v1.png`（不進 Git）。
- 用途：雙臂與軀幹分離，供下一輪語意拆件、關節與被遮擋衣服修復。
- 審查：**未通過正式素材驗收**。衣服多出原圖沒有的口袋，人物邊緣仍有白邊與彩色雜點；手指、臉部比例與原圖需再次校正。
- 目前 viewer 使用的是原圖 See-through 拆件輸出，尚未換成這張草稿。

原始 prompt（完整保存）：

```text
Use case: identity-preserve. Asset type: neutral reference illustration for Live2D rigging. Image 1 is the edit target and character identity reference. Preserve exactly this adult friendly governess's face, brown bob hairstyle, brown eyes, small gold earrings, light blue cream-trim jacket and cream dress, existing cel-shaded linework and colors. Produce a single clean front-facing knee-up character on genuinely transparent background. Change ONLY the pose of both arms: extend them relaxed downward and slightly outward from the shoulders, both forearms and all fingers fully visible, with a clear transparent gap between each arm and torso so a layer decomposition model can separate them. Hands relaxed open, not spread dramatically. Keep the face and torso centered, shoulders level, eyes open and mouth gently closed as in the reference. Preserve proportions and calm mature identity. Complete the now-visible jacket and waist previously covered by crossed hands. Remove edge cutout speckles and colored fringe. Whole hairstyle, fingertips and skirt crop must fit with margin. No text, no labels, no background shadow, no new accessories, no character redesign.
```

## 部件製作規則

### 虹膜隱藏區補畫（2026-11-12 生成，2026-11-13 組裝）

使用內建 imagegen，`transparent_background=true`，參考圖為原圖右眼的放大檢查裁切 `reports/g2/iris-source-analysis.png`。生成原件保存為 [iris-complete-v1.png](../authoring/shared-face/iris-complete-v1.png)，1282 × 1227；[完整 prompt](iris-completion-prompt.txt) 原樣保存。

完整生成虹膜沒有直接取代角色眼睛。v6 僅以原生 material_crop 擷取生成圖 `[450,165,400,100]` 的上方無高光深色區，補足原本被上睫毛遮住的位置；可見瞳孔與高光取自原圖。這避免生成圖與原圖同時顯示兩個高光。原生遮罩移除原圖烘焙在虹膜上方的黑色睫毛，再與生成深色區合成。

原生工程、方法、輸出與驗證見 [GAZE.md](GAZE.md)。素材只用於獨立視線候選，尚未通過視線質感驗收，未整合主程式。生成與拆件沒有改寫已通過閉眼的 v5 模型。

### neutral_v2 修正紀錄（2026-11-12）

內建 imagegen，transparent_background=true；edit target 為 neutral_v1，另附原始 idle_listen_1 作衣服參考。產物 `authoring/imagegen/neutral_v2.png`，1086 × 1448。多出的口袋已移除，但透明外緣雜點仍存在，**尚未通過邊緣品質驗收**；本次只供本機骨架實驗。See-through 再拆件因公開服務 ZeroGPU 額度不足未執行成功。

完整 prompt：

```text
Use case: precise identity-preserving asset repair for Live2D. Image 1 is the edit target, the neutral separated-arms character. Image 2 is the authoritative original character and clothing reference. Keep image 1's exact canvas framing, separated relaxed arms, all fingers visible, head placement, proportions and cel-shaded illustration style. Only repair these defects: remove the two rectangular jacket pockets because image 2 has NO pockets; match the original plain light-blue jacket and cream edge trim. Clean away every disconnected white, yellow, red, blue and green speck outside the silhouette, especially by hands and elbows; remove thick white fringe. Keep a clean antialiased alpha edge against a fully transparent background, no matte, checkerboard, shadow, border or text. Preserve the existing face, brown bob, earrings, skin and clothing colors, and keep both arms clearly separated from the torso. Do not redesign or add details. Output one character only with transparent background.
```

imagegen 可補畫素材，但不直接產生已綁定的 moc3。生成後仍要檢查 alpha 邊緣、座標、比例、顏色及前後遮擋。以同一張中立基準、同一畫布與肩肘定位點產生差分，避免每個狀態重新生成完整人物造成外觀漂移。

優先順序：

1. 修正 neutral_v1 衣服細節與邊緣；補全手臂遮住的衣身。
2. 分離上臂、前臂、衣袖及手掌，保留關節重疊區。
3. 先做托腮、舉食指及中間姿勢，驗證同一模型的臉／手遮擋與轉場。
4. 補耳旁聆聽、胸前合手、手放胸前與攤掌差分。
5. 補閉眼、嘴內部、上下唇與必要表情；由連續參數控制，避免用整張臉切換。

只有通過同尺寸疊圖、深淺背景與參數極值檢查的部件才進正式模型。草稿與候選不能視為完成七姿勢。
