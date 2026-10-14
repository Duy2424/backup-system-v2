@echo off
title BACKUP SYSTEM - Cai dat
echo ============================================================
echo  BACKUP SYSTEM - Cai dat moi truong Python (.venv)
echo ============================================================
echo.

cd /d "%~dp0"

rem Uu tien trinh khoi chay py (co san khi cai Python tu python.org), roi den python tren PATH
set PYBOOT=
py -3.11 --version > nul 2>&1 && set "PYBOOT=py -3.11"
if not defined PYBOOT (
    python --version > nul 2>&1 && set "PYBOOT=python"
)
if not defined PYBOOT (
    echo [LOI] Chua co Python 3.11. Cai tai https://www.python.org/downloads/windows/
    pause
    exit /b 1
)
%PYBOOT% --version

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Tao moi truong ao .venv ...
    %PYBOOT% -m venv .venv
    if errorlevel 1 goto :fail
)

echo [2/2] Cai thu vien theo requirements.txt (dung phien ban da pin) ...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
if not errorlevel 1 goto :done

if exist "wheels\" (
    echo Khong co Internet - cai tu thu muc wheels ...
    .venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-index --find-links=wheels -r requirements.txt
    if not errorlevel 1 goto :done
)

:fail
echo.
echo [LOI] Khong cai duoc. Neu may khong co Internet: chay download_wheels.bat
echo       tren may co mang, chep thu muc "wheels" sang day roi chay lai.
pause
exit /b 1

:done
echo.
echo [OK] Xong. Chay:
echo    server\start_server.bat   (tren PC lam may chu)
echo    agent\start_agent.bat     (tren may can sao luu, quyen Administrator)
pause
