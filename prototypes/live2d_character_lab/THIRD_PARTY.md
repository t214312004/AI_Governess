# 外部工具與素材紀錄

本機下載品置於 Git 忽略的 `vendor/`，生成模型在 `models/`、製作素材在 `authoring/`。未將第三方二進位或樣本打包提交。

| 項目 | 本次版本與用途 | 來源 |
|---|---|---|
| PSD2Live | 3.6.7 Windows x64 portable；獨立 authoring 工具，GPL-3.0 | [release](https://github.com/tsunehimatoi/psd2live/releases/tag/v3.6.7) |
| Cubism SDK for Web | 5-r.5；Core 及 Framework 實際載入與渲染 | [官方下載](https://www.live2d.com/en/sdk/download/web/) |
| PSD2Live tml fixture | tml-1.0.0，SHA-256 `f6c98e308e4419d58328e0ced5b703b4ee0e790424ae503f2b0d6d5ad7620a66`；僅本機相容性測試 | [example release](https://github.com/tsunehimatoi/psd2live-examples/releases/tag/assets-v1) |
| See-through | 公開 Hugging Face demo；resolution=768、seed=42、split=True；服務版本未固定 | [原始專案](https://github.com/shitagaki-lab/see-through) |
| gradio_client | 2.7.2，隔離於 vendor/python，呼叫拆件服務 | [官方原始碼](https://github.com/gradio-app/gradio/tree/main/client/python) |
| imagegen | 內建工具；中立姿勢草稿及修正 | [生成紀錄](design/IMAGEGEN.md) |
| Playwright FFmpeg | Playwright 1.65.0 對應 ffmpeg v1013；僅供本機無聲瀏覽器錄影，附 COPYING.LGPLv2.1 | Playwright CLI 下載至 `.cache/playwright/ffmpeg-1013/`，不隨模型發布 |

SDK 及 PSD2Live 下載檔 hash 固定於 `tools/dependencies.lock.json`，`tools/setup-tools.ps1` 會驗證。npm 版本由 `package-lock.json` 固定。SDK Framework 與 Core 有各自附帶的 Live2D 授權文件，不能因製作工具是開源就把 Core 稱為 MIT 或完全開源；正式發佈前按交付形態檢查官方條款。

See-through 本次將角色圖送到外部服務處理，沒有傳送私人設定、聲音樣本或記憶。保存 PSD 與輸出 hash 作為此次候選基準；同 seed 不保證日後 demo 更新後能重現。測試聲音為本機 Windows System.Speech 新生成，文字在 `tools/demo-speech.txt`。

tml 為上游測試案例，目前不作產品角色、不再分發。正式打包只包含有權使用的愛管家素材及 SDK notices。本機 MCP 使用獨立的 `.cache/rig-store`，連線 token 留在 `.cache`，不寫入 reports。`vendor/mcp_proxy.py` 來自 PSD2Live 同一固定版本。
