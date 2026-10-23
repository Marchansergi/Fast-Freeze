@echo off
REM Genera dist\UWFManager.exe (ejecutar en Windows, desde la raíz del proyecto).
python -m pip install -r requirements-dev.txt || exit /b 1
python -m pytest -q || exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin --name UWFManager run_uwf_manager.py || exit /b 1
echo Listo: dist\UWFManager.exe
