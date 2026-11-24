@echo off
setlocal
rem Runs every Cisco IOS-XR query against one router through ODL.
rem Usage: run_queries.bat [router-ip]   (default 10.54.174.13)

set ODL_BASE=http://10.137.202.20:8181
set ODL_USER=admin
set NODE=%~1
if "%NODE%"=="" set NODE=10.54.174.13

set /p ODL_PASSWORD=ODL password:

cd /d "%~dp0"
python run_queries.py --node %NODE% --all

echo.
pause
