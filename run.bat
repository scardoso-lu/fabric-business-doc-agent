@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

echo ============================================================
echo  Fabric Business Documentation Agent
echo ============================================================
echo.

:: ── 1. Check uv ──────────────────────────────────────────────
uv --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] uv not found. Install it from https://docs.astral.sh/uv/getting-started/installation/
    pause & exit /b 1
)

:: ── 2. Read provider and model from .env (defaults if not set) ──
set "LLM_PROVIDER=anthropic"
set "LLM_MODEL="
for /f "tokens=1,* delims==" %%A in ('findstr /b "LLM_PROVIDER=" ".env" 2^>nul') do set "LLM_PROVIDER=%%B"
for /f "tokens=1,* delims==" %%A in ('findstr /b "LLM_MODEL=" ".env" 2^>nul') do set "LLM_MODEL=%%B"

echo  Provider : !LLM_PROVIDER!
echo  Model    : !LLM_MODEL! (blank = provider default)
echo.

:: ── 3. Sync dependencies ─────────────────────────────────────
echo [1/3] Syncing dependencies...
uv sync -q
if errorlevel 1 (
    echo [ERROR] uv sync failed.
    pause & exit /b 1
)
echo       Done.
echo.

:: ── 4. Resolve source and output dirs ────────────────────────
set "SRC_DIR=src"
set "OUT_DIR=output"

if not "%~1"=="" set "SRC_DIR=%~1"
if not "%~2"=="" set "OUT_DIR=%~2"

if not exist "!SRC_DIR!" (
    echo [ERROR] Source directory "!SRC_DIR!" does not exist.
    echo         Usage:  run.bat [src_dir] [output_dir]
    pause & exit /b 1
)

:: ── 5. Run the agent ─────────────────────────────────────────
echo [2/3] Scanning "!SRC_DIR!" for pipelines, notebooks, and dataflows...
echo       Output will be written to "!OUT_DIR!"
echo.

uv run agent --src "!SRC_DIR!" --output "!OUT_DIR!"
if errorlevel 1 (
    echo.
    echo [ERROR] Documentation generation failed. Check output above for details.
    pause & exit /b 1
)

:: ── 6. Open output folder ────────────────────────────────────
echo.
echo [3/3] Opening output folder...
start "" explorer "!OUT_DIR!"

echo.
echo ============================================================
echo  Done. Documentation written to: !OUT_DIR!
echo ============================================================
pause
