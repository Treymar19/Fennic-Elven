@echo off
cd /d "%~dp0"
echo Installing requirements (first run takes a minute)...
python -m pip install -q -r requirements.txt requests
echo Starting Maparonnarn... your browser will open in a few seconds.
start "" /b cmd /c "timeout /t 8 >nul & start http://127.0.0.1:7860"
python maparonnarn_app.py
pause
