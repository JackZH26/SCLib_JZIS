"""Check the opt-in private QEMU export using synthetic bytes on Linux tmpfs."""
import argparse
import ctypes
import errno
import hashlib
import json
import mmap
import os
from pathlib import Path
import random
import subprocess
import tempfile
import time
from contextlib import contextmanager

PAGE = 8192
SIZE = 16 * 2**20


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def resident(view):
    address = ctypes.addressof(ctypes.c_char.from_buffer(view))
    pages = (ctypes.c_ubyte * (len(view) // mmap.PAGESIZE))()
    assert ctypes.CDLL(None).mincore(ctypes.c_void_p(address), ctypes.c_size_t(len(view)), pages) == 0
    return sum(page & 1 for page in pages) * mmap.PAGESIZE


def call(*args):
    return subprocess.run([str(arg) for arg in args], capture_output=True, check=True, timeout=30).stdout


@contextmanager
def export(daemon, packed, target, sealed):
    option = ',sealed=on' if sealed else ''
    proc = subprocess.Popen([
        str(daemon), '--blockdev', 'driver=file,node-name=file,filename=' + str(packed),
        '--blockdev', 'driver=qcow2,node-name=image,file=file', '--export',
        'type=fuse,id=owned,node-name=image,mountpoint=' + str(target)
        + ',growable=off,writable=on,allow-other=on' + option,
    ], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        for _ in range(50):
            if proc.poll() is not None:
                raise RuntimeError(proc.stderr.read().decode()[-500:])
            if target.is_mount():
                break
            time.sleep(0.1)
        assert target.is_mount()
        yield
    finally:
        if proc.poll() is None:
            proc.terminate()
        proc.wait(timeout=8)
        assert not target.is_mount()


def read_pages(handle, positions):
    digest = hashlib.sha256()
    start = time.perf_counter()
    for position in positions:
        data = os.pread(handle.fileno(), PAGE, position * PAGE)
        assert len(data) == PAGE
        digest.update(data)
    return {'sha256': digest.hexdigest(), 'ms': (time.perf_counter() - start) * 1000}


def denied(operation):
    try:
        operation()
    except OSError as error:
        assert error.errno == errno.EROFS, error.errno
    else:
        raise AssertionError('Sealed content mutation was accepted')


def direct_sha(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECT | os.O_NOFOLLOW)
    try:
        digest = hashlib.sha256()
        with mmap.mmap(-1, 128 * 1024) as buffer:
            for offset in range(0, SIZE, len(buffer)):
                assert os.preadv(descriptor, [buffer], offset) == len(buffer)
                digest.update(buffer)
        return digest.hexdigest()
    finally:
        os.close(descriptor)


def main(args):
    assert os.getuid() == 0
    assert call('findmnt', '-nro', 'FSTYPE', '-T', '/dev/shm').strip() == b'tmpfs'
    with tempfile.TemporaryDirectory(dir='/dev/shm', prefix='sclib-sealed-export-') as directory:
        root = Path(directory)
        bind = root / 'private'
        bind.mkdir(mode=0o755)
        bind.chmod(0o755)
        raw, packed, target = root / 'source', root / 'image.qcow2', bind / 'segment'
        generator = random.Random(8121)
        with raw.open('xb') as handle:
            for _ in range(SIZE // PAGE):
                handle.write(generator.randbytes(32) + bytes(1056) + generator.randbytes(PAGE - 1088))
        expected = sha(raw)
        call(args.qemu_img, 'convert', '-m', '1', '-f', 'raw', '-O', 'qcow2', '-c',
             '-o', 'cluster_size=8192,compression_type=zstd', raw, packed)
        target.touch()
        packed_before = sha(packed)
        with export(args.daemon, packed, target, True):
            os.chown(target, 70, 70)
            assert target.stat().st_uid == 70 and target.stat().st_mode & 0o777 == 0o600
            assert direct_sha(target) == expected
            with target.open('r+b', buffering=0) as handle:
                with mmap.mmap(handle.fileno(), SIZE, access=mmap.ACCESS_COPY) as direct_view:
                    direct_cached = resident(direct_view)
                    assert direct_cached == 0
                os.posix_fadvise(handle.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                with mmap.mmap(handle.fileno(), SIZE, access=mmap.ACCESS_COPY) as view:
                    assert resident(view) == 0
                    positions = random.Random(711).sample(range(SIZE // PAGE), 256)
                    cold = read_pages(handle, positions)
                    cached = resident(view)
                    initial_mtime = os.fstat(handle.fileno()).st_mtime_ns
                    time.sleep(1.2)
                    assert os.fstat(handle.fileno()).st_mtime_ns == initial_mtime
                    after_stat = resident(view)
                    with target.open('r+b', buffering=0) as reopened:
                        after_open = resident(view)
                        warm = read_pages(reopened, positions)
                    assert cached > 0 and after_stat == cached and after_open == cached
                    assert cold['sha256'] == warm['sha256']
                denied(lambda: os.pwrite(handle.fileno(), b'changed', 0))
                denied(lambda: os.ftruncate(handle.fileno(), SIZE - PAGE))
                denied(lambda: os.posix_fallocate(handle.fileno(), 0, PAGE))
            assert sha(target) == expected
            command = [
                'docker', 'run', '--rm', '--pull', 'never', '--platform', 'linux/amd64',
                '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges=true', '--user', '70:70',
                '--memory', '32m', '--memory-swap', '32m', '--pids-limit', '16',
                '--mount', f'type=bind,source={bind},target=/cold', '--entrypoint', '/bin/sh',
                args.pg_image, '-ec', 'exec 9<>/cold/segment; sha256sum /cold/segment',
            ]
            assert call(*command).decode().split()[0] == expected
            with target.open('rb') as handle:
                os.posix_fadvise(handle.fileno(), 0, 0, os.POSIX_FADV_DONTNEED)
                with mmap.mmap(handle.fileno(), SIZE, access=mmap.ACCESS_COPY) as view:
                    assert resident(view) == 0
        assert sha(packed) == packed_before
        # The default exporter retains its existing writable behavior.
        with export(args.daemon, packed, target, False), target.open('r+b', buffering=0) as handle:
            value = b'default-write-check'
            assert os.pwrite(handle.fileno(), value, 0) == len(value)
            os.fsync(handle.fileno())
            assert os.pread(handle.fileno(), len(value), 0) == value
        assert sha(raw) == expected
        return {
            'status': 'sealed_export_verified', 'kernel': os.uname().release,
            'synthetic_bytes': SIZE, 'source_sha256': expected,
            'daemon_sha256': sha(args.daemon), 'cold': cold, 'warm_after_refresh_and_reopen': warm,
            'resident_after_cold': cached, 'resident_after_metadata_refresh': after_stat,
            'resident_after_reopen': after_open, 'scoped_eviction_verified': True,
            'default_write_verified': True, 'sealed_write_truncate_allocate_denied': True,
            'signed_pg_uid70_rdwr_and_full_readback': True, 'packed_sealed_bytes_unchanged': True,
            'direct_readback_verified': True,
            'resident_after_direct_readback': direct_cached,
            'owned_exports_released': True, 'real_graph_queries': 0,
        }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--qemu-img', required=True, type=Path)
    parser.add_argument('--daemon', required=True, type=Path)
    parser.add_argument('--pg-image', required=True)
    args = parser.parse_args()
    print(json.dumps(main(args)))
