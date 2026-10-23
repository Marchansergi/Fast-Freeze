@echo off
REM Genera "dist\Fast Freeze.exe" (ejecutar en Windows, desde la raíz del proyecto).
python -m pip install -r requirements-dev.txt || exit /b 1
python -m pytest -q || exit /b 1
python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin --name "Fast Freeze" --icon uwf_manager\assets\app.ico --version-file packaging\version_info.txt --add-data "uwf_manager\assets;uwf_manager\assets" run_uwf_manager.py || exit /b 1
echo Listo: "dist\Fast Freeze.exe"
