@echo off
title Lanzador - Extractor de Noticias INE
echo Iniciando el entorno virtual...
if not exist "venv\Scripts\activate.bat" (
    echo.
    echo [ERROR] No se encuentra la carpeta del entorno virtual 'venv'.
    echo Por favor, ejecuta primero 'win_instalador.bat' para instalar todas las dependencias.
    echo.
    pause
    exit /b
)

call venv\Scripts\activate
echo.
echo Ejecutando la aplicacion (app.py)...
python app.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] La aplicacion se ha cerrado de forma inesperada o con errores.
    echo Presiona cualquier tecla para cerrar esta ventana.
    pause
)
