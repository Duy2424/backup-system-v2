@echo off
title DEMO BACKUP SYSTEM v2 - 1 may
rem Mo 3 cua so: KHO v2 (API chi them), SERVER (web + API agent), AGENT (sao luu bang loi v2) roi mo trinh duyet.
rem Chay deploy\demo\chuan_bi_demo.ps1 truoc (tao du lieu mau, kho, tai khoan, file bien moi truong).
cd /d "%~dp0..\.."
set DEMO_ROOT=D:\DemoBackup
if not "%~1"=="" set DEMO_ROOT=%~1
if not exist "%DEMO_ROOT%\demo.env.cmd" (
    echo Chua co %DEMO_ROOT%\demo.env.cmd - chay truoc:
    echo    powershell -ExecutionPolicy Bypass -File deploy\demo\chuan_bi_demo.ps1
    pause
    exit /b 1
)
call "%DEMO_ROOT%\demo.env.cmd"
set PY=.venv\Scripts\python.exe
if not exist "%PY%" ( echo Chua co .venv - chay chuan_bi_demo.ps1 & pause & exit /b 1 )

echo [1/3] KHO v2  http://127.0.0.1:%KHO_PORT%  (thu muc %KHO_DIR%)
start "KHO v2 - API chi them (%KHO_PORT%)" cmd /k "%PY% -m kho --kho "%KHO_DIR%" --port %KHO_PORT%"
timeout /t 2 /nobreak >nul
echo [2/3] SERVER  http://127.0.0.1:%BACKUP_PORT%
start "SERVER - web + API (%BACKUP_PORT%)" cmd /k "%PY% -m server --host 127.0.0.1 --port %BACKUP_PORT%"
timeout /t 3 /nobreak >nul
echo [3/3] AGENT (ENGINE=v2, kho %BACKUP_V2_REPO%)
start "AGENT - loi v2" cmd /k "%PY% -m agent"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:%BACKUP_PORT%
echo.
echo Da mo 3 cua so. Dang nhap web bang admin + mat khau da dat khi chuan bi.
echo Dung demo: dong 3 cua so (hoac Ctrl+C trong tung cua so).
