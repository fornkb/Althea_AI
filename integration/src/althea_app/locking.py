"""Nonblocking per-job locks shared by threads and local app processes."""
import threading
from pathlib import Path
from contextlib import contextmanager
from .errors import require,AppError

_guard = threading.Lock()
_locks = {}


@contextmanager
def job_lock(data_dir, mode, job_id):
    # job IDs are generated/validated UUIDs, never input filenames.
    from uuid import UUID
    try:
        UUID(job_id)
    except (ValueError,TypeError,AttributeError) as exc:
        raise AppError('CONTRACT_INVALID','Invalid job identifier.') from exc
    folder = Path(data_dir)/'locks'
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/(mode+'-'+job_id+'.lock')
    with _guard:
        lock = _locks.setdefault(str(path.resolve()),threading.Lock())
    require(lock.acquire(blocking=False),'This job is already running. Wait for it to finish.','JOB_BUSY')
    handle = None
    acquired = False
    try:
        handle = path.open('a+b')
        handle.seek(0,2)
        if handle.tell()==0:
            handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            import os
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            acquired = True
        except OSError as exc:
            raise AppError('JOB_BUSY','This job is already running in another app process.') from exc
        yield
    finally:
        if handle:
            if acquired:
                handle.seek(0)
                if __import__('os').name=='nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
            handle.close()
        lock.release()
