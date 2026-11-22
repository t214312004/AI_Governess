# 眉尾與髮際接合修正 v8.1

2026-11-14。依使用者指出的左上角眉毛不連續與左右不對稱進行修正；使用者已回覆「好 通過，繼續吧」，本輪眉毛修正通過。已接受的 v5 閉眼、v6 視線、v7 嘴型保持原檔。所有工作在獨立 lab。

74 份接受版備份在 `authoring/checkpoints/brows-v8-1/`，見 `reports/g2/brows-v8-1-accepted.json`。本次確認不擴大為全表情、頭身或手勢驗收。

## 問題與最終修改

畫面左側是角色的右眉 `BrowR`。舊拆件的眉尾包含一小段直立黑色髮際線，隨眉毛移動時形成斷線或突起；共用臉底同處仍有少量眉尾殘影。只刪除黑色碎片會讓說話時的眉尾離開髮際，因此還需要修正局部形變。

最終做法保留同一個臉底、20 個 ArtMesh 和 15 個控制：

- 以原生 `source_paint_eraser` 清理 94 個指定來源像素；以既有乾淨 underpaint 的取樣色，局部修補底圖 143 個指定位置。原始 PNG 不覆寫，修補保存在新的原生工程。
- 在既有右眉 ArtMesh 上加入 27 組 `ParamBrowRY × ParamBrowRAngle × ParamBrowRForm` 條件形變，只移動靠近髮際的頂點並向鄰近頂點平滑過渡。眉尾的來源定位點取 `(384.5, 392.5)`，髮際從既有乾淨底圖取樣；修正目標為髮際內側約 0.25 px，避免露出亮縫。
- 保留眉峰與眉頭、另一側眉毛，以及既有眼睛、嘴型和臉部幾何。沒有新增遮罩圖層，也沒有把整頭或整張眉毛鏡像替換。

曾試過替換來源圖層、加入獨立髮際遮罩，但原生工具會重新計算生成骨架並造成其他眉毛位置偏移，因此未採用。最終採用局部原生繪製與既有 mesh keyforms；已用匯出後的 Core 幾何逐一對照，確認其他部件沒有移位。

## 左右眉毛的校對方式

原圖兩側可見長度與弧度本來就不同，畫面右側更多眉尾被頭髮遮住。因此以相同來源座標校對高度、角度和髮際，而不是強制鏡像。

待機及說話用各自原圖參數；「疑問」「單眼閉合」刻意左右不同，不拿它們作中立對稱判斷。可在 [預覽](http://127.0.0.1:5187/shared-face.html?expression=1) 按「待機」再播放「雙眉慢速檢查」，或展開「與原圖校對」疊圖檢查。慢速檢查可暫停；錄影見 [brow-v8-1.webm](../reports/g2/brow-v8-1.webm)。

## 驗證

`npm.cmd run test:brow` 對高度、角度、眉形各取 −1、−0.5、0、0.5、1，共 125 組：

| 檢查 | 結果 |
|---|---|
| 另一側眉毛與其餘五官的全部頂點，相對原 v8 | 最大差 0 px |
| 拓撲、其他部件透明度與遮罩 | 保持一致 |
| 眉尾距髮際的最大正向間隙 | 0.3093 原圖 px |
| 相對預定接合位置的最大誤差 | 0.5593 原圖 px，測試限值 0.65 px |
| 慢速眉毛暫停 | 通過，停止後參數保持 |
| 模型載入、瀏覽器例外 | 單次載入，無例外 |

原有 22 組參數回歸、63 組眉眼／視線／嘴型組合及音訊疊加也通過。舊幾何回歸明確排除本輪刻意修改的右眉尾，改由上述專用檢查驗證。v7 嘴型的 63 組嘴型、21 組眼部測試仍通過。

最終原生工程重新開啟並另行匯出後，moc3 及三張 atlas 的 hash 均與已測候選一致，見 `reports/g2/brow-roundtrip.json`。錄影可播放、長約 40.8 秒，使用相同候選模型。30 張原圖與 v5／v6／v7 全部驗收備份亦已核對未變。

說話原圖的右眉 ROI 色差由 v8 的 19.1583 變成 19.5681；此輪改善的是錯誤髮絲與動態接合，沒有把色差宣稱為全面改善。另一側眉毛、嘴部指標保持 12.7802、10.1599。右眼 ROI 邊緣包含少量本輪修補的髮際皮膚，指標由 19.8696 變為 19.9353，眼部幾何不變。完整原圖表情仍未驗收。

## 檔案與重建

- 已接受 v7 與前版 v8 不覆寫；前版 v8 模型另存 `models/expression-face-v8/`，現行候選在 `models/expression-face/`。
- 清理後來源工程：`authoring/brow-v8-1/shared-face-rig-v8-1-source.psd2live`。
- 最終可編輯工程：`authoring/brow-v8-1/shared-face-rig-v8-1-brow.psd2live` 及同名 PSD。
- 輪廓分析素材：`authoring/brow-v8-1/BrowR.png`、`brow-tail-mask.svg`；原生 source paint 修改不寫回原圖 PNG。
- `tools/fix-brow-hairline.py` 重建原生局部清理並匯出暫時來源模型；`npm.cmd run prepare:assets` 後，`node tools/fit-brow-tail.mjs` 計算條件形變；最後執行 `tools/rig-brow-hairline.py` 匯出正式候選，再 prepare/build/test。
- 接合曲線：`design/brow-tail-constraints.json`；髮際分析：`reports/g2/brow-hairline-authoring-boundary.json`；測試：`reports/g2/brow-hairline-results.json`；錄影 hash：`reports/g2/brow-recording.json`。

本輪不使用新生成圖像。視覺檢查仍需使用者確認；頭身與手勢，以及其他原圖表情，不在此局部修正完成範圍。
