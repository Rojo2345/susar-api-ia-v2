
import os
import re
import io
import json
import csv
import base64
import argparse
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple, List, Union

from PIL import Image
from api_susar.api_utilities import PYTESERRACT_PATH

# -------------------------
# Regex / Heuristicas
# -------------------------
COUNTRY_RE = re.compile(
    r"\b(CHILE|CHINA|ARGENTINA|BRAZIL|PERU|COLOMBIA|MEXICO|UNITED STATES(?: OF AMERICA)?)\b",
    re.IGNORECASE
)
PV_RE = re.compile(r"\bPV\d{8,}\b", re.IGNORECASE)

REPORT_ID_RE = re.compile(
    r"\b(?:PV\d{8,}|[A-Z]{2}-\d{6,}-\d{4,})\b",
    re.IGNORECASE
)

TYPE_RE = re.compile(r"\b(FOLLOWUP|INITIAL)\b", re.IGNORECASE)

# -------------------------
# Output formats
# -------------------------
def as_pretty(res: dict, selected_view: str = "best") -> str:
    selected = build_selected_payload(res, selected_view)

    def block(title: str, d: dict) -> str:
        return (
            f"{title}\n"
            f"  reporte       : {d.get('reporte')}\n"
            f"  id_reporte    : {d.get('id_reporte')}\n"
            f"  fecha_reporte : {d.get('fecha_reporte')}\n"
            f"  pais          : {d.get('pais')}\n"
            f"  tipo          : {d.get('tipo')}"
        )

    parts = [
        f"INPUT       : {res.get('input')}",
        f"PROVIDER    : {res.get('provider')}",
        f"OCR_STATUS  : {res.get('ocr_status')}",
        f"SELECTED_VIEW   : {selected['selected_view']}",
        f"SELECTED_METHOD : {selected['selected_method']}",
        block("RESULTADO", selected["selected_result"]),
    ]
    return "\n".join(parts) + "\n"

def as_table(res: dict, selected_view: str = "best") -> str:
    selected = build_selected_payload(res, selected_view)
    d = selected["selected_result"]

    headers = ["metodo", "reporte", "id_reporte", "fecha_reporte", "pais", "tipo"]
    row = [
        str(selected["selected_method"]),
        str(d.get("reporte")),
        str(d.get("id_reporte")),
        str(d.get("fecha_reporte")),
        str(d.get("pais")),
        str(d.get("tipo")),
    ]

    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    out.append("| " + " | ".join(row) + " |")
    return "\n".join(out) + "\n"

