"""Application-owned capability hint, independent of old private AGENTS files."""
from pathlib import Path
import sys


def music_context(manager,settings,board):
    if manager is None:
        return ''
    from tools.music_tool import capabilities
    from core.music_catalog import catalog
    app=Path(__file__).resolve().parents[1]
    python=app/'venv/Scripts/python.exe'
    if not python.is_file():
        python=Path(sys.executable)
    backend=settings.get('llm',{}).get('active_backend','')
    workspace=Path(settings.get('llm',{}).get(backend,{}).get('project_dir','agent_workspace'))
    if not workspace.is_absolute():
        workspace=app/workspace
    payloads=(workspace/'tool_payloads/music').resolve()
    payloads.mkdir(parents=True,exist_ok=True)
    quote=lambda p:"'"+str(p).replace("'","''")+"'"
    cap=capabilities(manager,settings,board)
    return (
        f"app 音樂工具 v1：music_available={cap['music_available']}，player_available={cap['player_available']}，"
        "所有新音樂固定 lyria-3.5。官方音樂播放器不限 HTML 時間，一般 HTML 遊戲限制不變。"
        "這是 app 提供的音樂專用入口，補充舊 TOOLS/AGENTS 的一般白板入口規則；不需改寫私人指引。\n"
        f"PowerShell 入口：& {quote(python)} {quote(app/'tools/music_tool.py')} <command>。"
        f"完整指南：{app/'tools/music/USAGE.md'}；payload 目錄：{payloads}（UTF-8 JSON）。\n"
        "先 capabilities／styles；使用者要求創作才 generate --payload，保留 request_id，取得 job_id，"
        "用 job-status --job-id 查詢；completed 有 track_id 才能說已完成。只要求播放先 list，不擅自付費重生成。"
        "用 show-player --track-id 開官方播放器，再 player-status 取 content_id／revision；"
        "player-control --payload 帶 expected_revision，可 play/pause/next/previous/seek/set-volume/set-repeat/set-filter。"
        "accepted 只是排隊，用 player-status --command-id 核對 applied ack；needs_user_gesture 時請按一次播放。"
        "busy 表示前一指令尚未套用，先查狀態，不大量重送；UI 狀態改變會讓舊 revision 過期。"
        "renderer_unavailable、過時狀態或未知遠端結果要說明，不假稱已播放、不自動重試付費。"
        "既有曲庫可在沒有 API key 時播放。不要讀取或輸出 key、直接改 SQLite 或白板 JSON。\n"
        "使用者要求刪歌時先 list 確認 track_id，再 delete --track-id 移到回收區；trash 查詢、restore --track-id 復原，不需付費重生成。只刪使用者指定的歌曲，不自行清理曲庫。\n"
        "12 種大風格（可多選）："+'；'.join(s['id']+'='+s['zh']+'/'+s['en'] for s in catalog()['styles'])+
        "。空曲庫也提供全部風格；細節放 style_notes。list --genre-id 可重複傳入，--genre-match any/all；結果歌曲不重複。"
    )
