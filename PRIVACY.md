# Privacy of the distributable project

## Español

- El proyecto y los ZIP no incluyen cuentas, sesiones de Stremio, copias de una TV, claves privadas ADB ni claves privadas de firma Android.
- Cada instalación crea su propia clave ADB y sus copias fuera de esta carpeta. La etiqueta pública de la clave es genérica. Las copias pueden contener ajustes y capturas privadas y no deben publicarse.
- No se copian las preferencias personales ni el orden de otra instalación. Si el launcher ya existe, no se sustituye.
- Se excluyeron del ejecutable los registros de instalación de Python que contenían rutas del ordenador de compilación. Los APK contienen un certificado público de firma, no la clave privada.
- Los análisis del código, APK, ejecutables y ZIP no encontraron el usuario actual, su carpeta personal ni material de claves privadas. Una búsqueda por patrones no demuestra que sea imposible que exista otro identificador.
- La biblioteca criptográfica de macOS conserva rutas genéricas de su propio servidor de integración, ajenas a este ordenador. Se mantienen para no modificar el binario criptográfico de terceros.

## English

- No Fire TV account, Stremio session, device backup, ADB private key or Android signing key is included in the project or ZIPs.
- The installer creates a new ADB key on the user's computer, outside this folder, with a generic public-key label. Its backup folder is also outside the project and is private to that installation.
- Existing launcher settings and saved app order are not copied into a new installation. An existing launcher is not replaced.
- The release executable excludes Python installation records and SBOM metadata that may contain build-machine paths. The launcher and marker APKs have a public Android signing certificate, not the corresponding private key.
- Automated scans of the source, APK contents, executables and ZIPs found no current-user name, current-user home path or private-key material. These pattern scans are useful but cannot prove the absence of every possible identifier.
- The macOS cryptography library contains generic paths from its upstream CI build machine. They are part of the third-party binary, not paths from this computer. They are retained to avoid modifying the cryptographic library.
- Runtime backups contain sensitive device settings and screenshots. They should not be committed, uploaded or shared.
