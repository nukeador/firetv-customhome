# Technical documentation

## Installer details


- Downloads compatible official releases of SmartTube Beta, Stremio for Android TV and Usque when selected. The ZIP includes only the custom launcher and its small SmartTube compatibility bridge; third-party apps are not bundled.
- Offers a reviewed list of telemetry, advertising and Amazon apps to disable. It keeps the core system, remote, keyboard, settings and updates. Removing updated app copies and their data is a separate choice; **deleted data cannot be restored**.
- On the exact tested **Fire TV Stick 4K Max 1st generation, AFTKA/kara, PS7713/5443** firmware, offers a single temporary-root attempt after an explicit confirmation. It downloads the upstream GhostLock binary, applies the included patch, verifies the reconstructed hash and performs the safety probe. Other firmware keeps Amazon Home; the launcher can still be opened as an app.
- Saves backup and recovery information locally. After changing Home, test the physical Home button and restart as instructed to end temporary root. Restoring Amazon Home after a restart can require another explicitly confirmed root attempt.

Usque's VPN status icon indicates any Android VPN. Disconnecting Usque directly requires separately granting the launcher access to notifications. Read [privacy details](../PRIVACY.md) before sharing logs or backups.

## Troubleshooting

- **No connection:** check the IP, network and ADB setting; accept the prompt on the TV. A USB Ethernet adapter may lose power when debugging is enabled. The installer asks separately about it.
- **No recommendations:** open SmartTube Beta once, ensure its channel service is enabled, and return Home. Its published channel can refresh at a different time from SmartTube's own screen.
- **Restore apps:** reopen the installer and select restoration. Keep the backup folder it created. Deleted app data and removed updates are not recovered automatically.
- **Home unchanged:** the firmware may not match the one supported for the temporary-root method. No attempt is made on other builds.

## Building and maintenance

Build on each target OS using Python 3.11, `requirements-build.txt`, `python -m unittest discover -s tests -v`, `python -m PyInstaller --noconfirm installer.spec`, `python smoke.py`, and `python make_release.py`. GitHub Actions builds preview ZIPs for Linux x86-64/ARM64, macOS Apple Silicon, and Windows x86-64, and publishes a prerelease after all builds pass. Windows ARM devices may use x86-64 emulation.

The project is licensed under AGPL-3.0; upstream notices are in [third-party notices](THIRD-PARTY-NOTICES.md). Updates require the same Android signing identity; private signing keys are not distributed. Do not commit ADB keys, device backups, downloaded third-party APKs or signing keys. See [GhostLock provenance](GHOSTLOCK-PROVENANCE.md) for the binary patch, exact hashes and upstream licensing status.
