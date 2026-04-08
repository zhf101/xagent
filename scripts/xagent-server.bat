@echo off
setlocal EnableDelayedExpansion

:: XAgent Backend Server Management Script
:: Usage: xagent-server.bat [start|stop|restart|status|log|health|help]

set "SERVICE_NAME=xagent-backend"
set "SCRIPT_DIR=%~dp0"
set "PROJECT_DIR=%SCRIPT_DIR%.."
set "VENV_DIR=%PROJECT_DIR%\.venv"

if not defined XAGENT_HOST set "XAGENT_HOST=0.0.0.0"
if not defined XAGENT_PORT set "XAGENT_PORT=8000"
if not defined XAGENT_WORKERS set "XAGENT_WORKERS=1"

set "LOG_DIR=%PROJECT_DIR%\logs"
set "LOG_FILE=%LOG_DIR%\server.log"
set "PID_FILE=%LOG_DIR%\server.pid"

set "APP_MODULE=xagent.web.app:app"
set "PYTHONPATH=%PROJECT_DIR%\src"

goto :main

:log
echo [%~1] %~2
goto :eof

:check_venv
if not exist "%VENV_DIR%\Scripts\python.exe" (
    call :log ERROR "Virtual environment not found: %VENV_DIR%"
    call :log INFO "Please create venv first: python -m venv .venv"
    exit /b 1
)
goto :eof

:check_running
if not exist "%PID_FILE%" goto :not_running
set /p PID=<"%PID_FILE%"
if "!PID!"=="" goto :not_running
tasklist /FI "PID eq !PID!" 2>nul | findstr "!PID!" >nul
if %errorlevel%==0 (
    exit /b 0
) else (
    goto :not_running
)
:not_running
exit /b 1

:cmd_start
call :log INFO "Starting %SERVICE_NAME% service..."

call :check_running
if %errorlevel%==0 (
    set /p PID=<"%PID_FILE%"
    call :log WARN "Service is already running (PID: !PID!)"
    goto :eof
)

call :check_venv
if %errorlevel%==1 exit /b 1

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

set "PYTHON=%VENV_DIR%\Scripts\python.exe"
call :log INFO "Using Python: %PYTHON%"
call :log INFO "Server URL: http://%XAGENT_HOST%:%XAGENT_PORT%"
call :log INFO "Log file: %LOG_FILE%"

set "PYTHONPATH=%PYTHONPATH%"
set "XAGENT_LOG_LEVEL=%XAGENT_LOG_LEVEL:INFO%"

start /B "" "%PYTHON%" -m uvicorn "%APP_MODULE%" --host "%XAGENT_HOST%" --port "%XAGENT_PORT%" --workers "%XAGENT_WORKERS%" >> "%LOG_FILE%" 2>&1

timeout /t 3 /nobreak >nul

:: Find PID by port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%XAGENT_PORT%" ^| findstr "LISTENING"') do (
    echo %%a > "%PID_FILE%"
    goto :pid_found
)

:pid_found
if exist "%PID_FILE%" (
    call :log SUCCESS "Service started successfully"
    call :log INFO "Health check: http://%XAGENT_HOST%:%XAGENT_PORT%/health"
) else (
    call :log ERROR "Failed to start service, check log: %LOG_FILE%"
    exit /b 1
)
goto :eof

:cmd_stop
call :log INFO "Stopping %SERVICE_NAME% service..."

call :check_running
if %errorlevel%==1 (
    call :log WARN "Service is not running"
    if exist "%PID_FILE%" del "%PID_FILE%"
    goto :eof
)

set /p PID=<"%PID_FILE%"
call :log INFO "Killing process (PID: !PID!)..."

taskkill /PID !PID! /F >nul 2>&1
if %errorlevel%==0 (
    call :log SUCCESS "Service stopped"
    if exist "%PID_FILE%" del "%PID_FILE%"
) else (
    call :log ERROR "Failed to stop service"
    exit /b 1
)
goto :eof

:cmd_restart
call :log INFO "Restarting %SERVICE_NAME% service..."
call :cmd_stop
timeout /t 2 /nobreak >nul
call :cmd_start
goto :eof

:cmd_status
call :check_running
if %errorlevel%==0 (
    set /p PID=<"%PID_FILE%"
    call :log SUCCESS "Service is running"
    call :log INFO "URL: http://%XAGENT_HOST%:%XAGENT_PORT%"
    call :log INFO "Log: %LOG_FILE%"
) else (
    call :log WARN "Service is not running"
    if exist "%PID_FILE%" (
        call :log INFO "Found stale PID file: %PID_FILE%"
    )
)
goto :eof

:cmd_log
if not exist "%LOG_FILE%" (
    call :log ERROR "Log file not found: %LOG_FILE%"
    exit /b 1
)
call :log INFO "Showing log (Press Ctrl+C to exit)..."
type "%LOG_FILE%"
goto :eof

:cmd_health
set "URL=http://%XAGENT_HOST%:%XAGENT_PORT%/health"
call :log INFO "Checking health: %URL%"

curl -s "%URL%" >nul 2>&1
if %errorlevel%==0 (
    for /f "usebackq delims=" %%a in (`curl -s "%URL%" 2^>nul`) do (
        call :log SUCCESS "Service healthy: %%a"
    )
) else (
    call :log ERROR "Health check failed"
    exit /b 1
)
goto :eof

:show_help
echo XAgent Backend Server Management Script
echo.
echo Usage: %~nx0 ^<command^>
echo.
echo Commands:
echo   start     Start the service
echo   stop      Stop the service
echo   restart   Restart the service
echo   status    Show service status
echo   log       Show server log
echo   health    Check service health
echo   help      Show this help message
echo.
echo Environment Variables:
echo   XAGENT_HOST      Server host (default: 0.0.0.0)
echo   XAGENT_PORT      Server port (default: 8000)
echo   XAGENT_WORKERS   Worker processes (default: 1)
echo   XAGENT_LOG_LEVEL Log level (default: INFO)
echo.
echo Examples:
echo   %~nx0 start
echo   set XAGENT_PORT=8080 ^&^& %~nx0 start
echo.
goto :eof

:main
set "COMMAND=%~1"
if "!COMMAND!"=="" set "COMMAND=help"

if "!COMMAND!"=="start" (
    call :cmd_start
) else if "!COMMAND!"=="stop" (
    call :cmd_stop
) else if "!COMMAND!"=="restart" (
    call :cmd_restart
) else if "!COMMAND!"=="status" (
    call :cmd_status
) else if "!COMMAND!"=="log" (
    call :cmd_log
) else if "!COMMAND!"=="health" (
    call :cmd_health
) else if "!COMMAND!"=="help" (
    call :show_help
) else if "!COMMAND!"=="--help" (
    call :show_help
) else if "!COMMAND!"=="-h" (
    call :show_help
) else (
    call :log ERROR "Unknown command: !COMMAND!"
    call :show_help
    exit /b 1
)

goto :eof
