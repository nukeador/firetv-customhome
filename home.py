"""Home-only root transition for the single documented firmware; never retries."""
import hashlib
import shlex
import time
from pathlib import Path
from policy import matches_identity, matches_sheldon_5746

ROOT_SHA256 = '46804934a67e34f260ee324161ec26288bc95a464fe02cb8dde93feb50d2aec0'
REMOTE = '/data/local/tmp/kara-home-only.arm'
HOME = 'com.gathin.tvhome/.MainActivity'
SHELDON_REMOTE = '/data/local/tmp/sheldon-home-only.arm'
SHELDON_SHA256 = '7db65c5570309b20f6664cf48ed2d141ae9d0a42a2ed35035d79662269d96ff2'


def root_command(device, command):
    if getattr(device, 'root_variant', '') == 'sheldon-5746':
        return device.shell(SHELDON_REMOTE + ' --client ' + shlex.quote(command), timeout=120)
    return device.shell(REMOTE + ' --cmd ' + shlex.quote(command), timeout=120)


def apply(device, props, kernel, machine, root_asset, session, confirm, review_step=None, restore_only=False, on_root=None, maintenance_only=False):
    sheldon = matches_sheldon_5746(props, kernel, machine)
    if not sheldon and not matches_identity(props, kernel, machine):
        raise RuntimeError('Firmware not verified; root is unavailable on this device')
    device.root_variant = 'sheldon-5746' if sheldon else 'kara'
    remote = SHELDON_REMOTE if sheldon else REMOTE
    root_asset = Path(root_asset)
    if hashlib.sha256(root_asset.read_bytes()).hexdigest() != (SHELDON_SHA256 if sheldon else ROOT_SHA256):
        raise RuntimeError('Root helper hash mismatch')
    original_cec = device.shell('settings get secure block_cec_standby').strip()
    if original_cec not in ('0', '1', 'null'):
        raise RuntimeError('Unexpected CEC setting')
    if not confirm:
        return 'skipped'
    if device.shell('cat /sys/devices/system/cpu/online').strip() != '0-3':
        raise RuntimeError('CPU topology differs from the reviewed device')
    existing = root_command(device, '/system/bin/id') if sheldon else ''
    reuse_root = sheldon and 'uid=0' in existing
    expected_selinux = 'Permissive' if reuse_root else 'Enforcing'
    if device.shell('getenforce').strip() != expected_selinux or 'uid=2000' not in device.shell('id'):
        raise RuntimeError('Expected ADB shell and SELinux state were not confirmed')
    launcher_before = device.shell('dumpsys package com.amazon.tv.launcher')
    starter_before = device.shell('dumpsys package com.amazon.firehomestarter')
    if not maintenance_only:
        expected_home = disabled_home_component(launcher_before) if restore_only else enabled_home_component(launcher_before)
        expected_starter = '3' if restore_only else '0'
        if not expected_home or not __import__('re').search(r'User 0:.*\benabled=' + expected_starter + r'\b', starter_before):
            raise RuntimeError('Original Home component or starter state differs; stop')
    if reuse_root:
        remote_hash = device.shell('md5sum ' + remote).split()
        if not remote_hash or remote_hash[0] != hashlib.md5(root_asset.read_bytes()).hexdigest():
            raise RuntimeError('Active root helper does not match the reviewed helper; stop')
        print('Root temporal activo; no se repetirá GhostLock / Reusing active root.', flush=True)
    else:
        device.push(root_asset, remote)
        device.shell('chmod 700 ' + remote)
    probe = device.shell(remote + (' --check-profile' if sheldon else ' --probe'), timeout=120)
    (Path(session) / 'root-probe.txt').write_text(probe, encoding='utf-8')
    if ('target=sheldonp-PS7717.5746-experimental' not in probe if sheldon else 'V2 SAFE PROBE PASS' not in probe):
        raise RuntimeError('Safety probe failed; exploit not started')
    if not reuse_root and 'uid=0' in root_command(device, '/system/bin/id'):
        raise RuntimeError('Root daemon already present; refusing a second exploit')
    log_path = '/data/local/tmp/sheldon-home-only.log' if sheldon else '/data/local/tmp/kara-home-only.log'
    old_log = device.shell('cat ' + log_path + ' 2>/dev/null')
    mutation_started = False
    live_started = False
    try:
        device.shell('settings put secure block_cec_standby 1')
        if device.shell('settings get secure block_cec_standby').strip() != '1':
            raise RuntimeError('CEC guard could not be confirmed; exploit not started')
        live_started = True
        (Path(session) / 'root-attempt.txt').write_text(('Existing root reused.' if reuse_root else 'One live attempt started.') + ' Restart the Fire TV to end temporary root.\n', encoding='utf-8')
        if reuse_root:
            log = old_log
        else:
            if sheldon:
                print('Iniciando GhostLock / Starting GhostLock…', flush=True)
                start_output = device.shell('(nohup ' + remote + ' --tries 1 >>' + log_path + ' 2>&1 </dev/null &); sleep 1', timeout=30)
                (Path(session) / 'root-start.txt').write_text(start_output, encoding='utf-8')
                print('Esperando resultado / Waiting for result…', flush=True)
            else:
                device.shell('nohup ' + remote + ' --live RUN-KARA-PS7713-HOME-ONLY-V2 >/data/local/tmp/kara-home-only-start.log 2>&1 </dev/null; sleep 5', timeout=120)
            deadline = time.monotonic() + (120 if sheldon else 45)
            log = ''
            last_report = time.monotonic()
            while time.monotonic() < deadline:
                log = device.shell('cat ' + log_path, timeout=30)
                new_log = log[len(old_log):] if log.startswith(old_log) else ''
                if sheldon and time.monotonic() - last_report >= 15:
                    print('GhostLock: ' + (new_log.strip().splitlines()[-1][:180] if new_log.strip() else 'esperando registro / waiting for log'), flush=True)
                    last_report = time.monotonic()
                if ('[ROOT] uid=0 daemon' in new_log and '[home-only] OTA untouched' in new_log or 'holding reclaim' in new_log or 'preloaded read slot failed' in new_log or 'profile rejected' in new_log) if sheldon else ('ROOT DAEMON READY' in new_log or 'reclaim preparation failed' in new_log):
                    break
                time.sleep(2)
        (Path(session) / 'root-result.txt').write_text(log, encoding='utf-8')
        if not log.startswith(old_log):
            raise RuntimeError('Root log changed unexpectedly; stop')
        new_log = log if reuse_root else log[len(old_log):]
        if (('[home-only] OTA untouched' not in new_log or '[ROOT] uid=0 daemon' not in new_log) if sheldon else ('HOME_ONLY_POLICY: updater packages/settings/staged files untouched' not in new_log or 'ROOT DAEMON READY' not in new_log)):
            raise RuntimeError('Root was not verified; stop, do not retry automatically')
        if 'uid=0' not in root_command(device, '/system/bin/id'):
            raise RuntimeError('Root identity not confirmed; stop')
        if sheldon and device.shell('getenforce').strip() != 'Permissive':
            raise RuntimeError('Temporary SELinux state was not confirmed; Home was not changed')
        ota = root_command(device, 'if [ -n "$(ls -A /data/ota_package 2>/dev/null)" ] || [ -e /cache/recovery/command ] || [ -e /cache/recovery/block.map ]; then echo PENDING; else echo CLEAR; fi')
        (Path(session) / 'ota-check.txt').write_text(ota, encoding='utf-8')
        if not sheldon and not maintenance_only and ('CLEAR' not in ota or 'PENDING' in ota):
            raise RuntimeError('Pending update state is not clear; Home was not changed')
        if sheldon and ('CLEAR' not in ota or 'PENDING' in ota):
            print('Estado de actualización no confirmado; se conserva y se continúa. / Update state unconfirmed; leaving it untouched and continuing.', flush=True)
        if maintenance_only:
            if on_root is None:
                raise RuntimeError('Maintenance action missing')
            on_root(device)
            return 'maintenance'
        if restore_only:
            restore_home(device, session)
            (Path(session) / 'home-restored.txt').write_text('Amazon Home restored and resolved.\n', encoding='utf-8')
            if review_step:
                review_step('home-restored.png')
            return 'restored'
        (Path(session) / 'root-variant.txt').write_text(device.root_variant, encoding='utf-8')
        journal = Path(session) / 'home-intent.txt'
        journal.write_text('Home transition intended; restore requires temporary root.\n', encoding='utf-8')
        mutation_started = True
        root_command(device, 'runcon u:r:shell:s0 /system/bin/pm disable-user --user 0 com.amazon.firehomestarter')
        disabled = device.shell('pm list packages -d')
        if 'package:com.amazon.firehomestarter' not in disabled.splitlines():
            raise RuntimeError('Starter did not disable; stop and restore Home')
        journal.write_text('Starter disabled; restore requires temporary root.\n', encoding='utf-8')
        if review_step:
            review_step('home-starter.png')
        root_command(device, 'runcon u:r:shell:s0 /system/bin/pm disable --user 0 com.amazon.tv.launcher/.ui.HomeActivity_vNext')
        state = device.shell('dumpsys package com.amazon.tv.launcher')
        if not disabled_home_component(state):
            raise RuntimeError('Home component not verified disabled; stop and restore Home')
        journal.write_text('Starter and Amazon Home component disabled; restore requires temporary root.\n', encoding='utf-8')
        if review_step:
            review_step('home-component.png')
        root_command(device, 'runcon u:r:shell:s0 /system/bin/cmd package set-home-activity --user 0 ' + HOME)
        resolved = device.shell('cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME')
        (Path(session) / 'home-after.txt').write_text(resolved, encoding='utf-8')
        if HOME not in resolved:
            raise RuntimeError('Home resolution not confirmed; stop and restore Home')
        device.shell('input keyevent 3')
        focused = device.shell('dumpsys activity activities')
        if not any(HOME in line for line in focused.splitlines() if 'mFocusedApp' in line or 'topResumedActivity' in line or 'mResumedActivity' in line):
            raise RuntimeError('Focused Home activity could not be verified; stop and restore Home')
        if review_step:
            review_step('home-result.png')
        if on_root is not None:
            try:
                on_root(device)
            except Exception as update_error:
                (Path(session) / 'updates-error.txt').write_text(str(update_error), encoding='utf-8')
                print('No se pudo cambiar las actualizaciones / Could not change updates: ' + str(update_error), flush=True)
        return 'changed'
    except Exception as error:
        if mutation_started and not restore_only:
            try:
                restore_home(device, session)
                (Path(session) / 'home-rollback.txt').write_text('Amazon Home restored and resolved.\n', encoding='utf-8')
            except Exception as rollback_error:
                (Path(session) / 'home-rollback.txt').write_text('Rollback failed: ' + str(rollback_error), encoding='utf-8')
        if live_started:
            raise RuntimeError(str(error) + ' | Root attempt started: restart the Fire TV to end temporary root; do not retry automatically.') from error
        raise
    finally:
        try:
            if original_cec == 'null':
                device.shell('settings delete secure block_cec_standby')
            else:
                device.shell('settings put secure block_cec_standby ' + original_cec)
        except Exception as cleanup_error:
            raise RuntimeError('CEC guard could not be restored; reconnect and restart the Fire TV. Do not retry the exploit automatically.') from cleanup_error


