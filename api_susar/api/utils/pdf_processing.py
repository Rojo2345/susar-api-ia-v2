
import pdfplumber
import numpy as np
import cv2
import pytesseract
import re
from api_susar.api_utilities import PYTESERRACT_PATH
import string

pytesseract.pytesseract.tesseract_cmd = PYTESERRACT_PATH

MAX_PAGES_LIMIT = 100
#Se establece este límite debido a fallos el 05-02-2026 con un archivo de 5000 páginas.

def remove_weird_chars(text):
    # remover esto "(cid:6)""(cid:11)(cid:5)",,(cid:9)(cid:5)(cid:10)(cid:11)(cid:0)(cid:12)(cid:6)(cid:13)(cid:14)(cid:15)(cid:11)(cid:8)(cid:5)(cid:11),(cid:21)(cid:24)(cid:6)(cid:10)(cid:13)(cid:12)(cid:2)(cid:11)(cid:16)(cid:12)(cid:6)(cid:2),
    # usar regex
    text = re.sub(r'\(cid:\d+\)', '', text)
    return text


def procesar_texto(texto):
    # Eliminar el contenido dentro de paréntesis y corchetes, incluyendo espacios adyacentes
    if "(R)" in texto:
        texto = texto.replace("(R)", "R")
    texto = texto.split('(')[0]
    texto = texto.split('[')[0]
    try:
        texto = texto.strip()
        texto = texto.replace('(the max)', '')
        texto = re.sub(r'^\d+\.\s*', '', texto)
        texto = re.sub(r'\s*\(.*?\)\s*', ' ', texto)
        texto = re.sub(r'\s*\[.*?\]\s*', ' ', texto)
        texto = re.sub(r'\s*\d+\)\s*', ' ', texto)  # Eliminar números seguidos de paréntesis
        texto = re.sub(r'[^\w\s\-,\.\'"/]', ' ', texto)    # Eliminar caracteres no deseados, excepto comas, apostrofes y slash
        texto = re.sub(r'\s{2,}', ' ', texto)       # Reemplazar múltiples espacios por uno solo
        # remover estos valores: "(cid:6)""(cid:11)(cid:5)",,(cid:9)(cid:5)(cid:10)(cid:11)(cid:0)(cid:12)(cid:6)(cid:13)(cid:14)(cid:15)(cid:11)(cid:8)(cid:5)(cid:11),(cid:21)(cid:24)(cid:6)(cid:10)(cid:13)(cid:12)(cid:2)(cid:11)(cid:16)(cid:12)(cid:6)(cid:2),
        # usar regex
        texto = texto.strip()
        texto = re.sub(r'\(cid:\d+\)', '', texto)
        texto = re.sub(r'v\.\d+\.\d+', '', texto)
        texto = re.sub(r'v\d+\.\d+', '', texto)
        texto = re.sub(r'\s*,\s*', ', ', texto)     # Reemplazar espacios alrededor de comas por uno solo
        texto = texto.upper()
        texto = texto.replace('MEDDRA VERSION', '')
        texto = texto.replace('MEDDRA VERSIO', '')
        texto = texto.replace('MEDDRA VERSI', '')
        texto = texto.replace('MEDDRA VERS', '')
        texto = texto.replace('MEDDRA VER', '')
        texto = texto.replace('MEDDRA VE', '')
        texto = texto.replace('MEDDRA V', '')
        texto = texto.replace('MEDDRA', '')
        texto = texto.replace('ENGLISH', '')
        texto = texto.replace('INVESTIGATIONS-OTHER', '')
        texto = texto.replace('INVESTIGATIONS-OTHE', '')
        texto = texto.replace('INVESTIGATIONS-OTH', '')
        texto = texto.replace('INVESTIGATIONS-OT', '')
        texto = texto.replace('INVESTIGATIONS-O', '')
        texto = texto.replace('INVESTIGATIONS-', '')
        texto = texto.replace('EVENT VERBATIM', '')
        texto = texto.replace('CASE DESCRIPTION', '')
        texto = texto.replace('DESCRIBE REACTION', '')
        texto = texto.replace('OTHER SERIOUS CRITERIA', '')
        texto = texto.replace('OTROS CRITER', '')
        texto = texto.replace('OTROS CRITERI', '')
        texto = texto.replace('OTROS CRITERIO', '')
        texto = texto.replace('OTROS CRITERIOS', '')
        texto = texto.replace('OTROS CRITERIOS D', '')
        texto = texto.replace('OTROS CRITERIOS DE', '')
        texto = texto.replace('OTROS CRITERIOS DE SE', '')
        texto = texto.replace('OTROS CRITERIOS DE SERIE', '')
        texto = texto.replace('OTROS CRITERIOS DE SERIEDAD M', '')
        texto = texto.replace('OTROS CRITERIOS DE SERIEDAD MÉDICAMENTE SIGNIFICATIVO', '')
        texto = texto.replace('OTROS CRITERIOS SE', '')
        texto = texto.replace('OTROS CRITERIOS SERIOS M', '')
        return texto.strip()
    except:
        return texto


