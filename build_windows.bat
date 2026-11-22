@echo off
REM ==========================================================================
REM  EduKit - build the Windows program and installer (double-click me)
REM
REM  Needs once on the build PC (not on the classroom PCs):
REM    * Python 3.12 from python.org  (tick "Add python.exe to PATH")
REM    * Inno Setup 6 (optional, for the installer): https://jrsoftware.org/isdl.php
REM
REM  Result:
REM    desktop\dist\installer\EduKit-Setup-0.1.0.exe   <- send this to schools
REM    desktop\dist\EduKit-portable.zip                <- no-install version (unzip, run EduKit.exe)
REM ==========================================================================
setlocal
cd /d "%~dp0desktop"

set PY=
where py >nul 2>nul && set PY=py -3.12
if "%PY%"=="" (where python >nul 2>nul && set PY=python)
if "%PY%"=="" (
  echo [X] Python 3.12 was not found. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
  pause & exit /b 1
)

echo [1/4] Preparing build environment...
if not exist .venv-build (%PY% -m venv .venv-build || (echo [X] could not create venv & pause & exit /b 1))
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip >nul
python -m pip install -r requirements.txt pyinstaller || (echo [X] pip install failed - is the internet connected? & pause & exit /b 1)

echo [2/4] Building EduKit.exe ...
if exist dist\EduKit rmdir /s /q dist\EduKit
pyinstaller --noconfirm --clean packaging\edukit.spec || (echo [X] PyInstaller failed & pause & exit /b 1)

echo [3/4] Creating portable zip...
if exist dist\EduKit-portable.zip del dist\EduKit-portable.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\EduKit\*' -DestinationPath 'dist\EduKit-portable.zip'"

echo [4/4] Creating installer...
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LocalAppData%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LocalAppData%\Programs\Inno Setup 6\ISCC.exe"
if not defined ISCC goto :no_inno

"%ISCC%" /Q packaging\edukit.iss
if errorlevel 1 goto :inno_failed
echo.
echo [OK] Installer ready: desktop\dist\installer\EduKit-Setup-0.1.0.exe
goto :done

:no_inno
echo [!] Inno Setup 6 not found - skipped the installer.
echo     The portable version is ready: desktop\dist\EduKit-portable.zip
echo     Install Inno Setup 6 from https://jrsoftware.org/isdl.php and run this file again.
goto :done

:inno_failed
echo [X] Inno Setup failed - see the messages above.

:done
echo.
explorer dist
pause
