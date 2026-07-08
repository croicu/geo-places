@echo off
setlocal EnableDelayedExpansion
REM Installs geo-builder and builds the deploy-ready output for every area into out\.
REM Local Windows equivalent of build.sh (which is what CI actually runs).
REM
REM public\ is hand-authored input ONLY: public\catalog.json + public\catalog.debug.json
REM (id/name/bbox per area) + public\areas\<id>\manifest.json (layer/acquisition defs, no
REM "url" field yet). Never generated into. geo-builder reads the *whole* catalog from
REM --in in one call and acquires data for every area that needs it -- there is no
REM per-area loop. tasks_path is only used for __poi__/__void__ style lookup, so it
REM points at the shared template.json at repo root rather than any one area's manifest.
REM
REM geo-builder writes its own native shape directly to out\ (--out out\): catalog.head*.json,
REM catalog.json OR catalog.debug.json (whichever the active debug flag resolves to -- never
REM both in one run), and per area: areas\<id>\manifest.json (now with "url" populated),
REM areas\<id>\<id>.csv, areas\<id>\layers\*.geojson. This script then: (1) copies both
REM catalog.json and catalog.debug.json from public\ into out\ so both are always present
REM regardless of which one this run actually used, and (2) strips geo-builder's
REM catalog.head*.json and per-area .csv files, which aren't part of the deploy contract.
REM out\ is gitignored and rebuilt fresh every run -- nothing under it is ever committed.
REM
REM geo-builder loads settings.json/settings.local.json from the CWD -- this script cd's
REM to REPO_ROOT before invoking it so those are picked up. This repo's build\ directory
REM is reserved exclusively for geo-builder's own debug output: geo-builder hardcodes
REM debug snapshots to .\build\ relative to CWD and wipes that directory on every debug
REM run (settings.local.json's debug:true). This script therefore lives at repo root,
REM not under build\ -- putting anything we care about under build\ WILL eventually get deleted.

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
cd /d "%REPO_ROOT%"

if "%GEO_BUILDER_REF%"=="" set "GEO_BUILDER_REF=main"
set "CATALOG_DIR=%REPO_ROOT%\public"
set "TASKS_PATH=%REPO_ROOT%\template.json"
set "DEPLOY_OUT=%REPO_ROOT%\out"
if exist "%DEPLOY_OUT%" rmdir /s /q "%DEPLOY_OUT%"

REM Prefer a sibling geo-builder checkout's own venv (local dev: already has geo-builder
REM installed editable, no need to pip install a copy from GitHub every run). Falls back
REM to installing into whatever `python`/`pip` resolve to (CI: actions/setup-python's
REM runner-owned Python, which doesn't need a venv to avoid permission errors).
set "SIBLING_VENV_PY=%REPO_ROOT%\..\geo-builder\.venv\Scripts\python.exe"
if exist "%SIBLING_VENV_PY%" (
    set "PYTHON=%SIBLING_VENV_PY%"
    echo Using geo-builder venv at %REPO_ROOT%\..\geo-builder\.venv ^(skipping install^)
) else (
    set "PYTHON=python"
    echo Installing geo-builder@%GEO_BUILDER_REF%
    pip install --quiet "git+https://github.com/croicu/geo-builder.git@%GEO_BUILDER_REF%"
    if errorlevel 1 exit /b 1
)

if not exist "%CATALOG_DIR%\catalog.json" (
    echo No catalog found at %CATALOG_DIR%\catalog.json 1>&2
    exit /b 1
)

if not exist "%CATALOG_DIR%\catalog.debug.json" (
    echo No debug catalog found at %CATALOG_DIR%\catalog.debug.json 1>&2
    exit /b 1
)

if not exist "%TASKS_PATH%" (
    echo No template found at %TASKS_PATH% 1>&2
    exit /b 1
)

echo Building catalog ^(tasks_path=%TASKS_PATH%^)
"%PYTHON%" -m geo_builder.cli "%TASKS_PATH%" --in "%CATALOG_DIR%" --out "%DEPLOY_OUT%"
if errorlevel 1 exit /b 1

copy /y "%CATALOG_DIR%\catalog.json" "%DEPLOY_OUT%\catalog.json" >nul
copy /y "%CATALOG_DIR%\catalog.debug.json" "%DEPLOY_OUT%\catalog.debug.json" >nul

if exist "%DEPLOY_OUT%\catalog.head.json" del /q "%DEPLOY_OUT%\catalog.head.json"
if exist "%DEPLOY_OUT%\catalog.head.debug.json" del /q "%DEPLOY_OUT%\catalog.head.debug.json"

set "PRODUCED=0"
for /d %%P in ("%DEPLOY_OUT%\areas\*") do (
    set "ID=%%~nxP"
    if exist "%%P\!ID!.csv" del /q "%%P\!ID!.csv"
    set /a PRODUCED+=1
)

if "!PRODUCED!"=="0" (
    echo geo-builder produced no area output 1>&2
    exit /b 1
)

echo Build complete ^(!PRODUCED! areas^) -^> %DEPLOY_OUT%
endlocal
