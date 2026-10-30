"""Change only reviewed packages and journal each intent before changing it."""
import json
import re
from pathlib import Path
from device import packages
from policy import validate_packages


def save_journal(path, journal):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(journal, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


def disable(device, selected, session, original_disabled, confirm_batch, review_dump=None):
    validate_packages(selected)
    session = Path(session)
    journal_path = session / 'changes.json'
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {'intended_disable': [], 'verified_disable': [], 'irreversible': []}
    installed = packages(device.shell('pm list packages'))
    current = packages(device.shell('pm list packages -d'))
    batch_size = 0
    screenshot_number = 0
    refused = []
    changed = 0
    def finish_batch():
        nonlocal batch_size, screenshot_number
        if not batch_size:
            return
        screenshot_number += 1
        try:
            device.screenshot(session / ('cleanup-%02d.png' % screenshot_number))
        except Exception as error:
            (session / ('cleanup-%02d-screenshot-error.txt' % screenshot_number)).write_text(str(error), encoding='utf-8')
        batch_size = 0
        if not confirm_batch():
            raise RuntimeError('Stopped after a cleanup batch at user request')
    for package in selected:
        if package not in installed or package in original_disabled or package in current:
            continue
        dump = device.shell('dumpsys package ' + package)
        (session / (package + '-before.txt')).write_text(dump, encoding='utf-8')
        if review_dump is not None and not review_dump(package, dump):
            continue
        if package not in journal['intended_disable']:
            journal['intended_disable'].append(package)
            save_journal(journal_path, journal)
        result = device.shell('pm disable-user --user 0 ' + package)
        current = packages(device.shell('pm list packages -d'))
        if package not in current:
            refused.append(package)
            journal['intended_disable'].remove(package)
            journal.setdefault('refused', []).append(package)
            save_journal(journal_path, journal)
            print('No se pudo desactivar / Could not disable: ' + package, flush=True)
            if 'SecurityException' in result and 'protected package' not in result.lower():
                raise RuntimeError('Package manager refused this operation: ' + result.strip())
            continue
        changed += 1
        journal['verified_disable'].append(package)
        save_journal(journal_path, journal)
        batch_size += 1
        if batch_size == 3:
            finish_batch()
    finish_batch()
    if refused and not changed:
        raise RuntimeError('Package manager refused all selected packages; no cleanup was applied')
    return journal


def restore(device, session):
    session = Path(session)
    journal = json.loads((session / 'changes.json').read_text(encoding='utf-8'))
    before = packages((session / 'disabled.txt').read_text(encoding='utf-8'))
    items = journal.get('intended_disable', [])
    validate_packages(items)
    for package in items:
        if package in before:
            continue
        device.shell('pm enable --user 0 ' + package)
        if package in packages(device.shell('pm list packages -d')):
            raise RuntimeError('Could not restore ' + package)


def remove_update_and_data(device, package, session):
    from policy import APPS
    if package not in APPS:
        raise ValueError('Package is not a reviewed Amazon app')
    session = Path(session)
    info = device.shell('dumpsys package ' + package)
    block = re.search(r'^  Package \[' + re.escape(package) + r'\].*?(?=^  Package \[|\Z)', info, re.M | re.S)
    flags = re.search(r'^\s+flags=\[(.*?)\]', block.group(0), re.M) if block else None
    if not flags or not {'SYSTEM', 'UPDATED_SYSTEM_APP'} <= set(flags.group(1).split()):
        raise RuntimeError('No updated factory app was verified; nothing removed')
    path = session / 'changes.json'
    journal = json.loads(path.read_text()) if path.exists() else {'intended_disable': [], 'verified_disable': [], 'irreversible': []}
    journal['irreversible'].append({'package': package, 'operation': 'remove_update_and_clear_data', 'status': 'intended'})
    save_journal(path, journal)
    result = device.shell('pm uninstall ' + package)
    if result.strip() != 'Success':
        raise RuntimeError('Uninstall refused: ' + result.strip())
    device.shell('pm disable-user --user 0 ' + package)
    paths = device.shell('pm path ' + package)
    if '/data/app/' in paths or '/system/' not in paths or package not in packages(device.shell('pm list packages -d')):
        raise RuntimeError('Factory copy or disabled state was not verified; stop')
    result = device.shell('pm clear --user 0 ' + package)
    if result.strip() != 'Success':
        raise RuntimeError('Clearing data refused: ' + result.strip())
    journal['irreversible'][-1]['status'] = 'complete'
    save_journal(path, journal)
