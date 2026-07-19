@echo off
copy /Y "%~dp0agent_ui.py" "F:\build\agent_ui.py"
cd /d F:\build
call build_env\Scripts\activate.bat
pyinstaller --onefile --icon=mouse32x32.ico agent_ui.py
copy /Y "F:\build\dist\agent_ui.exe" "%~dp0agent_ui.exe"
pause
