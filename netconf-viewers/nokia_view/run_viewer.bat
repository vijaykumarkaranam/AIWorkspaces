@echo off
rem ============================================================
rem  Nokia NETCONF viewer - sets ODL settings and starts server.py
rem  Open http://127.0.0.1:8765/ after it starts.
rem  Extra arguments are passed to server.py, e.g.  run_viewer.bat --port 8800
rem ============================================================

rem ---- ODL settings (edit these) ----
set "ODL_BASE=http://10.137.202.20:8181"
set "ODL_USER=admin"
rem Leave the password empty to be asked for it when the script starts.
set "ODL_PASSWORD="
rem Optional session cookie, e.g. JSESSIONID=...  (leave empty if basic auth works)
set "ODL_COOKIE="

if "%ODL_PASSWORD%"=="" set /p "ODL_PASSWORD=ODL password for %ODL_USER%: "

cd /d "%~dp0"
python server.py --port 8765 %*
if errorlevel 1 echo.& echo server.py stopped with an error. Check that Python is on PATH.
pause
