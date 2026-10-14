@echo off
title BACKUP AGENT
echo ============================================================
echo  BACKUP SYSTEM - AGENT
echo ============================================================
echo  Can chay bang quyen Administrator (khoi phuc IP/firewall can quyen nay).
echo.
echo  Truoc khi chay: vao web ^> Cai dat ^> "Ket noi agent", chep 2 dong
echo  SERVER_URL=... va AGENT_TOKEN=... vao agent\agent_config.txt
echo  Dung agent: dong cua so nay hoac Ctrl+C
echo ============================================================
echo.

cd /d "%~dp0.."
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% -m agent
pause
