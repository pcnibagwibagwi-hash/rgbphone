@echo off
REM Start OpenRGB first (Settings -> SDK Server -> Start Server), then run this.
cd /d "%~dp0"
python rgb_gateway.py run
pause
