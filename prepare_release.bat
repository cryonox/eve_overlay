@echo off
setlocal enabledelayedexpansion

for /f "tokens=*" %%i in ('git describe --tags --exact-match HEAD 2^>nul') do set TAG=%%i

if "%TAG%"=="" (
    echo Error: No git tag found on current HEAD. Please tag the commit first.
    exit /b 1
)

echo Building release for tag: %TAG%

echo.
echo === Building exe with PyInstaller ===
pyinstaller eve_overlay.spec
if errorlevel 1 (
    echo Error: PyInstaller build failed.
    exit /b 1
)

echo.
echo === Copying cache files ===
if not exist "dist\cache" mkdir "dist\cache"

for %%f in (cache\*.bin) do (
    copy "%%f" "dist\cache\" >nul
    echo Copied %%f
)

if exist "cache\names.pkl" (
    copy "cache\names.pkl" "dist\cache\" >nul
    echo Copied cache\names.pkl
)

echo.
echo === Copying config.yaml ===
if exist "config.yaml" (
    copy "config.yaml" "dist\" >nul
    echo Copied config.yaml
)

echo.
echo === Copying ships.json ===
if exist "ships.json" (
    copy "ships.json" "dist\" >nul
    echo Copied ships.json
)



echo.
echo === Creating zip archive ===
if exist "%TAG%.zip" del "%TAG%.zip"
powershell -command "Compress-Archive -Path 'dist\*' -DestinationPath '%TAG%.zip'"

echo.
echo Release %TAG% prepared successfully!
