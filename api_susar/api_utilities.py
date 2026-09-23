from dotenv import load_dotenv
import sys
import os

load_dotenv()

# Environment variables
BASE_PATH = sys.path[0]
ENV = os.getenv("ENV")
API_KEY = os.getenv("API_KEY")
PYTESERRACT_PATH = os.getenv("PYTESERRACT_PATH")


# Dates locale
LOCALE = "es_ES.utf8"

# tables

# columns



# Api ficha endpoints
PATH_APPLICATION_CONFIGURATION_ENDPOINT = "/api/abp/application-configuration"
PATH_USERS = '/api/app/selectorList/user'
