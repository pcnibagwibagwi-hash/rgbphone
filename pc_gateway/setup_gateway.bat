@echo off
REM Run ONCE: right-click -> "Run as administrator".
cd /d "%~dp0"
net session >nul 2>&1
if errorlevel 1 (
  echo Right-click this file and choose "Run as administrator".
  pause & exit /b 1
)

echo [1/4] Removing the OLD unsafe OpenRGB port forward and firewall rule...
for /f "tokens=1,2" %%a in ('netsh interface portproxy show v4tov4 ^| findstr /r "6742"') do (
  netsh interface portproxy delete v4tov4 listenaddress=%%a listenport=%%b >nul 2>&1
)
netsh advfirewall firewall delete rule name="OpenRGB SDK" >nul 2>&1

echo [2/4] Allowing ONLY your home network to reach the gateway (TCP 6743)...
netsh advfirewall firewall delete rule name="RGB Gateway" >nul 2>&1
netsh advfirewall firewall add rule name="RGB Gateway" dir=in action=allow protocol=TCP localport=6743 remoteip=localsubnet >nul

echo [3/4] Installing the one needed Python package...
python -m pip install --upgrade cryptography
if errorlevel 1 ( echo Python/pip not found. Install Python from python.org first. & pause & exit /b 1 )

echo [4/4] Creating the gateway certificate...
python rgb_gateway.py init
echo.
echo DONE. Next: double-click add_device.bat to get your pairing code.
pause