def preprocess_image(image, target_size=640):
    """
    Redimensiona la imagen a un cuadrado de 640x640 píxeles deformándola.
    """
    # Redimensionar la imagen directamente al tamaño objetivo
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    resized_image = cv2.resize(image, (target_size, target_size), interpolation=cv2.INTER_LINEAR)
    return resized_image


def predict(chosen_model, img):
    return chosen_model.predict(img, conf=0.4, verbose=False, device="cpu")


def should_process_page(boxes, names, labels_of_interest, confidence_threshold=0.7):
    for box in boxes:
        label = names[int(box.cls[0])]
        confidence = box.conf.cpu().numpy()[0]
        if label in labels_of_interest and confidence > confidence_threshold:
            return True
    return False


def safe_margin(x1, x2, y1, y2, label, mode, img_width):
    if mode == 'ocr':
        margin = 0
        if label == 'Reporte':
            margin += (10 * 7)
            x1 = max(0, x1 - margin)
            x2 = min(img_width, x2 + margin)
        return x1, x2, y1, y2
    elif mode == 'pdf':
        margin = 3
        y1 = y1+margin+1
        y2 = y2-margin

        if y2 - y1 <= 0:
            y1 = y1 - 1
            y2 = y2 + 1

        if y2 - y1 <= 0:
            y1 = y1 - 1
            y2 = y2 + 1

        if label == 'Reporte':

            margin += 10
            x1 = max(0, x1 - margin)
            x2 = min(img_width, x2 + margin)
        return x1, x2, y1, y2

def pytesseract_ocr(image):
    """
    Extrae texto de una imagen utilizando pytesseract.
    """
    try:
        return pytesseract.image_to_string(image, lang='eng+spa')
    except Exception as e:
        print("Error en pytesseract, ", e)
        return ''

