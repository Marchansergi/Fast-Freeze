# UWF Manager

Aplicación de escritorio (Python + Tkinter, sin dependencias externas) para activar y desactivar
**Unified Write Filter (UWF)** en Windows 11 IoT Enterprise LTSC.

> ## ⚠ Advertencia
> Con UWF activo, **Windows descarta al reiniciar los cambios hechos en C: durante la sesión protegida**
> (archivos, programas, configuración). Guarde sus datos importantes antes de activar la congelación
> y manténgalos en una unidad no protegida o en red.

## Estado de verificación (leer antes de usar)

- **Documentación de Microsoft: NO se pudo consultar** durante el desarrollo (el entorno bloqueaba
  `learn.microsoft.com`). La sintaxis de `uwfmgr`, DISM y las clases WMI (`UWF_Filter`, `UWF_Volume`,
  `UWF_OverlayConfig`, espacio `root\standardcimv2\embedded`) proviene del enunciado del proyecto y de
  conocimiento previo, **sin contrastar** con las páginas oficiales. Contrástelas antes de uso real.
- **Nunca se ha ejecutado en Windows ni contra un UWF real.** Las 33 pruebas usan un Windows simulado.
- **La interfaz gráfica no se ha ejecutado** (el entorno de desarrollo no tenía Tkinter); solo se
  comprobó que compila. La lógica que usa (controlador, textos de estado) sí está probada.
- El `.exe` lo compila GitHub Actions; no se ha comprobado que funcione.
- El tutorial «Tutorial de Congelacio W11 LTSC.txt» no estaba en el entorno; se usaron los comandos
  citados en el enunciado.
- Suposiciones sin verificar: `overlay set-size` está en **MB**; una unidad sin entrada en `UWF_Volume`
  para una sesión se interpreta como no protegida; `Get-WindowsOptionalFeature` requiere administrador.

## Qué hace

- Muestra el estado real (consultado a Windows en cada actualización; no se guarda ningún "congelado" local).
- **Activar congelación y protección**: habilita la característica si falta (DISM), configura
  superposición `DISK` de 2048 MB, protege `C:` y habilita el filtro, omitiendo lo ya configurado y
  verificando el estado tras cada paso.
- **Desactivar congelación**: tras confirmación, ejecuta `uwfmgr filter disable`. **No** ejecuta
  `volume unprotect`, `reset-settings` ni desinstala nada; la protección de C: queda guardada.
- Nunca reinicia el equipo: solo avisa.

Edición admitida: Windows 11 Enterprise / Education / IoT Enterprise (incluidas LTSC). Pro/Home se rechazan.

## Uso (sin Python)

1. En GitHub: pestaña **Actions** → última ejecución «Compilar UWFManager.exe» → descargar el artefacto
   **UWFManager** (zip) y extraer `UWFManager.exe`.
2. Doble clic. El `.exe` se compila con manifiesto de administrador, así que Windows pedirá UAC al abrirlo.

Alternativa con Python (desarrollo): `python -m uwf_manager` o `python -m uwf_manager --status`.

## Estados

| Texto | Significado |
|---|---|
| UWF: ACTIVO / DESACTIVADO | Filtro en la **sesión actual**; entre paréntesis, el valor tras reiniciar si difiere |
| Protección C:: CONFIGURADA | C: está marcada para protección (indica si ya actúa o se aplicará al reiniciar) |
| Característica UWF: INSTALADA / NO INSTALADA / PENDIENTE DE REINICIO | Característica opcional de Windows |
| Reinicio pendiente | Estado actual y configurado para la próxima sesión difieren |
| Posible cambio pendiente de reinicio | No se pudo leer parte del estado; no se puede asegurar |
| Estado desconocido: no se pudo verificar | Dato no disponible; no se inventa |

## Por qué hay que reiniciar

UWF aplica los cambios de filtro, volúmenes y superposición en el **siguiente arranque**. Habilitar la
característica también suele exigirlo; en ese caso la app se detiene, y al reabrirla continúa donde
quedó (todo se deduce del estado de Windows).

## Pruebas y compilación

```
pip install -r requirements-dev.txt
python -m pytest -q
build.bat          # en Windows: pytest + PyInstaller → dist\UWFManager.exe
```

El `.exe` se compila con `--uac-admin` (UAC al abrir). La compilación automática está en `.github/workflows/build.yml`; su resultado aún no se ha comprobado en Windows.

## Registro

`%LOCALAPPDATA%\UWFManager\logs\uwf-manager.log` (rotativo): operación, comando, código de retorno,
verificación posterior y errores. Si no se puede escribir, la app funciona igual.

## Estructura

`uwf_manager/`: `runner` (procesos), `errors`, `state` (consulta CIM), `commands`, `operations`
(activar/desactivar), `presentation` (textos), `controller` (hilo de trabajo), `gui`, `system`
(admin/UAC), `logs`. Tests en `tests/` con un Windows simulado (`tests/fakes.py`).

## Limitaciones conocidas

- No cambia a superposición RAM si DISK falla: se detiene y muestra el error.
- No ofrece botón de reinicio; el usuario reinicia manualmente.
- Solo la unidad `C:`.
