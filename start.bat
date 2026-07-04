@echo off
chcp 65001 >nul
REM Duplicate File Finder - Windows launcher

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

where python >nul 2>&1 || (
    echo ERROR: Python not found. Please install Python first.
    pause
    exit /b 1
)

python -c "import flask" 2>nul || (
    echo Installing Flask...
    pip install flask
)

REM 从 app.py 读取版本号
for /f "tokens=*" %%v in ('powershell -NoProfile -Command "(Select-String -Path app.py -Pattern '__version__\s*=\s*[\x22\x27]([^\x22\x27]+)[\x22\x27]' | Select-Object -First 1).Matches[0].Groups[1].Value"') do set VERSION=%%v

echo.
echo ============================================
echo   Duplicate File Finder v%VERSION%
echo   Open: http://localhost:36901
echo   Press Ctrl+C to stop
echo ============================================
echo.

python gui_app.py
pause
