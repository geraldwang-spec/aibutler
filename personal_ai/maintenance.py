"""Single-process runtime and periodic read-only backup. No inference."""
import os
import threading
from pathlib import Path


def start(app):
    if app.config.get('TESTING'): return
    path=Path(app.instance_path)/'ai-runtime.lock';path.parent.mkdir(parents=True,exist_ok=True)
    handle=path.open('a+b')
    try:
        handle.seek(0)
        if os.name=='nt':
            import msvcrt
            if path.stat().st_size==0:handle.write(b'1');handle.flush()
            handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError as exc:
        handle.close();raise RuntimeError('另一個 AI Butler 實例正在執行，請先關閉它再啟動。') from exc
    app.extensions['ai_runtime_lock']=handle
    interval=int(os.getenv('BACKUP_INTERVAL_SECONDS','3600'))
    if interval<300 or app.config.get('DB_TYPE')!='mariadb' or app.config.get('DB_READ_ONLY'): return
    def work():
        import importlib.util
        tool=Path(__file__).resolve().parents[1]/'tools'/'database_backup.py'
        spec=importlib.util.spec_from_file_location('database_backup',tool)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        while True:
            threading.Event().wait(interval)
            try:
                module.backup()
            except Exception:
                app.logger.exception('定期備份失敗；保留上一份快照。')
    threading.Thread(target=work,name='database-backup',daemon=True).start()
