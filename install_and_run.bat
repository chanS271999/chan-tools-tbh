@echo off
chcp 65001 > nul
echo =============================================
echo  Log Color Monitor - セットアップ & 起動
echo =============================================
echo.

where py >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python が見つかりません。
    echo  https://www.python.org/ から Python 3.10 以上をインストールしてください。
    pause & exit /b 1
)

echo [1/2] 必要パッケージをインストール中...
py -3 -m pip install PyQt6 mss numpy --quiet
if %errorlevel% neq 0 (
    echo ERROR: パッケージのインストールに失敗しました。
    pause & exit /b 1
)

echo [2/2] アプリを起動しています...
for /f "delims=" %%i in ('py -3 -c "import sys; print(sys.executable.replace('python.exe','pythonw.exe'))"') do set PYTHONW=%%i
start "" "%PYTHONW%" "%~dp0main.py"
exit
