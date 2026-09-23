import os
import tempfile
import uuid
from typing import Any, Dict

from api_susar.api.utils.demo_ia import procesar_archivo_con_ia
from api_susar.api.utils.logger_config import setup_daily_logger

logger = setup_daily_logger()


def _clean_value(value: Any) -> Any:
    """Campos faltantes se envían vacíos para mantener compatibilidad externa."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return value


def _missing_fields(selected: Dict[str, Any]) -> list:
    fields = {
        "reporte": "Reporte",
        "id_reporte": "Id del reporte",
        "fecha_reporte": "Fecha del reporte",
        "pais": "País",
        "tipo": "Tipo",
    }
    return [label for key, label in fields.items() if not selected.get(key)]


def _missing_fields(selected: Dict[str, Any]) -> list:
    fields = {
        "reporte": "Reporte",
        "id_reporte": "Id del reporte",
        "fecha_reporte": "Fecha del reporte",
        "pais": "País",
        "tipo": "Tipo",
    }
    return [label for key, label in fields.items() if not selected.get(key)]


def convertir_a_formato_api_original(resultado_demo: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    selected = resultado_demo.get("selected_result") or resultado_demo.get("heuristics") or {}

    tipo = _clean_value(selected.get("tipo"))
    if isinstance(tipo, str):
        tipo = tipo.upper()

    page_result = {
        "Reporte": _clean_value(selected.get("reporte")),
        "Id del reporte": _clean_value(selected.get("id_reporte")),
        "Fecha del reporte": _clean_value(selected.get("fecha_reporte")),
        "País": _clean_value(selected.get("pais")),
    }

    if tipo in {"INITIAL", "FOLLOWUP"}:
        page_result[tipo] = tipo

    return {"page_1": page_result}


def procesar_pdf_con_demo(
    file_storage,
    provider: str = "openai",
    preprocess_only: bool = False,
    debug_preprocess: bool = False,
) -> Dict[str, Any]:
    filename = file_storage.filename or "archivo.pdf"
    execution_id = str(uuid.uuid4())[:8]
    execution_id = str(uuid.uuid4())[:8]

    if not filename.lower().endswith(".pdf"):
        raise ValueError("El archivo debe ser PDF.")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        temp_path = tmp.name
        file_storage.save(temp_path)

    logger.info("[%s] Archivo recibido: %s", execution_id, filename)
    logger.info("Archivo temporal guardado en: %s", temp_path)

    try:
        resultado_demo = procesar_archivo_con_ia(
            input_path=temp_path,
            provider=provider,
            max_pages=3,
            dpi=200,
            result_view="best",
            preprocess_only=preprocess_only,
            debug_preprocess=debug_preprocess,
        )

        logger.info("AI status: %s", resultado_demo.get("ai_status"))
        logger.info("Metodo seleccionado: %s", resultado_demo.get("selected_method"))
        logger.info("Resultado seleccionado: %s", resultado_demo.get("selected_result"))
        if resultado_demo.get("ai_error"):
            logger.warning("Problema con proveedor IA; se conservó el resultado disponible: %s", resultado_demo["ai_error"])

        selected = resultado_demo.get("selected_result") or resultado_demo.get("heuristics") or {}
        processing_status = "PARTIAL" if resultado_demo.get("selected_method") == "heuristics_fallback" else "SUCCESS"

        logger.info(
            "[%s] FINAL STATUS=%s | method=%s | missing_fields=%s",
            execution_id,
            processing_status,
            resultado_demo.get("selected_method"),
            _missing_fields(selected),
        )

        selected = resultado_demo.get("selected_result") or resultado_demo.get("heuristics") or {}

        if resultado_demo.get("selected_method") == "heuristics_fallback":
            logger.warning(
                "[%s] RESULTADO PARCIAL POR HEURÍSTICAS | campos_faltantes=%s | motivo=%s",
                execution_id,
                _missing_fields(selected),
                resultado_demo.get("ai_error"),
            )
        else:
            logger.info("[%s] RESULTADO COMPLETO IA | metodo=%s", execution_id, resultado_demo.get("selected_method"))

        logger.info(
            "[%s] EXTRACCION FINAL | id=%s | fecha=%s | pais=%s | reporte=%s | tipo=%s",
            execution_id,
            selected.get("id_reporte", ""),
            selected.get("fecha_reporte", ""),
            selected.get("pais", ""),
            selected.get("reporte", ""),
            selected.get("tipo", ""),
        )

        response = convertir_a_formato_api_original(resultado_demo)

        # Modo de prueba: entrega además lo ocurrido antes de OpenAI.
        if debug_preprocess:
            response["debug_pre_openai"] = {
                "ocr_status": resultado_demo.get("ocr_status"),
                "ocr_preview": resultado_demo.get("ocr_preview"),
                "heuristics": resultado_demo.get("heuristics"),
                "ai_status": resultado_demo.get("ai_status"),
                "ai_error": resultado_demo.get("ai_error"),
                "selected_method": resultado_demo.get("selected_method"),
            }

        logger.info("Respuesta API: %s", response)
        return response

    finally:
        try:
            os.remove(temp_path)
            logger.info("Archivo temporal eliminado: %s", temp_path)
        except OSError:
            logger.warning("No se pudo eliminar archivo temporal: %s", temp_path)
