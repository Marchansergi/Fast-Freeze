# Fast Freeze

Aplicación de escritorio para activar y desactivar **Unified Write Filter (UWF)** («congelar» Windows)
en Windows 11 IoT Enterprise LTSC y otras ediciones Enterprise/Education. Se distribuye como un único
`Fast Freeze.exe`: no hace falta instalar Python.

> ## ⚠ Advertencia
> Con UWF activo, **Windows descarta al reiniciar los cambios hechos en C: durante la sesión protegida**
> (archivos, programas, configuración). Guarde sus datos importantes antes de activar la congelación
> y manténgalos en una unidad no protegida o en red.

## Descargar y usar

1. En GitHub: pestaña **Actions** → última ejecución correcta de «Compilar Fast Freeze» →
   apartado **Artifacts** → **Fast Freeze** (zip). Extraiga `Fast Freeze.exe`.
2. Doble clic. Windows pedirá permiso de administrador (UAC); acéptelo.
3. Pulse **Buscar compatibilidad** para comprobar si el equipo puede usar UWF.
4. Use **Activar congelación y protección** o **Desactivar congelación**, y reinicie Windows cuando
   la aplicación lo indique (nunca reinicia sola).

Si aparece SmartScreen («Windows protegió su PC»), es porque el `.exe` no está firmado digitalmente:
«Más información» → «Ejecutar de todas formas». También puede evitarse antes de abrirlo: clic derecho
en el `.exe` → Propiedades → marcar **Desbloquear** → Aceptar. Ver [Firma digital](#firma-digital).

## La ventana

- **Estado del equipo**: CONGELADO / SIN CONGELAR / DESCONOCIDO, con lo que pasará al reiniciar.
- **Aviso de reinicio** (franja ámbar) cuando hay cambios que se aplicarán al reiniciar.
- **Tarjetas**: Filtro UWF, Protección de C:, Característica UWF, Superposición, Reinicio y
  Compatibilidad. Cada estado lleva texto, icono y color (no depende solo del color).
- **Acciones**: los dos botones principales, *Buscar compatibilidad*, *Actualizar estado* (F5) y
  *Abrir carpeta de registros*.
- **Actividad**: historial con hora de lo que se ha hecho y su resultado.
- Las operaciones se ejecutan en segundo plano: la ventana no se congela y los botones se
  desactivan mientras tanto.

## Buscar compatibilidad

Comprobación **de solo lectura** (no modifica nada). Revisa:

| Comprobación | Qué mira |
|---|---|
| Versión de Windows | Windows 10 u 11 |
| Edición de Windows | Enterprise, Education o IoT Enterprise (Pro y Home no incluyen UWF) |
| Arquitectura | 64 bits (32 bits: aviso, no probado) |
| Privilegios de administrador | Necesarios para activar/desactivar |
| Característica UWF | Instalada, disponible para instalar, pendiente de reinicio o inexistente |
| Herramienta uwfmgr.exe | Presente si la característica está instalada |
| Servicio UWF | Responde a las consultas (si está instalada) |
| Espacio libre en C: | Aviso si hay menos del doble de la reserva de 4096 MB del perfil recomendado |

Resultado global: **COMPATIBLE**, **COMPATIBLE CON AVISOS**, **NO COMPATIBLE** o
**NO SE PUEDE DETERMINAR**. El informe se puede copiar al portapapeles.

## Configuración recomendada (botón «Aplicar configuración recomendada»)

Perfil pensado para usar el equipo con normalidad (copiar archivos grandes, descargar) sin perder
la restauración al reiniciar:

| Ajuste | Valor |
|---|---|
| Overlay | disco (`DISK`) |
| Reserva del overlay | 4096 MB |
| Acceso al espacio libre (free-space passthrough) | activado |
| Persistencia del overlay | desactivada |
| Volumen protegido | C: |
| Restauración al reiniciar | activada (UWF activo y overlay no persistente) |

**Importante:** los 4096 MB son la reserva para gestionar el overlay, no el límite de datos nuevos.
Con el acceso al espacio libre, las escrituras nuevas usan el espacio libre del disco, que **sigue
siendo el límite**; las sobrescrituras y otras operaciones pueden consumir la reserva. No hay
capacidad ilimitada.

El panel muestra cada ajuste en dos columnas: **Ahora** (sesión actual) y **Tras reiniciar**
(próxima sesión). Solo se muestra en verde cuando todo está verificado en ambas.

### Reinicios

- **UWF desactivado** o **UWF activo con overlay ya en disco**: se aplica lo que falte y basta **un
  reinicio**.
- **UWF activo con overlay en RAM**: Windows no permite cambiar el overlay a disco con UWF activo en
  la sesión, así que hay **dos fases**:
  1. *Fase 1*: se programa la desactivación de UWF (la protección de C: se conserva). Tras el
     primer reinicio, Windows arranca **sin la protección habitual de UWF** (sesión de mantenimiento).
  2. *Fase 2*: al abrir la aplicación aparece **«Continuar configuración recomendada»**; configura el
     overlay, vuelve a activar UWF y pide el segundo reinicio.
- Si falta la característica UWF, se instala primero (puede requerir otro reinicio) y luego se
  continúa con el mismo botón.
- Cada vez que hace falta reiniciar se pregunta **«Reiniciar ahora»** o **«Más tarde»**. La aplicación
  nunca reinicia sola; con «Más tarde» el paso queda pendiente y se indica en pantalla.
- Pulsar el botón varias veces es seguro: solo ejecuta lo que falta.

### Cómo se recuerda la fase pendiente

Mientras UWF protege C:, lo que se escribe en el disco o en el Registro se pierde al reiniciar. Por
eso la fase se guarda en **un único valor** del Registro
(`HKLM\SOFTWARE\UWFManager\RecommendedProfilePhase`) y, si se escribe durante una sesión protegida,
se hace persistente solo ese valor con `uwfmgr registry commit`. No se añaden exclusiones de UWF.
Ese valor es solo una pista: la fase se deduce siempre del estado real de UWF, así que aunque se
perdiera, el botón sigue sabiendo qué falta.

### Superposición persistente

Si la sesión actual usa una superposición **persistente**, antes de cambiar nada se pide
confirmación: aplicar el perfil puede descartar los cambios acumulados de sesiones anteriores. Solo
en ese caso se ejecuta `uwfmgr overlay reset-persistentstate ON`.

## Qué hacen los otros botones

- **Activar congelación y protección**: habilita la característica si falta (DISM, sin reiniciar),
  configura superposición `DISK` de 2048 MB si todavía no es de disco (si ya lo es, por ejemplo con
  el perfil recomendado, la conserva), protege `C:` y habilita el filtro. Si UWF está activo y el
  overlay es RAM, se detiene y remite al botón del perfil recomendado. Omite lo ya
  configurado y verifica el estado tras cada paso. Si hay que reiniciar para terminar de instalar
  UWF, se detiene: tras reiniciar, vuelva a pulsar el botón.
- **Desactivar congelación**: tras confirmación, ejecuta `uwfmgr filter disable`. **No** ejecuta
  `volume unprotect`, `reset-settings` ni desinstala nada; la protección de C: queda guardada.

## Estados

| Texto | Significado |
|---|---|
| UWF: ACTIVO / DESACTIVADO | Filtro en la **sesión actual**; entre paréntesis, el valor tras reiniciar si difiere |
| Protección C:: CONFIGURADA | C: está marcada para protección (indica si ya actúa o se aplicará al reiniciar) |
| Característica UWF: INSTALADA / NO INSTALADA / PENDIENTE DE REINICIO | Característica opcional de Windows |
| Reinicio pendiente | Estado actual y configurado para la próxima sesión difieren |
| Posible cambio pendiente de reinicio | No se pudo leer parte del estado; no se puede asegurar |
| Estado desconocido: no se pudo verificar | Dato no disponible; no se inventa |

UWF aplica los cambios de filtro, volúmenes y superposición en el **siguiente arranque**; por eso
hay que reiniciar. Todo el estado se lee de Windows cada vez: no se guarda ningún «congelado» local.

## Estado de verificación (sea consciente antes de usarlo)

- **Documentación de Microsoft: no se pudo consultar** durante el desarrollo (el entorno bloqueaba
  `learn.microsoft.com`). La sintaxis de `uwfmgr`, DISM y las clases WMI (`UWF_Filter`, `UWF_Volume`,
  `UWF_OverlayConfig` en `root\standardcimv2\embedded`) es del enunciado y de conocimiento previo.
- **Nunca se ha probado contra un UWF real.** Las pruebas usan un Windows simulado.
- Sí se comprueba en cada compilación (GitHub Actions, Windows Server, que no tiene UWF): las
  pruebas, la ventana real, la consulta real de PowerShell (solo lectura) y que el `.exe` arranca y
  lleva el icono.
- Suposiciones sin verificar: `overlay set-size` usa **MB**; una unidad sin entrada en `UWF_Volume`
  para una sesión se interpreta como no protegida; la superposición DISK ocupa espacio en C:.
- Perfil recomendado, sin verificar en documentación ni en un equipo real: la sintaxis de
  `overlay set-passthrough`, `set-persistent`, `reset-persistentstate` y `registry commit`; que el
  cambio a DISK exija UWF desactivado en la sesión (se sigue lo indicado en los requisitos); y los
  nombres de las propiedades WMI de passthrough y persistencia. La aplicación busca cualquier
  propiedad de `UWF_OverlayConfig` cuyo nombre contenga «passthrough» o «persist». Si no existe,
  esos ajustes aparecen como **no verificables («?»)** y el perfil nunca se marca en verde. Los nombres
  reales quedan anotados en el registro de la aplicación para poder ajustarlo.

## Desarrollo

```
pip install -r requirements-dev.txt
python -m pytest -q                 # pruebas (las de la ventana se omiten si no hay pantalla)
python -m uwf_manager               # interfaz
python -m uwf_manager --status      # estado en consola (solo lectura)
python -m uwf_manager --compat      # compatibilidad en consola (solo lectura)
build.bat                           # en Windows: pruebas + PyInstaller → "dist\Fast Freeze.exe"
```

Código en `uwf_manager/`: `runner` (procesos, sin shell y con timeout), `errors`, `state` (consulta
CIM por PowerShell `-EncodedCommand`), `commands` (rutas absolutas de System32), `operations`
(activar/desactivar/perfil), `profile` (fases del perfil), `progress` (indicador en el Registro), `compat`,
`presentation`, `controller` (hilo de trabajo), `gui`, `system` (admin/UAC), `logs`, `assets/` (icono).

Registro: `%LOCALAPPDATA%\UWFManager\logs\uwf-manager.log`.

## Limitaciones conocidas

- No cambia a superposición RAM si DISK falla: se detiene y muestra el error.
- Solo reinicia si el usuario pulsa «Reiniciar ahora» (`shutdown /r /t 0`).
- Solo la unidad `C:`.
- El `.exe` no está firmado (aviso de SmartScreen); ver [Firma digital](#firma-digital).
- Los nombres internos conservan «UWFManager» (clave del Registro del progreso y carpeta de
  registros) para no perder el progreso guardado en equipos que ya lo usen.

## Firma digital

La compilación está preparada para firmar `Fast Freeze.exe`, pero **sin un certificado de firma de
código emitido por una autoridad reconocida, el aviso de SmartScreen no desaparece**:

- **Certificado autofirmado** («Fast Freeze» creado por nosotros): Windows no lo reconoce. En otros
  equipos el aviso sigue igual y el editor aparece como desconocido. Solo serviría instalando ese
  certificado como de confianza en cada equipo, y eso tiene un coste de seguridad (quien tenga la
  clave podría firmar cualquier programa que esos equipos aceptarían).
- **Certificado de una autoridad** (Sectigo, DigiCert, SSL.com…) o **Azure Trusted Signing**: de
  pago y con verificación de identidad. Para que el editor aparezca como «Fast Freeze», ese nombre
  debe corresponder a una entidad registrada; para un particular, el certificado muestra su nombre
  legal. Incluso firmado, SmartScreen puede avisar hasta que el programa gane reputación.
- **Antivirus (Microsoft Defender)**: los ejecutables de PyInstaller a veces dan falsos positivos.
  Si ocurre, puede enviarse el archivo a Microsoft para revisión (gratuito):
  https://www.microsoft.com/wdsi/filesubmission

Para firmar automáticamente con un certificado real (.pfx), guárdelo en el repositorio en
**Settings → Secrets and variables → Actions** como `SIGN_PFX_BASE64` (el archivo en Base64) y
`SIGN_PFX_PASSWORD`. La compilación lo usará sola (con sello de tiempo) y mostrará quién firma.
Cada compilación comprueba además el mecanismo de firma con un certificado temporal sobre una copia
desechable, para que esté probado antes de usarlo.
