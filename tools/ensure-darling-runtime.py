#!/usr/bin/env python3
"""Clear a dead Darling server's stale PID marker, and stale shared buffers once no server runs."""
import os
from pathlib import Path
import sys
import time
def recover_marker(prefix):
    marker = prefix / '.init.pid'
    try:
        pid = int(marker.read_text().strip())
    except (OSError, ValueError):
        pid = 0
    if pid > 0:
        status = Path('/proc') / str(pid) / 'status'
        try:
            state = next(line.split()[1] for line in status.read_text().splitlines() if line.startswith('State:'))
            dead = state == 'Z'
        except FileNotFoundError:
            dead = True
        except (OSError, StopIteration):
            dead = False
        if dead:
            os.replace(marker, prefix / f'.init.pid.stale-{pid}-{time.time_ns()}')
            print(f'Recovered stale Darling server marker for PID {pid}', flush=True)

def any_server_running(proc_root=Path('/proc')):
    """True if any darlingserver runs, for any prefix: /dev/shm buffers are not per prefix."""
    for proc in proc_root.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if (proc / 'comm').read_text().strip() == 'darlingserver':
                return True
        except PermissionError:
            # A hidden process might be a server; shared buffers are global, so fail closed.
            return True
        except OSError:
            pass
    return False

def stop_orphaned_launchd(proc_root=Path('/proc')):
    """Do not signal launchd: its guest name/UID cannot prove prefix ownership."""
    # Keep the entry point safe for direct callers as well as main(). No process
    # scan, server absence, or orphan-looking name proves the original namespace.
    print('Automatic launchd cleanup disabled: prefix ownership cannot be proved. '
          'If setup is blocked by a leftover process, use manual shutdown from its '
          'original Darling namespace; do not kill processes by name.',
          file=sys.stderr, flush=True)

def stop_riot_crashpad(proc_root=Path('/proc')):
    """Do not signal crashpad: a Riot/League bundle path is not ownership proof."""
    print('Automatic Riot/League crashpad cleanup disabled: prefix ownership cannot '
          'be proved. If a leftover handler blocks startup, use manual shutdown '
          'from its original Darling namespace; unrelated prefixes are left alone.',
          file=sys.stderr, flush=True)

def remove_owned(paths):
    uid = os.getuid()
    for path in paths:
        try:
            if path.is_file() and path.stat().st_uid == uid:
                path.unlink()
        except OSError:
            pass

def main():
    prefix = Path(os.environ.get('DPREFIX', str(Path.home() / '.darling')))
    recover_marker(prefix)
    # Frame and present buffers left by a killed session confuse the next one's publishers.
    if not any_server_running():
        stop_orphaned_launchd()
        stop_riot_crashpad()
        remove_owned((prefix / 'private/tmp').glob('.com.riotgames.*'))
        remove_owned(Path('/dev/shm').glob('darling-*'))


if __name__ == '__main__':
    main()
