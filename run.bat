@echo off
setlocal

REM ------------------------------------------
REM Healthcare Eligibility Automation Launcher
REM ------------------------------------------

REM Always run from the folder this file lives in
cd /d "%~dp0"

echo ==========================================
echo Healthcare Eligibility Automation
echo ==========================================
echo.

REM Detect Python (python preferred, fallback to py)
where python >nul 2>nul
if %errorlevel%==0 (
    set "PY=python"
) else (
    where py >nul 2>nul
    if %errorlevel%==0 (
        set "PY=py"
    ) else (
        echo ERROR: Python not found.
        echo Please install Python 3.x and try again.
        pause
        exit /b 1
    )
)

REM Create virtual environment if missing
if not exist ".venv\" (
    echo Creating virtual environment...
    %PY% -m venv .venv
)

REM Activate virtual environment
call ".venv\Scripts\activate.bat"

REM Install / update dependencies
echo Installing dependencies...
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt

echo.
echo Running eligibility automation...
python src\run.py

echo.
echo ==========================================
echo Run complete.
echo Check the outputs\YYYY-MM\ folder for results.
echo ==========================================
echo.

pause
endlocal
