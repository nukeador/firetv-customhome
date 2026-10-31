#!/usr/bin/env python3
"""Interactive Fire TV installer. Existing application data and dock order are preserved."""
import argparse
import hashlib
import json
import locale
import os
import re
import socket
import sys
import time
from datetime import datetime
from pathlib import Path

from cleanup import disable, remove_update_and_data, restore, save_journal
from apkmeta import inspect as inspect_apk
from apkverify import verify as verify_signature
from device import Device, packages
from downloads import fetch
import home
import rootpatch
import updates
from policy import (APPS, CONTENT, METRICS, SHELDON_METRICS, SHELDON_CONTENT,
                    SHELDON_FACTORY_VERSION, matches_identity, matches_sheldon_5746, parse_getprop)

ASSETS = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'assets'
STATE = Path(os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_STATE_HOME') or Path.home() / '.local' / 'state') / 'firetv-customhome'
APP_LABELS = {'com.amazon.shoptv.client': 'Amazon Shopping', 'com.amazon.shoptv.firetv.client': 'Amazon Shopping (TV)',
              'com.amazon.bueller.photos': 'Amazon Photos', 'com.amazon.bueller.music': 'Amazon Music',
              'com.amazon.gamehub': 'Amazon Games', 'com.amazon.firebat': 'Prime Video'}


def choose_language():
    current = (locale.getlocale()[0] or '').lower()
    default = 'es' if current.startswith('es') else 'en'
    try:
        choice = input('Idioma / Language [es/en] (' + default + '): ').strip().lower()
    except EOFError:
        choice = ''
    return choice if choice in ('es', 'en') else default


LANG = choose_language()


def t(es, en):
    return es if LANG == 'es' else en


def ask(es, en, default=False):
    suffix = ' [s/N]: ' if LANG == 'es' and not default else ' [S/n]: ' if LANG == 'es' else ' [Y/n]: ' if default else ' [y/N]: '
    reply = input(t(es, en) + suffix).strip().lower()
    if not reply:
        return default
    return reply in ('s', 'si', 'sí', 'y', 'yes')


def choose_menu(title, entries):
    print('\n' + title)
    def numbered():
        for i, label in enumerate(entries, 1):
            print(str(i) + '. ' + label)
        while True:
            value = input(t('Número: ', 'Number: ')).strip()
            if value.isdigit() and 1 <= int(value) <= len(entries):
                return int(value) - 1
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        return numbered()
    if os.name == 'nt':
        import msvcrt
        def read_key():
            key = msvcrt.getwch()
            if key in ('\x00', '\xe0'):
                return {'H': 'up', 'P': 'down'}.get(msvcrt.getwch(), '')
            return 'enter' if key in ('\r', '\n') else key
        restore = lambda: None
    else:
        import termios, tty, select
        fd = sys.stdin.fileno()
        original = termios.tcgetattr(fd)
        tty.setcbreak(fd)
        def restore(): termios.tcsetattr(fd, termios.TCSADRAIN, original)
        def read_key():
            key = os.read(fd, 1).decode('ascii', errors='ignore')
            if key == '\x1b' and select.select([sys.stdin], [], [], 0.1)[0]:
                key += os.read(fd, 1).decode('ascii', errors='ignore')
                if select.select([sys.stdin], [], [], 0.1)[0]: key += os.read(fd, 1).decode('ascii', errors='ignore')
                return {'\x1b[A': 'up', '\x1b[B': 'down'}.get(key, '')
            if key == '\x03': raise KeyboardInterrupt
            return 'enter' if key in ('\r', '\n') else key
    selected = 0
    print(t('Usa ↑/↓ y pulsa Intro.', 'Use ↑/↓ and press Enter.'))
    try:
        while True:
            for i, label in enumerate(entries):
                print(('  › ' if i == selected else '    ') + label + '\x1b[K')
            key = read_key()
            if key == 'enter':
                return selected
            if key == 'up': selected = (selected - 1) % len(entries)
            elif key == 'down': selected = (selected + 1) % len(entries)
            elif key.isdigit() and 1 <= int(key) <= len(entries): selected = int(key) - 1
            print('\x1b[' + str(len(entries)) + 'A', end='', flush=True)
    finally:
        restore()


def asset(name):
    manifest = json.loads((ASSETS / 'sha256.json').read_text(encoding='utf-8'))
    path = ASSETS / name
    if hashlib.sha256(path.read_bytes()).hexdigest() != manifest.get(name):
        raise RuntimeError(t('El archivo incluido no supera la comprobación: ', 'Bundled file failed its integrity check: ') + name)
    return path


def connection():
    print(t('En el Fire TV: Ajustes > Mi Fire TV > Opciones para desarrolladores > Depuración ADB. Actívala.',
            'On Fire TV: Settings > My Fire TV > Developer options > ADB debugging. Turn it on.'))
    print(t('En Acerca de > Red encontrarás la dirección IP. El ordenador y el Fire TV deben estar en la misma red.',
            'Find its IP address in About > Network. The computer and Fire TV must be on the same network.'))
    remote = ask('¿Está el Fire TV en otra casa y usarás su dirección Tailscale?',
                 'Is the Fire TV in another home, accessed through its Tailscale address?')
    candidate = ''
    if not remote:
        try:
            candidate = socket.getaddrinfo('firetv.local', 5555, type=socket.SOCK_STREAM)[0][4][0]
            print(t('Dirección detectada: ', 'Detected address: ') + candidate)
        except OSError:
            pass
    while True:
        entered = input(t('IP o nombre del Fire TV', 'Fire TV IP or hostname') + (f' [{candidate}]' if candidate else '') + ': ').strip() or candidate
        if entered and re.fullmatch(r'[A-Za-z0-9.:-]+', entered):
            break
        print(t('Introduce una IP o un nombre válido.', 'Enter a valid IP address or hostname.'))
    port_text = input(t('Puerto ADB [5555]: ', 'ADB port [5555]: ')).strip()
    port = int(port_text or '5555')
    if not 1 <= port <= 65535:
        raise ValueError('Invalid ADB port')
    print(t('Cuando aparezca «¿Permitir depuración USB?» en la TV, acepta con el mando.',
            'When the TV asks “Allow USB debugging?”, accept it with the remote.'))
    return entered, port


def inspect_usb():
    usb = ask('¿Hay accesorios conectados por USB u OTG?', 'Are any USB or OTG accessories connected?')
    wired = ask('¿Usa el Fire TV un adaptador Ethernet USB para conectarse a la red?',
                'Does this Fire TV use a USB Ethernet adapter for its network connection?')
    if usb or wired:
        print(t('La depuración USB puede cortar la alimentación del puerto. No desconectes el adaptador mientras trabajamos.',
                'USB debugging can cut power to the port. Keep the adapter connected during this session.'))
    return wired


def usb_network_check(device, wired):
    if not wired:
        return
    usb = device.shell('dumpsys usb')
    connectivity = device.shell('dumpsys connectivity')
    match = re.search(r'host_connected=(true|false)', usb)
    transports = set(re.findall(r'Transports: ([A-Z]+)', connectivity))
    print('USB host_connected:', match.group(1) if match else 'unknown', '| Transports:', ', '.join(sorted(transports)) or 'unknown')
    if not match or match.group(1) == 'false' or 'ETHERNET' not in transports:
        raise RuntimeError(t('No puedo confirmar el adaptador Ethernet USB: no se harán cambios.',
                             'USB Ethernet is not confirmed: no changes will be made.'))


def read_identity(device):
    props = parse_getprop(device.shell('getprop'))
    kernel = device.shell('uname -r').strip()
    machine = device.shell('uname -m').strip()
    return props, kernel, machine


def show_compatibility(device, props, kernel, machine):
    print(t('Datos de compatibilidad (no modifican la TV):', 'Compatibility information (no TV changes):'))
    for label, value in (
        ('Modelo / Model', props.get('ro.product.model', '?')),
        ('Dispositivo / Device', props.get('ro.product.device', '?')),
        ('Compilacion / Build', props.get('ro.build.version.incremental', '?')),
        ('Firmware', props.get('ro.build.display.id', '?')),
        ('Kernel', kernel), ('Arquitectura / Architecture', machine),
        ('Kernel version', device.shell('cat /proc/version').strip()),
        ('SELinux', device.shell('getenforce').strip()),
    ):
        print(label + ': ' + value)
    if props.get('ro.product.device') == 'sheldonp':
        print(t('Registro del último intento de Home:', 'Last Home attempt log:'))
        result = device.shell('if [ -f /data/local/tmp/sheldon-home-only.log ]; then wc -c /data/local/tmp/sheldon-home-only.log; tail -n 30 /data/local/tmp/sheldon-home-only.log; else echo NO_LOG_FILE; fi', timeout=30).strip()
        print(result or t('Registro vacío.', 'Empty log.'))
        print(t('Disponibilidad de nohup:', 'nohup availability:') + ' ' + (device.shell('command -v nohup || echo NOT_FOUND').strip() or '?'))
        device.root_variant = 'sheldon-5746'
        root_id = home.root_command(device, '/system/bin/id').strip()
        print(t('Root actual:', 'Current root:') + ' ' + (root_id or t('sin respuesta', 'no response')))
        if 'uid=0' in root_id:
            print(t('Estado de actualización, consulta sin cambios:', 'Update status, read-only:'))
            for label, command in (
                ('OTA', 'if [ -d /data/ota_package ]; then ls -la /data/ota_package; else echo NO_OTA_DIR; fi'),
                ('Recovery', 'for p in /cache/recovery/command /cache/recovery/block.map; do if [ -e "$p" ]; then echo "PRESENT $p"; else echo "ABSENT $p"; fi; done'),
                ('Check', 'if [ -n "$(ls -A /data/ota_package 2>/dev/null)" ] || [ -e /cache/recovery/command ] || [ -e /cache/recovery/block.map ]; then echo PENDING; else echo CLEAR; fi'),
            ):
                output = home.root_command(device, command).strip()
                print(label + ': ' + (output or t('sin respuesta', 'no response')))

    print(t('Puedes hacer una foto de esta pantalla. No incluye tu cuenta ni el número de serie.',
            'You can photograph this screen. It does not include your account or serial number.'))


def check_apk(path, package, sdk, abis):
    meta = inspect_apk(path)
    if meta['package'] != package or meta['min_sdk'] > sdk:
        raise ValueError('APK package or minimum Android version is incompatible')
    if meta['abis'] and not meta['abis'].intersection(abis):
        raise ValueError('APK native architecture is incompatible')


def install_launcher(device, session, sdk, abis):
    check_apk(asset('tvhome.apk'), 'com.gathin.tvhome', sdk, abis)
    installed = packages(device.shell('pm list packages'))
    if 'com.gathin.tvhome' in installed:
        print(t('El launcher ya está instalado: conservamos su versión y su orden.',
                'The launcher is already installed: its version and order will be preserved.'))
    else:
        device.install(asset('tvhome.apk'), 'home')
    device.shell('pm grant com.gathin.tvhome android.permission.READ_TV_LISTINGS')
    permissions = device.shell('dumpsys package com.gathin.tvhome')
    if not re.search(r'android\.permission\.READ_TV_LISTINGS:\s*granted=true', permissions):
        print(t('No se ha podido verificar el permiso para recomendaciones de SmartTube.',
                'SmartTube recommendation permission could not be verified.'))
    device.shell('am start -W -n com.gathin.tvhome/.MainActivity')
    try:
        device.screenshot(session / 'launcher.png')
        print(t('Captura del launcher: ', 'Launcher screenshot: ') + str(session / 'launcher.png'))
    except Exception as error:
        print(t('No se pudo capturar la pantalla: ', 'Could not capture the screen: ') + str(error))
    print(t('Abre SmartTube al menos una vez; activa su servicio de canales y vuelve a Home para ver recomendaciones.',
            'Open SmartTube at least once; enable its channel service and return Home to see recommendations.'))
    print(t('El orden existente se conserva. En un launcher nuevo puedes ordenar apps manteniendo OK.',
            'Existing app order is preserved. In a fresh launcher, hold OK to reorder apps.'))


def install_bridge(device, sdk, abis):
    check_apk(asset('smarttube-marker.apk'), 'com.tv.leanback.launcher', sdk, abis)
    installed = packages(device.shell('pm list packages'))
    if 'com.tv.leanback.launcher' in installed:
        print(t('El puente ya está instalado; se conserva.', 'The bridge is already installed; it will be preserved.'))
    else:
        device.install(asset('smarttube-marker.apk'), 'marker')
    if 'com.gathin.tvhome' in installed:
        device.shell('pm grant com.gathin.tvhome android.permission.READ_TV_LISTINGS')
    print(t('El puente puede instalarse antes de SmartTube.', 'The bridge can be installed before SmartTube.'))


def install_upstream(device, kind, abi, session, sdk, abis):
    print(t('Descargando ', 'Downloading ') + kind + t(' desde su fuente oficial…', ' from its official source…'), flush=True)
    def show_progress(size):
        print(t('Descargados: ', 'Downloaded: ') + str(size // (1024 * 1024)) + ' MB', flush=True)
    path, url, digest = fetch(kind, abi, session / 'downloads', progress=show_progress)
    print(t('Comprobando e instalando ', 'Checking and installing ') + kind + '…', flush=True)
    expected = {'stremio': 'com.stremio.one', 'smarttube': 'org.smarttube.beta', 'usque': 'io.github.georgexie2333.usque'}[kind]
    check_apk(path, expected, sdk, abis)
    (session / (kind + '-download.json')).write_text(json.dumps({'url': url, 'sha256': digest}, indent=2), encoding='utf-8')
    print(t('Enviando al Fire TV…', 'Sending to Fire TV…'), flush=True)
    device.install(path, kind)
    path.unlink(missing_ok=True)
    try:
        device.screenshot(session / (kind + '-installed.png'))
    except Exception as error:
        print(t('No se pudo capturar la pantalla: ', 'Could not capture the screen: ') + str(error))
    print(t('Instalada: ', 'Installed: ') + kind)


def select_cleanup(device, props, kernel, machine, session):
    sheldon = matches_sheldon_5746(props, kernel, machine)
    if not sheldon and not matches_identity(props, kernel, machine):
        print(t('Modelo o firmware sin lista de limpieza revisada; se omitirá.',
                'No reviewed cleanup list for this model or firmware; skipping.'))
        return
    installed = packages(device.shell('pm list packages'))
    chosen = []
    keep_voice = sheldon and any(package in installed for package in SHELDON_CONTENT) and ask('¿Usas Alexa o el dictado por voz?', 'Do you use Alexa or voice dictation?', default=True)
    for title_es, title_en, group in (
        ('telemetría y métricas', 'telemetry and metrics', SHELDON_METRICS if sheldon else METRICS),
        ('publicidad y servicios de contenido de Amazon', 'Amazon advertising and content services', SHELDON_CONTENT if sheldon else CONTENT)):
        present = [package for package in group if package in installed and not (sheldon and keep_voice and package in SHELDON_CONTENT)]
        if not present:
            continue
        print('\n' + t(title_es, title_en) + ': ' + ', '.join(present))
        if ask('¿Desactivar estos componentes?', 'Disable these components?'):
            chosen.extend(present)
    for package in APPS:
        if package not in installed:
            continue
        label = APP_LABELS[package]
        if ask('¿Desactivar ' + label + '?', 'Disable ' + label + '?'):
            chosen.append(package)
    if chosen:
        before = packages((session / 'disabled.txt').read_text(encoding='utf-8'))
        def next_batch():
            print(t('Se ha guardado una captura en la carpeta de copia; comprueba la pantalla y el mando.',
                    'A screenshot is saved in the backup folder; check the screen and remote.'))
            return ask('¿Continuar con la limpieza?', 'Continue cleanup?', default=True)
        def review_dump(package, dump):
            if not sheldon:
                return True
            match = re.search(r'(?m)^\s*versionCode=(\d+)', dump)
            expected = SHELDON_FACTORY_VERSION.get(package)
            if not match or expected is None:
                print(t('No se puede identificar la versión de ', 'Cannot identify the version of ') + package + t('; se conserva.', '; keeping it.'))
                return False
            if int(match.group(1)) != expected:
                print(t('Esta aplicación está actualizada y puede tener funciones distintas: ', 'This app is updated and may have different functions: ') + package)
                return ask('¿Desactivarla de todos modos?', 'Disable it anyway?')
            return True
        disable(device, chosen, session, before, next_batch, review_dump=review_dump)
    if chosen and ask('¿Eliminar también actualizaciones y datos de apps de Amazon seleccionadas? Sus datos se perderán.',
           'Also remove updates and data for selected Amazon apps? Their data will be lost.'):
        journal = json.loads((session / 'changes.json').read_text(encoding='utf-8'))
        for package in [p for p in APPS if p in journal.get('verified_disable', [])]:
            if ask('¿Eliminar actualización y datos de ' + APP_LABELS[package] + '?', 'Remove update and data for ' + APP_LABELS[package] + '?'):
                remove_update_and_data(device, package, session)
                try:
                    device.screenshot(session / (package + '-removed.png'))
                except Exception as error:
                    print(str(error))


def finish_adb(device, host, port, wired):
    if ask('¿Cerrar la depuración ADB al terminar?', 'Turn off ADB debugging when finished?'):
        device.shell('settings put global adb_enabled 0')
        device.close()
        print(t('Desactiva también depuración de red/USB y revoca autorizaciones en Ajustes, si aparecen.',
                'Also disable network/USB debugging and revoke authorizations in Settings, if available.'))
        if wired:
            print(t('Desconecta y vuelve a conectar el adaptador Ethernet; confirma que la TV usa Ethernet.',
                    'Unplug and reconnect the Ethernet adapter; confirm the TV is using Ethernet.'))
        try:
            with socket.create_connection((host, port), timeout=3):
                print(t('El puerto ADB aún responde; comprueba los ajustes de la TV.', 'The ADB port still responds; check TV settings.'))
        except ConnectionRefusedError:
            print(t('Puerto ADB cerrado: conexión rechazada.', 'ADB port closed: connection refused.'))
        except OSError:
            print(t('No se pudo confirmar el cierre del puerto desde este ordenador.', 'The port closure could not be confirmed from this computer.'))
    else:
        print(t('ADB se deja activado.', 'ADB debugging remains enabled.'))


def apply_update_choice(device, session, block):
    states = updates.set_updates(device, session, block)
    print(t('Actualizaciones bloqueadas.' if block else 'Actualizaciones activadas.',
            'System updates blocked.' if block else 'System updates enabled.'))
    if block:
        print(t('Una actualización ya descargada puede seguir pendiente; el bloqueo no garantiza que Inicio persista.',
                'An already staged update may remain pending; blocking is not a guarantee that Home persists.'))
    return states


def run_updates_maintenance(device, props, kernel, machine, session, host, port, wired, block=None):
    sheldon = matches_sheldon_5746(props, kernel, machine)
    if not sheldon and not matches_identity(props, kernel, machine):
        raise RuntimeError(t('Este firmware no tiene un método de root revisado.', 'No reviewed root method for this firmware.'))
    current = updates.snapshot(device)
    disabled_count = sum(item['disabled'] for item in current.values())
    status = t('bloqueadas', 'blocked') if disabled_count == len(current) else t('activas', 'enabled') if disabled_count == 0 else t('bloqueo parcial', 'partly blocked')
    print(t('Estado de los servicios de actualización: ', 'Update service state: ') + status)
    if block is None:
        choice = choose_menu(t('Actualizaciones de Fire OS:', 'Fire OS updates:'),
            [t('Bloquear (recomendado para conservar Inicio)', 'Block (recommended to protect Home)'),
             t('Volver a activarlas', 'Enable updates again'), t('Cancelar', 'Cancel')])
        if choice == 2: return
        block = choice == 0
    if all(item['disabled'] == block for item in current.values()):
        print(t('Ya estaban en el estado elegido; no se necesita root.', 'Already in the selected state; root is not needed.'))
        return
    print(t('Bloquearlas también impide recibir correcciones de seguridad; activarlas puede cambiar Inicio.',
            'Blocking also prevents security fixes; enabling updates may change Home.'))
    print(t('Una actualización ya descargada puede seguir pendiente. No se borrarán sus datos.',
            'A staged update may remain pending. Its data will not be deleted.'))
    if not ask('¿Continuar?', 'Continue?'): return
    print(t('Puede ser necesario un intento de root temporal, con riesgo de cuelgue o reinicio.',
            'A temporary root attempt may be needed; it can freeze or reboot the Fire TV.'))
    if input(t('Escribe ROOT para continuar: ', 'Type ROOT to continue: ')).strip() != 'ROOT': return
    helper = (rootpatch.reconstruct_sheldon(asset('sheldonp-5746-home-only.bsdiff'), session / 'sheldon-home-only.arm') if sheldon else rootpatch.reconstruct(asset('kara-home-only.bsdiff'), session / 'kara-home-only.arm'))
    home.apply(device, props, kernel, machine, helper, session, True,
               on_root=lambda rooted: apply_update_choice(rooted, session, block), maintenance_only=True)
    print(t('Reinicia el Fire TV con el mando para cerrar el root temporal.',
            'Restart the Fire TV with the remote to end temporary root.'))
    input(t('Cuando vuelva a Inicio, pulsa Intro para comprobar: ', 'When Home returns, press Enter to verify: '))
    device.close()
    check = Device(host, port, STATE / 'keys')
    try:
        check.connect()
        old_boot = (session / 'boot-id.txt').read_text(encoding='utf-8').strip()
        if old_boot == check.shell('cat /proc/sys/kernel/random/boot_id').strip():
            raise RuntimeError('Reboot was not confirmed')
        if check.shell('getenforce').strip() != 'Enforcing':
            raise RuntimeError('SELinux enforcing state not confirmed after reboot')
        states = updates.snapshot(check)
        if any(item['disabled'] != block for item in states.values()):
            print(t('El estado de las actualizaciones cambió tras reiniciar; revísalo en el menú.',
                    'The update state changed after reboot; check it in the menu.'))
        else:
            print(t('Estado de actualizaciones verificado tras reiniciar.', 'Update state verified after reboot.'))
        try: check.screenshot(session / 'updates-after-reboot.png')
        except Exception as error: print(str(error))
        finish_adb(check, host, port, wired)
    finally:
        check.close()


def main():
    parser = argparse.ArgumentParser(description='firetv-customhome')
    parser.add_argument('--restore', metavar='BACKUP')
    parser.add_argument('--self-check', action='store_true', help='Check bundled files without connecting to a device')
    args = parser.parse_args()
    if args.self_check:
        apk = asset('tvhome.apk')
        asset('smarttube-marker.apk')
        asset('kara-home-only.bsdiff')
        asset('sheldonp-5746-home-only.bsdiff')
        check_apk(apk, 'com.gathin.tvhome', 28, {'armeabi-v7a'})
        verify_signature(apk, '0c379f3f3b049fa37be14f1e4045b83728cddaa7976804af787fc4e39030c70d')
        print(t('Comprobación local correcta; no se ha conectado a ninguna TV.',
                'Local self-check passed; no TV connection was made.'))
        return
    mode = 'restore' if args.restore else ('setup', 'components', 'cleanup', 'home', 'updates', 'restore', 'diagnose', 'quit')[choose_menu(
        t('¿Qué quieres hacer?', 'What would you like to do?'),
        [t('Instalar desde cero o continuar', 'Install or continue setup'),
         t('Instalar solo componentes concretos', 'Install selected components'),
         t('Limpiar aplicaciones de Amazon', 'Clean up Amazon apps'),
         t('Cambiar el botón Inicio', 'Change the Home button'),
         t('Bloquear o activar actualizaciones', 'Block or enable system updates'),
         t('Restaurar una limpieza anterior', 'Restore a previous cleanup'),
         t('Comprobar compatibilidad', 'Check compatibility'), t('Salir', 'Exit')])]
    if mode == 'quit': return
    diagnose = mode == 'diagnose'
    component = None
    if mode == 'components':
        index = choose_menu(t('Elige qué instalar:', 'Choose what to install:'),
            ['Launcher', t('Puente de SmartTube', 'SmartTube bridge'), 'SmartTube Beta', 'Stremio', 'Usque (VPN)', t('Cancelar', 'Cancel')])
        component = ('launcher', 'bridge', 'smarttube', 'stremio', 'usque', None)[index]
        if component is None: return
    usque_only = component == 'usque'
    if mode == 'restore' and not args.restore:
        backups = sorted((STATE / 'backups').glob('*/identity.json'), reverse=True)
        if not backups:
            raise RuntimeError(t('No hay copias guardadas en este ordenador.', 'No backups were found on this computer.'))
        for index, item in enumerate(backups, 1):
            print(str(index) + '. ' + item.parent.name)
        selection = int(input(t('Número de la copia: ', 'Backup number: ')))
        if not 1 <= selection <= len(backups):
            raise ValueError('Invalid selection')
        args.restore = str(backups[selection - 1].parent)
    wired = inspect_usb()
    host, port = connection()
    device = Device(host, port, STATE / 'keys')
    print(t('Conectando… Si la TV solicita autorización, acéptala ahora.', 'Connecting… If prompted on the TV, accept authorization now.'))
    try:
        device.connect()
        usb_network_check(device, wired)
        props, kernel, machine = read_identity(device)
        print(t('Dispositivo: ', 'Device: ') + props.get('ro.product.model', '?') + ' / ' + props.get('ro.build.version.incremental', '?'))
        serial = props.get('ro.serialno', '')
        if diagnose:
            show_compatibility(device, props, kernel, machine)
            input(t('Pulsa Intro para salir: ', 'Press Enter to exit: '))
            return
        if args.restore:
            session = Path(args.restore)
            saved = json.loads((session / 'identity.json').read_text(encoding='utf-8'))
            if not serial or serial in ('unknown', '0123456789ABCDEF') or serial != saved.get('serial'):
                raise RuntimeError(t('La copia no coincide con el dispositivo o falta el número de serie.', 'Backup does not match the device or serial number is unavailable.'))
            restore(device, session)
            if (session / 'home-intent.txt').exists():
                before_restore_boot = device.shell('cat /proc/sys/kernel/random/boot_id').strip()
                try:
                    home.restore_home(device, session)
                except RuntimeError as error:
                    if 'Temporary root is not active' not in str(error):
                        raise
                    print(t('El root temporal ya no está activo. Restaurar Home requiere un nuevo intento, que puede colgar o reiniciar la TV.',
                            'Temporary root is no longer active. Restoring Home needs another attempt, which may freeze or restart the TV.'))
                    sheldon = matches_sheldon_5746(props, kernel, machine)
                    if not sheldon and not matches_identity(props, kernel, machine):
                        raise RuntimeError('Cannot safely obtain root on this firmware')
                    if not ask('¿Has comprobado que no hay una actualización pendiente y quieres preparar la restauración?',
                               'Have you checked that no update is pending and want to prepare restoration?'):
                        raise RuntimeError('Home restoration cancelled')
                    helper = (rootpatch.reconstruct_sheldon(asset('sheldonp-5746-home-only.bsdiff'), session / 'sheldon-home-only.arm') if sheldon else rootpatch.reconstruct(asset('kara-home-only.bsdiff'), session / 'kara-home-only.arm'))
                    print(t('Se hará un único intento. Escribe ROOT para aceptar el riesgo.',
                            'One attempt will be made. Type ROOT to accept the risk.'))
                    if input('ROOT: ').strip() != 'ROOT':
                        raise RuntimeError('Home restoration cancelled')
                    home.apply(device, props, kernel, machine, helper, session, True, restore_only=True)
                print(t('Home de Amazon restaurado. Compruébalo con el mando.', 'Amazon Home restored. Check it with the remote.'))
                device.shell('input keyevent 3')
                try:
                    device.screenshot(session / 'amazon-home-restored.png')
                except Exception as error:
                    print(str(error))
                if not ask('¿El botón Home abre el inicio de Amazon?', 'Does the Home button open Amazon Home?'):
                    raise RuntimeError('Amazon Home was not confirmed by the user')
                print(t('Reinicia el Fire TV con el mando para cerrar el root temporal.',
                        'Restart the Fire TV with the remote to end temporary root.'))
                input(t('Cuando haya reiniciado, pulsa Intro: ', 'After it restarts, press Enter: '))
                device.close()
                device = Device(host, port, STATE / 'keys')
                device.connect()
                after_restore_boot = device.shell('cat /proc/sys/kernel/random/boot_id').strip()
                if not before_restore_boot or not after_restore_boot or before_restore_boot == after_restore_boot:
                    raise RuntimeError('A reboot could not be verified')
                if device.shell('getenforce').strip() != 'Enforcing':
                    raise RuntimeError('SELinux enforcing state was not confirmed after reboot')
                resolved = device.shell('cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME')
                if 'com.amazon.tv.launcher/.ui.HomeActivity_vNext' not in resolved:
                    raise RuntimeError('Amazon Home was not confirmed after reboot')
            print(t('Apps restauradas; los datos borrados no se recuperan.', 'Apps restored; deleted data cannot be recovered.'))
            finish_adb(device, host, port, wired)
            return
        session = STATE / 'backups' / datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        device.backup(session)
        (session / 'identity.json').write_text(json.dumps({'serial': serial, 'model': props.get('ro.product.model'), 'incremental': props.get('ro.build.version.incremental')}, indent=2), encoding='utf-8')
        save_journal(session / 'changes.json', {'intended_disable': [], 'verified_disable': [], 'irreversible': []})
        print(t('Copia privada guardada en: ', 'Private backup saved in: ') + str(session))
        sdk = int(props.get('ro.build.version.sdk', '0'))
        abi = props.get('ro.product.cpu.abi', '')
        abis = {item.strip() for item in props.get('ro.product.cpu.abilist', abi).split(',') if item.strip()}
        if mode == 'updates':
            run_updates_maintenance(device, props, kernel, machine, session, host, port, wired)
            return
        if usque_only:
            if abi not in ('armeabi-v7a', 'arm64-v8a', 'x86', 'x86_64'):
                raise RuntimeError(t('Arquitectura no compatible con Usque.', 'Unsupported Usque architecture.'))
            install_upstream(device, 'usque', abi, session, sdk, abis)
            if 'com.gathin.tvhome' in packages(device.shell('pm list packages')):
                print(t('Para desconectar la VPN desde Home, concede acceso a notificaciones al launcher.',
                        'To disconnect VPN from Home, grant notification access to the launcher.'))
                if ask('¿Conceder acceso a notificaciones?', 'Grant notification access?'):
                    device.shell('cmd notification allow_listener com.gathin.tvhome/.UsqueNotificationListener')
                    listeners = device.shell('settings get secure enabled_notification_listeners')
                    if 'com.gathin.tvhome.UsqueNotificationListener' not in listeners:
                        print(t('No se pudo verificar el permiso.', 'The permission could not be verified.'))
            finish_adb(device, host, port, wired)
            return
        installed = packages(device.shell('pm list packages'))
        status_apps = (('Launcher', 'com.gathin.tvhome'), ('SmartTube bridge', 'com.tv.leanback.launcher'),
                       ('SmartTube Beta', 'org.smarttube.beta'), ('Stremio', 'com.stremio.one'),
                       ('Usque', 'io.github.georgexie2333.usque'))
        print(t('Estado actual; elige los pasos que quieras realizar:', 'Current status; choose the steps to perform:'))
        for label, package in status_apps:
            print('  ' + label + ': ' + (t('instalado', 'installed') if package in installed else t('no instalado', 'not installed')))
        print(t('Puedes repetir el instalador y omitir los pasos ya realizados.',
                'You can run the installer again and skip completed steps.'))
        if sdk >= 26:
            if component == 'launcher' or (mode == 'setup' and ask('¿Instalar o comprobar el launcher?', 'Install or check the launcher?', default='com.gathin.tvhome' not in installed)):
                install_launcher(device, session, sdk, abis)
            if component == 'bridge' or (mode == 'setup' and ask('¿Instalar o comprobar el puente de SmartTube?', 'Install or check the SmartTube bridge?', default='com.tv.leanback.launcher' not in installed)):
                install_bridge(device, sdk, abis)
        else:
            print(t('Este Android es anterior a 8.0; el launcher no es compatible.', 'This Android version is older than 8.0; the launcher is incompatible.'))
        launcher_installed = 'com.gathin.tvhome' in packages(device.shell('pm list packages'))
        if abi in ('armeabi-v7a', 'arm64-v8a', 'x86', 'x86_64'):
            for kind in ('smarttube', 'stremio', 'usque'):
                package = {'smarttube': 'org.smarttube.beta', 'stremio': 'com.stremio.one', 'usque': 'io.github.georgexie2333.usque'}[kind]
                already_installed = package in installed
                question_es = ('¿Actualizar o reinstalar ' if already_installed else '¿Descargar e instalar ') + kind + '?'
                question_en = ('Update or reinstall ' if already_installed else 'Download and install ') + kind + '?'
                if component == kind or (mode == 'setup' and ask(question_es, question_en, default=not already_installed)):
                    try:
                        download_abi = 'universal' if kind == 'smarttube' and abi == 'x86_64' else abi
                        install_upstream(device, kind, download_abi, session, sdk, abis)
                    except Exception as error:
                        print(t('No se instaló ', 'Not installed: ') + kind + ': ' + str(error))
        else:
            print(t('Arquitectura no reconocida; se omiten las descargas.', 'Unknown architecture; downloads skipped.'))
        if mode == 'components':
            finish_adb(device, host, port, wired)
            return
        installed = packages(device.shell('pm list packages'))
        if 'com.gathin.tvhome' in installed and 'io.github.georgexie2333.usque' in installed:
            print(t('El acceso a notificaciones permite desconectar Usque desde Home; Android concede acceso a todas las notificaciones.',
                    'Notification access enables disconnecting Usque from Home; Android grants access to all notifications.'))
            if ask('¿Conceder acceso a notificaciones al launcher?', 'Grant notification access to the launcher?'):
                component = 'com.gathin.tvhome/.UsqueNotificationListener'
                device.shell('cmd notification allow_listener ' + component)
                listeners = device.shell('settings get secure enabled_notification_listeners')
                if 'com.gathin.tvhome.UsqueNotificationListener' not in listeners:
                    print(t('No se pudo verificar el permiso. Configúralo en los ajustes de la TV.',
                            'The permission could not be verified. Configure it in the TV settings.'))
        if mode in ('setup', 'cleanup'):
            select_cleanup(device, props, kernel, machine, session)
        home_changed = False
        supported_home = matches_identity(props, kernel, machine) or matches_sheldon_5746(props, kernel, machine)
        block_updates = False
        if mode in ('setup', 'home') and launcher_installed and supported_home:
            print(t('Recomendado para proteger Inicio: bloquear actualizaciones de Fire OS. No es una garantía y también bloquea correcciones de seguridad.',
                    'Recommended to protect Home: block Fire OS updates. This is not a guarantee and also blocks security fixes.'))
            print(t('Puedes activarlas de nuevo desde el menú. Una actualización ya descargada puede seguir pendiente.',
                    'You can enable them again from the menu. An already staged update may remain pending.'))
            block_updates = ask('¿Bloquear actualizaciones de Fire OS?', 'Block Fire OS updates?')
        current_home = device.shell('cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME')
        if home.HOME in current_home:
            print(t('El launcher ya es Home.', 'The launcher is already Home.'))
            if block_updates:
                run_updates_maintenance(device, props, kernel, machine, session, host, port, wired, block=True)
                return
        elif mode in ('setup', 'home') and launcher_installed and (matches_identity(props, kernel, machine) or matches_sheldon_5746(props, kernel, machine)):
            sheldon = matches_sheldon_5746(props, kernel, machine)
            print(t('Cambio experimental en 5746: no probado en un Fire TV real.' if sheldon else 'Firmware compatible con el perfil revisado.', 'Experimental 5746 change: not tested on a real Fire TV.' if sheldon else 'Firmware matches the reviewed profile.'))
            print(t('El root temporal puede colgar o reiniciar el Fire TV; restaurar Home después puede requerir repetirlo.', 'Temporary root can freeze or reboot the Fire TV; restoring Home later may require repeating it.'))
            print(t('Comprueba en la TV que el launcher y Ajustes funcionan.', 'On the TV, check that the launcher and Settings work.'))
            if ask('¿Quieres preparar el cambio del botón Home?', 'Prepare the Home button change?'):
                if not ask('¿Has comprobado el launcher y Ajustes?', 'Have you checked the launcher and Settings?'):
                    raise RuntimeError(t('Cambio de Home cancelado.', 'Home change cancelled.'))
                print(t('Descargando GhostLock y aplicando el parche verificado…', 'Downloading GhostLock and applying the verified patch…'))
                helper = (rootpatch.reconstruct_sheldon(asset('sheldonp-5746-home-only.bsdiff'), session / 'sheldon-home-only.arm') if sheldon else rootpatch.reconstruct(asset('kara-home-only.bsdiff'), session / 'kara-home-only.arm'))
                print(t('Usará el root activo o hará un solo intento; no desactivará las actualizaciones. Escribe ROOT para confirmar.',
                        'Use existing root or make one attempt; updates will not be disabled. Type ROOT to confirm.'))
                if input('ROOT: ').strip() == 'ROOT':
                    def review_step(name):
                        path = session / name
                        try:
                            device.screenshot(path)
                            print(t('Captura: ', 'Screenshot: ') + str(path))
                        except Exception as error:
                            print(t('Captura no disponible: ', 'Screenshot unavailable: ') + str(error))
                        if not ask('¿Se ve bien la TV y continuamos?', 'Does the TV look OK; continue?', default=True):
                            raise RuntimeError(t('Detenido por el usuario.', 'Stopped by the user.'))
                    callback = (lambda rooted: apply_update_choice(rooted, session, True)) if block_updates else None
                    home_changed = home.apply(device, props, kernel, machine, helper, session, True, review_step, on_root=callback) == 'changed'
                    if home_changed:
                        print(t('Comprueba con el botón Home físico desde otra aplicación.', 'Test the physical Home button from another app.'))
                        if not ask('¿Abre el launcher nuevo?', 'Does it open the new launcher?'):
                            home.restore_home(device, session)
                            raise RuntimeError(t('No se confirmó Home; se intentó restaurar Amazon Home.', 'Home was not confirmed; Amazon Home restoration was attempted.'))
                else:
                    print(t('Cambio de Home cancelado.', 'Home change cancelled.'))
        elif mode == 'home' and not launcher_installed:
            print(t('Instala primero el launcher desde el menú de componentes.', 'Install the launcher first from the components menu.'))
        elif mode in ('setup', 'home') and not matches_identity(props, kernel, machine):
            print(t('Modelo o firmware no verificado: se conserva Home de Amazon.',
                    'Unverified model or firmware: Amazon Home is retained.'))
        journal = json.loads((session / 'changes.json').read_text(encoding='utf-8'))
        reboot_requested = home_changed
        if not home_changed and journal.get('verified_disable'):
            reboot_requested = ask('¿Reiniciar ahora para comprobar que la limpieza persiste?',
                                   'Restart now to check that cleanup persists?', default=True)
        if reboot_requested:
            print(t('Reinicia el Fire TV con el mando. Si se usó root, el reinicio también lo cierra y restaura SELinux.',
                    'Restart the Fire TV with the remote. If root was used, reboot also ends it and restores SELinux.'))
            input(t('Cuando haya reiniciado y aparezca Home, pulsa Intro para verificar: ',
                    'When it has restarted and Home appears, press Enter to verify: '))
            device.close()
            device = Device(host, port, STATE / 'keys')
            device.connect()
            before_boot = (session / 'boot-id.txt').read_text(encoding='utf-8').strip()
            after_boot = device.shell('cat /proc/sys/kernel/random/boot_id').strip()
            if not before_boot or not after_boot or before_boot == after_boot:
                raise RuntimeError('A reboot could not be verified')
            if home_changed and device.shell('getenforce').strip() != 'Enforcing':
                raise RuntimeError('SELinux enforcing state was not confirmed after reboot')
            if home_changed:
                result = device.shell('cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME')
                if home.HOME not in result:
                    raise RuntimeError('Launcher Home was not confirmed after reboot')
                if not ask('Después del reinicio, ¿el botón Home del mando abre el launcher nuevo desde otra app?',
                           'After reboot, does the physical Home button open the new launcher from another app?'):
                    raise RuntimeError('Physical Home button not confirmed after reboot')
            try:
                device.screenshot(session / 'home-after-reboot.png')
            except Exception as error:
                print(str(error))
        elif journal.get('verified_disable'):
            print(t('La persistencia de la limpieza tras reiniciar queda sin verificar.', 'Cleanup persistence after reboot is unverified.'))
        if journal.get('verified_disable'):
            disabled_after = packages(device.shell('pm list packages -d'))
            reenabled = sorted(set(journal['verified_disable']) - disabled_after)
            if reenabled:
                (session / 're-enabled-after-check.txt').write_text('\n'.join(reenabled) + '\n', encoding='utf-8')
                print(t('Estos paquetes se han vuelto a activar: ', 'These packages became enabled again: ') + ', '.join(reenabled))
        print(t('Para restaurar la limpieza, ejecuta este programa con --restore y la ruta de la copia.',
                'To restore cleanup, run this program with --restore and the backup folder path.'))
        print(t('No compartas la copia: contiene información privada del Fire TV.',
                'Do not share the backup: it contains private Fire TV information.'))
        finish_adb(device, host, port, wired)
    finally:
        device.close()


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print('\n' + t('Operación interrumpida; conserva la copia y el registro.', 'Interrupted; keep the backup and journal.'))
        sys.exit(1)
    except Exception as error:
        print(t('Se ha detenido: ', 'Stopped: ') + str(error), file=sys.stderr)
        sys.exit(1)
