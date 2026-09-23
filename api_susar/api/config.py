from api_susar.api_utilities import BASE_PATH, LOCALE
from flask import Flask
from flask_cors import CORS
from flask_talisman import Talisman
import locale


app = Flask(__name__, root_path=BASE_PATH)

# TODO: configure Talisman for hosted app

# local development
CORS(app, supports_credentials=True)  # Change to True if we ever need to use cookies

# locale.setlocale(locale.LC_TIME, LOCALE)
