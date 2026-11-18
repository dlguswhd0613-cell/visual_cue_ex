@echo off
cd /d "%~dp0"
py select_analysis.py
if errorlevel 1 pause
