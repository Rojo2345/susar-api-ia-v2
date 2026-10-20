
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
    r"(?:\b20\d{2}-\d{4,9}\(\d{1,4}\)(?!\w)|\bPV\d{8,}\b|\b[A-Z]{2}-\d{6,}-\d{4,}\b)",
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
    """Normaliza fechas verificables; nunca construye una fecha imposible."""
    if not s:
        return None
    from datetime import date
    months = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    }
    value = s.strip()
    parsed = re.search(r"\b(\d{1,2})\s*[-/ ]\s*([A-Za-z]{3,9}|\d{1,2})\s*[-/ ]\s*(\d{4})\b", value)
    if not parsed:
        return None
    day, token, year = parsed.groups()
    token = token.upper()
    if token.isdigit():
        month = int(token)
    else:
        # Nombres completos en inglés (September), abreviaturas SEP/SEPT.
        month = months.get(token[:3])
        if token == "SEPT":
            month = 9
    if not month:
        return None
    try:
        result = date(int(year), month, int(day))
    except ValueError:
        return None
    return f"{result.day:02d}-{list(months)[result.month - 1]}-{result.year:04d}"

def _clean_ocr_text(text: str) -> str:
    """Normaliza espacios y saltos sin destruir la estructura por líneas."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _valid_report_id_candidate(value: str) -> bool:
    """Acepta identificadores de caso, pero no códigos postales ni etiquetas."""
    if not value:
        return False
    value = value.strip().upper().rstrip(".,;:")
    # ZIP+4 precedido de estado, p. ej. NJ-08543-4000, no es ID SUSAR.
    if re.fullmatch(r"[A-Z]{2}-\d{5}-\d{4}", value):
        return False
    # En los CIOMS de este lote 24b contiene IDs como 2025-100830(1).
    # No exigir letras: esa validación antigua descartaba el ID correcto.
    if re.fullmatch(r"20\d{2}-\d{4,9}\(\d{1,4}\)", value):
        return True
    if re.fullmatch(r"PV\d{8,}(?:-\d+)*", value):
        return True
    if re.fullmatch(r"[A-Z]{2,10}-\d{5,}(?:-\d{3,})+", value):
        return True
    if re.fullmatch(r"[A-Z]{2,10}-\d{8,}", value):
        return True
    if re.fullmatch(r"20\d{2}-AER-\d{4,}(?:-\d+)*", value):
        return True
    return False


def _extract_report_id(text: str) -> Optional[str]:
    """Prioriza 24b. MFR CONTROL NO.; nunca ID de direcciones postales.

    Con etiqueta presente pero valor ininteligible: devolver None, en vez de
    seleccionar un código de la carta de presentación por su longitud.
    """
    labeled = (
        r"24\s*b\s*\.\s*MFR\s+CONTROL\s+NO\.?",
        r"\bMFR\s+CONTROL\s+NO\.?",
        r"\bWORLDWIDE\s+UID\b",
    )
    for label in labeled:
        for match in re.finditer(label, text, re.I):
            tail = text[match.end():match.end() + 135]
            # Los tokens normalmente están en la línea siguiente, a veces con
            # espacios en blanco de formulario entre etiqueta y valor.
            for line in tail.splitlines()[:4]:
                line = line.strip().lstrip(":- ").strip()
                if not line:
                    continue
                found = re.match(
                    r"(20\d{2}-\d{4,9}\(\d{1,4}\)|"
                    r"20\d{2}-AER-\d{4,}(?:-\d+)*|"
                    r"PV\d{8,}(?:-\d+)*|"
                    r"[A-Z]{2,10}-\d{5,}(?:-\d{3,})+|"
                    r"[A-Z]{2,10}-\d{8,})", line, re.I)
                if found and _valid_report_id_candidate(found.group(1)):
                    return found.group(1).upper()
                # Al llegar a otro número de campo, dejar de leer este bloque.
                if re.match(r"\d{1,2}[a-d]?\s*\.\s*[A-Z]", line, re.I):
                    break
    # Respaldo: SOLO si existe un único identificador de caso inequívoco.
    # Un código postal tipo NJ-08543-4000 no cumple el patrón de caso.
    found = set()
    for expression in (r"\b20\d{2}-\d{4,9}\(\d{1,4}\)",
                       r"\b20\d{2}-AER-\d{4,}(?:-\d+)*\b",
                       r"\bPV\d{8,}(?:-\d+)*\b"):
        found.update(m.group(0).upper() for m in re.finditer(expression, text, re.I))
    return next(iter(found)) if len(found) == 1 else None

def _extract_country(text: str) -> Optional[str]:
    """Toma país solo de 1a. COUNTRY; admite hojas de continuación.

    No inferir país desde el fabricante, el identificador o una dirección.
    """
    aliases = {
        "USA": "UNITED STATES OF AMERICA", "U.S.A.": "UNITED STATES OF AMERICA",
        "UNITED STATES": "UNITED STATES OF AMERICA",
        "UNITED STATES OF AMERICA": "UNITED STATES OF AMERICA",
        "UNITED KINGDOM OF GREAT BRITAIN AND NORTHERN IRELAND": "UNITED KINGDOM",
        "UK": "UNITED KINGDOM", "UNITED KINGDOM": "UNITED KINGDOM",
        "BRASIL": "BRAZIL", "MÉXICO": "MEXICO", "PERÚ": "PERU",
    }
    bad = {"UNITED", "CONT", "CONT.", "CONT..", "UNKNOWN", "MASKED",
           "N/A", "NOT KNOWN", "NOT AVAILABLE", "NOT REPORTED"}
    # Buscar TODAS las apariciones: un país partido puede estar completo en
    # la hoja de continuación, incluso si la primera aparición dice UNITED.
    for m in re.finditer(r"(?:^|\n)\s*1a\s*\.\s*COUNTRY\s*:?[ \t]*", text, re.I):
        tail = text[m.end():m.end() + 110]
        for line in tail.splitlines()[:3]:
            value = re.sub(r"\s+", " ", line).strip(" .:-\t").upper()
            if not value:
                continue
            if value in bad or re.match(r"\d+[a-d]?\.\s", value):
                break
            if not (2 <= len(value) <= 85 and
                    re.fullmatch(r"[A-ZÀ-Ÿ][A-ZÀ-Ÿ .'-]*", value)):
                break
            if re.search(r"(?:CONTINUATION|REPORT|REACTION|MANUFACTURER|PATIENT|COUNTRY)", value):
                break
            return aliases.get(value, value)
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
    """Solo DATE OF THIS REPORT, nunca DATE RECEIVED ni fechas clínicas.

    No adivinar con la primera fecha del documento; en el lote anterior
    ese comportamiento capturaba fechas de cartas o del evento adverso.
    """
    # Permite valores dd/MMM/yyyy, dd-MMM-yyyy o dd/mm/yyyy.
    date_token = (r"\d{1,2}\s*[-/]\s*"
                  r"(?:[A-Za-z]{3,9}|\d{1,2})\s*[-/]\s*\d{4}")
    for label in (r"\bDATE\s+OF\s+THIS\s+REPORT\b",):
        for match in re.finditer(label, text, re.I):
            tail = text[match.end():match.end() + 100]
            # La etiqueta suele estar en línea distinta; no entrar a 25a.
            tail = re.split(r"(?:25a\.|REPORT\s+TYPE|24[cd]\.)", tail, maxsplit=1, flags=re.I)[0]
            candidate = re.search(date_token, tail, re.I)
            if candidate:
                normalized = normalizar(candidate.group(0))
                if normalized:
                    return normalized
    return None

def _extract_report_type(text: str) -> Optional[str]:
    """Devuelve tipo solo con marca textual visible dentro del campo 25a.

    Normalmente un PDF conserva dos etiquetas sin indicar cuál está marcada;
    en ese caso devolver None. La validación visual del CIOMS decide.
    """
    checked = r"(?:\[\s*[X✓✔]\s*\]|[☒✓✔])"
    for m in re.finditer(r"25\s*a\s*\.\s*REPORT\s+TYPE", text, re.I):
        segment = text[m.end():m.end() + 140]
        segment = re.split(r"(?:CONTINUATION\s+ATTACHED|Page\s+\d+\s+of)",
                           segment, maxsplit=1, flags=re.I)[0]
        for field in ("FOLLOWUP", "INITIAL"):
            if (re.search(rf"{checked}\s*{field}\b", segment, re.I)
                    or re.search(rf"\b{field}\s*{checked}", segment, re.I)):
                return field
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
    """Extrae únicamente el término del evento 1) en la sección 7+13.

    Nunca elige el evento 2), la narrativa o un fármaco como sustituto.
    """
    for head in re.finditer(
        r"7\s*\+\s*13\s*DESCRIBE\s+REACTION\(S\)", text, re.I):
        tail = text[head.end():head.end() + 1400]
        # Excluir las hojas de continuación narrativas: en ellas no figura
        # la lista principal con el evento 1) de forma fiable.
        if re.match(r"[^\n]*\(Continuation", tail, re.I):
            continue
        tail = re.split(r"\b(?:II\.\s*SUSPECT\s+DRUG|14\.\s*SUSPECT\s+DRUG)\b",
                        tail, maxsplit=1, flags=re.I)[0]
        event = re.search(r"(?:^|\n)\s*1\)\s*(.+)", tail, re.I)
        if not event:
            continue
        name = re.split(r"\s*\(", event.group(1), maxsplit=1)[0]
        name = re.sub(r"\s+", " ", name).strip(" -:;,.")
        if not (3 <= len(name) <= 160 and re.search(r"[A-Za-z]", name)):
            continue
        if re.search(r"(?:DESCRIBE|REACTION\(S\)|MEDDRA|VERSION)", name, re.I):
            continue
        # Usar capitalización consistente sin cambiar terminología médica.
        return name if name.isupper() else name
    return None

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
    # No derivar el país del prefijo de ID: puede representar otra jurisdicción.

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
    "COLOMBIA", "MEXICO", "UNITED STATES", "UNITED STATES OF AMERICA",
    "UNITED KINGDOM", "SPAIN", "BELGIUM", "AUSTRALIA", "CANADA",
    "GERMANY", "FRANCE", "ITALY", "NETHERLANDS", "PORTUGAL",
    "JAPAN", "INDIA", "SOUTH KOREA", "SWITZERLAND", "POLAND",
    "AUSTRIA", "SWEDEN", "CZECH REPUBLIC", "HUNGARY", "SINGAPORE",
    "NEW ZEALAND", "IRELAND", "TURKEY", "TAIWAN", "ISRAEL"
}

GENERIC_REPORT_TERMS = {
    "reaction", "adverse reaction", "unknown", "n/a", "none", "null"
}

def _is_valid_date(s: Optional[str]) -> bool:
    if not isinstance(s, str) or not s.strip():
        return False
    return normalizar(s) is not None

def _is_valid_pv(s: Optional[str]) -> bool:
    return isinstance(s, str) and _valid_report_id_candidate(s)

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

def choose_llm_first_result(res: Dict[str, Any]) -> Dict[str, Any]:
    """Choose among AI outputs only; heuristics never competes with a successful AI output.

    Heuristics may complete genuinely absent AI fields. Explicit CIOMS evidence
    validation is applied afterwards by the calling workflow.
    """
    ai_methods = ("llm_text", "llm_image", "llm_text_image")
    ranking = []
    for method in ai_methods:
        candidate = res.get(method) or {}
        if not any(candidate.get(k) not in (None, "", "null") for k in
                   ("reporte", "id_reporte", "fecha_reporte", "pais", "tipo")):
            continue
        scored = score_candidate(candidate, res.get("heuristics"))
        ranking.append({"method": method, "candidate": candidate,
                        "score": scored["score"], "details": scored["details"]})
    ranking.sort(key=lambda item: item["score"], reverse=True)
    if not ranking:
        return {"best_method": "heuristics_fallback_empty_ai",
                "best_result": dict(res.get("heuristics") or {}),
                "ranking": [], "filled_from_heuristics": []}

    winner = ranking[0]
    chosen = dict(winner["candidate"])
    fallback = res.get("heuristics") or {}
    filled = []
    for key in ("reporte", "id_reporte", "fecha_reporte", "pais", "tipo"):
        if chosen.get(key) in (None, "", "null") and fallback.get(key) not in (None, "", "null"):
            chosen[key] = fallback[key]
            filled.append(key)
    return {"best_method": winner["method"], "best_result": chosen,
            "ranking": ranking, "filled_from_heuristics": filled}


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
    """Campos CIOMS para resumen SUSAR; no confundir narrativa con casillas."""
    return (
        "Extrae campos exclusivamente del formulario CIOMS (no de la carta de presentación).\n"
        "REGLA OBLIGATORIA PARA 'reporte': busca el campo 7+13 DESCRIBE REACTION(S). "
        "Devuelve EXCLUSIVAMENTE el nombre del evento numerado 1), el PRIMER evento de esa lista. "
        "Aunque existan 2), 3) o más eventos, ignóralos para el campo 'reporte'. "
        "No los concatenes ni resumas la lista completa. "
        "Ejemplo: '1) PNEUMONITIS (Pneumonitis (10035742), ...)' -> 'Pneumonitis'. "
        "Ejemplo: '1) COLITIS ... 2) DIARRHOEA ... 3) VOMITING ...' -> 'Colitis'. "
        "Quita '1)', códigos MedDRA, paréntesis con sinónimos, fechas y explicaciones; "
        "conserva el término médico completo del PRIMER evento, sin traducirlo.\n"
        "Para 'tipo', observa visualmente la sección 25a. REPORT TYPE: "
        "el valor es SOLO la casilla efectivamente marcada junto a INITIAL o FOLLOWUP. "
        "La mera aparición de las palabras no significa que estén marcadas. "
        "No deduzcas el tipo por la narrativa ('initial report', 'follow-up report #1'), "
        "la numeración del caso, el nombre del archivo ni las cartas de presentación. "
        "Si no puedes ver con claridad cuál casilla está marcada, devuelve null.\n"
        "Para 'id_reporte', prioriza 24b. MFR CONTROL NO o un Worldwide UID explícito "
        "del reporte, sin direcciones, códigos postales ni IDs ajenos.\n"
        "El país es el de 1a. COUNTRY (paciente), NUNCA el de la dirección del fabricante.\n"
        "La fecha es DATE OF THIS REPORT, NO DATE RECEIVED ni fechas clínicas.\n"
        "No devuelvas encabezados como valores. Devuelve SOLO un JSON válido con las llaves EXACTAS:\n"
        '  {"reporte": ..., "id_reporte": ..., "fecha_reporte": ..., "pais": ..., "tipo": ...}\n'
        "Si falta evidencia fiable, usa null. 'tipo' solo admite 'INITIAL', 'FOLLOWUP' o null. "
        "Normaliza la fecha a DD-MMM-YYYY cuando sea posible.\n"
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


# Verificacion documental independiente de IA: solo campos explicitamente rotulados.
# Se aplica a PDFs con texto seleccionable; si no hay evidencia, no se inventan datos.
def _first_reaction_from_cioms(page_text: str) -> Optional[str]:
    """Lee SOLO el evento 1) de la primera sección 7+13, sin otros eventos."""
    match = re.search(r"7\s*\+\s*13\s*DESCRIBE\s+REACTION\(S\)", page_text, re.I)
    if not match:
        return None
    tail = page_text[match.end():]
    # Limitarse al bloque de reacciones, nunca tomar numeraciones de fármacos.
    tail = re.split(r"\bII\.\s*SUSPECT\s+DRUG|\b14\.\s*SUSPECT\s+DRUG", tail, maxsplit=1, flags=re.I)[0]
    for line in tail.splitlines()[:35]:
        item = re.match(r"^\s*1\)\s+(.+)$", line.strip())
        if not item:
            continue
        raw = item.group(1).strip()
        # El primer paréntesis contiene los sinónimos/códigos MedDRA.
        first = re.split(r"\s+\(", raw, maxsplit=1)[0].strip(" -:;,.\t")
        if not first or len(first) > 160 or re.search(r"DESCRIBE REACTION|MEDDRA VERSION", first, re.I):
            return None
        if first.isupper() and len(first) > 4:
            # Mantener los acrónimos clínicos conocidos en mayúscula.
            keep = {"HIV", "COVID-19", "ARDS", "ALT", "AST", "SARS", "ECG"}
            first = " ".join(x if x in keep else (x[0].upper() + x[1:].lower() if x else x)
                             for x in first.split())
        return first
    return None


def _cioms_visual_checkbox_type(page) -> Optional[Dict[str, Any]]:
    """Detecta tinta *dentro* de la casilla junto a INITIAL/FOLLOWUP.

    Solo evalúa el campo 25a del CIOMS usando las posiciones del PDF y píxeles.
    Si no podemos localizar las dos casillas, no inventamos un tipo.
    """
    text = page.get_text("text")
    if not re.search(r"25a\.\s*REPORT\s+TYPE", text, re.I):
        return None
    words = page.get_text("words")
    anchors = [w for w in words if re.fullmatch(r"25a\.?", w[4], re.I)]
    if not anchors:
        return None
    anchor = anchors[0]
    options = {}
    for name in ("INITIAL", "FOLLOWUP"):
        eligible = [w for w in words if w[4].strip(".,:").upper() == name
                    and 0 < w[1] - anchor[1] < 44
                    and abs(w[1] - anchor[1]) < 44
                    and abs(w[0] - anchor[0]) < 190]
        if eligible:
            options[name] = min(eligible, key=lambda w: abs(w[1] - anchor[1]))
    if len(options) != 2 or abs(options["INITIAL"][1] - options["FOLLOWUP"][1]) > 6:
        return None

    def ink_ratios(dx0, dy0, dx1, dy1, inset_box):
        scores = {}
        for name, word in options.items():
            x, y = word[0], word[1]
            clip = page.rect & __import__("fitz").Rect(x + dx0, y + dy0, x + dx1, y + dy1)
            if clip.is_empty or clip.width < 10 or clip.height < 12:
                return None
            pix = page.get_pixmap(matrix=__import__("fitz").Matrix(4, 4), clip=clip, alpha=False)
            raster = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("L")
            inset = raster.crop(inset_box)
            if inset.width < 20 or inset.height < 20:
                return None
            gray = inset.tobytes()
            scores[name] = sum(v < 160 for v in gray) / len(gray)
        return scores

    # Dos geometrías documentadas: cuadrado 11-12pt con check y 9pt con X.
    layouts = ((-14, -6, -1, 9, (14, 14, 44, 43), 0.09, 0.08),
               (-18, -2, -4, 12, (14, 12, 46, 44), 0.22, 0.14))
    for dx0, dy0, dx1, dy1, inset, minimum_ink, min_diff in layouts:
        scores = ink_ratios(dx0, dy0, dx1, dy1, inset)
        if not scores:
            continue
        marked = max(scores, key=scores.get)
        other = "INITIAL" if marked == "FOLLOWUP" else "FOLLOWUP"
        if scores[marked] > minimum_ink and scores[marked] - scores[other] > min_diff:
            return {"value": marked, "source": "cioms_checkbox_visual",
                    "confidence": "high", "checkbox_scores": {k: round(v, 3) for k, v in scores.items()}}
    return {"value": None, "source": "cioms_checkbox_ambiguous", "confidence": "uncertain"}


def _cioms_country_from_page(page_text: str) -> Optional[str]:
    """País del campo explícito 1a, nunca una dirección o inferencia.

    Devuelve None cuando el valor es una palabra cortada o un indicador de
    continuación. La búsqueda en hojas siguientes ocurre por separado.
    """
    match = re.search(r"(?:^|\n)1a\.\s*COUNTRY\s*(?:\n|:\s*)([^\n]+)", page_text, re.I)
    if not match:
        return None
    country = re.sub(r"\s+", " ", match.group(1)).strip().upper()
    country = country.split(" - ")[0].strip()
    if (not (2 <= len(country) <= 85)
            or not re.fullmatch(r"[A-ZÀ-Ÿ .'-]+", country)
            or re.search(r"DESCRIBE|REACTION|MANUFACTURER|PATIENT|UNKNOWN|MASKED|\bCONT\b", country, re.I)
            or country in {"UNITED", "U.S.", "CONT..", "CONT."}):
        return None
    if country == "UNITED KINGDOM OF GREAT BRITAIN AND NORTHERN IRELAND":
        return "UNITED KINGDOM"
    return country


def _cioms_continuation_same_report(page_text: str, main_report_id: Optional[str]) -> bool:
    """Acepta solo hojas CIOMS de continuación del mismo control de reporte."""
    if not re.search(r"CIOMS\s+FORM", page_text, re.I):
        return False
    if not re.search(r"CONTINUATION\s+SHEET\s+FOR\s+CIOMS\s+REPORT", page_text, re.I):
        return False
    header = re.search(r"Mfr\.?\s*CONTROL\s+NO\s*:?\s*([A-Z0-9()/_-]{6,75})", page_text, re.I)
    if header and main_report_id and header.group(1).upper() != main_report_id.upper():
        return False
    return True


def extract_cioms_evidence(pdf_path: str) -> Dict[str, Any]:
    evidence = {}
    try:
        import fitz
        with fitz.open(pdf_path) as document:
            main_page_index = None
            # Extraer los demás campos únicamente de la hoja principal del CIOMS.
            for page_number in range(min(len(document), 12)):
                page_text = document[page_number].get_text("text", sort=False)
                if not page_text or not re.search(r"CIOMS\s+FORM", page_text, re.I):
                    continue
                if not re.search(r"1a\.\s*COUNTRY|24b\.\s*MFR", page_text, re.I):
                    continue
                if re.search(r"CONTINUATION\s+SHEET\s+FOR\s+CIOMS\s+REPORT", page_text, re.I):
                    continue
                main_page_index = page_number
                first_reaction = _first_reaction_from_cioms(page_text)
                if first_reaction:
                    evidence["reporte"] = {"value": first_reaction, "page": page_number + 1,
                                           "source": "cioms_first_reaction"}
                checkbox = _cioms_visual_checkbox_type(document[page_number])
                if checkbox is not None:
                    evidence["tipo"] = {**checkbox, "page": page_number + 1}
                lines = [re.sub(r"\s+", " ", x).strip() for x in page_text.splitlines() if x.strip()]
                joined = "\n".join(lines)
                patterns = {
                    "fecha_reporte": r"DATE\s+OF\s+THIS\s+REPORT\s*(?:\n|:\s*)(\d{1,2}[/\-][A-Za-z]{3,9}[/\-]\d{4}|\d{1,2}[/\-]\d{1,2}[/\-]\d{4})",
                    "id_reporte": r"24b\.\s*MFR\s+CONTROL\s+NO\.?\s*(?:\n|:\s*)([^\n]+)",
                }
                for field, pattern in patterns.items():
                    match = re.search(pattern, joined, re.I)
                    if not match:
                        continue
                    raw = match.group(1).strip()
                    if field == "fecha_reporte":
                        raw = normalizar(raw)
                        if not raw:
                            continue
                    elif field == "id_reporte":
                        raw = raw.upper()
                        if not re.fullmatch(r"[A-Z0-9][A-Z0-9()/_\-]{5,75}", raw):
                            continue
                    evidence[field] = {"value": raw, "page": page_number + 1,
                                       "source": "cioms_labeled_field"}
                main_country = _cioms_country_from_page(joined)
                if main_country:
                    evidence["pais"] = {"value": main_country, "page": page_number + 1,
                                        "source": "cioms_labeled_field"}
                break

            # Los campos 1a a veces muestran UNITED + Cont.. en la hoja principal.
            # Buscar el valor COMPLETO en la continuación del MISMO reporte, sin
            # modificar fechas/IDs/eventos, ni tomar la dirección del fabricante.
            if main_page_index is not None and not evidence.get("pais"):
                main_id = (evidence.get("id_reporte") or {}).get("value")
                for page_number in range(main_page_index + 1, min(len(document), main_page_index + 11)):
                    text = document[page_number].get_text("text", sort=False)
                    if not _cioms_continuation_same_report(text, main_id):
                        continue
                    country = _cioms_country_from_page(text)
                    if country:
                        evidence["pais"] = {"value": country, "page": page_number + 1,
                                            "source": "cioms_country_continuation"}
                        break
    except Exception as exc:
        # La validación independiente no bloquea el fallback histórico.
        evidence["_error"] = type(exc).__name__
    return evidence


def validate_selected_with_evidence(result: Dict[str, Any], evidence: Dict[str, Any]) -> Tuple[Dict[str, Any], list]:
    result = dict(result or {})
    changes = []
    for field in ("pais", "fecha_reporte", "id_reporte", "reporte", "tipo"):
        item = evidence.get(field)
        if not isinstance(item, dict):
            continue
        canonical = item["value"]
        current = result.get(field)
        # Para tipo visual ambiguo, dejar en blanco; no fabricar INITIAL/FOLLOWUP.
        if field == "tipo" and canonical is None and current is None:
            continue
        if (current or None) != (canonical or None) and (not current or str(current).strip().upper() != str(canonical).strip().upper()):
            changes.append({"field": field, "previous": current, "corrected": canonical,
                            "source": item["source"], "page": item["page"]})
            result[field] = canonical
    # Rechazar paises incompletos, aunque procedan del OCR o de la IA.
    country = str(result.get("pais") or "").strip().upper()
    if country in {"UNITED", "U.S."}:
        changes.append({"field": "pais", "previous": result.get("pais"),
                        "corrected": None, "source": "invalid_incomplete_country", "page": None})
        result["pais"] = None
    return result, changes


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
    cioms_evidence = extract_cioms_evidence(input_path)
    heuristic_result, heuristic_corrections = validate_selected_with_evidence(heuristic_result, cioms_evidence)

    res = {
        "input": input_path,
        "provider": provider,
        "model_text": final_model_text,
        "model_vision": final_model_vision,
        "ocr_status": ocr_status,
        "ocr_preview": (ocr_text[:600] + "...") if ocr_text and len(ocr_text) > 600 else ocr_text,
        "heuristics": heuristic_result,
        "cioms_evidence": cioms_evidence,
        "field_corrections": heuristic_corrections[:],
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
            raw = provider_client.text_only(
                prompt + "\nMODO SOLO TEXTO: las casillas marcadas no se identifican "
                "de forma fiable en OCR. Para 'tipo', devuelve null; nunca lo infieras de la narrativa.\n"
                + "\n\nTEXTO OCR:\n" + ocr_text
            )
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
    selection = choose_llm_first_result(res) if provider == "openai" else choose_best_result(res)
    res["best_method"] = selection["best_method"]
    res["best_result"] = selection["best_result"]
    res["ranking"] = selection["ranking"]
    res["filled_from_heuristics"] = selection.get("filled_from_heuristics", [])

    merged = merge_best_fields(res)
    res["merged_result"] = merged["merged_result"]
    res["merged_from"] = merged["merged_from"]

    res.update(build_selected_payload(res, result_view))
    # Default API view is 'best'. Explicit alternate result views remain available
    # for CLI/debugging, without changing the client-facing JSON schema.
    res["selected_result"], corrections = validate_selected_with_evidence(res.get("selected_result"), cioms_evidence)
    res["field_corrections"].extend(corrections)
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