def predict_and_detect_with_ocr(img, results):
    ocr_results = {}
    proccesed_labels = []
    for box in results[0].boxes:
        label = results[0].names[int(box.cls[0])]
        if label in proccesed_labels or (label == 'FOLLOWUP' and 'INITIAL' in proccesed_labels) or (label == 'INITIAL' and 'FOLLOWUP' in proccesed_labels):
            continue
        proccesed_labels.append(label)
        xyxy = box.xyxy.cpu().numpy()[0]
        x1, y1, x2, y2 = map(int, xyxy)

        # Scale bounding box coordinates considering predictions are on a 640x640 image
        scaling_factor_x = img.shape[1] / 640
        scaling_factor_y = img.shape[0] / 640
        x1 = int(x1 * scaling_factor_x)
        y1 = int(y1 * scaling_factor_y)
        x2 = int(x2 * scaling_factor_x)
        y2 = int(y2 * scaling_factor_y)

        x1, x2, y1, y2 = safe_margin(x1, x2, y1, y2, label, 'ocr', img.shape[1])

        cropped_img = img[y1:y2, x1:x2]
        bbox_text = pytesseract_ocr(cropped_img)

        bbox_text = bbox_text.replace('|', '')
        # text processing
        bbox_text = bbox_text.strip()
        bbox_text = bbox_text.strip('/').strip()
        bbox_text = bbox_text.replace('\n', ', ').strip(', ')
        bbox_text = remove_weird_chars(bbox_text)
        bbox_text = procesar_texto(bbox_text) if label == 'Reporte' else bbox_text
        bbox_text = bbox_text.strip(', ')
        if label != 'Reporte':
            bbox_text = bbox_text.replace(', ', ' ')
        bbox_text = bbox_text.upper()
        bbox_text = bbox_text.strip()
        
        if label == 'Fecha del reporte':
            bbox_text = bbox_text.replace('DATE OF THIS REPORT', '').strip('')
            bbox_text = bbox_text.replace('BY MANUFACTURER', '').strip('')
            bbox_text = bbox_text.replace('24C. DATE RECEIVED', '').strip('')
            bbox_text = bbox_text.strip()
        elif label == 'Id del reporte':
            bbox_text = bbox_text.replace('24B.MFRCONTROLNO.', '').strip('')
            bbox_text = bbox_text.replace('24D.REPORTSOURCE', '').strip('')
            bbox_text = bbox_text.replace('STUDY', '').strip('')
            bbox_text = bbox_text.replace('LITERATURE', '').strip('')
            bbox_text = bbox_text.replace('HEALTH', '').strip('')
            bbox_text = bbox_text.replace('PROFESIONAL', '').strip('')
            bbox_text = bbox_text.replace('OTHER', '').strip('')
            bbox_text = bbox_text.replace(':', '').strip('')
            bbox_text = bbox_text.strip()

        if label == 'FOLLOWUP':
            ocr_results[label] = "FOLLOWUP"
        elif label == 'INITIAL':
            ocr_results[label] = "INITIAL"
        else:
            ocr_results[label] = bbox_text

    return ocr_results