def write_csv(res: dict, path: str, selected_view: str = "best") -> None:
    selected = build_selected_payload(res, selected_view)
    d = selected["selected_result"]

    headers = ["metodo", "reporte", "id_reporte", "fecha_reporte", "pais", "tipo"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        w.writerow([
            selected["selected_method"],
            d.get("reporte"),
            d.get("id_reporte"),
            d.get("fecha_reporte"),
            d.get("pais"),
            d.get("tipo"),
        ])
# -------------------------
# Utils
# -------------------------
def pil_to_png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def pil_to_data_url(img: Image.Image) -> str:
    b = pil_to_png_bytes(img)
    b64 = base64.b64encode(b).decode("utf-8")
    return f"data:image/png;base64,{b64}"

def try_ocr(img: Image.Image) -> Tuple[Optional[str], str]:
    try:
        import pytesseract
    except Exception as exc:
        return None, f"no_pytesseract: {type(exc).__name__}: {exc}"

    try:
        if not PYTESERRACT_PATH:
            return None, "tesseract_config_error: PYTESERRACT_PATH no está definida"

        tesseract_path = str(PYTESERRACT_PATH).strip().strip('"').strip("'")
        if not os.path.isfile(tesseract_path):
            return None, f"tesseract_config_error: no existe {tesseract_path}"

        pytesseract.pytesseract.tesseract_cmd = tesseract_path

        big = img.resize((img.width * 2, img.height * 2))
        text = pytesseract.image_to_string(big, lang="eng", config="--oem 3 --psm 6")
        text = re.sub(r"[ \t]+", " ", text).strip()

        if not text:
            return None, "ocr_empty"
        return text, "ok"
    except Exception as exc:
        return None, f"tesseract_error: {type(exc).__name__}: {exc}"
    
def try_ocr_multi(images: List[Image.Image], max_pages_ocr: int = 3) -> Tuple[Optional[str], str]:
    if not images:
        return None, "no_images"

    texts = []
    statuses = []
    for img in images[:max_pages_ocr]:
        txt, st = try_ocr(img)
        statuses.append(st)
        if txt:
            texts.append(txt)

    if texts:
        return "\n\n".join(texts), "ok_multi"
    if statuses and all(s == "no_pytesseract" for s in statuses):
        return None, "no_pytesseract"
    return None, "tesseract_error"

def normalizar(s: str) -> Optional[str]:
    if not s:
        return None
    s = s.strip()

    # dd-MMM-yyyy (04-Dec-2025)
    m = re.search(r"\b(\d{1,2})[-/ ]([A-Za-z]{3,4})[-/ ](\d{4})\b", s)
    if m:
        d = int(m.group(1))
        mon = m.group(2).upper()[:3]
        y = m.group(3)
        return f"{d:02d}-{mon}-{y}"

    # dd/mm/yyyy or dd-mm-yyyy
    m = re.search(r"\b(\d{1,2})[-/](\d{1,2})[-/](\d{4})\b", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        mon_map = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
        if 1 <= mo <= 12:
            return f"{d:02d}-{mon_map[mo-1]}-{y}"
    return None

def _clean_ocr_text(text: str) -> str:
    """Normaliza espacios y saltos sin destruir la estructura por líneas."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _valid_report_id_candidate(value: str) -> bool:
    """Valida candidatos de ID de reporte."""
    if not value:
        return False

    value = value.strip().upper().rstrip(".,;:")
    if len(value) < 6:
        return False

    # Debe tener letras y números
    if not re.search(r"[A-Z]", value):
        return False
    if not re.search(r"\d", value):
        return False

    # Evitar fechas/campos que OCR pueda capturar
    invalid = [
        "DATE",
        "REPORT",
        "STUDY",
        "PATIENT",
        "CENTER",
        "NUMBER",
    ]
    if any(x in value for x in invalid):
        return False

    return True


def _extract_report_id(text: str) -> Optional[str]:
    """
    Extrae el ID más completo posible.

    Prioridad:
    1) Campos explícitos CIOMS (Worldwide UID, MFR Control, Case number)
    2) Candidatos generales
    3) Si hay varios candidatos válidos, gana el más largo
    """
    candidates = []

    labeled_patterns = [
        # Worldwide UID - CN-009507513-2328416
        r"WORLDWIDE\s+UID\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]+)",
        # MFR CONTROL NO. CN-009507513-2328416
        r"MFR\.?\s*CONTROL\s*NO\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]+)",
        r"CONTROL\s*NO\.?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]+)",
        # Case number: CN-009507513-2328416
        r"CASE\s+NUMBER\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-/]+)",
        r"SUSPECT\s+ADVERSE\s+REACTION\s+REPORT\s*\n\s*([A-Z0-9][A-Z0-9\-/]+)",
    ]

    for pattern in labeled_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidate = match.group(1).strip().upper().rstrip(".,;:")
            if _valid_report_id_candidate(candidate):
                candidates.append(candidate)

    general_patterns = [
        r"\b\d{4}-AER-\d{4,}(?:-\d+)*\b",
        r"\bPV\d{8,}(?:-\d+)*\b",
        r"\b[A-Z]{2,10}-\d+(?:-\d+)+\b",
        r"\b[A-Z]{2,10}-\d{5,}\b",
    ]

    for pattern in general_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            candidate = match.group(0).strip().upper()
            if _valid_report_id_candidate(candidate):
                candidates.append(candidate)

    if not candidates:
        return None

    # Eliminar duplicados y quedarse con el ID más informativo.
    candidates = list(set(candidates))
    return max(candidates, key=len)


def _extract_country(text: str) -> Optional[str]:
    aliases = {
        "CHILE": "CHILE",
        "CHINA": "CHINA",
        "ARGENTINA": "ARGENTINA",
        "BRAZIL": "BRAZIL",
        "BRASIL": "BRAZIL",
        "PERU": "PERU",
        "PERÚ": "PERU",
        "COLOMBIA": "COLOMBIA",
        "MEXICO": "MEXICO",
        "MÉXICO": "MEXICO",
        "UNITED STATES OF AMERICA": "UNITED STATES OF AMERICA",
        "UNITED STATES": "UNITED STATES",
        "USA": "UNITED STATES",
    }
    values = sorted(aliases, key=len, reverse=True)
    country_union = "|".join(re.escape(v) for v in values)

    # Prioriza el campo del paciente para evitar capturar la dirección del fabricante.
    patterns = [
        rf"(?:1a\.?\s*)?COUNTRY\s*[:\-]?\s*(?:\n\s*)?({country_union})\b",
        rf"PA[IÍ]S\s*[:\-]?\s*(?:\n\s*)?({country_union})\b",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return aliases.get(m.group(1).upper(), m.group(1).upper())

    # Fallback limitado a la parte inicial de la primera página.
    head = text[:2500]
    for value in values:
        if re.search(rf"\b{re.escape(value)}\b", head, re.IGNORECASE):
            return aliases[value]
    return None


def _date_score(text: str, start: int, end: int, label: str) -> float:
    """
    Puntúa una fecha encontrada cerca de una etiqueta CIOMS.
    Más cercanía = más confianza.
    """
    distance = min(abs(start), abs(end))
    score = 100 - distance

    # Bonus si está en la misma línea de la etiqueta.
    context = text[max(0, start-80):min(len(text), end+80)]
    if "\n" not in context:
        score += 15

    # Bonus por etiqueta principal.
    if "DATE OF THIS REPORT" in label.upper():
        score += 50

    return score


def _extract_report_date(text: str) -> Optional[str]:
    """
    Extrae la fecha principal del CIOMS.

    Prioridad:
    1) Fecha dentro de la sección de cabecera del reporte.
    2) DATE OF THIS REPORT.
    3) REPORT DATE.
    4) DATE RECEIVED BY MANUFACTURER.
    5) fallback general.

    Se evita tomar fechas de tratamientos, eventos o antecedentes.
    """

    date_token = (
        r"\d{1,2}\s*[-/]\s*"
        r"(?:JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|APR(?:IL)?|MAY|JUN(?:E)?|"
        r"JUL(?:Y)?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|NOV(?:EMBER)?|DEC(?:EMBER)?)"
        r"\s*[-/]\s*\d{4}"
        r"|\d{1,2}\s*[-/]\s*\d{1,2}\s*[-/]\s*\d{4}"
    )

    candidates = []

    # Bloque superior del CIOMS. Normalmente contiene:
    # Date of this report + Report type.
    header_blocks = re.findall(
        r"(?:DATE\s+OF\s+THIS\s+REPORT|25A\.\s*REPORT\s+TYPE|REPORT\s+TYPE)"
        r"[\s\S]{0,250}",
        text,
        re.IGNORECASE,
    )

    for block in header_blocks:
        for m in re.finditer(date_token, block, re.IGNORECASE):
            value = normalizar(m.group(0))
            if value:
                candidates.append({
                    "date": value,
                    "score": 200,
                    "source": "header_block",
                })

    # Etiqueta explícita DATE OF THIS REPORT.
    for label in [
        r"DATE\s+OF\s+THIS\s+REPORT",
        r"REPORT\s+DATE",
        r"FECHA\s+DEL\s+REPORTE",
    ]:
        for m in re.finditer(label, text, re.IGNORECASE):
            start = max(0, m.start() - 120)
            end = min(len(text), m.end() + 120)
            block = text[start:end]

            for date_match in re.finditer(date_token, block, re.IGNORECASE):
                value = normalizar(date_match.group(0))
                if value:
                    candidates.append({
                        "date": value,
                        "score": 150,
                        "source": label,
                    })

    # Fecha recibida por fabricante solo como respaldo.
    for label in [
        r"DATE\s+RECEIVED\s+BY\s+MANUFACTURER",
        r"RECEIPT\s+DATE",
    ]:
        for m in re.finditer(label, text, re.IGNORECASE):
            start = max(0, m.start() - 80)
            end = min(len(text), m.end() + 80)
            block = text[start:end]

            for date_match in re.finditer(date_token, block, re.IGNORECASE):
                value = normalizar(date_match.group(0))
                if value:
                    candidates.append({
                        "date": value,
                        "score": 50,
                        "source": label,
                    })

    if candidates:
        # La fecha de cabecera siempre gana.
        best = max(candidates, key=lambda x: x["score"])
        return best["date"]

    # Último fallback.
    m = re.search(rf"\b({date_token})\b", text, re.IGNORECASE)
    return normalizar(m.group(1)) if m else None


def _extract_report_type(text: str) -> Optional[str]:
    """Evita escoger INITIAL solo porque aparece antes en la plantilla."""
    upper = text.upper()
    compact = re.sub(r"[ \t]+", " ", upper)

    checked = r"(?:\[\s*[X✓✔]\s*\]|[☒✓✔]|\bX\b)"
    followup_checked = [
        rf"{checked}\s*FOLLOW[\s-]?UP",
        rf"FOLLOW[\s-]?UP\s*{checked}",
    ]
    initial_checked = [
        rf"{checked}\s*INITIAL",
        rf"INITIAL\s*{checked}",
    ]
    for pattern in followup_checked:
        if re.search(pattern, compact, re.IGNORECASE):
            return "FOLLOWUP"
    for pattern in initial_checked:
        if re.search(pattern, compact, re.IGNORECASE):
            return "INITIAL"

    # En muchos CIOMS el OCR no conserva la marca de la casilla. La narrativa sí
    # suele declarar explícitamente que se trata de un follow-up.
    followup_evidence = [
        r"\bTHIS\s+(?:IS\s+)?(?:AN?\s+)?FOLLOW[\s-]?UP\s+REPORT\b",
        r"\bFOLLOW[\s-]?UP\s*\(\d{1,2}[A-Z]{3}\d{4}\)",
        r"\bAMENDMENT:\s*THIS\s+FOLLOW[\s-]?UP\s+REPORT\b",
        r"\bUPDATED\s+INFORMATION\b",
    ]
    if any(re.search(p, upper, re.IGNORECASE) for p in followup_evidence):
        return "FOLLOWUP"

    initial_evidence = [
        r"\bTHIS\s+(?:IS\s+)?(?:AN?\s+)?INITIAL\s+REPORT\b",
        r"\bFIRST\s+(?:SAE\s+)?REPORT\s+WAS\s+SUBMITTED\b",
    ]
    if any(re.search(p, upper, re.IGNORECASE) for p in initial_evidence):
        return "INITIAL"

    return None


def _valid_report_candidate(candidate: str) -> bool:
    candidate = re.sub(r"\s+", " ", candidate).strip(" :-\t")
    if not (5 <= len(candidate) <= 320):
        return False
    if not re.search(r"[A-Za-z]", candidate):
        return False

    blacklist = [
        "event verbatim",
        "preferred term",
        "lower level term",
        "related symptoms",
        "separated by commas",
        "describe reaction",
        "reaction(s)",
        "adverse event",
        "prolonged inpatient",
        "seriousness criteria",
        "event outcome",
        "page ",
    ]
    lower = candidate.lower()
    return not any(fragment in lower for fragment in blacklist)


def _report_candidate_score(candidate: str) -> float:
    score = 0.0
    lower = candidate.lower()
    if 10 <= len(candidate) <= 220:
        score += 2.0
    if re.match(r"^\s*1\)", candidate):
        score += 3.0
    if re.search(r"\(\d{8}\)", candidate):
        score += 5.0
    if re.search(r"\b(infection|pneumonia|tuberculosis|pain|fever|rash|sepsis|dyspnea|vomiting|nausea|thrombosis|injury)\b", lower):
        score += 2.0
    if len(candidate.split()) <= 2:
        score -= 2.0
    return score


def _extract_report(text: str) -> Optional[str]:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines() if line.strip()]
    candidates: List[str] = []

    # Prioriza la sección 7+13 de la primera página.
    for index, line in enumerate(lines):
        if re.search(r"(?:7\s*\+\s*13\s*)?DESCRIBE\s+REACTION\(S\)", line, re.IGNORECASE):
            for offset in range(1, 10):
                if index + offset >= len(lines):
                    break
                candidate = lines[index + offset]
                if re.search(r"^(?:II\.|14\.)\s*SUSPECT\s+DRUG", candidate, re.IGNORECASE):
                    break
                if _valid_report_candidate(candidate):
                    candidates.append(candidate)

    # Formato habitual: "1) reacción (...)".
    for line in lines:
        if re.match(r"^\s*\d+\)\s+", line) and _valid_report_candidate(line):
            if re.search(r"\(\d{8}\)|\b(infection|pneumonia|tuberculosis|pain|fever|rash|sepsis)\b", line, re.IGNORECASE):
                candidates.append(line)

    if not candidates:
        return None

    # Elimina duplicados conservando orden y luego puntúa.
    unique = list(dict.fromkeys(candidates))
    unique.sort(key=_report_candidate_score, reverse=True)
    return unique[0]



COUNTRY_BY_ID_PREFIX = {
    "CN": "CHINA",
    "US": "UNITED STATES OF AMERICA",
    "GB": "UNITED KINGDOM",
    "CA": "CANADA",
    "DE": "GERMANY",
    "AU": "AUSTRALIA",
    "AT": "AUSTRIA",
    "CZ": "CZECH REPUBLIC",
    "HU": "HUNGARY",
    "PL": "POLAND",
    "SE": "SWEDEN",
    "SG": "SINGAPORE",
}


def infer_country_from_id(report_id: Optional[str]) -> Optional[str]:
    if not report_id:
        return None
    prefix = re.match(r"([A-Z]{2})", report_id.upper())
    if prefix:
        return COUNTRY_BY_ID_PREFIX.get(prefix.group(1))
    return None


def clean_report_text(value: Optional[str]) -> Optional[str]:
    if not value:
        return value

    value = re.split(r"\[|Seriousness:|Severity:|Hospitalisation|HOSPITALISATION", value, flags=re.IGNORECASE)[0]
    value = re.sub(r"\s+", " ", value).strip(" :-")
    return value or None


def heuristics(text: str) -> Dict[str, Any]:
    out = {
        "reporte": None,
        "id_reporte": None,
        "fecha_reporte": None,
        "pais": None,
        "tipo": None,
    }
    if not text:
        return out

    clean_text = _clean_ocr_text(text)
    out["id_reporte"] = _extract_report_id(clean_text)
    out["pais"] = _extract_country(clean_text)
    out["fecha_reporte"] = _extract_report_date(clean_text)
    out["tipo"] = _extract_report_type(clean_text)
    out["reporte"] = _extract_report(clean_text)
    if not out["pais"]:
        out["pais"] = infer_country_from_id(out["id_reporte"])

    out["reporte"] = clean_report_text(out["reporte"])

    return out

# -------------------------
# PDF -> imagenes
# -------------------------
def load_images_from_input(path: str, max_pages: int = 3, dpi: int = 200) -> List[Image.Image]:
    """
    Devuelve lista de PIL Images.
    - Si es imagen: [img]
    - Si es PDF: renderiza 1..max_pages
    """
    p = path.lower()
    if p.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff")):
        return [Image.open(path).convert("RGB")]

    if p.endswith(".pdf"):
        try:
            import pypdfium2 as pdfium
            pdf = pdfium.PdfDocument(path)
            n = min(len(pdf), max_pages)
            imgs = []
            for i in range(n):
                page = pdf.get_page(i)
                pil = page.render(scale=dpi/72).to_pil()
                imgs.append(pil.convert("RGB"))
                page.close()
            pdf.close()
            return imgs
        except Exception:
            pass

        # Fallback para pymupdf
        try:
            import fitz  
            doc = fitz.open(path)
            n = min(doc.page_count, max_pages)
            imgs = []
            for i in range(n):
                page = doc.load_page(i)
                mat = fitz.Matrix(dpi/72, dpi/72)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                pil = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                imgs.append(pil)
            doc.close()
            return imgs
        except Exception as e:
            raise RuntimeError(
                "No pude renderizar PDF. Instala pypdfium2 o pymupdf.\n"
                "  pip install pypdfium2\n"
                "  (alternativa) pip install pymupdf"
            ) from e

    raise ValueError(f"Formato no soportado: {path}")

# -------------------------
# LLM Interfaz
# -------------------------
@dataclass
class Fields:
    reporte: Optional[str] = None
    id_reporte: Optional[str] = None
    fecha_reporte: Optional[str] = None
    pais: Optional[str] = None
    tipo: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "reporte": self.reporte,
            "id_reporte": self.id_reporte,
            "fecha_reporte": self.fecha_reporte,
            "pais": self.pais,
            "tipo": self.tipo,
        }

def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Extrae el primer objeto JSON del output, aunque el modelo meta texto alrededor.
    """
    if not text:
        return {}
    # Busca un bloque {...} grande
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        chunk = text[start:end+1]
        try:
            return json.loads(chunk)
        except Exception:
            pass
    # fallback: intenta line por line
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                return json.loads(line)
            except Exception:
                continue
    return {}

