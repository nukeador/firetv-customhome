import json
import hashlib
import bz2
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import apkverify
import apkmeta
import cleanup
import downloads
import device
import home
import policy
import rootpatch


class FakeDevice:
    def __init__(self, disabled=()):
        self.disabled = set(disabled)
        self.calls = []

    def shell(self, command, timeout=60):
        self.calls.append(command)
        if command == 'pm list packages':
            return 'package:com.amazon.bueller.music\npackage:com.amazon.firebat\n'
        if command == 'pm list packages -d':
            return ''.join('package:' + p + '\n' for p in sorted(self.disabled))
        if command.startswith('pm disable-user --user 0 '):
            self.disabled.add(command.split()[-1])
        if command.startswith('pm enable --user 0 '):
            self.disabled.discard(command.split()[-1])
        return 'ok\n'

    def screenshot(self, target):
        Path(target).write_bytes(b'png')


class Tests(unittest.TestCase):
    def test_reviewed_identity_and_other_device(self):
        p = {'ro.product.model':'AFTKA', 'ro.product.device':'kara', 'ro.build.version.incremental':'0035334210436', 'ro.build.version.sdk':'28', 'ro.product.cpu.abi':'armeabi-v7a'}
        self.assertTrue(policy.matches_identity(p, '4.14.87+', 'armv7l'))
        p['ro.build.version.incremental'] = '9999999999999'
        self.assertFalse(policy.matches_identity(p, '4.14.87+', 'armv7l'))
        with self.assertRaises(RuntimeError):
            home.apply(FakeDevice(), p, '4.14.87+', 'armv7l', 'missing', '.', True)

    def test_forbidden_core_package(self):
        with self.assertRaises(ValueError):
            policy.validate_packages(['com.android.systemui'])

    def test_generated_adb_key_has_generic_label(self):
        with tempfile.TemporaryDirectory() as directory:
            d = device.Device('127.0.0.1', 5555, directory)
            public = (Path(directory) / 'adbkey.pub').read_text()
            self.assertTrue(public.endswith(' firetv-customhome\n'))
            d.close()

    def test_home_component_checks_do_not_match_other_sections(self):
        text = ('      enabledComponents:\n        com.example.Other\n'
                '      disabledComponents:\n        com.amazon.tv.launcher.ui.HomeActivity_vNext\n\n')
        self.assertFalse(home.enabled_home_component(text))
        self.assertTrue(home.disabled_home_component(text))

    def test_disable_and_restore_preserves_previous_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            (path / 'disabled.txt').write_text('package:com.amazon.firebat\n')
            dev = FakeDevice(['com.amazon.firebat'])
            cleanup.disable(dev, ['com.amazon.bueller.music', 'com.amazon.firebat'], path, {'com.amazon.firebat'}, lambda: True)
            self.assertIn('com.amazon.bueller.music', dev.disabled)
            cleanup.restore(dev, path)
            self.assertEqual(dev.disabled, {'com.amazon.firebat'})

    def test_stremio_picks_latest_tv_not_phone_or_beta(self):
        html = b'<a href="https://dl.strem.io/android/v1.9.0-androidTV/com.stremio.one-1.9.0-1-armeabi-v7a.apk">old</a><a href="https://dl.strem.io/android/v1.10.4-androidTV/com.stremio.one-1.10.4-2-armeabi-v7a.apk">new</a><a href="https://dl.strem.io/android/v9.9.9/com.stremio.one-9-armeabi-v7a.apk">phone</a>'
        with patch.object(downloads, 'request', return_value=html):
            self.assertIn('v1.10.4-androidTV', downloads.stremio_url('armeabi-v7a'))

    def test_apk_signer_and_tamper(self):
        apk = Path(__file__).resolve().parents[1] / 'assets' / 'tvhome.apk'
        cert = '0c379f3f3b049fa37be14f1e4045b83728cddaa7976804af787fc4e39030c70d'
        self.assertEqual(apkverify.verify(apk, cert), cert)
        with tempfile.TemporaryDirectory() as temp:
            changed = Path(temp) / 'bad.apk'
            blob = bytearray(apk.read_bytes())
            blob[50] ^= 1
            changed.write_bytes(blob)
            with self.assertRaises(Exception):
                apkverify.verify(changed, cert)

    def test_bundled_apks_target_identity_and_android_8(self):
        assets = Path(__file__).resolve().parents[1] / 'assets'
        self.assertEqual(apkmeta.inspect(assets / 'tvhome.apk')['package'], 'com.gathin.tvhome')
        self.assertEqual(apkmeta.inspect(assets / 'tvhome.apk')['min_sdk'], 26)
        self.assertEqual(apkmeta.inspect(assets / 'smarttube-marker.apk')['package'], 'com.tv.leanback.launcher')

    def test_existing_launcher_and_marker_are_not_replaced(self):
        import importlib
        with patch('builtins.input', return_value='en'):
            app = importlib.import_module('main')
        class ExistingDevice:
            def __init__(self): self.calls = []
            def shell(self, command, timeout=60):
                self.calls.append(command)
                if command == 'pm list packages':
                    return 'package:com.gathin.tvhome\npackage:com.tv.leanback.launcher\n'
                if command.startswith('dumpsys package'):
                    return 'android.permission.READ_TV_LISTINGS: granted=true'
                return ''
            def install(self, *args): raise AssertionError('Existing package must not be replaced')
            def screenshot(self, target): Path(target).write_bytes(b'png')
        with tempfile.TemporaryDirectory() as directory:
            dev = ExistingDevice()
            app.install_launcher(dev, Path(directory), 28, {'armeabi-v7a'})

    def test_latest_matching_release_without_digest_fails_closed(self):
        release = [{'draft':False, 'assets':[{'name':'SmartTube_beta_1_armeabi-v7a.apk', 'digest':None}]}]
        with patch.object(downloads, 'request', return_value=json.dumps(release).encode()):
            with self.assertRaises(ValueError):
                downloads.github_release('yuliskov/SmartTube', 'smarttube', 'armeabi-v7a')

    def test_smarttube_uses_direct_official_download_and_checks_signer(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(downloads, 'request', return_value=b'apk') as request, \
                 patch.object(downloads, 'verify') as verify, \
                 patch.object(downloads, 'github_release', side_effect=AssertionError('API must not be used')):
                path, url, _ = downloads.fetch('smarttube', 'armeabi-v7a', directory)
                self.assertEqual(url, downloads.SMARTTUBE_BETA_URL)
                request.assert_called_once_with(downloads.SMARTTUBE_BETA_URL, 250 * 1024 * 1024, progress=None)
                verify.assert_called_once_with(path, downloads.SMARTTUBE_CERT)

    def test_binary_patch_and_hash(self):
        def n(x):
            return int(x).to_bytes(8, 'little')
        ctrl = bz2.compress(n(3) + n(1) + n(0))
        diff = bz2.compress(bytes([0, 1, 0]))
        extra = bz2.compress(b'!')
        patch_bytes = b'BSDIFF40' + n(len(ctrl)) + n(len(diff)) + n(4) + ctrl + diff + extra
        self.assertEqual(rootpatch.apply_patch(b'abc', patch_bytes), b'acc!')
        with self.assertRaises(ValueError):
            rootpatch.apply_patch(b'abc', b'bad')

    def test_home_only_after_exact_identity_and_proven_root(self):
        class HomeDevice:
            def __init__(self):
                self.calls, self.live, self.starter, self.activity, self.resolved, self.cec = [], False, False, False, False, '0'
            def push(self, source, destination):
                self.calls.append('push')
            def shell(self, cmd, timeout=60):
                self.calls.append(cmd)
                if cmd == 'settings get secure block_cec_standby': return self.cec + '\n'
                if cmd.startswith('settings put secure block_cec_standby '): self.cec = cmd.split()[-1]; return ''
                if cmd == 'cat /sys/devices/system/cpu/online': return '0-3\n'
                if cmd == 'getenforce': return 'Enforcing\n'
                if cmd == 'id': return 'uid=2000(shell)\n'
                if cmd == 'dumpsys package com.amazon.firehomestarter': return 'User 0: installed=true enabled=' + ('3' if self.starter else '0') + '\n'
                if cmd == 'dumpsys package com.amazon.tv.launcher':
                    return ('      disabledComponents:\n' if self.activity else '      enabledComponents:\n') + '        com.amazon.tv.launcher.ui.HomeActivity_vNext\n\n'
                if cmd.endswith(' --probe'): return 'V2 SAFE PROBE PASS\n'
                if '--cmd' in cmd:
                    if '/system/bin/id' in cmd: return 'uid=0(root)' if self.live else 'not running'
                    if 'echo PENDING' in cmd: return 'CLEAR'
                    if 'disable-user' in cmd: self.starter = True
                    if 'pm disable --user' in cmd: self.activity = True
                    if 'pm enable --user' in cmd: self.activity = False
                    if 'pm default-state' in cmd: self.starter = False
                    if 'set-home-activity' in cmd: self.resolved = 'com.amazon.tv.launcher/.ui.HomeActivity_vNext' if 'com.amazon.tv.launcher/' in cmd else home.HOME
                    return 'ok'
                if cmd.startswith('nohup '): self.live = True; return ''
                if cmd.startswith('cat /data/local/tmp/kara-home-only.log'):
                    return ('HOME_ONLY_POLICY: updater packages/settings/staged files untouched\nROOT DAEMON READY\n' if self.live else '')
                if cmd == 'pm list packages -d': return 'package:com.amazon.firehomestarter\n' if self.starter else ''
                if cmd.startswith('cmd package resolve-activity'): return self.resolved or ''
                if cmd == 'dumpsys activity activities': return 'mFocusedApp ' + home.HOME
                return ''
        props = {'ro.product.model':'AFTKA', 'ro.product.device':'kara', 'ro.build.version.incremental':'0035334210436', 'ro.build.version.sdk':'28', 'ro.product.cpu.abi':'armeabi-v7a'}
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / 'helper'
            helper.write_bytes(b'test helper')
            dev = HomeDevice()
            with patch.object(home, 'ROOT_SHA256', hashlib.sha256(b'test helper').hexdigest()):
                self.assertEqual(home.apply(dev, props, '4.14.87+', 'armv7l', helper, directory, True), 'changed')
            self.assertEqual(sum(' --live ' in call for call in dev.calls), 1)
            self.assertTrue((Path(directory) / 'home-intent.txt').exists())
            self.assertTrue(any('settings put secure block_cec_standby 0' == c for c in dev.calls))
            failed = HomeDevice()
            original_shell = failed.shell
            def reject_probe(cmd, timeout=60):
                if cmd.endswith(' --probe'):
                    failed.calls.append(cmd)
                    return 'PROBE FAILED'
                return original_shell(cmd, timeout)
            failed.shell = reject_probe
            with patch.object(home, 'ROOT_SHA256', hashlib.sha256(b'test helper').hexdigest()):
                with self.assertRaises(RuntimeError):
                    home.apply(failed, props, '4.14.87+', 'armv7l', helper, directory, True)
            self.assertFalse(any(' --live ' in call for call in failed.calls))
            pending = HomeDevice()
            original_shell = pending.shell
            def pending_update(cmd, timeout=60):
                if 'echo PENDING' in cmd:
                    pending.calls.append(cmd)
                    return 'PENDING'
                return original_shell(cmd, timeout)
            pending.shell = pending_update
            pending_session = Path(directory) / 'pending'
            pending_session.mkdir()
            with patch.object(home, 'ROOT_SHA256', hashlib.sha256(b'test helper').hexdigest()):
                with self.assertRaises(RuntimeError):
                    home.apply(pending, props, '4.14.87+', 'armv7l', helper, pending_session, True)
            self.assertFalse(any('pm disable-user' in call for call in pending.calls))
            self.assertEqual(pending.cec, '0')
            restored = HomeDevice()
            restored.starter = True
            restored.activity = True
            with patch.object(home, 'ROOT_SHA256', hashlib.sha256(b'test helper').hexdigest()):
                self.assertEqual(home.apply(restored, props, '4.14.87+', 'armv7l', helper, directory, True, restore_only=True), 'restored')
            self.assertFalse(restored.starter)
            self.assertFalse(restored.activity)
            self.assertEqual(restored.resolved, 'com.amazon.tv.launcher/.ui.HomeActivity_vNext')


if __name__ == '__main__':
    unittest.main()
