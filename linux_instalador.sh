#!/bin/bash
echo "======================================================="
echo "  Instalador de Entorno para Extractor de Noticias INE"
echo "======================================================="
echo ""

# Comprobar si python3 esta instalado
if ! command -v python3 &> /dev/null
then
    echo "[!] Python3 no se encuentra instalado en el sistema."
    echo "Intentando instalar Python3 y dependencias usando apt..."
    sudo apt update
    sudo apt install -y python3 python3-venv python3-pip python3-tk
    
    if ! command -v python3 &> /dev/null
    then
        echo "=============================================================================="
        echo "Error: No se pudo instalar Python3. Por favor, instalelo manualmente."
        echo "=============================================================================="
        exit 1
    fi
else
    echo "[OK] Python3 esta instalado correctamente."
    python3 --version
    
    # Comprobar e instalar python3-venv y tkinter si faltan (común en Ubuntu/Debian)
    echo "Asegurando dependencias del sistema (venv y tkinter para la GUI)..."
    sudo apt-get install -y python3-venv python3-tk || sudo apt install -y python3-venv python3-tk
fi

echo ""
echo "[1/5] Creando entorno virtual (venv)..."
python3 -m venv venv

echo ""
echo "[2/5] Activando entorno virtual..."
source venv/bin/activate

echo ""
echo "[3/5] Actualizando gestor de paquetes (pip)..."
python3 -m pip install --upgrade pip

echo ""
echo "[4/5] Instalando librerias necesarias..."
pip install openai fpdf2 customtkinter

echo ""
echo "[5/5] Creando archivo de arranque rapido (iniciar.sh)..."
cat << 'EOF' > iniciar.sh
#!/bin/bash
source venv/bin/activate
python3 app.py
EOF
chmod +x iniciar.sh

echo ""
echo "======================================================="
echo "  ¡Instalacion completada con exito!"
echo "  Se ha creado un entorno virtual en la carpeta 'venv'."
echo "  "
echo "  Para abrir tu aplicacion facilmente, usa el nuevo "
echo "  archivo './iniciar.sh' que se ha generado."
echo "======================================================="
