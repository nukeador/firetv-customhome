"""Explicit, reversible control of Fire OS update packages; never clears update data."""
import json
import re
from pathlib import Path
from device import packages
from home import root_command

OTA = 'com.amazon.device.software.ota'
CANDIDATES = (OTA, 'com.amazon.device.software.ota.override', 'com.amazon.tv.forcedotaupdater.v2')
RESTORE = {0: 'default-state', 1: 'enable', 2: 'disable', 3: 'disable-user', 4: 'disable-until-used'}


def snapshot(device):
    installed = packages(device.shell('pm list packages -u'))
    if OTA not in installed:
        raise RuntimeError('Fire OS update package not found; update settings unchanged')
    disabled = packages(device.shell('pm list packages -d'))
    states = {}
    for package in CANDIDATES:
        if package not in installed:
            continue
        dump = device.shell('dumpsys package ' + package)
        user_line = re.search(r'(?m)^\s*User 0:([^\n]*)', dump)
        if user_line and re.search(r'\binstalled=false\b', user_line.group(1)):
            if package == OTA:
                raise RuntimeError('Fire OS update package is not installed for the current user')
            continue
        match = re.search(r'\benabled=(\d+)', user_line.group(1)) if user_line else None
        if not match or int(match.group(1)) not in RESTORE:
            raise RuntimeError('Could not determine update package state: ' + package)
        states[package] = {'enabled_setting': int(match.group(1)), 'disabled': package in disabled}
    return states


def set_updates(device, session, block):
    if 'uid=0' not in root_command(device, '/system/bin/id'):
        raise RuntimeError('Temporary root is not active; update settings unchanged')
    session = Path(session)
    before = snapshot(device)
    journal = {'operation': 'block' if block else 'enable', 'before': before, 'changed': [], 'status': 'started'}
    path = session / 'updates.json'
    def save():
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(journal, indent=2), encoding='utf-8')
        temp.replace(path)
    save()
    try:
        for package, state in before.items():
            desired_disabled = block
            if state['disabled'] == desired_disabled:
                continue
            # Persist intent before touching the package, so recovery is possible after interruption.
            journal['changed'].append(package)
            save()
            action = 'disable-user' if block else 'enable'
            output = root_command(device, 'runcon u:r:shell:s0 /system/bin/pm ' + action + ' --user 0 ' + package)
            now_disabled = packages(device.shell('pm list packages -d'))
            if (package in now_disabled) != desired_disabled:
                raise RuntimeError('Could not verify update package ' + package + ': ' + output.strip())
            try:
                device.screenshot(session / ('updates-' + str(len(journal['changed'])) + '.png'))
            except Exception as screenshot_error:
                (session / 'updates-screenshot-error.txt').write_text(str(screenshot_error), encoding='utf-8')
        journal['status'] = 'complete'
        save()
        return snapshot(device)
    except Exception:
        errors = []
        for package in reversed(journal['changed']):
            try:
                state = before[package]
                root_command(device, 'runcon u:r:shell:s0 /system/bin/pm ' + RESTORE[state['enabled_setting']] + ' --user 0 ' + package)
                disabled = packages(device.shell('pm list packages -d'))
                if (package in disabled) != state['disabled']:
                    errors.append(package)
            except Exception:
                errors.append(package)
        journal['status'] = 'rollback_failed' if errors else 'rolled_back'
        journal['rollback_errors'] = errors
        save()
        if errors:
            raise RuntimeError('Update setting failed; could not verify rollback for ' + ', '.join(errors))
        raise
