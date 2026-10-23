# UWF Manager

Aplicación de escritorio para activar y desactivar **Unified Write Filter (UWF)** («congelar» Windows)
en Windows 11 IoT Enterprise LTSC y otras ediciones Enterprise/Education. Se distribuye como un único
`UWFManager.exe`: no hace falta instalar Python.

> ## ⚠ Advertencia
> Con UWF activo, **Windows descarta al reiniciar los cambios hechos en C: durante la sesión protegida**
> (archivos, programas, configuración). Guarde sus datos importantes antes de activar la congelación
> y manténgalos en una unidad no protegida o en red.

## Descargar y usar

1. En GitHub: pestaña **Actions** → última ejecución correcta de «Compilar UWFManager.exe» →
   apartado **Artifacts** → **UWFManager** (zip). Extraiga `UWFManager.exe`.
2. Doble clic. Windows pedirá permiso de administrador (UAC); acéptelo.
3. Pulse **Buscar compatibilidad** para comprobar si el equipo puede usar UWF.
4. Use **Activar congelación y protección** o **Desactivar congelación**, y reinicie Windows cuando
   la aplicación lo indique (nunca reinicia sola).

Si aparece SmartScreen («Windows protegió su PC»), es porque el `.exe` no está firmado digitalmente:
«Más información» → «Ejecutar de todas formas».

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
| Espacio libre en C: | Aviso si hay menos del doble de los 2048 MB de la superposición |

Resultado global: **COMPATIBLE**, **COMPATIBLE CON AVISOS**, **NO COMPATIBLE** o
**NO SE PUEDE DETERMINAR**. El informe se puede copiar al portapapeles.

## Qué hacen los botones

- **Activar congelación y protección**: habilita la característica si falta (DISM, sin reiniciar),
  configura superposición `DISK` de 2048 MB, protege `C:` y habilita el filtro. Omite lo ya
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

## Desarrollo

```
pip install -r requirements-dev.txt
python -m pytest -q                 # pruebas (las de la ventana se omiten si no hay pantalla)
python -m uwf_manager               # interfaz
python -m uwf_manager --status      # estado en consola (solo lectura)
python -m uwf_manager --compat      # compatibilidad en consola (solo lectura)
build.bat                           # en Windows: pruebas + PyInstaller → dist\UWFManager.exe
```

Código en `uwf_manager/`: `runner` (procesos, sin shell y con timeout), `errors`, `state` (consulta
CIM por PowerShell `-EncodedCommand`), `commands`, `operations` (activar/desactivar), `compat`,
`presentation`, `controller` (hilo de trabajo), `gui`, `system` (admin/UAC), `logs`, `assets/` (icono).

Registro: `%LOCALAPPDATA%\UWFManager\logs\uwf-manager.log`.

## Limitaciones conocidas

- No cambia a superposición RAM si DISK falla: se detiene y muestra el error.
- No ofrece botón de reinicio; el usuario reinicia manualmente.
- Solo la unidad `C:`.
- El `.exe` no está firmado (aviso de SmartScreen).
