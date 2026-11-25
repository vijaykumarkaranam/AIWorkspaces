@echo off
setlocal
rem Runs every Cisco IOS-XR query against one router through ODL.
rem Usage: run_queries.bat [router-ip]   (default 10.54.174.13)

rem The controller is asked for when the script starts (choose_odl.bat): dev and prod mount different routers.
call "%~dp0..\choose_odl.bat"
set ODL_USER=admin
set NODE=%~1
if "%NODE%"=="" set NODE=10.54.174.13

set /p ODL_PASSWORD=ODL password:

cd /d "%~dp0"
python run_queries.py --node %NODE% --all

echo.
pause
