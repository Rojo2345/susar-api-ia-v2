from flask import request, make_response, jsonify
from flask_restful import Resource

from api_susar.api.utils.demo_bridge import procesar_pdf_con_demo
from api_susar.api.utils.logger_config import setup_daily_logger

logger = setup_daily_logger()


class Process(Resource):
    # decorators = [apiKeyWrapper]

    def post(self):
        try:
            if "file" not in request.files:
                logger.warning("Request sin campo file.")
                return make_response(jsonify({
                    "message": "No se recibió ningún archivo. Debes enviar el campo 'file'."
                }), 400)

            file = request.files["file"]

            if file.filename == "":
                logger.warning("Archivo recibido sin nombre.")
                return make_response(jsonify({
                    "message": "El archivo recibido no tiene nombre."
                }), 400)

            if not file.filename.lower().endswith(".pdf"):
                logger.warning("Archivo no PDF recibido: %s", file.filename)
                return make_response(jsonify({
                    "message": "El archivo debe ser PDF."
                }), 400)

            provider = request.form.get("provider", "openai")
            preprocess_only = request.form.get("preprocess_only", "false").lower() in {"1", "true", "yes", "si", "sí"}
            debug_preprocess = request.form.get("debug_preprocess", "false").lower() in {"1", "true", "yes", "si", "sí"}

            logger.info(
                "Procesando archivo %s con provider=%s preprocess_only=%s",
                file.filename, provider, preprocess_only
            )

            response = procesar_pdf_con_demo(
                file,
                provider=provider,
                preprocess_only=preprocess_only,
                debug_preprocess=debug_preprocess,
            )

            logger.info("Procesamiento exitoso: %s", file.filename)
            return make_response(jsonify(response), 200)

        except Exception as e:
            logger.exception("Error processing file: %s", e)
            return make_response(jsonify({
                "message": f"Error processing file: {e}"
            }), 500)
