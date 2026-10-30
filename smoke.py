"""Exercise the frozen binary without contacting a device."""
import os
import subprocess
from pathlib import Path

binary = Path(os.environ.get('FIRETV_BUILD_BINARY') or Path('dist') / ('firetv-customhome.exe' if os.name == 'nt' else 'firetv-customhome'))
run = subprocess.run([str(binary.resolve()), '--self-check'], input='en\n', text=True,
                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=45)
if run.returncode or 'Local self-check passed' not in run.stdout:
    raise SystemExit('Frozen executable self-check failed: ' + run.stdout + run.stderr)
print('Frozen executable self-check passed')