def _normalize_fields(d: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normaliza claves y fecha.
    """
    out = {"reporte": None, "id_reporte": None, "fecha_reporte": None, "pais": None, "tipo": None}
    if not isinstance(d, dict):
        return out

    for k in out.keys():
        if k in d:
            out[k] = d.get(k)

    # normaliza tipo
    if isinstance(out["tipo"], str):
        t = out["tipo"].strip().upper()
        if t in ("INITIAL", "FOLLOWUP"):
            out["tipo"] = t
        else:
            out["tipo"] = None

    # normaliza fecha
    if isinstance(out["fecha_reporte"], str):
        nd = normalizar(out["fecha_reporte"])
        out["fecha_reporte"] = nd or out["fecha_reporte"]

    # normaliza PV
    if isinstance(out["id_reporte"], str):
        m = REPORT_ID_RE.search(out["id_reporte"])
        out["id_reporte"] = m.group(0) if m else out["id_reporte"].strip()

    # pais upper
    if isinstance(out["pais"], str):
        out["pais"] = out["pais"].strip().upper()

    # reporte trim
    if isinstance(out["reporte"], str):
        out["reporte"] = out["reporte"].strip()

    return out
VALID_COUNTRIES = {
    "CHILE", "CHINA", "ARGENTINA", "BRAZIL", "PERU",
    "COLOMBIA", "MEXICO", "UNITED STATES", "UNITED STATES OF AMERICA"
}

GENERIC_REPORT_TERMS = {
    "reaction", "adverse reaction", "unknown", "n/a", "none", "null"
}

def _is_valid_date(s: Optional[str]) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    return normalizar(s) is not None or bool(re.match(r"^\d{2}-[A-Z]{3}-\d{4}$", s.strip()))

def _is_valid_pv(s: Optional[str]) -> bool:
    return isinstance(s, str) and REPORT_ID_RE.fullmatch(s.strip()) is not None

def _is_valid_type(s: Optional[str]) -> bool:
    return isinstance(s, str) and s.strip().upper() in {"INITIAL", "FOLLOWUP"}

def _is_valid_country(s: Optional[str]) -> bool:
    return isinstance(s, str) and s.strip().upper() in VALID_COUNTRIES

def _report_quality_score(s: Optional[str]) -> float:
    if not isinstance(s, str):
        return 0.0
    s = s.strip()
    if not s:
        return 0.0

    score = 0.0
    if len(s) >= 5:
        score += 1.0
    if len(s) >= 12:
        score += 1.0
    if len(s) <= 140:
        score += 0.5
    if s.lower() not in GENERIC_REPORT_TERMS:
        score += 1.0
    if re.search(r"[A-Za-z]", s):
        score += 0.5
    return score

def score_candidate(candidate: Dict[str, Any], heur: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Puntua un candidato según completitud + validez + consistencia con heuristicas.
    """
    heur = heur or {}
    score = 0.0
    details = {}

    # completitud base
    non_null_fields = sum(1 for k in ["reporte", "id_reporte", "fecha_reporte", "pais", "tipo"] if candidate.get(k) not in (None, "", "null"))
    score += non_null_fields * 2.0
    details["non_null_fields"] = non_null_fields

    # validez por campo
    if _is_valid_pv(candidate.get("id_reporte")):
        score += 4.0
        details["valid_id_reporte"] = True
    else:
        details["valid_id_reporte"] = False

    if _is_valid_date(candidate.get("fecha_reporte")):
        score += 3.0
        details["valid_fecha_reporte"] = True
    else:
        details["valid_fecha_reporte"] = False

    if _is_valid_country(candidate.get("pais")):
        score += 2.0
        details["valid_pais"] = True
    else:
        details["valid_pais"] = False

    if _is_valid_type(candidate.get("tipo")):
        score += 2.0
        details["valid_tipo"] = True
    else:
        details["valid_tipo"] = False

    rq = _report_quality_score(candidate.get("reporte"))
    score += rq
    details["report_quality"] = rq

    # bonus por consistencia con heuristicas OCR
    for field, bonus in [
        ("id_reporte", 2.5),
        ("fecha_reporte", 1.5),
        ("pais", 1.0),
        ("tipo", 1.0),
    ]:
        cv = candidate.get(field)
        hv = heur.get(field)
        if cv and hv and str(cv).strip().upper() == str(hv).strip().upper():
            score += bonus
            details[f"match_heur_{field}"] = True
        else:
            details[f"match_heur_{field}"] = False

    # penalizaciones suaves
    if non_null_fields <= 1:
        score -= 3.0
    if candidate.get("reporte") and len(str(candidate["reporte"]).strip()) > 180:
        score -= 1.0

    return {
        "score": round(score, 3),
        "details": details,
    }

def choose_best_result(res: Dict[str, Any]) -> Dict[str, Any]:
    candidates = {
        "heuristics": res.get("heuristics") or {},
        "llm_text": res.get("llm_text") or {},
        "llm_image": res.get("llm_image") or {},
        "llm_text_image": res.get("llm_text_image") or {},
    }

    ranking = []
    for method, candidate in candidates.items():
        scored = score_candidate(candidate, res.get("heuristics"))
        ranking.append({
            "method": method,
            "candidate": candidate,
            "score": scored["score"],
            "details": scored["details"],
        })

    ranking.sort(key=lambda x: x["score"], reverse=True)

    best = ranking[0] if ranking else None
    return {
        "best_method": best["method"] if best else None,
        "best_result": best["candidate"] if best else None,
        "ranking": ranking,
    }

def merge_best_fields(res: Dict[str, Any]) -> Dict[str, Any]:
    methods = ["heuristics", "llm_text", "llm_image", "llm_text_image"]
    candidates = {m: res.get(m) or {} for m in methods}

    field_validators = {
        "reporte": lambda x: _report_quality_score(x) > 0,
        "id_reporte": _is_valid_pv,
        "fecha_reporte": _is_valid_date,
        "pais": _is_valid_country,
        "tipo": _is_valid_type,
    }

    merged = {}
    provenance = {}

    for field, validator in field_validators.items():
        best_val = None
        best_method = None
        best_score = -1.0

        for method, cand in candidates.items():
            value = cand.get(field)
            if value is None:
                continue

            local_score = 0.0
            if validator(value):
                local_score += 5.0

            # bonus si coincide con heuristicas
            hv = (res.get("heuristics") or {}).get(field)
            if hv and str(value).strip().upper() == str(hv).strip().upper():
                local_score += 2.0

            # bonus extra para reporte mas informativo
            if field == "reporte":
                local_score += _report_quality_score(value)

            if local_score > best_score:
                best_score = local_score
                best_val = value
                best_method = method

        merged[field] = best_val
        provenance[field] = best_method

    return {
        "merged_result": merged,
        "merged_from": provenance,
    }

RESULT_VIEW_MAP = {
    "best": "best_result",
    "merged": "merged_result",
    "heuristics": "heuristics",
    "llm_text": "llm_text",
    "llm_image": "llm_image",
    "llm_text_image": "llm_text_image",
}

def resolve_selected_method(res: Dict[str, Any], selected_view: str) -> str:
    if selected_view == "best":
        return res.get("best_method") or "best_result"
    if selected_view == "merged":
        return "merged"
    return selected_view

def resolve_selected_result(res: Dict[str, Any], selected_view: str) -> Dict[str, Any]:
    key = RESULT_VIEW_MAP.get(selected_view, "best_result")
    return res.get(key) or {}

def build_selected_payload(res: Dict[str, Any], selected_view: str) -> Dict[str, Any]:
    return {
        "selected_view": selected_view,
        "selected_method": resolve_selected_method(res, selected_view),
        "selected_result": resolve_selected_result(res, selected_view),
    }

class BaseProvider:
    def __init__(self, model_text: str, model_vision: str):
        self.model_text = model_text
        self.model_vision = model_vision

    def text_only(self, prompt: str) -> str:
        raise NotImplementedError

    def image_only(self, prompt: str, images: List[Image.Image]) -> str:
        raise NotImplementedError

    def text_and_image(self, prompt: str, text: str, images: List[Image.Image]) -> str:
        raise NotImplementedError
# -------------------------
# OpenAI Provider
# -------------------------
class OpenAIProvider(BaseProvider):
    def __init__(self, model_text: str, model_vision: str):
        super().__init__(model_text, model_vision)
        try:
            from openai import OpenAI
        except Exception as e:
            raise RuntimeError("Falta SDK OpenAI: pip install openai") from e

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("Falta OPENAI_API_KEY en variables de entorno.")
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)

    def text_only(self, prompt: str) -> str:
        r = self.client.responses.create(
            model=self.model_text,
            input=[{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
        )
        return r.output_text or ""

    def image_only(self, prompt: str, images: List[Image.Image]) -> str:
        content = [{"type": "input_text", "text": prompt}]
        # adjunta hasta 3 páginas por defecto
        for img in images:
            content.append({"type": "input_image", "image_url": pil_to_data_url(img)})
        r = self.client.responses.create(
            model=self.model_vision,
            input=[{"role": "user", "content": content}],
        )
        return r.output_text or ""

    def text_and_image(self, prompt: str, text: str, images: List[Image.Image]) -> str:
        content = [
            {"type": "input_text", "text": prompt},
            {"type": "input_text", "text": f"OCR_TEXT:\n{text}"},
        ]
        for img in images:
            content.append({"type": "input_image", "image_url": pil_to_data_url(img)})
        r = self.client.responses.create(
            model=self.model_vision,
            input=[{"role": "user", "content": content}],
        )
        return r.output_text or ""

# -------------------------
# Gemini  
# -------------------------
class GeminiProvider(BaseProvider):
    def __init__(self, model_text: str, model_vision: str):
        super().__init__(model_text, model_vision)
        try:
            from google import genai
            from google.genai import types
        except Exception as e:
            raise RuntimeError("Falta SDK Gemini: pip install google-genai") from e

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("Falta GEMINI_API_KEY (o GOOGLE_API_KEY) en variables de entorno.")

        from google import genai
        from google.genai import types
        self.client = genai.Client(api_key=api_key)
        self.types = types  # <-- CLAVE

    def text_only(self, prompt: str) -> str:
        r = self.client.models.generate_content(
            model=self.model_text,
            contents=prompt,
        )
        return getattr(r, "text", "") or ""

    def image_only(self, prompt: str, images: List[Image.Image]) -> str:
        parts = [prompt]
        for img in images:
            img_bytes = pil_to_png_bytes(img)
            parts.append(self.types.Part.from_bytes(data=img_bytes, mime_type="image/png"))

        r = self.client.models.generate_content(
            model=self.model_vision,
            contents=parts,
        )
        return getattr(r, "text", "") or ""

    def text_and_image(self, prompt: str, text: str, images: List[Image.Image]) -> str:
        parts = [prompt, f"OCR_TEXT:\n{text}"]
        for img in images:
            img_bytes = pil_to_png_bytes(img)
            parts.append(self.types.Part.from_bytes(data=img_bytes, mime_type="image/png"))

        r = self.client.models.generate_content(
            model=self.model_vision,
            contents=parts,
        )
        return getattr(r, "text", "") or ""


# -------------------------
# Claude (anthropic)
# -------------------------
class ClaudeProvider(BaseProvider):
    def __init__(self, model_text: str, model_vision: str):
        super().__init__(model_text, model_vision)
        try:
            import anthropic
        except Exception as e:
            raise RuntimeError("Falta SDK Anthropic: pip install anthropic") from e

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("Falta ANTHROPIC_API_KEY en variables de entorno.")
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key)

    def text_only(self, prompt: str) -> str:
        msg = self.client.messages.create(
            model=self.model_text,
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        # Anthropic devuelve lista de bloques
        return "".join([b.text for b in msg.content if getattr(b, "type", "") == "text"])

    def image_only(self, prompt: str, images: List[Image.Image]) -> str:
        content = [{"type": "text", "text": prompt}]
        for img in images:
            b64 = base64.b64encode(pil_to_png_bytes(img)).decode("utf-8")
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}})
        msg = self.client.messages.create(
            model=self.model_vision,
            max_tokens=900,
            messages=[{"role": "user", "content": content}],
        )
        return "".join([b.text for b in msg.content if getattr(b, "type", "") == "text"])

    def text_and_image(self, prompt: str, text: str, images: List[Image.Image]) -> str:
        content = [
            {"type": "text", "text": prompt},
            {"type": "text", "text": f"OCR_TEXT:\n{text}"},
        ]
        for img in images:
            b64 = base64.b64encode(pil_to_png_bytes(img)).decode("utf-8")
            content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}})
        msg = self.client.messages.create(
            model=self.model_vision,
            max_tokens=900,
            messages=[{"role": "user", "content": content}],
        )
        return "".join([b.text for b in msg.content if getattr(b, "type", "") == "text"])

