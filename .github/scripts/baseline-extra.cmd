@echo off
setlocal

python -m pip install -e .[dev]
if errorlevel 1 exit /b %ERRORLEVEL%

python -m pytest