def extract_text_from_pdf(pdf_path, model):
    ocr_results = {}
    with pdfplumber.open(pdf_path) as pdf:
		#06-02-2026 
		# --- NUEVA VALIDACIÓN ---
        # Verificar cantidad de páginas antes de procesar nada.
        # Esto es muy rápido y no consume memoria porque solo lee los metadatos.
        if len(pdf.pages) > MAX_PAGES_LIMIT:
			
            raise ValueError(f"El archivo excede el límite de páginas permitido ({len(pdf.pages)} > {MAX_PAGES_LIMIT}). Procesamiento abortado para proteger el sistema.")
        for page_idx, page in enumerate(pdf.pages):
            for dpi in [100, 75, 72]:
                page_image = preprocess_image(np.array(page.to_image(antialias=True, resolution=dpi).original))

                # Perform detection
                results = predict(model, page_image)

                # remove duplicates with lower confidence
                results[0].boxes = sorted(results[0].boxes, key=lambda x: x.conf.cpu().numpy()[0], reverse=True)

               

                # si no se detecto reporte, continuamos
                no_hay_reporte = True
                for box in results[0].boxes:
                    label = results[0].names[int(box.cls[0])]
                    if label in ['Reporte']:
                        no_hay_reporte = False
                        break
                if no_hay_reporte:
                    continue
				
				# ignorar si no hay followup ni initial
                ignore = not should_process_page(results[0].boxes, results[0].names, {'FOLLOWUP', 'INITIAL'},  0.8)

                if ignore:
                    break
                
                page_results = {}
                proccesed_labels = []
                for box in results[0].boxes:
                    xyxy = box.xyxy.cpu().numpy()[0]  # Get bounding box coordinates
                    label = results[0].names[int(box.cls[0])]
                    if label in proccesed_labels or (label == 'FOLLOWUP' and 'INITIAL' in proccesed_labels) or (label == 'INITIAL' and 'FOLLOWUP' in proccesed_labels):
                        continue
                    proccesed_labels.append(label)
                    x1, y1, x2, y2 = map(int, xyxy)
                    page_width, page_height = page.width, page.height
                    scaling_factor_x = page_width / page_image.shape[1]  # Scale for width
                    scaling_factor_y = page_height / page_image.shape[0]  # Scale for height
                    # Scale bounding box coordinates
                    x1 = int(max(0, min(x1 * scaling_factor_x, page_width)))
                    y1 = int(max(0, min(y1 * scaling_factor_y, page_height)))
                    x2 = int(max(0, min(x2 * scaling_factor_x, page_width)))
                    y2 = int(max(0, min(y2 * scaling_factor_y, page_height)))
                    
                    x1, x2, y1, y2 = safe_margin(x1, x2, y1, y2, label, 'pdf', page_width)
                    
                    # Extract text within bounding box with margin
                    bbox_text = page.crop((x1, y1, x2, y2)).extract_text()

                    # text processing
                    bbox_text = bbox_text.strip()
                    bbox_text = bbox_text.replace('\n', ', ').strip(', ')
                    bbox_text = remove_weird_chars(bbox_text)
                    bbox_text = procesar_texto(bbox_text) if label == 'Reporte' else bbox_text
                    bbox_text = bbox_text.strip(', ')
                    if label != 'Reporte':
                        bbox_text = bbox_text.replace(', ', ' ')
                    bbox_text = bbox_text.upper()
                    bbox_text = bbox_text.strip()

                    if label == 'Fecha del reporte':
                        bbox_text = bbox_text.replace('DATE OF THIS REPORT','').strip('')
                        bbox_text = bbox_text.replace('BY MANUFACTURER','').strip('')
                        bbox_text = bbox_text.replace('24C. DATE RECEIVED','').strip('')
                        bbox_text = bbox_text.strip()
                    elif label == 'Id del reporte':
                        bbox_text = bbox_text.replace('24B.MFRCONTROLNO.','').strip('')
                        bbox_text = bbox_text.replace('24D.REPORTSOURCE','').strip('')
                        bbox_text = bbox_text.replace('STUDY','').strip('')
                        bbox_text = bbox_text.replace('LITERATURE','').strip('')
                        bbox_text = bbox_text.replace('HEALTH','').strip('')
                        bbox_text = bbox_text.replace('PROFESIONAL','').strip('')
                        bbox_text = bbox_text.replace('OTHER','').strip('')
                        bbox_text = bbox_text.replace(':','').strip('')
                        bbox_text = bbox_text.strip()
                    valid_chars = set(string.ascii_letters + '☒ÁÉÍÓÚÜáéíóúüñÑ 0123456789,.-()/_:"' + "'")
                    # si llegados este punto y habiendo detectado fecha del reporte, aun así esta vacio. Usar OCR como segunda opción
                    if (bbox_text == '' and label == 'Fecha del reporte') or any(char not in valid_chars for char in bbox_text) or (label == 'Reporte' and bbox_text == ''):
                        image = np.array(page.to_image(antialias=True, resolution=500).original)
                        img = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                        # Perform detection and OCR
                        page_results = predict_and_detect_with_ocr(img, results)
                        break
                    else:
                        if label == 'FOLLOWUP':
                            page_results[label] = "FOLLOWUP"
                        elif label == 'INITIAL':
                            page_results[label] = "INITIAL"
                        else:
                            page_results[label] = bbox_text

                ocr_results[f"page_{page_idx + 1}"] = page_results
                if not no_hay_reporte:
                    break

    return ocr_results