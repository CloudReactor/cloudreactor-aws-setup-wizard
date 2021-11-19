@ECHO OFF
REM Run this the first time you clone this repository or whenever you pull the branch.
type NUL >> .env
docker compose build wizard
echo.
echo The CloudReactor AWS Quick Start Wizard is now built and ready to run!
echo Run it by typing
echo.
echo   .\wizard.bat
echo.
