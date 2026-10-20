@echo off
rem Run Python with the QGIS 4 environment (headless). Usage: scripts\qgis_python.bat script.py [args]
rem Override the install location with QGIS_ROOT, e.g. set QGIS_ROOT=C:\Program Files\QGIS 4.2.3
if "%QT_QPA_PLATFORM%"=="" set QT_QPA_PLATFORM=offscreen
if "%QGIS_ROOT%"=="" set "QGIS_ROOT=C:\Program Files\QGIS 4.2.3"
call "%QGIS_ROOT%\bin\python-qgis.bat" %*