# -------------------------
# Prompt comun de extraccion
# -------------------------
def build_extraction_prompt() -> str:
    #sin schema. Solo pedimos JSON y luego lo parseamos
    return (
        "Extrae campos desde un formulario CIOMS.\n"
        "IMPORTANTE: en este proyecto, el reporte debe ser el primero.\n"
        "IMPORTANTE: en este proyecto, 'reporte' = el término de Reaction(s) (ej: 'Non-cardiac chest pain') solamente el sintoma no los corchetes.\n"
        "Para el ID del reporte extrae el Worldwide, es decir, el mas completo"
        "Devuelve SOLO un JSON válido con estas llaves EXACTAS:\n"
        '  {"reporte": ..., "id_reporte": ..., "fecha_reporte": ..., "pais": ..., "tipo": ...}\n'
        "Reglas:\n"
        "- Si no aparece un campo, usa null.\n"
        "- 'tipo' solo puede ser 'INITIAL' o 'FOLLOWUP' o null.\n"
        "- 'fecha_reporte' idealmente en formato DD-MMM-YYYY (ej 04-DEC-2025) si la ves.\n"
    )

def provider_factory(name: str, model_text: str, model_vision: str) -> BaseProvider:
    name = name.lower().strip()
    if name == "openai":
        return OpenAIProvider(model_text=model_text, model_vision=model_vision)
    if name == "gemini":
        return GeminiProvider(model_text=model_text, model_vision=model_vision)
    if name == "claude":
        return ClaudeProvider(model_text=model_text, model_vision=model_vision)
    raise ValueError("provider inválido. Usa: openai | gemini | claude")



