"""One shared two-worker provider round for extraction or source auditing."""
from contextlib import contextmanager
import fcntl
from pathlib import Path


@contextmanager
def provider_round(root):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    with (root/'.production90-provider-round.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('production90_provider_round_already_running') from None
        yield
