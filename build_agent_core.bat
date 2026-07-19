@echo off
copy /Y "%~dp0agent_core.py" "F:\build\agent_core.py"
cd /d F:\build
call build_env\Scripts\activate.bat
pyinstaller --onefile --noconsole --icon=core.ico agent_core.py
copy /Y "F:\build\dist\agent_core.exe" "%~dp0agent_core.exe"
pause
