Este repositorio contiene el código fuente de la api de recetas, desarrollada en Python con el framework Flask. A continuación se detallan los pasos para ejecutar la api en un ambiente local.

# Generar un ambiente

Ir a la carpeta del proyecto y ejecutar el siguiente comando:

```bash
python3.9 -m venv venv
```

# Activar el ambiente en Linux o Mac

```bash
source venv/bin/activate 
```

# Activar el ambiente en Windows

```bash
venv\Scripts\Activate.ps1
```

# Instalar dependencias

```bash
pip install -r requirements.txt
```

# En caso de utilizar linux se debe instalar el siguiente paquete

```bash
if ! [[ "18.04 20.04 22.04 23.04" == *"$(lsb_release -rs)"* ]];
then
    echo "Ubuntu $(lsb_release -rs) is not currently supported.";
    exit;
fi

curl https://packages.microsoft.com/keys/microsoft.asc | sudo tee /etc/apt/trusted.gpg.d/microsoft.asc

curl https://packages.microsoft.com/config/ubuntu/$(lsb_release -rs)/prod.list | sudo tee /etc/apt/sources.list.d/mssql-release.list

sudo apt-get update
sudo ACCEPT_EULA=Y apt-get install -y msodbcsql18
# optional: for bcp and sqlcmd
sudo ACCEPT_EULA=Y apt-get install -y mssql-tools18
echo 'export PATH="$PATH:/opt/mssql-tools18/bin"' >> ~/.bashrc
source ~/.bashrc
# optional: for unixODBC development headers
sudo apt-get install -y unixodbc-dev
```

# En caso de utilizar apple silicon, se debe realizar lo siguiente

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/master/install.sh)"
brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release
brew update
HOMEBREW_ACCEPT_EULA=Y brew install msodbcsql18 mssql-tools18
pip install --pre --no-binary :all: pyodbc
```


# Asignar variables de entorno
Se debe crear un archivo .env en la raíz del proyecto con las siguientes variables de entorno:

```bash
ENV = 'LOCALHOST' # LOCALHOST o DEV o PROD
API_KEY = ''
DB_SERVER = ''
DB_NAME = ''
DB_USERNAME = ''
DB_PASSWORD = ''
DB_PORT = ''
SHAREPOINT_BASE_URL = ''
SHAREPOINT_USERNAME = ''
SHAREPOINT_PASSWORD = ''
SHAREPOINT_SITE = ''
```

# Ejecutar el proyecto

```bash
python -m api_susar.api_run
```
