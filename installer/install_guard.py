# SPDX-License-Identifier: MIT
"""Installer-only check: never update/remove PuryF while its desktop is open."""
import os
from pathlib import Path
import sys

def main():
    root = Path(os.environ['LOCALAPPDATA']) / 'PuryF'
    paths=[root/folder/'instance.lock' for folder in ('Explorer','Conversion')]
    paths.extend((root/'IntegrationHosts').glob('*/instance.lock'))
    for path in paths:
        if not path.exists():
            continue
        import msvcrt
        try:
            with path.open('r+b') as stream:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            print('Close PuryF desktop, CLI jobs and MCP/API hosts before changing the installation.', flush=True)
            return 5
    return 0

if __name__ == '__main__':
    sys.exit(main())
