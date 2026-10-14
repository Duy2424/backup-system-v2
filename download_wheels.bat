@echo off
title Tai thu vien de cai offline
echo ============================================================
echo  Chay tren may CO Internet de tai san cac goi (Windows 64-bit,
echo  Python 3.11) vao thu muc "wheels", roi chep sang may khong co mang
echo  va chay install.bat.
echo ============================================================
echo.

cd /d "%~dp0"
if not exist wheels mkdir wheels

python -m pip download -r requirements.txt --dest wheels --platform win_amd64 ^
    --python-version 311 --implementation cp --only-binary :all:
if errorlevel 1 (
    echo [LOI] Tai that bai - kiem tra ket noi Internet.
) else (
    echo [OK] Da tai vao thu muc wheels.
)
pause
