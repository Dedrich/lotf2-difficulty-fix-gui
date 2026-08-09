@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo  Building portable LOTF2 Difficulty Fix EXE
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo Python not found on PATH.
  pause
  exit /b 1
)

python -m pip install --upgrade pip pyinstaller >nul
if errorlevel 1 (
  echo Failed to install PyInstaller.
  pause
  exit /b 1
)

if exist build rmdir /s /q build
if exist dist\LOTF2_Difficulty_Fix.exe del /q dist\LOTF2_Difficulty_Fix.exe

python -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "LOTF2_Difficulty_Fix" ^
  --paths . ^
  --hidden-import lotf2_difficulty ^
  --hidden-import lotf2_difficulty.save_format ^
  --hidden-import lotf2_difficulty.properties ^
  --hidden-import lotf2_difficulty.slots ^
  --hidden-import lotf2_difficulty.patch ^
  app.py

if errorlevel 1 (
  echo.
  echo BUILD FAILED
  pause
  exit /b 1
)

echo.
echo ============================================
echo  OK: dist\LOTF2_Difficulty_Fix.exe
echo ============================================
echo Portable — copy that single file anywhere.
echo.
pause
