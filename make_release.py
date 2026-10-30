"""Assemble a platform-specific ZIP without copying developer keys or backups."""
import importlib.metadata
import os
import platform
import shutil
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
system = platform.system().lower()
machine = platform.machine().lower()
if system not in ('darwin', 'linux', 'windows'):
    raise SystemExit('Unsupported build platform')
binary = Path(os.environ.get('FIRETV_BUILD_BINARY') or ROOT / 'dist' / ('firetv-customhome.exe' if system == 'windows' else 'firetv-customhome'))
if not binary.is_file():
    raise SystemExit('Build the executable before packaging')
out = ROOT / 'releases'
out.mkdir(exist_ok=True)
target = out / ('firetv-customhome-' + system + '-' + machine + '.zip')
if target.exists():
    raise SystemExit('Output already exists: ' + str(target))
with tempfile.TemporaryDirectory(prefix='firetv-release-') as temp:
    folder = Path(temp) / 'firetv-customhome'
    folder.mkdir()
    shutil.copy2(binary, folder / binary.name)
    for name in ('README.md', 'LEEME.es.md', 'PRIVACY.md'):
        shutil.copy2(ROOT / name, folder / name)
    (folder / 'docs').mkdir()
    for name in ('GHOSTLOCK-PROVENANCE.md', 'home-only-source.patch'):
        shutil.copy2(ROOT / 'docs' / name, folder / 'docs' / name)
    licenses = folder / 'licenses'
    licenses.mkdir()
    shutil.copy2(ROOT / 'LICENSE', licenses / 'AGPL-3.0.txt')
    shutil.copy2(ROOT / 'docs' / 'THIRD-PARTY-NOTICES.md', licenses / 'third-party-notices.txt')
    shutil.copy2(ROOT / 'launcher' / 'FONT-LICENSE-OFL.txt', licenses / 'outfit-OFL.txt')
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get('Name', 'unknown')
        for item in dist.files or []:
            if Path(str(item)).name.lower().startswith(('license', 'copying', 'notice')):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    dest = licenses / name / Path(str(item)).name
                    dest.parent.mkdir(exist_ok=True)
                    shutil.copy2(source, dest)
    if system == 'windows':
        (folder / 'Start.bat').write_text('@echo off\r\n"%~dp0firetv-customhome.exe"\r\npause\r\n', encoding='utf-8')
    else:
        name = 'Start.command' if system == 'darwin' else 'Start.sh'
        script = folder / name
        script.write_text('#!/bin/sh\ncd "$(dirname "$0")"\nexec ./firetv-customhome\n', encoding='utf-8')
        script.chmod(0o755)
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for item in sorted(folder.rglob('*')):
            if item.is_file():
                archive.write(item, item.relative_to(folder.parent))
print(target)