def classify_ai_error(exc: Exception) -> str:
    msg = str(exc).lower()
    if "insufficient_quota" in msg or "credit_balance" in msg:
        return "NO_CREDITS"
    if "timeout" in msg:
        return "TIMEOUT"
    if "429" in msg or "rate" in msg:
        return "RATE_LIMIT"
    if "401" in msg or "api key" in msg:
        return "AUTH_ERROR"
    return "OPENAI_ERROR"


def procesar_archivo_con_ia(
    input_path: str,
    provider: str = "openai",
    model_text: str = "",
    model_vision: str = "",
    max_pages: int = 3,
    dpi: int = 200,
    preprocess_only: bool = False,
    debug_preprocess: bool = False,
    result_view: str = "best",
) -> Dict[str, Any]:
    """Procesa OCR/heurísticas y usa IA; ante cualquier error de IA retorna heurísticas."""
    default_text = {
        "openai": "gpt-4.1-mini",
        "gemini": "gemini-3-flash-preview",
        "claude": "claude-3-5-sonnet-latest",
    }
    default_vision = {
        "openai": "gpt-4.1-mini",
        "gemini": "gemini-3-flash-preview",
        "claude": "claude-3-5-sonnet-latest",
    }

    provider = provider.lower().strip()
    if provider not in default_text:
        raise ValueError("provider inválido. Usa: openai | gemini | claude")

    final_model_text = model_text or default_text[provider]
    final_model_vision = model_vision or default_vision[provider]

    images = load_images_from_input(input_path, max_pages=max_pages, dpi=dpi)
    ocr_text, ocr_status = try_ocr_multi(images, max_pages_ocr=min(3, len(images)))
    heuristic_result = heuristics(ocr_text or "")

    res = {
        "input": input_path,
        "provider": provider,
        "model_text": final_model_text,
        "model_vision": final_model_vision,
        "ocr_status": ocr_status,
        "ocr_preview": (ocr_text[:600] + "...") if ocr_text and len(ocr_text) > 600 else ocr_text,
        "heuristics": heuristic_result,
        "llm_text": None,
        "llm_image": None,
        "llm_text_image": None,
        "ai_error": None,
    }

    # Prueba local: termina antes de inicializar o llamar al proveedor de IA.
    if preprocess_only:
        res["ai_status"] = "skipped_for_test"
        res["selected_method"] = "heuristics_pre_openai"
        res["selected_result"] = heuristic_result
        return res

    prompt = build_extraction_prompt()

    # Todo el tramo de IA está en un solo bloque: el primer error detiene las llamadas restantes.
    try:
        provider_client = provider_factory(
            provider,
            model_text=final_model_text,
            model_vision=final_model_vision,
        )

        if ocr_text:
            raw = provider_client.text_only(prompt + "\n\nTEXTO OCR:\n" + ocr_text)
            res["llm_text"] = _normalize_fields(_extract_json_object(raw))
        else:
            res["llm_text"] = {
                "reporte": None, "id_reporte": None, "fecha_reporte": None,
                "pais": None, "tipo": None,
            }

        raw = provider_client.image_only(prompt, images)
        res["llm_image"] = _normalize_fields(_extract_json_object(raw))

        raw = provider_client.text_and_image(prompt, ocr_text or "", images)
        res["llm_text_image"] = _normalize_fields(_extract_json_object(raw))

    except Exception as exc:
        res["ai_status"] = "failed"
        res["ai_error"] = f"{type(exc).__name__}: {exc}"
        res["ai_error_type"] = classify_ai_error(exc)
        res["selected_method"] = "heuristics_fallback"
        res["selected_result"] = heuristic_result
        return res

    # Solo se conserva la selección original si todas las llamadas de IA terminaron bien.
    selection = choose_best_result(res)
    res["best_method"] = selection["best_method"]
    res["best_result"] = selection["best_result"]
    res["ranking"] = selection["ranking"]

    merged = merge_best_fields(res)
    res["merged_result"] = merged["merged_result"]
    res["merged_from"] = merged["merged_from"]

    res.update(build_selected_payload(res, result_view))
    res["ai_status"] = "success"
    return res