def disabled_home_component(dump):
    import re
    for match in re.finditer(r'(?m)^[ \t]*disabledComponents:[ \t]*\n((?:[ \t]{8,}[^ \t\n][^\n]*\n)+)', dump):
        if 'HomeActivity_vNext' in match.group(1):
            return True
    return False


def enabled_home_component(dump):
    import re
    for match in re.finditer(r'(?m)^[ \t]*enabledComponents:[ \t]*\n((?:[ \t]{8,}[^ \t\n][^\n]*\n)+)', dump):
        if 'HomeActivity_vNext' in match.group(1):
            return True
    return False


def restore_home(device, session):
    variant = Path(session) / 'root-variant.txt'
    if variant.exists():
        device.root_variant = variant.read_text(encoding='utf-8').strip()
    if not (Path(session) / 'home-intent.txt').exists():
        return False
    if 'uid=0' not in root_command(device, '/system/bin/id'):
        raise RuntimeError('Temporary root is not active; Home restoration requires a new authorized root session')
    root_command(device, 'runcon u:r:shell:s0 /system/bin/pm enable --user 0 com.amazon.tv.launcher/.ui.HomeActivity_vNext')
    root_command(device, 'runcon u:r:shell:s0 /system/bin/pm default-state --user 0 com.amazon.firehomestarter')
    root_command(device, 'runcon u:r:shell:s0 /system/bin/cmd package set-home-activity --user 0 com.amazon.tv.launcher/.ui.HomeActivity_vNext')
    if not enabled_home_component(device.shell('dumpsys package com.amazon.tv.launcher')):
        raise RuntimeError('Amazon Home component restoration could not be verified')
    if not __import__('re').search(r'User 0:.*\benabled=0\b', device.shell('dumpsys package com.amazon.firehomestarter')):
        raise RuntimeError('Amazon Home starter restoration could not be verified')
    resolved = device.shell('cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME')
    if 'com.amazon.tv.launcher/.ui.HomeActivity_vNext' not in resolved:
        raise RuntimeError('Amazon Home restoration could not be verified')
    return True
