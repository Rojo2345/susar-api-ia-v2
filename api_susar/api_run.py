from api_susar.api.endpoints import susar as exposed_susar
import api_susar.api.config as config
from flask_restful import Api
from api_susar.api_utilities import ENV
from waitress import serve
import argparse

from api_susar.api.utils.logger_config import setup_daily_logger

app = config.app
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
api = Api(app)

api.add_resource(exposed_susar.Process, "/susar")

logger = setup_daily_logger()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port", help="Port to run the api on", default=5002, required=False
    )
    args = parser.parse_args()
    api_port = int(args.port)

    logger.info("Iniciando API SUSAR en puerto %s. ENV=%s", api_port, ENV)

    if ENV == "LOCALHOST":
        app.run(host="0.0.0.0", port=5002, debug=True)
    else:
        serve(app, host="0.0.0.0", port=api_port)
