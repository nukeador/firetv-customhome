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
from policy import APPS, CONTENT, METRICS, matches_identity, parse_getprop

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


def check_apk(path, package, sdk, abis):
    meta = inspect_apk(path)
    if meta['package'] != package or meta['min_sdk'] > sdk:
        raise ValueError('APK package or minimum Android version is incompatible')
    if meta['abis'] and not meta['abis'].intersection(abis):
        raise ValueError('APK native architecture is incompatible')


def install_launcher(device, session, sdk, abis):
    check_apk(asset('tvhome.apk'), 'com.gathin.tvhome', sdk, abis)
    check_apk(asset('smarttube-marker.apk'), 'com.tv.leanback.launcher', sdk, abis)
    installed = packages(device.shell('pm list packages'))
    if 'com.tv.leanback.launcher' in installed:
        print(t('Ya existe un paquete con el identificador del puente; no lo sustituiremos.',
                'A package already uses the bridge ID; it will not be replaced.'))
    else:
        device.install(asset('smarttube-marker.apk'), 'marker')
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


def install_upstream(device, kind, abi, session, sdk, abis):
    print(t('Descargando ', 'Downloading ') + kind + t(' desde su fuente oficial…', ' from its official source…'), flush=True)
    def show_progress(size):
        print(t('Descargados: ', 'Downloaded: ') + str(size // (1024 * 1024)) + ' MB', flush=True)
    path, url, digest = fetch(kind, abi, session / 'downloads', progress=show_progress)
    print(t('Comprobando e instalando ', 'Checking and installing ') + kind + '…', flush=True)
    expected = {'stremio': 'com.stremio.one', 'smarttube': 'org.smarttube.beta', 'usque': 'io.github.georgexie2333.usque'}[kind]
    check_apk(path, expected, sdk, abis)
    (session / (kind + '-download.json')).write_text(json.dumps({'url': url, 'sha256': digest}, indent=2), encoding='utf-8')
    device.install(path, kind)
    path.unlink(missing_ok=True)
    try:
        device.screenshot(session / (kind + '-installed.png'))
    except Exception as error:
        print(t('No se pudo capturar la pantalla: ', 'Could not capture the screen: ') + str(error))
    print(t('Instalada: ', 'Installed: ') + kind)


def select_cleanup(device, props, kernel, machine, session):
    if not matches_identity(props, kernel, machine):
        print(t('La limpieza automática solo está revisada para el firmware AFTKA exacto; se omitirá.',
                'Automatic cleanup is only reviewed for the exact AFTKA firmware; it will be skipped.'))
        return
    chosen = []
    for title_es, title_en, group in (
        ('telemetría y métricas', 'telemetry and metrics', METRICS),
        ('publicidad y servicios de contenido de Amazon', 'Amazon advertising and content services', CONTENT)):
        print('\n' + t(title_es, title_en) + ': ' + ', '.join(group))
        if ask('¿Desactivar estos componentes?', 'Disable these components?'):
            chosen.extend(group)
    for package in APPS:
        label = APP_LABELS[package]
        if ask('¿Desactivar ' + label + '?', 'Disable ' + label + '?'):
            chosen.append(package)
    if chosen:
        before = packages((session / 'disabled.txt').read_text(encoding='utf-8'))
        def next_batch():
            print(t('Se ha guardado una captura en la carpeta de copia; comprueba la pantalla y el mando.',
                    'A screenshot is saved in the backup folder; check the screen and remote.'))
            return ask('¿Continuar con la limpieza?', 'Continue cleanup?', default=True)
        disable(device, chosen, session, before, next_batch)
    if ask('¿Eliminar también actualizaciones y datos de apps de Amazon seleccionadas? Sus datos se perderán.',
           'Also remove updates and data for selected Amazon apps? Their data will be lost.'):
        for package in [p for p in APPS if p in chosen]:
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


def main():
    parser = argparse.ArgumentParser(description='firetv-customhome')
    parser.add_argument('--restore', metavar='BACKUP')
    parser.add_argument('--self-check', action='store_true', help='Check bundled files without connecting to a device')
    args = parser.parse_args()
    if args.self_check:
        apk = asset('tvhome.apk')
        asset('smarttube-marker.apk')
        asset('kara-home-only.bsdiff')
        check_apk(apk, 'com.gathin.tvhome', 28, {'armeabi-v7a'})
        verify_signature(apk, '0c379f3f3b049fa37be14f1e4045b83728cddaa7976804af787fc4e39030c70d')
        print(t('Comprobación local correcta; no se ha conectado a ninguna TV.',
                'Local self-check passed; no TV connection was made.'))
        return
    if not args.restore and ask('¿Quieres restaurar una limpieza anterior?', 'Do you want to restore a previous cleanup?'):
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
                    if not matches_identity(props, kernel, machine):
                        raise RuntimeError('Cannot safely obtain root on this firmware')
                    if not ask('¿Has comprobado que no hay una actualización pendiente y quieres preparar la restauración?',
                               'Have you checked that no update is pending and want to prepare restoration?'):
                        raise RuntimeError('Home restoration cancelled')
                    helper = rootpatch.reconstruct(asset('kara-home-only.bsdiff'), session / 'kara-home-only.arm')
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
        launcher_installed = False
        if sdk >= 26 and ask('¿Instalar el launcher y el puente de SmartTube?', 'Install the launcher and SmartTube bridge?', default=True):
            install_launcher(device, session, sdk, abis)
            launcher_installed = True
        elif sdk < 26:
            print(t('Este Android es anterior a 8.0; el launcher no es compatible.', 'This Android version is older than 8.0; the launcher is incompatible.'))
        if abi in ('armeabi-v7a', 'arm64-v8a', 'x86', 'x86_64'):
            for kind in ('smarttube', 'stremio', 'usque'):
                if ask('¿Descargar e instalar ' + kind + '?', 'Download and install ' + kind + '?', default=True):
                    try:
                        download_abi = 'universal' if kind == 'smarttube' and abi == 'x86_64' else abi
                        install_upstream(device, kind, download_abi, session, sdk, abis)
                    except Exception as error:
                        print(t('No se instaló ', 'Not installed: ') + kind + ': ' + str(error))
        else:
            print(t('Arquitectura no reconocida; se omiten las descargas.', 'Unknown architecture; downloads skipped.'))
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
        select_cleanup(device, props, kernel, machine, session)
        home_changed = False
        current_home = device.shell('cmd package resolve-activity --brief -a android.intent.action.MAIN -c android.intent.category.HOME')
        if home.HOME in current_home:
            print(t('El launcher ya es Home; no se ejecutará root.', 'The launcher is already Home; root will not be run.'))
        elif launcher_installed and matches_identity(props, kernel, machine):
            print(t('Este firmware coincide con el dispositivo probado. El root temporal puede colgar o reiniciar el Fire TV; para restaurar Home después puede ser necesario repetirlo.',
                    'This firmware matches the tested device. Temporary root can freeze or reboot the Fire TV; restoring Home later may require repeating it.'))
            print(t('Comprueba en la TV que el launcher y Ajustes funcionan y que no hay una actualización pendiente de instalar.',
                    'On the TV, check that the launcher and Settings work and no update is waiting to install.'))
            if ask('¿Quieres preparar el cambio del botón Home?', 'Prepare the Home button change?'):
                if not ask('¿Has comprobado el launcher, Ajustes y la ausencia de actualización pendiente?',
                           'Have you checked the launcher, Settings, and that no update is pending?'):
                    raise RuntimeError(t('Cambio de Home cancelado.', 'Home change cancelled.'))
                print(t('Descargando GhostLock y aplicando el parche verificado…', 'Downloading GhostLock and applying the verified patch…'))
                helper = rootpatch.reconstruct(asset('kara-home-only.bsdiff'), session / 'kara-home-only.arm')
                print(t('Un solo intento; no se desactivarán las actualizaciones. Escribe ROOT para aceptar el riesgo.',
                        'One attempt only; updates will not be disabled. Type ROOT to accept the risk.'))
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
                    home_changed = home.apply(device, props, kernel, machine, helper, session, True, review_step) == 'changed'
                    if home_changed:
                        print(t('Comprueba con el botón Home físico desde otra aplicación.', 'Test the physical Home button from another app.'))
                        if not ask('¿Abre el launcher nuevo?', 'Does it open the new launcher?'):
                            home.restore_home(device, session)
                            raise RuntimeError(t('No se confirmó Home; se intentó restaurar Amazon Home.', 'Home was not confirmed; Amazon Home restoration was attempted.'))
                else:
                    print(t('Cambio de Home cancelado.', 'Home change cancelled.'))
        elif not matches_identity(props, kernel, machine):
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
