"""Run with the existing venv. No production startup or private state imports."""
import bootstrap  # must precede production imports
import argparse
import atexit
import sys
import traceback
from contextlib import ExitStack
from tempfile import TemporaryDirectory
from pathlib import Path
import customtkinter as ctk
from bootstrap import RUNTIME
from main_window import MainWindow

def acquire_instance(runtime=RUNTIME):
    """One preview process owns the demo usage file; stale locks release on exit."""
    import msvcrt
    runtime.mkdir(parents=True,exist_ok=True)
    handle=(runtime/'instance.lock').open('a+b')
    handle.seek(0)
    if not handle.read(1): handle.write(b'0');handle.flush()
    handle.seek(0)
    try: msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
    except OSError:
        handle.close()
        raise RuntimeError('Native Demo 已在執行，請先以 Alt+F4 關閉。')
    atexit.register(handle.close)
    return handle

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--review-tools',action='store_true')
    parser.add_argument('--smoke',action='store_true',help='Render both views without fullscreen/keyboard hooks, then exit.')
    parser.add_argument('--smoke-html',action='store_true',help='Exercise native Edge attach, hide, restore and cleanup.')
    parser.add_argument('--smoke-fullscreen',action='store_true',help='Verify fullscreen bounds with real Windows guards, then exit.')
    args=parser.parse_args()
    args.smoke=args.smoke or args.smoke_html or args.smoke_fullscreen
    ctk.set_appearance_mode('light')
    temporary=TemporaryDirectory(prefix='governess-ui-smoke-') if args.smoke else None
    resources=ExitStack()
    if temporary: resources.callback(temporary.cleanup)
    runtime=Path(temporary.name) if temporary else RUNTIME
    lock=acquire_instance(runtime)
    resources.callback(lock.close)
    app=None
    callback_errors=[]
    callback_diagnostics=[]
    smoke_success=False
    def callback_error(kind,value,tb):
        callback_errors.append(value)
        callback_diagnostics.append(''.join(traceback.format_exception(kind,value,tb)))
        if sys.stderr: traceback.print_exception(kind,value,tb)
        # Any unexpected callback exception is fatal. A partially functioning
        # fullscreen child session must never continue silently after failure.
        app.close()
    try:
        app=MainWindow.__new__(MainWindow)
        app.__init__(review_tools=args.review_tools,smoke=args.smoke and not args.smoke_fullscreen,runtime_path=runtime)
    except Exception:
        if app and hasattr(app,'cleanup_errors'): app.close()
        resources.close()
        raise
    app.report_callback_exception=callback_error
    if args.smoke:
        from domain import SessionConfig
        def require(condition,message):
            if not condition: raise AssertionError(message)
        def check_fullscreen():
            if not args.smoke_fullscreen: return
            host=app._fullscreen_host
            target=host.monitor_bounds()
            require(host.window_bounds()==target,'Fullscreen window does not cover monitor')
            require(host.client_bounds().width==target.width and host.client_bounds().height==target.height,
                    'Fullscreen client does not fill monitor')
            require(bool(app.attributes('-fullscreen')),'Tk fullscreen disabled')
            require(bool(app._keyboard_hook_handle),'Keyboard guard missing')
            require(bool(app._screen_guard_proc),'Screen guard missing')
        def check():
            for step in range(5):
                app.startup.navigate(step);app.update_idletasks()
            settings=app.startup.settings
            app.start_session(SessionConfig('codex_cli','demo-balanced','medium'),settings)
            app.update_idletasks()
            app.show_board('md');app.hide_board();app.restore_board();app.close_board()
            app.controller.enqueue('smoke');app.dispatch()
            app.after(1600,finish)
        def finish():
            nonlocal smoke_success
            check_fullscreen()
            require(app.controller.phase.value=='speaking','Speech phase missing')
            app.toggle_mic()
            require(app.controller.phase.value=='listening','Interrupt did not start capture')
            if args.smoke_html:
                app.show_board('html')
                import time
                deadline=time.monotonic()+18
                cycle=0
                def attached():
                    nonlocal cycle,deadline,smoke_success
                    renderer=app.html_whiteboard_renderer
                    if renderer and renderer.is_attached:
                        check_fullscreen()
                        if cycle==0:
                            app.hide_board()
                            require(app.board_kind=='html' and not app.board_visible,'Hidden HTML state lost')
                            app.restore_board()
                            cycle=1;deadline=time.monotonic()+18
                            app.after(100,attached)
                        elif cycle==1:
                            # Change the available board width after restore.
                            # The cropped browser content must follow its host.
                            app.chat.configure(width=460)
                            app.update_idletasks();app._resize_html_now()
                            cycle=2;deadline=time.monotonic()+18
                            app.after(100,attached)
                        else:
                            app.budget.used=app.budget.limit
                            if app._tick_job: app.after_cancel(app._tick_job)
                            app.tick()
                            require(app.board_kind is None and not app.board_visible,'Expired HTML remained visible')
                            app.show_board('html')
                            require(app.board_kind is None,'Expired HTML reopened')
                            app.show_board('md')
                            require(app.board_kind=='md','Markdown fallback blocked')
                            smoke_success=True
                            app.close()
                            print('Native UI + HTML attach/restore/expiry smoke passed',flush=True)
                    elif time.monotonic()>deadline:
                        detail=renderer.last_error if renderer else app.notice.cget('text')
                        raise AssertionError(f'Native HTML renderer did not attach: {detail or "no diagnostic"}')
                    else: app.after(100,attached)
                app.after(100,attached)
            else:
                smoke_success=True
                app.close()
                print('Native UI smoke passed',flush=True)
        app.after(100,check)
        def watchdog():
            raise TimeoutError('Smoke test exceeded 60 seconds')
        app.after(60000,watchdog)
    try:
        app.mainloop()
    finally:
        app.close()
        resources.close()
    if app.cleanup_errors:
        if sys.stderr: print('Cleanup errors:',app.cleanup_errors,file=sys.stderr)
    if not args.smoke and (callback_errors or app.cleanup_errors):
        diagnostic='\n'.join(callback_diagnostics)+f'\nCleanup errors: {app.cleanup_errors}'
        try:
            (RUNTIME/'last-error.txt').write_text(diagnostic,encoding='utf-8')
        except OSError: pass
        from tkinter import messagebox
        messagebox.showerror('Native Demo','執行失敗，已關閉預覽。請查看 native/.runtime/last-error.txt。')
    return 1 if callback_errors or app.cleanup_errors or (args.smoke and not smoke_success) else 0

if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception:
        # pythonw has no console. Preserve a diagnostic and show a clear failure.
        error=traceback.format_exc()
        if sys.stderr: sys.stderr.write(error)
        try:
            RUNTIME.mkdir(parents=True,exist_ok=True)
            (RUNTIME/'last-error.txt').write_text(error,encoding='utf-8')
        except OSError: pass
        from tkinter import messagebox
        messagebox.showerror('Native Demo','啟動失敗，請查看 native/.runtime/last-error.txt。')
        raise SystemExit(1)
