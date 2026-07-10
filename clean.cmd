@echo off
REM Restores public\ to input-only shape after a geo-builder designer (--edit) session.
REM Thin wrapper around scripts\clean_public.py, mirroring build.cmd's naming, so there's a
REM one-command way to run it manually right after a designer session -- before committing
REM and before build.sh/build.cmd would otherwise run it for you automatically. Needed for
REM more than the documented first-launch pull: adding a *new* area in designer mode has
REM also been observed writing real url/layers/csv straight into that area's public\
REM manifest even under --noninvasive (see docs\CLI.md).

set "REPO_ROOT=%~dp0"
if "%REPO_ROOT:~-1%"=="\" set "REPO_ROOT=%REPO_ROOT:~0,-1%"

python "%REPO_ROOT%\scripts\clean_public.py"
