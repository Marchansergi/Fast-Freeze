"""Modelo del estado de UWF y su lectura desde Windows.

La lectura usa CIM/WMI (espacio root\\standardcimv2\\embedded) y devuelve JSON, de modo que
no se depende del idioma del texto de uwfmgr.exe. Todo valor no verificable es None.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field

from . import system
from .logs import get_logger
from .runner import CommandRunner

TARGET_VOLUME = "C:"
FEATURE_NAME = "Client-UnifiedWriteFilter"

_PS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$r = [ordered]@{ errors = @() }
try { $os = Get-CimInstance Win32_OperatingSystem
      $r.caption = $os.Caption; $r.version = $os.Version; $r.build = [int]$os.BuildNumber } catch { $r.errors += "os: $($_.Exception.Message)" }
try { $r.edition = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion').EditionID } catch { $r.errors += "edition: $($_.Exception.Message)" }
try { $r.is64 = [Environment]::Is64BitOperatingSystem } catch { }
try { $r.c_free = [int64](Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='C:'").FreeSpace } catch { $r.errors += "disco: $($_.Exception.Message)" }
try { $feat = Get-WindowsOptionalFeature -Online -FeatureName Client-UnifiedWriteFilter
      if ($null -eq $feat) { $r.feature = 'NotPresent' } else { $r.feature = $feat.State.ToString() } } catch { $r.errors += "feature: $($_.Exception.Message)" }
$ns = 'root\standardcimv2\embedded'
$r.wmi = $false
try {
  $f = @(Get-CimInstance -Namespace $ns -ClassName UWF_Filter)
  $r.wmi = $true
  $r.filter = @($f | ForEach-Object { @{ current = $_.CurrentEnabled; next = $_.NextEnabled } })
  $r.volumes = @(Get-CimInstance -Namespace $ns -ClassName UWF_Volume | ForEach-Object {
      @{ drive = $_.DriveLetter; protected = $_.Protected; session = $_.CurrentSession } })
  $r.overlay = @(Get-CimInstance -Namespace $ns -ClassName UWF_OverlayConfig | ForEach-Object {
      @{ session = $_.CurrentSession; size = $_.MaximumSize; type = $_.Type } })
} catch { $r.errors += "uwf: $($_.Exception.Message)" }
$r | ConvertTo-Json -Depth 6 -Compress
"""

# -EncodedCommand (UTF-16LE en Base64) evita problemas de comillas al pasar el script.
POWERSHELL = ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand",
              base64.b64encode(_PS_SCRIPT.encode("utf-16-le")).decode("ascii")]


@dataclass(frozen=True)
class OverlayInfo:
    type: str | None  # "DISK" | "RAM" | None
    size_mb: int | None


@dataclass
class UwfStatus:
    query_ok: bool = False
    windows_caption: str | None = None
    windows_build: int | None = None
    edition_id: str | None = None
    is_admin: bool = False
    is_64bit: bool | None = None
    c_free_bytes: int | None = None
    uwfmgr_path: str | None = None
    feature_state: str | None = None  # Enabled | Disabled | EnablePending | ...
    wmi_available: bool | None = None
    filter_current: bool | None = None
    filter_next: bool | None = None
    c_current: bool | None = None
    c_next: bool | None = None
    overlay_current: OverlayInfo | None = None
    overlay_next: OverlayInfo | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def edition_supported(self) -> bool | None:
        if not self.edition_id:
            return None
        e = self.edition_id.lower()
        return "enterprise" in e or "education" in e

    @property
    def is_windows_11(self) -> bool | None:
        return None if self.windows_build is None else self.windows_build >= 22000

    @property
    def feature_installed(self) -> bool | None:
        if self.feature_state == "Enabled":
            return True
        if self.feature_state in ("Disabled", "EnablePending", "DisablePending", "NotPresent"):
            return False
        if self.wmi_available:  # sin permisos para DISM, pero UWF responde
            return True
        return None

    @property
    def feature_pending(self) -> bool:
        return self.feature_state in ("EnablePending", "DisablePending")

    @property
    def reboot_pending(self) -> bool | None:
        """True si hay diferencias demostrables; None si no se puede descartar."""
        pairs = [
            (self.filter_current, self.filter_next),
            (self.c_current, self.c_next),
            (self.overlay_current, self.overlay_next),
        ]
        if self.feature_pending or any(c is not None and n is not None and c != n for c, n in pairs):
            return True
        if self.feature_installed is False:
            return False
        if any(c is None or n is None for c, n in pairs):
            return None
        return False


def _bool(v) -> bool | None:
    return v if isinstance(v, bool) else None


def _as_list(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _overlay(items: list, current: bool) -> OverlayInfo | None:
    for it in items:
        if isinstance(it, dict) and it.get("session") is current:
            t = {0: "RAM", 1: "DISK"}.get(it.get("type"))
            size = it.get("size")
            return OverlayInfo(t, size if isinstance(size, int) and not isinstance(size, bool) else None)
    return None


def _volume(items: list, current: bool, letter: str) -> bool | None:
    """Protección de una unidad; la ausencia de entrada cuando WMI responde = no protegida."""
    for it in items:
        if isinstance(it, dict) and it.get("session") is current \
                and str(it.get("drive") or "").upper() == letter.upper():
            return _bool(it.get("protected"))
    return False


def parse_status(raw: str, status: UwfStatus) -> UwfStatus:
    """Rellena `status` a partir del JSON de PowerShell. No lanza excepciones."""
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("JSON inesperado")
    except ValueError as exc:
        status.errors.append(f"Salida inesperada al consultar el sistema: {exc}")
        return status
    status.query_ok = True
    status.windows_caption = data.get("caption")
    status.windows_build = data.get("build") if isinstance(data.get("build"), int) else None
    status.edition_id = data.get("edition")
    status.feature_state = data.get("feature")
    status.is_64bit = _bool(data.get("is64"))
    free = data.get("c_free")
    status.c_free_bytes = free if isinstance(free, int) and not isinstance(free, bool) else None
    status.errors += [str(e) for e in _as_list(data.get("errors"))]
    status.wmi_available = _bool(data.get("wmi"))
    if status.wmi_available:
        flt = _as_list(data.get("filter"))
        if len(flt) == 1 and isinstance(flt[0], dict):
            status.filter_current = _bool(flt[0].get("current"))
            status.filter_next = _bool(flt[0].get("next"))
        vols = _as_list(data.get("volumes"))
        status.c_current = _volume(vols, True, TARGET_VOLUME)
        status.c_next = _volume(vols, False, TARGET_VOLUME)
        ov = _as_list(data.get("overlay"))
        status.overlay_current = _overlay(ov, True)
        status.overlay_next = _overlay(ov, False)
    return status


class UwfQuery:
    def __init__(self, runner: CommandRunner) -> None:
        self.runner = runner

    def read(self) -> UwfStatus:
        st = UwfStatus(is_admin=system.is_admin(),
                       uwfmgr_path=system.find_executable("uwfmgr.exe"))
        try:
            res = self.runner.run(POWERSHELL, timeout=60)
            if res.ok:
                parse_status(res.stdout, st)
            else:
                st.errors.append(f"No se pudo consultar el sistema: {res.output or res.error}")
        except Exception as exc:  # la consulta nunca debe tumbar la aplicación
            st.errors.append(f"Error inesperado al consultar: {exc}")
        get_logger().info("ESTADO %s", st)
        return st

    def raw_config(self) -> str:
        """Salida textual de `uwfmgr get-config`, solo informativa (no se interpreta)."""
        res = self.runner.run(["uwfmgr.exe", "get-config"], timeout=30)
        return res.output
