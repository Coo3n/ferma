@echo off
rem Android Farm launcher for Windows. All logic is in run.ps1 (PowerShell copes with
rem Unicode text and errors reliably; long cmd scripts break on code pages).
rem Double-click this file, or run  run.bat  in cmd,  .\run.bat  in PowerShell.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
if errorlevel 1 pause
