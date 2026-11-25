@echo off
rem ============================================================
rem  Picks the ODL controller for the viewers and query scripts.
rem  Dev and prod controllers mount different routers: a query against a router that is not
rem  mounted on the chosen controller fails with "Mount point does not exist".
rem  If ODL_BASE is already set (for example in your environment), it is kept.
rem  Edit the two addresses below if your controllers change.
rem ============================================================
set "ODL_PROD=http://10.137.202.20:8181"
set "ODL_DEV=http://10.218.66.24:8181"

if defined ODL_BASE (
  echo Using ODL_BASE from the environment: %ODL_BASE%
) else (
  echo Which ODL controller?
  echo   1 = PROD  %ODL_PROD%
  echo   2 = DEV   %ODL_DEV%
  echo   or type a full URL, e.g. http://10.137.202.19:8181
  set "ODL_PICK=1"
  set /p "ODL_PICK=Controller [1]: "
)
if not defined ODL_BASE (
  if "%ODL_PICK%"=="1" set "ODL_BASE=%ODL_PROD%"
  if "%ODL_PICK%"=="2" set "ODL_BASE=%ODL_DEV%"
)
if not defined ODL_BASE set "ODL_BASE=%ODL_PICK%"
echo ODL: %ODL_BASE%
