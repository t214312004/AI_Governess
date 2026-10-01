# Interactive HTML Apps

這個資料夾會在第一次啟動時複製到 private `agent_workspace/apps/`。放在這裡的
HTML app 可以由愛管家透過 HTML whiteboard 在全螢幕介面內直接開啟。

公開版附有 `html_whiteboard_demo/`，可用來確認 Canvas、JavaScript、鍵盤、
滑鼠／觸控、Web Audio 與 `localStorage` 都能正常運作。對愛管家說：

> 在白板打開 HTML 互動示範。

自己建立遊戲時，請使用獨立子資料夾，並交付一個自包含的 HTML：

```text
apps/
  my_game/
    index.html
```

`index.html` 必須是 UTF-8，並內嵌 CSS、JavaScript 與必要的小型素材，不依賴 CDN、
remote API、build step 或本機絕對路徑。新遊戲要以同一份檔案支援桌面白板與手機：
使用 responsive layout、Pointer Events、畫面觸控控制、safe-area padding，並檢查直向、
橫向與 resize。HTML whiteboard 不提供外部網路存取、登入或付款流程。

完整說明請看 repository 的 `docs/html_whiteboard.md`。
