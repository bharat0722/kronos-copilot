@echo off
setlocal

echo ==========================================
echo Kronos Copilot - Kronos Setup
echo ==========================================

cd /d "%~dp0"

if exist "vendor\Kronos-master" (
    echo Kronos source already exists.
    goto :done
)

if not exist "vendor" mkdir vendor

echo Cloning official Kronos repository...
git clone https://github.com/shiyu-coder/Kronos.git "vendor\Kronos-master"

if errorlevel 1 (
    echo.
    echo ERROR: Failed to clone Kronos.
    echo Make sure Git is installed and internet is available.
    pause
    exit /b 1
)

echo.
echo Kronos source cloned successfully.

:done
echo.
echo Setup complete.
pause