# -------------------------
# Main
# -------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Ruta a imagen o PDF.")
    ap.add_argument("--provider", default="openai", choices=["openai", "gemini", "claude"])
    ap.add_argument("--model_text", default="", help="Override modelo texto.")
    ap.add_argument("--model_vision", default="", help="Override modelo visión.")
    ap.add_argument("--max_pages", type=int, default=3, help="Si input es PDF: cuántas páginas renderizar.")
    ap.add_argument("--dpi", type=int, default=200, help="Si input es PDF: DPI de render.")
    ap.add_argument("--format", default="pretty", choices=["json", "pretty", "table", "csv"])
    ap.add_argument("--out", default="", help="Archivo de salida (json/pretty/table).")
    ap.add_argument("--csv_path", default="resultado.csv", help="Ruta CSV si --format=csv")
    ap.add_argument("--result_view",default="best",choices=["best", "merged", "heuristics", "llm_text", "llm_image", "llm_text_image"],help="Qué resultado mostrar/exportar. Por defecto: best")
    args = ap.parse_args()

    # defaults por proveedor
    default_text = {
        "openai": "gpt-4.1-mini",
        "gemini": "gemini-3-flash-preview",
        "claude": "claude-3-5-sonnet-latest",
    }
    default_vision = {
        "openai": "gpt-4.1-mini",
        "gemini": "gemini-3-flash-preview",
        "claude": "claude-3-5-sonnet-latest",
    }

    model_text = args.model_text or default_text[args.provider]
    model_vision = args.model_vision or default_vision[args.provider]

    images = load_images_from_input(args.input, max_pages=args.max_pages, dpi=args.dpi)

    # OCR multipágina (hasta 3 pAginas)
    ocr_text, ocr_status = try_ocr_multi(images, max_pages_ocr=min(3, len(images)))

    res = {
        "input": args.input,
        "provider": args.provider,
        "ocr_status": ocr_status,
        "ocr_preview": (ocr_text[:600] + "...") if ocr_text and len(ocr_text) > 600 else ocr_text,
        "heuristics": heuristics(ocr_text or ""),
        "llm_text": None,
        "llm_image": None,
        "llm_text_image": None,
    }


    provider = provider_factory(args.provider, model_text=model_text, model_vision=model_vision)
    prompt = build_extraction_prompt()

    # (2) LLM solo texto
    if ocr_text:
        raw = provider.text_only(prompt + "\n\nTEXTO OCR:\n" + ocr_text)
        res["llm_text"] = _normalize_fields(_extract_json_object(raw))
    else:
        res["llm_text"] = {"reporte": None, "id_reporte": None, "fecha_reporte": None, "pais": None, "tipo": None}

    # (3) LLM solo imagen (usa primeras n paginas)
    raw = provider.image_only(prompt, images)
    res["llm_image"] = _normalize_fields(_extract_json_object(raw))

    # (4) LLM texto + imagen
    raw = provider.text_and_image(prompt, ocr_text or "", images)
    res["llm_text_image"] = _normalize_fields(_extract_json_object(raw))

    # Seleccion del mejor candidato
    selection = choose_best_result(res)
    res["best_method"] = selection["best_method"]
    res["best_result"] = selection["best_result"]
    res["ranking"] = selection["ranking"]

    # Merge campo por campo
    merged = merge_best_fields(res)
    res["merged_result"] = merged["merged_result"]
    res["merged_from"] = merged["merged_from"]


    fmt = args.format
    selected_view = args.result_view
    if fmt == "json":
        out_payload = {
            **res,
            **build_selected_payload(res, selected_view),
        }
        out_str = json.dumps(out_payload, ensure_ascii=False, indent=2)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(out_str)
            print(f"[OK] Guardado: {args.out}")
        else:
            print(out_str)
    elif fmt == "pretty":
        out_str = as_pretty(res, selected_view=selected_view)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(out_str)
            print(f"[OK] Guardado: {args.out}")
        else:
            print(out_str)
    elif fmt == "table":
        out_str = as_table(res, selected_view=selected_view)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                f.write(out_str)
            print(f"[OK] Guardado: {args.out}")
        else:
            print(out_str)
    elif fmt == "csv":
        write_csv(res, args.csv_path, selected_view=selected_view)
        print(f"[OK] CSV guardado: {args.csv_path}")
        print(r.usage)

if __name__ == "__main__":
    main()
