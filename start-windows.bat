@echo off
setlocal
cd /d "%~dp0"
call npm run setup
if errorlevel 1 exit /b %errorlevel%
call npm start
