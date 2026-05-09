# LLM 通訊層（LLM）

這一層負責把同一個上層介面對接到不同的 LLM 後端。

## `base_client.py`

定義所有後端共用的抽象介面：

- `send_message(text)`：回傳逐段文字的 async generator
- `cancel()`：中斷目前請求
- `refresh_session()`：選配實作，不是每個 backend 都支援
- `aclose()`：釋放 subprocess 或背景 task

## `client_factory.py`

根據 `config.json` 的 `llm.active_backend` 建立對應 client。

目前支援：

- `codex_cli`
- `gemini_cli`
- `claude_code`
- `openclaw`

## `semantic_chunker.py`

目前的切句規則如下：

- 只會在指定標點出現時切句
- 預設會搭配 `config.json` 讀入切分標點
- `flush()` 會把 buffer 剩餘內容一次吐出
- `reset()` 只負責清空 buffer，避免跨對話殘留

## `codex_cli_client.py`

- 使用 `codex app-server --listen stdio://`
- 啟動後會先做 `initialize`、`initialized`、`account/read`
- 若 `thread_id` 可恢復，會先嘗試 `thread/resume`，失敗再回退到 `thread/start`
- 每次對話使用 `turn/start`
- 取消時送 `turn/interrupt`
- 會依 `item/started` 的 `phase` 過濾 `commentary`，只把 `final_answer` 或 phase 未知的內容往上層送
- `refresh_session()` 會在既有 app-server 連線上建立新 thread

## `gemini_cli_client.py`

- 使用 `gemini --acp --yolo`
- 建立後會透過 ACP `initialize`、`session/load` 或 `session/new` 建 session
- 若舊 session 無法載入，會自動回退到建立新 session
- 回覆是從 `session/update` 通知中持續收 chunk
- 會暫存「先到、但尚未綁定 future」的 ACP 回應，避免快速回應造成等待卡死
- `cancel()` 會先送 `session/cancel`，再對目前 request 補送 `$/cancelRequest`
- `refresh_session()` 會直接在既有 ACP 連線上建立新 session

目前 Codex 與 Gemini client 都具備背景預熱與長連線刷新能力，只是 Codex 刷新的是 thread，Gemini 刷新的是 session。

## `claude_code_client.py`

- 使用 Claude Code CLI print mode：`claude -p --output-format stream-json --verbose --include-partial-messages`
- 依官方 streaming 文件解析 `stream_event.event.delta.type == "text_delta"`，並保留舊版 top-level `content_block_delta` 相容性
- 會帶入 `project_dir` 作為 subprocess `cwd`
- 預設使用 `permission_mode=bypassPermissions` 與 `tools=default`，讓工具可用性接近 `gemini_cli --yolo`
- 會從 stream event 記住 `session_id`，下一次 request 以 `--resume` 延續上下文
- 遇到 tool/system/retry 類事件時送出 `STREAM_ACTIVITY_KEEPALIVE`，避免上層誤判 first-token timeout
- `refresh_session()` 只會清除 `session_id`。Claude Code `-p` 模式目前沒有 Gemini ACP 那種長連線 `session/new`，所以下一次 request 會建立新 CLI session
- `cancel()` 透過結束 subprocess 完成

## `openclaw_client.py`

- 使用 `httpx.AsyncClient` + `httpx_sse`
- 依 OpenClaw OpenResponses HTTP API 使用 `POST /v1/responses`
- request body 使用 item-based `input`，預設 `model=openclaw`
- `agent_id` 透過 `x-openclaw-agent-id` header 路由，不再使用舊的 `openclaw:<agent_id>` model 字串
- 會保留 `previous_response_id`，讓 OpenClaw 在同一個 user/agent scope 內延續 session
- 監聽 `response.output_text.delta`
- 遇到 `response.in_progress`、`response.output_item.added`、`response.content_part.added` 時送出 `STREAM_ACTIVITY_KEEPALIVE`
- `cancel()` 目前是切換本地 `_cancel_flag`
- `refresh_session()` 會清除 `previous_response_id` 並換新的 stable `user`。OpenResponses 是 HTTP request/response，沒有 Gemini ACP 那種長連線 session refresh
