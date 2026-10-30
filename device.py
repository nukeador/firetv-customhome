"""One ADB connection, one package-manager command per shell request."""
import base64
import hashlib
import re
import shlex
from pathlib import Path
from adb_shell.adb_device import AdbDeviceTcp
from adb_shell.auth.keygen import keygen
from adb_shell.auth.sign_pythonrsa import PythonRSASigner


def packages(output):
    return set(re.findall(r'^package:([^\r\n]+)', output, re.M))


class Device:
    def __init__(self, host, port, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        key = directory / 'adbkey'
        if not key.exists() and not key.with_suffix('.pub').exists():
            keygen(str(key))
            key.chmod(0o600)
            public_key = Path(str(key) + '.pub')
            public_key.write_text(public_key.read_text().split()[0] + ' firetv-customhome\n', encoding='ascii')
        if not key.exists() or not Path(str(key) + '.pub').exists():
            raise RuntimeError('Incomplete local ADB key pair')
        self.client = AdbDeviceTcp(host, port, default_transport_timeout_s=20)
        self.signer = PythonRSASigner.FromRSAKeyPath(str(key))

    def connect(self):
        if not self.client.connect(rsa_keys=[self.signer], auth_timeout_s=60):
            raise RuntimeError('ADB connection or authorization failed')

    def close(self):
        self.client.close()

    def shell(self, command, timeout=60):
        return self.client.shell(command, transport_timeout_s=timeout, read_timeout_s=timeout).replace('\r\n', '\n')

    def push(self, source, destination):
        source = Path(source)
        data = source.read_bytes()
        if not re.fullmatch(r'/data/local/tmp/[A-Za-z0-9_.-]+', destination):
            raise ValueError('Unsafe destination')
        tmp = destination + '.b64'
        self.shell('printf %s "" > ' + shlex.quote(tmp))
        encoded = base64.b64encode(data).decode('ascii')
        for offset in range(0, len(encoded), 16384):
            self.shell('printf %s ' + shlex.quote(encoded[offset:offset + 16384]) + ' >> ' + shlex.quote(tmp))
            if offset and offset % (1024 * 1024) == 0:
                print('.', end='', flush=True)
        self.shell('base64 -d ' + shlex.quote(tmp) + ' > ' + shlex.quote(destination), timeout=120)
        actual = self.shell('md5sum ' + shlex.quote(destination)).split()
        if not actual or actual[0] != hashlib.md5(data).hexdigest():
            raise RuntimeError('ADB transfer checksum mismatch')
        self.shell('rm -f ' + shlex.quote(tmp))
        print('', flush=True)

    def screenshot(self, target):
        self.shell('screencap -p /data/local/tmp/firetv-setup-shot.png')
        self.client.pull('/data/local/tmp/firetv-setup-shot.png', str(target))
        if not Path(target).stat().st_size:
            raise RuntimeError('Screen capture was empty (protected video may block screenshots)')

    def install(self, source, label):
        remote = '/data/local/tmp/firetv-setup-' + label + '.apk'
        self.push(source, remote)
        result = self.shell('pm install -r ' + shlex.quote(remote), timeout=180)
        if result.strip() != 'Success':
            raise RuntimeError('Installation failed: ' + result.strip())
        self.shell('rm -f ' + shlex.quote(remote))
        return result

    def backup(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        commands = {'packages.txt': 'pm list packages -f', 'disabled.txt': 'pm list packages -d',
                    'getprop.txt': 'getprop', 'settings-system.txt': 'settings list system',
                    'settings-secure.txt': 'settings list secure', 'settings-global.txt': 'settings list global',
                    'home.txt': 'cmd package query-activities -a android.intent.action.MAIN -c android.intent.category.HOME',
                    'launcher-state.txt': 'dumpsys package com.amazon.tv.launcher',
                    'starter-state.txt': 'dumpsys package com.amazon.firehomestarter',
                    'display.txt': 'wm size', 'density.txt': 'wm density',
                    'boot-id.txt': 'cat /proc/sys/kernel/random/boot_id'}
        for filename, command in commands.items():
            (directory / filename).write_text(self.shell(command), encoding='utf-8')
        try:
            self.screenshot(directory / 'before.png')
        except Exception as error:
            (directory / 'screenshot-error.txt').write_text(str(error), encoding='utf-8')
