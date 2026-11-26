@echo off
setlocal
where pythonw.exe >nul 2>nul
if not errorlevel 1 (
    python.exe -c "import sys,tkinter;sys.exit(sys.version_info < (3,10))" >nul 2>nul
    if not errorlevel 1 (
        start "" pythonw.exe -B "%~dp0bundle_reader.pyw"
        exit /b 0
    )
)
py -3 -c "import sys,tkinter;sys.exit(sys.version_info < (3,10))" >nul 2>nul
if not errorlevel 1 (
    start "" pyw.exe -3 -B "%~dp0bundle_reader.pyw"
    exit /b 0
)
echo Python 3.10 or later with Tcl/Tk is required. See README.md.
pause
exit /b 1
