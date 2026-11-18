@echo off
cd /d "%~dp0"
set /p NAME=Phone ka naam (jaise myphone, sirf letters/numbers): 
python rgb_gateway.py add-device %NAME%
echo.
echo Upar wala code (RGB1....) phone app me paste karo. Ye sirf ek baar dikhega.
pause
