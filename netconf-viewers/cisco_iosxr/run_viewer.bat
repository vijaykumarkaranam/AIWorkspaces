@echo off
setlocal
rem ============================================================
rem  Cisco IOS-XR viewer - starts viewer.py and opens the control page.
rem  On the page: pick a router, Run all queries, Build report, Open report.
rem  Routers are listed in viewer.py (ROUTERS) or set ROUTERS below.
rem ============================================================

rem ---- ODL settings (edit these) ----
rem The controller is asked for when the script starts (choose_odl.bat): dev and prod mount different routers.
call "%~dp0..\choose_odl.bat"
set "ODL_USER=admin"
rem Leave the password empty to be asked for it when the script starts.
set "ODL_PASSWORD="
set "ROUTERS=10.54.174.13 10.54.172.1"

if "%ODL_PASSWORD%"=="" set /p "ODL_PASSWORD=ODL password for %ODL_USER%: "

cd /d "%~dp0"
start "" "http://127.0.0.1:8766/"
python viewer.py --port 8766 %*
if errorlevel 1 echo.& echo viewer.py stopped with an error. Check that Python is on PATH.
pause
