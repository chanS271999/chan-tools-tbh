@echo off
chcp 65001 > nul
echo =============================================
echo  chan Tools for TBH - ビルド
echo =============================================
echo.

echo [1/3] PyInstaller をインストール中...
py -3 -m pip install pyinstaller pillow --quiet

echo [2/3] 既存ビルドをクリア中...
if exist "dist\chanToolsTBH" rmdir /s /q "dist\chanToolsTBH"
if exist "build" rmdir /s /q "build"
if exist "chanToolsTBH.spec" del /q "chanToolsTBH.spec"

echo [3/3] ビルド中（数分かかります）...
py -3 -m PyInstaller ^
    --onedir ^
    --windowed ^
    --name "chanToolsTBH" ^
    --icon "icon.ico" ^
    --add-data "icon.ico;." ^
    --add-data "icon.png;." ^
    --collect-all PyQt6 ^
    --hidden-import mss ^
    --hidden-import numpy ^
    --hidden-import PIL ^
    --hidden-import winrt ^
    --collect-all winrt ^
    main.py

if %errorlevel% neq 0 (
    echo ERROR: ビルドに失敗しました。
    pause & exit /b 1
)

echo.
echo =============================================
echo  完了！
echo  dist\chanToolsTBH\chanToolsTBH.exe を起動してください。
echo =============================================
echo.
pause
