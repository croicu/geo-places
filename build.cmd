@echo off
setlocal EnableDelayedExpansion
REM Installs geo-builder and builds the deploy-ready output for every area into out\.
REM Local Windows equivalent of build.sh (which is what CI actually runs).
REM
REM public\ is hand-authored input ONLY: public\catalog.json (id/name/bbox/optional group
REM per area) + public\areas\<id>\manifest.json (layer/acquisition defs, no "url" field
REM yet). Never generated into -- this script runs scripts\clean_public.py before every
REM build to guarantee it (see that script's docstring for why: designer mode pollutes
REM public\ with real url/geojson/head-file data on first launch). geo-builder reads the
REM *whole* catalog from --in in one call and acquires data for every area that needs it
REM -- there is no per-area loop. tasks_path is only used for __poi__/__void__ style
REM lookup, so it points at the shared template.json at repo root rather than any one
REM area's manifest.
REM
REM There is one catalog, period -- geo-builder dropped the debug-catalog-file concept
REM entirely (see tasks\area_grouping.md, geo-builder commit f9ff202): a per-area "group"
REM field (e.g. ["debug"]) is now how areas like redmond are tagged, filtered client-side
REM by geo-browser, not by building a different catalog file. Every area in
REM public\catalog.json ships and is always built here, regardless of group.
REM
REM geo-builder writes its own native shape directly to out\ (--out out\): catalog.head.json,
REM catalog.json, and per area: areas\<id>\manifest.json (now with "url" populated),
REM areas\<id>\<id>.csv, areas\<id>\layers\*.geojson. This script then: (1) copies
REM catalog.json from public\ into out\, and (2) strips geo-builder's catalog.head.json and
REM per-area .csv files, which aren't part of the deploy contract. out\ is gitignored and
REM rebuilt fresh every run -- nothing under it is ever committed.
REM
REM geo-builder loads settings.json/settings.local.json from the CWD -- this script cd's
REM to REPO_ROOT before invoking it so those are picked up. This repo's build\ directory
REM is reserved exclusively for geo-builder's own debug output: geo-builder hardcodes
REM debug snapshots to .\build\ relative to CWD and wipes that directory on every debug
REM run (settings.local.json's debug:true). This script therefore lives at repo root,
REM not under build\ -- putting anything we care about under build\ WILL eventually get deleted.
REM
REM GEO_PLACES_CATALOG_DIR / GEO_PLACES_TASKS_PATH override the catalog/template used --
REM ci.yaml points these at ci-fixtures\ (a tiny synthetic area with provider: fake, no
REM network) for routine validation. cd.yaml leaves them unset, using the real public\
REM catalog against live Overpass.
REM
REM GEO_PLACES_INCREMENTAL (set only by cd.yaml) switches --in from public\ directly to a
REM scratch directory assembled by scripts\prepare_incremental_build.py -- see build.sh's
REM header comment and tasks\incremental_publish.md for the full design. Unset (any local
REM run): behaves exactly as before this feature existed.

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"
cd /d "%REPO_ROOT%"

if "%GEO_BUILDER_REF%"=="" set "GEO_BUILDER_REF=main"
if "%GEO_PLACES_CATALOG_DIR%"=="" (set "CATALOG_DIR=%REPO_ROOT%\public") else (set "CATALOG_DIR=%GEO_PLACES_CATALOG_DIR%")
if "%GEO_PLACES_TASKS_PATH%"=="" (set "TASKS_PATH=%REPO_ROOT%\template.json") else (set "TASKS_PATH=%GEO_PLACES_TASKS_PATH%")
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

REM geo-builder's designer mode (--edit) pulls existing built artifacts into --in on
REM first launch, writing "url" fields, layers\*.geojson, and catalog.head*.json straight
REM into public\ -- always restore it to input-only shape before building, regardless of
REM what a previous designer session (or a forgotten manual cleanup) left behind.
"%PYTHON%" "%REPO_ROOT%\scripts\clean_public.py"
if errorlevel 1 exit /b 1

if not exist "%CATALOG_DIR%\catalog.json" (
    echo No catalog found at %CATALOG_DIR%\catalog.json 1>&2
    exit /b 1
)

if not exist "%TASKS_PATH%" (
    echo No template found at %TASKS_PATH% 1>&2
    exit /b 1
)

set "BUILD_IN=%CATALOG_DIR%"
set "REBUILD_ARGS="
set "STATE_OUT="

if "%GEO_PLACES_INCREMENTAL%"=="1" (
    set "SCRATCH_DIR=%TEMP%\geo-places-scratch-%RANDOM%%RANDOM%"
    set "STATE_OUT=%TEMP%\geo-places-state-%RANDOM%%RANDOM%.json"
    set "REBUILD_OUT=%TEMP%\geo-places-rebuild-%RANDOM%%RANDOM%.txt"
    if "%GEO_PLACES_PRODUCTION_URL%"=="" (set "PRODUCTION_URL=https://geo-places.croicu.com") else (set "PRODUCTION_URL=%GEO_PLACES_PRODUCTION_URL%")

    set "PREPARE_ARGS=--public-dir "%CATALOG_DIR%" --template-path "%TASKS_PATH%" --settings-path "%REPO_ROOT%\settings.json" --scratch-dir "!SCRATCH_DIR!" --state-out "!STATE_OUT!" --rebuild-out "!REBUILD_OUT!" --production-url "!PRODUCTION_URL!""
    if not "%GEO_PLACES_REBUILD_AREAS%"=="" set "PREPARE_ARGS=!PREPARE_ARGS! --areas "%GEO_PLACES_REBUILD_AREAS%""

    echo Assembling incremental --in from !PRODUCTION_URL!
    "%PYTHON%" "%REPO_ROOT%\scripts\prepare_incremental_build.py" !PREPARE_ARGS!
    if errorlevel 1 exit /b 1

    set "BUILD_IN=!SCRATCH_DIR!"
    for /f "usebackq delims=" %%A in ("!REBUILD_OUT!") do set "REBUILD_ARGS=!REBUILD_ARGS! --rebuild %%A"
)

echo Building catalog ^(tasks_path=%TASKS_PATH%^)
"%PYTHON%" -m geo_builder.cli "%TASKS_PATH%" --in "%BUILD_IN%" --out "%DEPLOY_OUT%" %REBUILD_ARGS%
if errorlevel 1 exit /b 1

copy /y "%CATALOG_DIR%\catalog.json" "%DEPLOY_OUT%\catalog.json" >nul

if not "%STATE_OUT%"=="" copy /y "%STATE_OUT%" "%DEPLOY_OUT%\build-state.json" >nul
if "%GEO_PLACES_INCREMENTAL%"=="1" (
    if exist "%SCRATCH_DIR%" rmdir /s /q "%SCRATCH_DIR%"
    if exist "%STATE_OUT%" del /q "%STATE_OUT%"
    if exist "%REBUILD_OUT%" del /q "%REBUILD_OUT%"
)

if exist "%DEPLOY_OUT%\catalog.head.json" del /q "%DEPLOY_OUT%\catalog.head.json"

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
