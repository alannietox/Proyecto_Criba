@echo off
title Instalador de Python y Dependencias
echo =======================================================
echo   Instalador de Entorno para Extractor de Noticias INE
echo =======================================================
echo.

:: Comprobar si Python esta instalado
python --version >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [!] Python no se encuentra instalado en el sistema o no esta en el PATH.
    echo Intentando instalar Python usando winget...
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    
    echo.
    echo ==============================================================================
    echo IMPORTANTE: Si Python se acaba de instalar, debes CERRAR esta ventana 
    echo y VOLVER A EJECUTAR el archivo win_instalador.bat para continuar 
    echo con la instalacion de las librerias.
    echo ==============================================================================
    pause
    exit /b
) ELSE (
    echo [OK] Python esta instalado correctamente.
    python --version
)

echo.
echo [1/5] Creando entorno virtual (venv)...
python -m venv venv

echo.
echo [2/5] Activando entorno virtual...
call venv\Scripts\activate

echo.
echo [3/5] Actualizando gestor de paquetes (pip)...
python -m pip install --upgrade pip

echo.
echo [4/5] Instalando librerias necesarias...
pip install openai fpdf2 customtkinter

echo.
echo [5/5] Creando archivo de arranque rapido (iniciar.bat)...
echo @echo off > iniciar.bat
echo call venv\Scripts\activate >> iniciar.bat
echo python app.py >> iniciar.bat
echo exit >> iniciar.bat

echo.
echo =======================================================
echo   ¡Instalacion completada con exito!
echo   Se ha creado un entorno virtual en la carpeta 'venv'.
echo   
echo   Para abrir tu aplicacion facilmente, usa el nuevo 
echo   archivo 'iniciar.bat' que se ha generado.
echo =======================================================
pause

