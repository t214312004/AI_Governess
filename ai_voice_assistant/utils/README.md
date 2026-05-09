# 實用工具層（Utils）

## `logger.py`

目前 `utils` 目錄主要提供共用日誌工具。

- 終端輸出會依環境決定是否使用 `colorlog.ColoredFormatter`
- 預設 console 等級是 `INFO`，檔案等級是 `DEBUG`
- 會同時輸出到終端與每日輪替的檔案日誌
- 預設日誌目錄是 `logs/`
- 預設只保留最近 5 天的檔案日誌
- `get_logger()` 取得的子 logger 會沿用 app logger 設定，不會重複綁 handler
- 可透過環境變數調整 console/file log level、log 目錄、保留天數與是否停用 logging

目前支援的環境變數：

- `AI_GOVERNESS_CONSOLE_LOG_LEVEL`
- `AI_GOVERNESS_FILE_LOG_LEVEL`
- `AI_GOVERNESS_LOG_DIR`
- `AI_GOVERNESS_LOG_RETENTION_DAYS`
- `AI_GOVERNESS_DISABLE_LOGGING`
