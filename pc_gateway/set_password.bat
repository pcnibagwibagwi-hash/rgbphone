@echo off
cd /d "%~dp0"
echo SIMPLE MODE: ek chhota password chuno (6-24 akshar: letters, numbers, - aur _ ; space nahi).
echo Isi IP aur password se aap aur aapke dost phone app mein connect karoge.
echo.
set /p PW=Naya password:
python rgb_gateway.py set-password %PW%
echo.
echo Ab gateway chalao (run_gateway.bat) aur phone app mein PC ka IP + yahi password daalo.
pause
