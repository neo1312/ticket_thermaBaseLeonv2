================================================================================
                     TICKET PRINTER - THERMAL TICKET SERVER
================================================================================

Imprime tickets de venta desde cualquier dispositivo en la red LAN a una
impresora termica compartida via CUPS.

--------------------------------------------------------------------------------
REQUISITOS
--------------------------------------------------------------------------------

- PC con Linux (Debian/Ubuntu) conectada via USB a una impresora termica
- Python 3.9+
- Red local con las PCs conectadas
- Impresora termica configurada en CUPS con nombre "ferre"

--------------------------------------------------------------------------------
INSTALACION (UN SOLO COMANDO)
--------------------------------------------------------------------------------

En la PC que tiene la impresora conectada via USB:

    1. Abrir terminal
    2. Ir al directorio del proyecto:
         cd ~/Documents/ticket_thermaBaseLeonv2/ticket_printer
    3. Ejecutar:
         bash install.sh

Esto crea el entorno virtual, instala dependencias (requests, flask) y genera
dos accesos directos en el Escritorio.

--------------------------------------------------------------------------------
CONFIGURACION DE RED (PC CON IMPRESORA - 192.168.1.100)
--------------------------------------------------------------------------------

1. IP ESTATICA (opcional pero recomendada):
   Configurar IP fija via nmcli o configuracion de red:
     Ej: 192.168.1.100/24, gateway 192.168.1.1

2. ABRIR PUERTO 5000 (para modo web):
     sudo ufw allow 5000
     -o-
     sudo iptables -A INPUT -p tcp --dport 5000 -j ACCEPT

3. CUPS - COMPARTIR IMPRESORA EN LA RED:
     En /etc/cups/cupsd.conf:
       Port 631
       Allow from 192.168.1.0/24
     Luego:
       sudo systemctl restart cups
       sudo lpadmin -p ferre -E -v usb://... (segun corresponda)

4. VERIFICAR IMPRESORA:
     lpstat -p -d

--------------------------------------------------------------------------------
MODO DE USO
--------------------------------------------------------------------------------

MODO GUI (local):
  $ ./run.sh
  -o- Doble click en "Ticket Printer" del Escritorio
  Ingresar Sale ID, Vista Previa, Imprimir.

MODO WEB (acceso desde celular/tablet):
  $ ./run.sh web
  -o- Doble click en "Ticket Printer (Web)" del Escritorio
  Desde el celular (misma red WiFi) abrir:
     http://192.168.1.100:5000
  Ingresar Sale ID, Vista Previa, Imprimir.

  El servidor web corre en el puerto 5000.

--------------------------------------------------------------------------------
CONFIGURACION INICIAL
--------------------------------------------------------------------------------

El archivo printer_config.json se crea con estos valores por defecto:

  {
    "server_url": "https://5.75.162.179",
    "cups_printer": "ferre",
    "store_name": "Ferreteria Leon"
  }

- server_url: URL del servidor baseleonV2 (API de ventas)
- cups_printer: nombre de la impresora en CUPS
- store_name: nombre del negocio que aparece en el ticket

Se puede editar a mano o desde la interfaz GUI (boton de configuracion).

--------------------------------------------------------------------------------
INSTALACION EN SEGUNDA PC (solo cliente de impresion)
--------------------------------------------------------------------------------

En una PC sin impresora USB (ej: 192.168.1.144):

  1. Agregar impresora remota via IPP:
       sudo lpadmin -p ferre -E -v ipp://192.168.1.100:631/printers/ferre
  2. Clonar repositorio e instalar:
       bash install.sh
  3. Editar printer_config.json si es necesario

--------------------------------------------------------------------------------
ESTRUCTURA DE ARCHIVOS
--------------------------------------------------------------------------------

ticket_printer/
  main.py               - Logica principal: GUI + servidor web Flask
  run.sh                - Lanzador (GUI por defecto, --web para servidor)
  install.sh            - Instalador one-click: venv + deps + accesos directos
  requirements.txt      - Dependencias Python
  printer_config.json   - Configuracion (server_url, cups_printer, store_name)
  README.txt            - Este archivo

--------------------------------------------------------------------------------
SOLUCION DE PROBLEMAS
--------------------------------------------------------------------------------

- "No module named flask": ejecutar:
    ./venv/bin/pip install flask

- "No se puede conectar al servidor": verificar server_url en printer_config.json

- "Error al imprimir": verificar que CUPS tenga la impresora configurada:
    lpstat -p -d

- No responde el modo web: verificar firewall, que el proceso corra:
    curl http://localhost:5000/
    cat run.log

- El log de ejecucion se guarda en: ticket_printer/run.log
