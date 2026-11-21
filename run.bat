@echo off
chcp 65001 >nul
cd /d %~dp0
"C:\Users\weikang\AppData\Local\Programs\Python\Python311\python.exe" -u qishui_auto.py
echo.
pause
