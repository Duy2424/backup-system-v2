@echo off
title BACKUP SERVER
echo ============================================================
echo  BACKUP SYSTEM - SERVER (web dieu khien + API + kho)
echo ============================================================
echo  Lan dau chay: mat khau admin duoc in ra ben duoi va luu o
echo  instance\admin_password.txt - dang nhap xong hay doi mat khau.
echo.
echo  Tu laptop: mo trinh duyet toi http://^<IP Tailscale cua PC^>:5000
echo  Dung server: dong cua so nay hoac Ctrl+C
echo ============================================================
echo.

cd /d "%~dp0.."
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% -m server %*
pause
