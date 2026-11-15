@echo off
title BACKUP KHO v2
echo ============================================================
echo  BACKUP SYSTEM - KHO v2 (API chi them, khong xoa)
echo ============================================================
echo  Thu muc kho: %KHO_DIR% (doi bang: set KHO_DIR=D:\kho-v2)
echo  Nghe 127.0.0.1:8080 - Caddy mTLS dung truoc (deploy\kho\Caddyfile)
echo  Lan dau: python -m core init --repo http://127.0.0.1:8080
echo  Dung kho: dong cua so nay hoac Ctrl+C
echo ============================================================
echo.

cd /d "%~dp0.."
if "%KHO_DIR%"=="" set KHO_DIR=D:\kho-v2
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% -m kho --kho "%KHO_DIR%" %*
pause
