import hashlib
import json
import os
import re
import sqlite3
import uuid
from datetime import date, datetime

from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file, send_from_directory

try:
    import pytesseract
except ImportError:  # pragma: no cover - optional dependency
    pytesseract = None

try:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps
except ImportError:  # pragma: no cover - optional dependency
    Image = None
    ImageEnhance = None
    ImageFilter = None
    ImageOps = None

try:
    from reportlab.pdfgen import canvas
except ImportError:  # pragma: no cover - optional dependency
    canvas = None

app = Flask(__name__)
app.secret_key = 'smartmetriq-demo-secret-key'

UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE = 10 * 1024 * 1024
DB_PATH = os.path.join(app.root_path, 'smartmetriq.db')

LANGUAGE_OPTIONS = {
    'eng': 'English',
    'hin': 'Hindi',
    'kan': 'Kannada',
    'eng+hin': 'English + Hindi',
    'eng+kan': 'English + Kannada',
    'hin+kan': 'Hindi + Kannada',
    'eng+hin+kan': 'English + Hindi + Kannada',
}

LEGAL_RULES = {
    'product_name': {
        'title': 'Product Name',
        'summary': 'The product name should be clearly shown so the item is identifiable.',
        'reference': 'Legal Metrology packaging declarations'
    },
    'mrp': {
        'title': 'MRP',
        'summary': 'The maximum retail price should be clearly declared where required.',
        'reference': 'Rules for declaration of price and quantity'
    },
    'quantity': {
        'title': 'Net Quantity',
        'summary': 'The declared net quantity should be visible and readable.',
        'reference': 'Net quantity declarations'
    },
    'manufacturer': {
        'title': 'Manufacturer / Packer / Importer',
        'summary': 'Required identity details should be declared for traceability.',
        'reference': 'Producer and importer declarations'
    },
    'date': {
        'title': 'Date Information',
        'summary': 'Manufacturing, packing, or import dates should be clear where required.',
        'reference': 'Date of manufacture and packaging declaration'
    },
    'care': {
        'title': 'Consumer Care',
        'summary': 'Consumer care details should be available where applicable.',
        'reference': 'Consumer grievance and contact information'
    },
    'origin': {
        'title': 'Country of Origin',
        'summary': 'Origin should be clearly declared for relevant imported products.',
        'reference': 'Country of origin and import declarations'
    },
}

VIOLATION_LABELS = {
    'Missing Information': 'Missing Information',
    'MRP Problem': 'MRP Problem',
    'Quantity Problem': 'Quantity Problem',
    'Manufacturer Details': 'Manufacturer Details',
    'Date Problem': 'Date Problem',
    'Consumer Care Problem': 'Consumer Care Problem',
    'Country of Origin': 'Country of Origin',
    'Text Not Clear': 'Text Not Clear',
    'Unable to Read': 'Unable to Read',
    'Other Issue': 'Other Issue',
}

VIOLATION_DISPLAY_MAP = {
    'R001': {
        'category': 'Missing Information',
        'detail': 'A required declaration could not be found.',
        'action': 'Please check the original product label and confirm the missing declaration.'
    },
    'R002': {
        'category': 'Missing Information',
        'detail': 'A required declaration could not be found.',
        'action': 'Please check the original product label and confirm the missing declaration.'
    },
    'R003': {
        'category': 'MRP Problem',
        'detail': 'MRP could not be clearly detected.',
        'action': 'Please verify the MRP on the original product label.'
    },
    'R004': {
        'category': 'Date Problem',
        'detail': 'A date marking could not be clearly detected.',
        'action': 'Please verify the manufacturing or packing date on the original product label.'
    },
    'R005': {
        'category': 'Quantity Problem',
        'detail': 'Net quantity could not be clearly detected.',
        'action': 'Please verify the net quantity on the original product label.'
    },
    'R006': {
        'category': 'Manufacturer Details',
        'detail': 'Manufacturer or address information could not be clearly detected.',
        'action': 'Please confirm the manufacturer, packer, importer or address details on the original label.'
    },
    'R007': {
        'category': 'Consumer Care Problem',
        'detail': 'Consumer care information could not be clearly detected.',
        'action': 'Please verify the consumer care phone number, email or contact details on the original label.'
    },
    'R008': {
        'category': 'Country of Origin',
        'detail': 'Country of origin information could not be clearly detected.',
        'action': 'Please confirm the country of origin on the original product label.'
    },
    'R009': {
        'category': 'Text Not Clear',
        'detail': 'The label text is present but difficult to read.',
        'action': 'Please review the label image and check the text size, clarity and image quality.'
    },
    'R010': {
        'category': 'Unable to Read',
        'detail': 'OCR could not reliably read the required information.',
        'action': 'Please review the original label manually to confirm the details.'
    },
    'R011': {
        'category': 'Other Issue',
        'detail': 'An issue was found that does not fit the common categories.',
        'action': 'Please review the original product label and note the issue for manual verification.'
    }
}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
PROCESSED_IMAGE_FOLDER = os.path.join(UPLOAD_FOLDER, 'processed')
os.makedirs(PROCESSED_IMAGE_FOLDER, exist_ok=True)


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS inspections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inspection_id TEXT UNIQUE,
            user_id TEXT,
            product_name TEXT,
            product_type TEXT,
            image_path TEXT,
            language TEXT,
            language_code TEXT,
            ocr_text TEXT,
            extracted_data TEXT,
            compliance_status TEXT,
            violation_details TEXT,
            officer_notes TEXT,
            evidence_hash TEXT,
            created_at TEXT,
            updated_at TEXT,
            result_summary TEXT,
            score INTEGER,
            findings TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inspection_id TEXT,
            user_id TEXT,
            event_type TEXT,
            description TEXT,
            timestamp TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS complaints (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            complaint_id TEXT UNIQUE,
            consumer TEXT,
            product_name TEXT,
            complaint_description TEXT,
            image_path TEXT,
            image_filename TEXT,
            ocr_result TEXT,
            extracted_data TEXT,
            compliance_result TEXT,
            status TEXT,
            evidence_hash TEXT,
            created_at TEXT,
            updated_at TEXT,
            metadata TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def generate_complaint_id():
    today = date.today().strftime('%Y%m%d')
    conn = get_db_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM complaints WHERE complaint_id LIKE ?",
        (f'CMP-{today}-%',),
    ).fetchone()
    conn.close()
    count = int(row[0]) + 1 if row else 1
    return f'CMP-{today}-{count:04d}'


def save_complaint_record(record):
    complaint_id = record.get('complaint_id') or generate_complaint_id()
    payload = {
        'complaint_id': complaint_id,
        'consumer': record.get('consumer') or session.get('username') or 'consumer',
        'product_name': record.get('product_name') or 'Unknown Product',
        'complaint_description': record.get('complaint_description') or '',
        'image_path': record.get('image_path') or '',
        'image_filename': record.get('image_filename') or os.path.basename(record.get('image_path') or ''),
        'ocr_result': record.get('ocr_result') or '',
        'extracted_data': json.dumps(record.get('extracted_data', {}), ensure_ascii=False),
        'compliance_result': json.dumps(record.get('compliance_result', {}), ensure_ascii=False),
        'status': record.get('status') or 'SUBMITTED',
        'evidence_hash': record.get('evidence_hash') or '',
        'created_at': record.get('created_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': record.get('updated_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'metadata': json.dumps(record.get('metadata', {}), ensure_ascii=False),
    }

    conn = get_db_connection()
    conn.execute(
        """
        INSERT OR REPLACE INTO complaints (
            complaint_id, consumer, product_name, complaint_description, image_path, image_filename,
            ocr_result, extracted_data, compliance_result, status, evidence_hash, created_at, updated_at, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            payload['complaint_id'], payload['consumer'], payload['product_name'], payload['complaint_description'],
            payload['image_path'], payload['image_filename'], payload['ocr_result'], payload['extracted_data'],
            payload['compliance_result'], payload['status'], payload['evidence_hash'], payload['created_at'],
            payload['updated_at'], payload['metadata'],
        ),
    )
    conn.commit()
    conn.close()
    return payload


def get_complaint_records(user=None):
    conn = get_db_connection()
    if user:
        rows = conn.execute(
            "SELECT * FROM complaints WHERE consumer = ? ORDER BY created_at DESC",
            (user,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM complaints ORDER BY created_at DESC").fetchall()
    conn.close()

    complaints = []
    for row in rows:
        complaints.append({
            'id': row['complaint_id'],
            'complaint_id': row['complaint_id'],
            'consumer': row['consumer'],
            'product_name': row['product_name'] or 'Unknown Product',
            'complaint_description': row['complaint_description'] or '',
            'image_path': row['image_path'] or '',
            'image_filename': row['image_filename'] or '',
            'ocr_result': row['ocr_result'] or '',
            'extracted_data': json.loads(row['extracted_data']) if row['extracted_data'] else {},
            'compliance_result': json.loads(row['compliance_result']) if row['compliance_result'] else {},
            'status': row['status'] or 'SUBMITTED',
            'evidence_hash': row['evidence_hash'] or '',
            'created_at': row['created_at'] or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': row['updated_at'] or row['created_at'],
            'metadata': json.loads(row['metadata']) if row['metadata'] else {},
        })
    return complaints


def get_complaint_by_id(complaint_id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM complaints WHERE complaint_id = ?", (complaint_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        'id': row['complaint_id'],
        'complaint_id': row['complaint_id'],
        'consumer': row['consumer'],
        'product_name': row['product_name'] or 'Unknown Product',
        'complaint_description': row['complaint_description'] or '',
        'image_path': row['image_path'] or '',
        'image_filename': row['image_filename'] or '',
        'ocr_result': row['ocr_result'] or '',
        'extracted_data': json.loads(row['extracted_data']) if row['extracted_data'] else {},
        'compliance_result': json.loads(row['compliance_result']) if row['compliance_result'] else {},
        'status': row['status'] or 'SUBMITTED',
        'evidence_hash': row['evidence_hash'] or '',
        'created_at': row['created_at'] or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'updated_at': row['updated_at'] or row['created_at'],
        'metadata': json.loads(row['metadata']) if row['metadata'] else {},
    }


def seed_demo_complaints():
    existing = get_complaint_records('consumer')
    if len(existing) >= 3:
        return existing

    demo_cases = [
        {
            'complaint_id': 'CMP-20260913-0001',
            'consumer': 'consumer',
            'product_name': 'Rice Pack 5kg',
            'complaint_description': 'Label lacks clear MRP and origin details.',
            'image_path': '',
            'image_filename': '',
            'ocr_result': 'Rice Pack 5kg\nMRP unclear\nCountry of Origin unclear',
            'extracted_data': {'product_name': 'Rice Pack 5kg', 'quantity': '5kg'},
            'compliance_result': {'status': 'REVIEW REQUIRED', 'summary': 'Sample review required'},
            'status': 'SUBMITTED',
            'evidence_hash': 'demo-evidence-1',
            'created_at': '2026-09-13 08:00:00',
            'updated_at': '2026-09-13 08:00:00',
            'metadata': {'source': 'demo'},
        },
        {
            'complaint_id': 'CMP-20260913-0002',
            'consumer': 'consumer',
            'product_name': 'Tea Masala 250g',
            'complaint_description': 'Need review for MRP and quantity readability.',
            'image_path': '',
            'image_filename': '',
            'ocr_result': 'Tea Masala 250g\nRate unclear\nNet Qty 250g',
            'extracted_data': {'product_name': 'Tea Masala 250g', 'quantity': '250g'},
            'compliance_result': {'status': 'UNDER REVIEW', 'summary': 'Sample complaint in review'},
            'status': 'UNDER REVIEW',
            'evidence_hash': 'demo-evidence-2',
            'created_at': '2026-09-13 09:10:00',
            'updated_at': '2026-09-13 09:20:00',
            'metadata': {'source': 'demo'},
        },
        {
            'complaint_id': 'CMP-20260913-0003',
            'consumer': 'consumer',
            'product_name': 'Soap Bar 100g',
            'complaint_description': 'Consumer care and date marking require confirmation.',
            'image_path': '',
            'image_filename': '',
            'ocr_result': 'Soap Bar 100g\nConsumer care unclear\nMfg date not visible',
            'extracted_data': {'product_name': 'Soap Bar 100g'},
            'compliance_result': {'status': 'RESOLVED', 'summary': 'Sample resolved complaint'},
            'status': 'RESOLVED',
            'evidence_hash': 'demo-evidence-3',
            'created_at': '2026-09-13 10:30:00',
            'updated_at': '2026-09-13 10:45:00',
            'metadata': {'source': 'demo'},
        },
    ]

    for case in demo_cases:
        save_complaint_record(case)
    return get_complaint_records('consumer')


init_db()

def ensure_inspection_schema():
    conn = get_db_connection()
    columns = [row['name'] for row in conn.execute("PRAGMA table_info(inspections)").fetchall()]
    if 'source_type' not in columns:
        conn.execute("ALTER TABLE inspections ADD COLUMN source_type TEXT DEFAULT 'PHYSICAL_PRODUCT'")
    conn.commit()
    conn.close()


ensure_inspection_schema()
seed_demo_complaints()


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_file(file_storage, target_folder=None):
    if file_storage is None or file_storage.filename == '':
        raise ValueError('No file was selected.')

    if not allowed_file(file_storage.filename):
        raise ValueError('Invalid file type. Only JPG, JPEG, and PNG files are allowed.')

    if file_storage.content_length and file_storage.content_length > MAX_FILE_SIZE:
        raise ValueError('File is too large. Please upload an image under 10 MB.')

    file_ext = os.path.splitext(file_storage.filename)[1].lower()
    unique_name = f"{uuid.uuid4().hex}{file_ext}"
    destination_folder = target_folder or UPLOAD_FOLDER
    os.makedirs(destination_folder, exist_ok=True)
    file_path = os.path.join(destination_folder, unique_name)
    file_storage.save(file_path)
    return unique_name


def get_language_label(language_value):
    value = (language_value or 'eng').strip()
    return LANGUAGE_OPTIONS.get(value, value)


def get_tesseract_language_code(language_value):
    value = (language_value or 'eng').strip()
    if value in LANGUAGE_OPTIONS:
        return value
    normalized = value.lower().replace(' ', '')
    return normalized if normalized else 'eng'


def get_ai_model_status():
    metadata_path = os.path.join(app.root_path, 'models', 'model_version.json')
    evaluation_path = os.path.join(app.root_path, 'models', 'evaluation_results.json')

    default_status = {
        'status': 'Model not trained yet',
        'dataset': 'Product Description Image - English Hindi OCR',
        'model_version': 'N/A',
        'training_date': 'N/A',
        'precision': None,
        'recall': None,
        'f1': None,
        'mAP': None,
        'using': 'Standard OCR',
        'available': False,
    }

    if not os.path.exists(metadata_path):
        return default_status

    try:
        with open(metadata_path, 'r', encoding='utf-8') as fh:
            metadata = json.load(fh)
    except Exception:
        return default_status

    status = {
        'status': 'Available',
        'dataset': metadata.get('dataset', 'Product Description Image - English Hindi OCR'),
        'model_version': metadata.get('version', 'v1.0'),
        'training_date': metadata.get('training_date', 'N/A'),
        'precision': None,
        'recall': None,
        'f1': None,
        'mAP': None,
        'using': 'ML text detection + OCR',
        'available': True,
    }

    if os.path.exists(evaluation_path):
        try:
            with open(evaluation_path, 'r', encoding='utf-8') as fh:
                metrics = json.load(fh)
            status['precision'] = metrics.get('precision')
            status['recall'] = metrics.get('recall')
            status['f1'] = metrics.get('f1')
            status['mAP'] = metrics.get('mAP')
        except Exception:
            pass

    return status


def format_violation_display(value):
    if value is None:
        return {
            'category': 'Other Issue',
            'detail': 'An issue was found during review.',
            'action': 'Please review the original product label manually.'
        }

    raw_value = str(value).strip()
    if not raw_value:
        return {
            'category': 'Other Issue',
            'detail': 'An issue was found during review.',
            'action': 'Please review the original product label manually.'
        }

    code = raw_value.upper()
    if code.startswith('R') and code in VIOLATION_DISPLAY_MAP:
        return VIOLATION_DISPLAY_MAP[code].copy()

    key = raw_value.lower()
    if 'mrp' in key or 'rate' in key or 'price' in key:
        return VIOLATION_DISPLAY_MAP['R003'].copy()
    if 'date' in key or 'manufactur' in key or 'packing' in key:
        return VIOLATION_DISPLAY_MAP['R004'].copy()
    if 'quantity' in key or 'net qty' in key or 'net quantity' in key:
        return VIOLATION_DISPLAY_MAP['R005'].copy()
    if 'manufacturer' in key or 'packer' in key or 'importer' in key or 'address' in key:
        return VIOLATION_DISPLAY_MAP['R006'].copy()
    if 'consumer care' in key or 'care' in key or 'phone' in key or 'email' in key:
        return VIOLATION_DISPLAY_MAP['R007'].copy()
    if 'origin' in key:
        return VIOLATION_DISPLAY_MAP['R008'].copy()
    if 'not clear' in key or 'readability' in key or 'difficult to read' in key or 'clarity' in key:
        return VIOLATION_DISPLAY_MAP['R009'].copy()
    if 'unable to read' in key or 'unable' in key or 'could not reliably read' in key or 'ocr' in key:
        return VIOLATION_DISPLAY_MAP['R010'].copy()
    if 'missing' in key:
        return VIOLATION_DISPLAY_MAP['R001'].copy()

    return {
        'category': 'Other Issue',
        'detail': 'An issue was found during review.',
        'action': 'Please review the original product label manually.'
    }


def build_violation_display_list(values):
    if values is None:
        return []
    if isinstance(values, str):
        values = [values]
    items = []
    for value in values:
        display = format_violation_display(value)
        if display not in items:
            items.append(display)
    return items


def normalize_product_name(value, image_type='front'):
    fallback = f"{(image_type or 'front').replace('_', ' ').title()} Product"
    if value is None:
        return fallback

    text = str(value).strip()
    if not text:
        return fallback

    lowered = text.lower()
    failure_markers = [
        'text could not be clearly detected',
        'manual verification required',
        'could not be clearly detected',
        'could not be reliably read',
        'no text detected',
        'label text detected',
        'unable to read',
        'ocr quality was insufficient',
        'insufficient to make a reliable decision',
        'no label text detected',
        'not clearly detected',
        'unable to detect',
    ]
    if any(marker in lowered for marker in failure_markers):
        return fallback
    return text


def _safe_ocr_text(raw_text):
    if raw_text is None:
        return ''
    return re.sub(r'\s+', ' ', str(raw_text)).strip()


def _estimate_ocr_confidence(image, language_code):
    if pytesseract is None or Image is None:
        return 0.0
    try:
        data = pytesseract.image_to_data(image, lang=language_code, output_type=pytesseract.Output.DICT)
        conf_values = []
        for item in data.get('conf', []):
            try:
                conf_values.append(float(item))
            except Exception:
                pass
        if not conf_values:
            return 0.0
        return max(0.0, min(100.0, sum(conf_values) / len(conf_values)))
    except Exception:
        return 0.0


def _rotate_image_for_best_ocr(image, language_code):
    if pytesseract is None or Image is None:
        return image, 0

    best_image = image
    best_score = -1
    best_angle = 0
    for angle in (0, 90, 180, 270):
        candidate = image.rotate(angle, expand=True) if angle else image.copy()
        try:
            text = pytesseract.image_to_string(candidate, lang=language_code, config='--psm 6')
            cleaned = _safe_ocr_text(text)
            score = len(re.sub(r'\s+', '', cleaned)) + (0.1 * _estimate_ocr_confidence(candidate, language_code))
        except Exception:
            score = 0
        if score > best_score:
            best_score = score
            best_image = candidate
            best_angle = angle
    return best_image, best_angle


def _apply_preprocessing_pipeline(image):
    if Image is None or ImageEnhance is None or ImageFilter is None or ImageOps is None:
        return {'normal': image}

    image = ImageOps.exif_transpose(image).convert('RGB')

    if min(image.size) < 1200:
        scale = 1400 / min(image.size)
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)

    gray = ImageOps.grayscale(image)
    gray = ImageOps.autocontrast(gray)
    gray = ImageEnhance.Contrast(gray).enhance(1.8)
    gray = gray.filter(ImageFilter.MedianFilter(3))
    gray = gray.filter(ImageFilter.SHARPEN)

    threshold = gray.point(lambda p: 255 if p > 180 else 0)
    return {
        'normal': ImageEnhance.Contrast(image).enhance(1.5).filter(ImageFilter.SHARPEN),
        'grayscale': gray,
        'threshold': threshold,
    }


def prepare_image_for_ocr(image_path, requested_language='eng'):
    if pytesseract is None or Image is None or not os.path.exists(image_path):
        return image_path

    original = Image.open(image_path)
    original = ImageOps.exif_transpose(original)
    rotated, _ = _rotate_image_for_best_ocr(original, get_tesseract_language_code(requested_language))
    variant_map = _apply_preprocessing_pipeline(rotated)

    processed = []
    for name, variant in variant_map.items():
        candidate_path = os.path.join(PROCESSED_IMAGE_FOLDER, f'{uuid.uuid4().hex}_{name}.png')
        variant.save(candidate_path, format='PNG')
        processed.append(candidate_path)
    return processed[0] if processed else image_path


def perform_multilingual_ocr(image_path, requested_language='eng'):
    language_code = get_tesseract_language_code(requested_language)
    language_label = get_language_label(language_code)

    fallback = {
        'success': False,
        'text': 'Text could not be clearly detected. Manual verification required.',
        'raw_text': '',
        'cleaned_text': 'Text could not be clearly detected. Manual verification required.',
        'language': language_label,
        'language_code': language_code,
        'confidence': 0.0,
        'processed_image_path': '',
        'debug': {
            'variants': [],
            'selected_variant': 'None',
            'processed_image_path': '',
            'confidence': 0.0,
            'rotation_applied': 0,
        },
    }

    if pytesseract is None or Image is None:
        return fallback

    try:
        original = Image.open(image_path)
        original = ImageOps.exif_transpose(original)
        rotated, best_angle = _rotate_image_for_best_ocr(original, language_code)
        variants = _apply_preprocessing_pipeline(rotated)
        scored = []

        for name, variant in variants.items():
            variant_path = os.path.join(PROCESSED_IMAGE_FOLDER, f'{uuid.uuid4().hex}_{name}.png')
            variant.save(variant_path, format='PNG')
            raw_text = pytesseract.image_to_string(variant, lang=language_code, config='--psm 6')
            cleaned = _safe_ocr_text(raw_text)
            confidence = _estimate_ocr_confidence(variant, language_code)
            scored.append({
                'name': name,
                'path': variant_path,
                'raw_text': raw_text,
                'cleaned_text': cleaned,
                'confidence': confidence,
                'angle': best_angle,
            })

        if not scored:
            return fallback

        best = max(scored, key=lambda item: (item['confidence'], len(item['cleaned_text'])))
        cleaned = best['cleaned_text']
        if not cleaned:
            return fallback

        return {
            'success': True,
            'text': cleaned,
            'raw_text': best['raw_text'],
            'cleaned_text': cleaned,
            'language': language_label,
            'language_code': language_code,
            'confidence': round(best['confidence'], 2),
            'processed_image_path': best['path'],
            'debug': {
                'variants': [
                    {'name': item['name'], 'path': item['path'], 'confidence': round(item['confidence'], 2), 'angle': item['angle']}
                    for item in scored
                ],
                'selected_variant': best['name'],
                'processed_image_path': best['path'],
                'confidence': round(best['confidence'], 2),
                'rotation_applied': best_angle,
            },
        }
    except Exception:
        return fallback


def extract_product_metadata(ocr_text, image_type='front'):
    product_name = f"{(image_type or 'front').replace('_', ' ').title()} Product"
    extracted = {
        'product_name': product_name,
        'manufacturer': None,
        'address': None,
        'quantity': None,
        'mrp': None,
        'mfg_date': None,
        'use_by_date': None,
        'batch_lot': None,
        'care_instructions': None,
        'origin': None,
        'raw_text': ocr_text or '',
    }

    if not ocr_text:
        return extracted

    text = _safe_ocr_text(ocr_text)
    normalized_text = text.lower()
    fallback_markers = [
        'text could not be clearly detected',
        'manual verification required',
        'could not be clearly detected',
        'no text detected',
        'unable to read',
    ]
    if any(marker in normalized_text for marker in fallback_markers):
        extracted['product_name'] = normalize_product_name(f"{(image_type or 'front').replace('_', ' ').title()} Product", image_type)
        return extracted

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    if lines:
        top_line = lines[0]
        if len(top_line) <= 80 and not re.match(r'^(?:m[rd]p|net|quantity|manufactured|packed|consumer|country|batch|lot|expiry|use by|rate)', top_line, re.I):
            extracted['product_name'] = top_line

    manufacturer_patterns = [
        r'(?:manufactured\s*(?:by|from)|packing\s*(?:by|from)|packed\s*(?:by|at)|imported\s*(?:by|from)|mfr\s*)\s*[:\-]?\s*([A-Za-z0-9,./&() -]+)',
        r'(?:manufactured\s*&\s*marketed\s*(?:by|from)|marketed\s*by)\s*[:\-]?\s*([A-Za-z0-9,./&() -]+)'
    ]
    for pattern in manufacturer_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            extracted['manufacturer'] = re.sub(r'\s+', ' ', match.group(1)).strip(' ,;:-')
            break

    if extracted['manufacturer'] is None:
        for line in lines:
            lowered = line.lower()
            if any(token in lowered for token in ['manufactured by', 'manufactured & marketed by', 'packed by', 'imported by', 'mfr', 'manufacturer']):
                extracted['manufacturer'] = re.sub(r'^(?:manufactured|packed|imported|manufacturer|mfr)\s*(?:by|from)?\s*[:\-]?\s*', '', line, flags=re.I)
                break

    address_match = re.search(r'(?:address|office|factory|plot|street|hno|no\.)\s*[:\-]?\s*([A-Za-z0-9,./ -]+)', text, flags=re.IGNORECASE)
    if address_match:
        extracted['address'] = re.sub(r'\s+', ' ', address_match.group(1)).strip(' ,;:-')

    quantity_patterns = [
        r'(?:net\s*qty|net\s*quantity|quantity|qty)\s*[:\-]?\s*([0-9]+\.?[0-9]*\s*(?:g|kg|ml|l|mg|gm|lbs?|oz))',
        r'([0-9]+\.?[0-9]*\s*(?:g|kg|ml|l|mg|gm|lbs?|oz))\s*(?:net\s*qty|net\s*quantity|quantity|qty)?',
    ]
    for pattern in quantity_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            extracted['quantity'] = re.sub(r'\s+', ' ', match.group(1)).strip()
            break

    mrp_match = re.search(r'(?:m\.r\.p\.|mrp|maximum\s+retail\s+price|mrp\s*/\s*usp)\s*[:\-]?\s*(?:rs\.?|₹)?\s*([0-9]+(?:\.[0-9]+)?)', text, flags=re.IGNORECASE)
    if not mrp_match:
        strict_match = re.search(r'(?:mrp|maximum retail price|m\.r\.p\.)\s*[:\-]?\s*.*?(?:rs\.?|₹)?\s*([0-9]+(?:\.[0-9]+)?)', text, flags=re.IGNORECASE)
        if strict_match:
            mrp_match = strict_match
    if mrp_match:
        extracted['mrp'] = mrp_match.group(1)

    date_patterns = [
        r'(?:mfd|mfg|manufactured|packed|packing|date\s*of\s*manufacture|date\s*of\s*packing|pack\s*date)\s*[:\-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})',
        r'([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4})\s*(?:mfd|mfg|manufactured|packed)',
        r'([0-9]{4}[/-][0-9]{1,2}[/-][0-9]{1,2})',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            extracted['mfg_date'] = match.group(1)
            break

    use_by_match = re.search(r'(?:use\s*by|best\s*before|expiry|exp\.|expir(y|ation))\s*[:\-]?\s*([0-9]{1,2}[/-][0-9]{1,2}[/-][0-9]{2,4}|[0-9]{4}[/-][0-9]{1,2}[/-][0-9]{1,2})', text, flags=re.IGNORECASE)
    if use_by_match:
        extracted['use_by_date'] = use_by_match.group(1)

    batch_match = re.search(r'(?:batch|lot)\s*(?:no|number|#)?\s*[:\-]?\s*([A-Za-z0-9/-]+)', text, flags=re.IGNORECASE)
    if batch_match:
        extracted['batch_lot'] = batch_match.group(1)

    care_match = re.search(r'(?:consumer\s*care|customer\s*care|toll\s*free|helpline|tel\.|phone|email)\s*[:\-]?\s*([A-Za-z0-9,./()\-+\s]+)', text, flags=re.IGNORECASE)
    if care_match:
        extracted['care_instructions'] = re.sub(r'\s+', ' ', care_match.group(1)).strip(' ,;:-')

    origin_match = re.search(r'(?:country\s*of\s*origin|made\s*in|origin)\s*[:\-]?\s*([A-Za-z0-9,./() -]+)', text, flags=re.IGNORECASE)
    if origin_match:
        extracted['origin'] = re.sub(r'\s+', ' ', origin_match.group(1)).strip(' ,;:-')

    return extracted


def generate_compliance_analysis(image_type, ocr_text='', extracted_data=None, ocr_debug=None):
    extracted = extracted_data or {}
    text = _safe_ocr_text(ocr_text or '')
    confidence = float((ocr_debug or {}).get('confidence', 0.0) or 0.0)
    required_fields = {
        'product_name': 'Product Name',
        'manufacturer': 'Manufacturer',
        'quantity': 'Net Quantity',
        'mrp': 'MRP',
        'mfg_date': 'Manufacturing Date',
        'care_instructions': 'Consumer Care',
        'origin': 'Country of Origin',
    }

    if not text or 'Text could not be clearly detected' in text or confidence < 35:
        rule_results = []
        for key, label in required_fields.items():
            value = extracted.get(key)
            rule_results.append({
                'field': key,
                'label': label,
                'detected_value': value or 'Not detected',
                'status': 'REVIEW REQUIRED',
                'confidence': round(confidence, 2),
                'explanation': 'OCR quality was insufficient to make a reliable decision.'
            })
        return {
            'score': 60,
            'status': 'REVIEW REQUIRED',
            'findings': ['OCR quality was insufficient to make a reliable decision.'],
            'summary': 'OCR confidence was too low for a reliable compliance decision. Manual verification is required.',
            'rule_results': rule_results,
            'field_results': rule_results,
            'overall_reason': 'Low OCR confidence prevented a reliable compliance determination.'
        }

    rule_results = []
    for key, label in required_fields.items():
        value = extracted.get(key)
        if value:
            status = 'PASS'
            explanation = f'{label} was clearly detected in the label text.'
        elif key in {'manufacturer', 'quantity', 'mrp', 'mfg_date', 'care_instructions'}:
            status = 'FAIL' if confidence >= 60 else 'REVIEW REQUIRED'
            explanation = f'{label} appears to be missing from the label.' if status == 'FAIL' else f'{label} was not confidently detected; manual verification recommended.'
        else:
            status = 'REVIEW REQUIRED'
            explanation = f'{label} was not confidently detected; manual verification recommended.'
        rule_results.append({
            'field': key,
            'label': label,
            'detected_value': value or 'Not detected',
            'status': status,
            'confidence': round(confidence, 2),
            'explanation': explanation,
        })

    if any(rule['status'] == 'FAIL' for rule in rule_results):
        final_status = 'POTENTIAL VIOLATION'
        summary = 'One or more mandatory declarations appear missing or invalid. Manual verification is still required.'
    elif all(rule['status'] == 'PASS' for rule in rule_results):
        final_status = 'COMPLIANT'
        summary = 'Mandatory declarations were detected and the label appears compliant based on available OCR evidence.'
    else:
        final_status = 'REVIEW REQUIRED'
        summary = 'Some fields were not clearly readable; manual verification is required.'

    return {
        'score': 90 if final_status == 'COMPLIANT' else 72 if final_status == 'REVIEW REQUIRED' else 45,
        'status': final_status,
        'findings': [rule['explanation'] for rule in rule_results],
        'summary': summary,
        'rule_results': rule_results,
        'field_results': rule_results,
        'overall_reason': summary
    }


def generate_inspection_id():
    today = date.today().strftime('%Y%m%d')
    conn = get_db_connection()
    row = conn.execute(
        "SELECT COUNT(*) FROM inspections WHERE inspection_id LIKE ?",
        (f'SMQ-{today}-%',),
    ).fetchone()
    conn.close()
    count = int(row[0]) + 1 if row else 1
    return f'SMQ-{today}-{count:04d}'


def append_audit_event(inspection_id, user_id, event_type, description):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO audit_events (inspection_id, user_id, event_type, description, timestamp) VALUES (?, ?, ?, ?, ?)",
        (inspection_id, user_id, event_type, description, datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
    )
    conn.commit()
    conn.close()


def save_inspection_to_db(record):
    conn = get_db_connection()
    conn.execute(
        """
        INSERT INTO inspections (
            inspection_id, user_id, product_name, product_type, image_path, language, language_code,
            ocr_text, extracted_data, compliance_status, violation_details, officer_notes,
            evidence_hash, created_at, updated_at, result_summary, score, findings, source_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            record.get('inspection_id') or record.get('id'),
            record.get('inspector') or 'System',
            record.get('product'),
            record.get('image_type'),
            record.get('image_path'),
            record.get('language'),
            record.get('language_code'),
            record.get('ocr_text'),
            json.dumps(record.get('extracted_data', {}), ensure_ascii=False),
            record.get('status'),
            json.dumps(record.get('violation_details', []), ensure_ascii=False),
            record.get('officer_notes', ''),
            record.get('evidence_hash'),
            record.get('created_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            record.get('updated_at') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            record.get('result'),
            record.get('score', 0),
            json.dumps(record.get('findings', []), ensure_ascii=False),
            record.get('source_type') or 'PHYSICAL_PRODUCT',
        ),
    )
    conn.commit()
    for event in record.get('audit_events', []):
        conn.execute(
            "INSERT INTO audit_events (inspection_id, user_id, event_type, description, timestamp) VALUES (?, ?, ?, ?, ?)",
            (
                record.get('inspection_id') or record.get('id'),
                record.get('inspector') or 'System',
                event.get('event_type'),
                event.get('description'),
                event.get('timestamp') or datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            ),
        )
    conn.commit()
    conn.close()


def get_inspection_records():
    conn = get_db_connection()
    rows = conn.execute(
        "SELECT * FROM inspections ORDER BY created_at DESC"
    ).fetchall()
    conn.close()

    inspections = []
    for row in rows:
        inspection = {
            'id': row['inspection_id'],
            'inspection_id': row['inspection_id'],
            'date': row['created_at'][:10] if row['created_at'] else date.today().isoformat(),
            'time': (row['created_at'][11:16] if len(row['created_at']) > 11 else ''),
            'product': normalize_product_name(row['product_name'] or 'Unknown Product', row['product_type'] or 'front'),
            'status': row['compliance_status'] or 'REVIEW REQUIRED',
            'inspector': row['user_id'] or 'System',
            'result': row['result_summary'] or 'Automated preliminary compliance screening. Final determination requires verification by an authorized officer.',
            'image_type': row['product_type'] or 'front',
            'filename': os.path.basename(row['image_path']) if row['image_path'] else '',
            'image_path': row['image_path'],
            'language': row['language'] or 'English',
            'language_code': row['language_code'] or 'eng',
            'ocr_text': row['ocr_text'] or 'Text could not be clearly detected. Manual verification required.',
            'extracted_data': json.loads(row['extracted_data']) if row['extracted_data'] else {},
            'score': row['score'] or 0,
            'findings': json.loads(row['findings']) if row['findings'] else [],
            'violation_details': json.loads(row['violation_details']) if row['violation_details'] else [],
            'evidence_hash': row['evidence_hash'],
            'audit_events': [],
            'action': 'View',
            'officer_notes': row['officer_notes'] or '',
            'source_type': row['source_type'] if 'source_type' in row.keys() else 'PHYSICAL_PRODUCT',
        }
        conn2 = get_db_connection()
        events = conn2.execute(
            "SELECT event_type, description, timestamp FROM audit_events WHERE inspection_id = ? ORDER BY id ASC",
            (inspection['inspection_id'],),
        ).fetchall()
        conn2.close()
        inspection['audit_events'] = [
            {
                'event_type': event['event_type'],
                'description': event['description'],
                'timestamp': event['timestamp'],
            }
            for event in events
        ]
        inspections.append(inspection)
    return inspections


def get_demo_inspection_catalog():
    return [
        {
            'id': 'SMQ-1001',
            'inspection_id': 'SMQ-1001',
            'date': '2026-09-12',
            'time': '14:10',
            'product': 'Rice Pack 5kg',
            'status': 'COMPLIANT',
            'inspector': 'A. Sharma',
            'result': 'All mandatory declarations present.',
            'language': 'English',
            'language_label': 'English',
            'violation_details': ['Missing Information'],
            'findings': ['Mandatory declarations present'],
            'extracted_data': {'product_name': 'Rice Pack 5kg', 'mrp': '₹ 100.00', 'quantity': '5kg', 'mfg_date': '2026-08-01', 'origin': 'India'},
            'image_path': '',
            'filename': '',
            'ocr_text': 'Rice Pack 5kg\nMRP: Rs. 100.00\nNet Qty: 5kg\nMfg. Date: 01/08/2026\nCountry of Origin: India',
            'evidence_hash': 'demo-sha256-1001',
            'audit_events': [
                {'event_type': 'Inspection Created', 'description': 'Inspection created for demo record', 'timestamp': '2026-09-12 14:10:00'},
                {'event_type': 'OCR Completed', 'description': 'OCR completed for English', 'timestamp': '2026-09-12 14:10:05'},
                {'event_type': 'Rules Evaluated', 'description': 'Compliance rules evaluated', 'timestamp': '2026-09-12 14:10:10'}
            ],
            'score': 92,
        },
        {
            'id': 'SMQ-1002',
            'inspection_id': 'SMQ-1002',
            'date': '2026-09-12',
            'time': '15:40',
            'product': 'Tea Masala 250g',
            'status': 'REVIEW REQUIRED',
            'inspector': 'N. Patel',
            'result': 'MRP and net quantity need verification.',
            'language': 'English + Hindi',
            'language_label': 'English + Hindi',
            'violation_details': ['MRP Problem'],
            'findings': ['MRP could not be clearly detected'],
            'extracted_data': {'product_name': 'Tea Masala 250g', 'quantity': '250g'},
            'image_path': '',
            'filename': '',
            'ocr_text': 'Tea Masala 250g\nRate: unclear\nNet Qty: 250g\nMfg: 01/09/2026',
            'evidence_hash': 'demo-sha256-1002',
            'audit_events': [
                {'event_type': 'Inspection Created', 'description': 'Inspection created for demo record', 'timestamp': '2026-09-12 15:40:00'},
                {'event_type': 'OCR Completed', 'description': 'OCR completed for English + Hindi', 'timestamp': '2026-09-12 15:40:05'}
            ],
            'score': 74,
        },
        {
            'id': 'SMQ-1003',
            'inspection_id': 'SMQ-1003',
            'date': '2026-09-11',
            'time': '11:20',
            'product': 'Soap Bar 100g',
            'status': 'POTENTIAL VIOLATION',
            'inspector': 'K. Rao',
            'result': 'Care info and date of manufacture flagged.',
            'language': 'Kannada',
            'language_label': 'Kannada',
            'violation_details': ['Date Problem'],
            'findings': ['Date marking requires verification'],
            'extracted_data': {'product_name': 'Soap Bar 100g'},
            'image_path': '',
            'filename': '',
            'ocr_text': 'Soap Bar 100g\nConsumer care unclear\nMfg. date not clearly visible',
            'evidence_hash': 'demo-sha256-1003',
            'audit_events': [
                {'event_type': 'Inspection Created', 'description': 'Inspection created for demo record', 'timestamp': '2026-09-11 11:20:00'},
                {'event_type': 'OCR Completed', 'description': 'OCR completed for Kannada', 'timestamp': '2026-09-11 11:20:05'}
            ],
            'score': 68,
        },
    ]


def find_inspection_record(inspection_id):
    session_inspections = session.get('inspections', [])
    for item in session_inspections:
        if str(item.get('id')) == str(inspection_id) or str(item.get('inspection_id')) == str(inspection_id):
            return item

    for item in get_inspection_records():
        if str(item.get('id')) == str(inspection_id) or str(item.get('inspection_id')) == str(inspection_id):
            return item

    for item in get_demo_inspection_catalog():
        if str(item.get('id')) == str(inspection_id) or str(item.get('inspection_id')) == str(inspection_id):
            return item
    return None


def merge_inspection_lists(*lists):
    merged = []
    seen = set()
    for group in lists:
        for item in group:
            key = str(item.get('inspection_id') or item.get('id') or '')
            if not key or key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def build_result_summary(inspection):
    inspection = dict(inspection or {})
    extracted = inspection.get('extracted_data') or {}
    problems = inspection.get('violation_display') or build_violation_display_list(inspection.get('violation_details') or inspection.get('findings') or [])

    default_status = str(inspection.get('status', 'REVIEW REQUIRED')).upper()
    overall = 'PASS' if default_status == 'COMPLIANT' else 'REVIEW REQUIRED' if default_status == 'REVIEW REQUIRED' else 'POTENTIAL VIOLATION'

    rules = [
        {
            'category': 'Manufacturer Details',
            'detected_value': extracted.get('manufacturer') or extracted.get('manufacturer_details') or 'Not detected',
            'status': 'PASS' if extracted.get('manufacturer') or extracted.get('manufacturer_details') else 'REVIEW REQUIRED',
            'explanation': 'Manufacturer or packer details were checked for completeness.'
        },
        {
            'category': 'Quantity Problem',
            'detected_value': extracted.get('quantity') or 'Not detected',
            'status': 'PASS' if extracted.get('quantity') else 'REVIEW REQUIRED',
            'explanation': 'Net quantity was checked for missing or unclear information.'
        },
        {
            'category': 'MRP Problem',
            'detected_value': extracted.get('mrp') or 'Not detected',
            'status': 'PASS' if extracted.get('mrp') else 'REVIEW REQUIRED',
            'explanation': 'MRP was checked for clarity and completeness.'
        },
        {
            'category': 'Date Problem',
            'detected_value': extracted.get('mfg_date') or 'Not detected',
            'status': 'PASS' if extracted.get('mfg_date') else 'REVIEW REQUIRED',
            'explanation': 'Manufacturing or packing date information was checked.'
        },
        {
            'category': 'Consumer Care Problem',
            'detected_value': extracted.get('care_instructions') or 'Not detected',
            'status': 'PASS' if extracted.get('care_instructions') else 'REVIEW REQUIRED',
            'explanation': 'Consumer care contact details were checked for availability and clarity.'
        },
        {
            'category': 'Country of Origin',
            'detected_value': extracted.get('origin') or 'Not detected',
            'status': 'PASS' if extracted.get('origin') else 'REVIEW REQUIRED',
            'explanation': 'Country of origin was checked where applicable.'
        }
    ]

    for item in problems:
        category = item.get('category') if isinstance(item, dict) else str(item)
        if category == 'MRP Problem':
            rules[2]['status'] = 'POTENTIAL VIOLATION'
        elif category == 'Quantity Problem':
            rules[1]['status'] = 'POTENTIAL VIOLATION'
        elif category == 'Date Problem':
            rules[3]['status'] = 'POTENTIAL VIOLATION'
        elif category == 'Consumer Care Problem':
            rules[4]['status'] = 'POTENTIAL VIOLATION'
        elif category == 'Manufacturer Details':
            rules[0]['status'] = 'POTENTIAL VIOLATION'
        elif category == 'Country of Origin':
            rules[5]['status'] = 'POTENTIAL VIOLATION'

    if default_status == 'POTENTIAL VIOLATION':
        overall = 'POTENTIAL VIOLATION'
    elif default_status == 'COMPLIANT':
        overall = 'PASS'
    else:
        overall = 'REVIEW REQUIRED'

    inspection['overall_status'] = overall
    inspection['rule_checks'] = rules
    inspection['problems_found'] = problems
    inspection['result_message'] = 'Automated preliminary compliance screening. Final determination requires verification by an authorized officer.'
    inspection['status_label'] = '🟢 PASS' if overall == 'PASS' else '🟡 REVIEW REQUIRED' if overall == 'REVIEW REQUIRED' else '🔴 POTENTIAL VIOLATION'
    return inspection


def generate_pdf_report(inspection):
    if canvas is None:
        raise RuntimeError('reportlab is not installed.')

    inspection = build_result_summary(inspection)
    output_path = os.path.join(UPLOAD_FOLDER, f"{inspection.get('inspection_id', 'report')}.pdf")
    pdf = canvas.Canvas(output_path)
    pdf.setTitle(f"Inspection Report {inspection.get('inspection_id', 'Unknown')}")
    pdf.setFont('Helvetica-Bold', 18)
    pdf.drawString(40, 780, f"INSPECTION: {inspection.get('inspection_id', 'Unknown')}")

    if inspection.get('image_path'):
        try:
            image_file = os.path.join(app.root_path, inspection['image_path'].lstrip('/'))
            if os.path.exists(image_file):
                img = Image.open(image_file)
                img = img.convert('RGB')
                img_width, img_height = img.size
                ratio = min(180 / img_width, 120 / img_height)
                width = max(1, int(img_width * ratio))
                height = max(1, int(img_height * ratio))
                pdf.drawInlineImage(img, 380, 690, width=width, height=height)
        except Exception:
            pass

    pdf.setFont('Helvetica', 12)
    y = 680
    violation_text = ' ; '.join(f"{item['category']} - {item['detail']}" for item in inspection.get('problems_found', [])) if inspection.get('problems_found') else 'No issue recorded.'
    summary_lines = [
        f"Product: {inspection.get('product', 'N/A')}",
        f"Language: {inspection.get('language', 'English')}",
        f"Officer: {inspection.get('inspector', 'System')}",
        f"Date & Time: {inspection.get('date', date.today().isoformat())} {inspection.get('time', '')}".strip(),
        f"Compliance: {inspection.get('overall_status', inspection.get('status', 'REVIEW REQUIRED'))}",
        f"SHA-256: {inspection.get('evidence_hash', 'N/A')}",
        '',
        'Automated preliminary compliance screening. Final determination requires verification by an authorized officer.',
        '',
        f"OCR Text: {inspection.get('ocr_text', 'Text could not be clearly detected. Manual verification required.')}",
        '',
        f"Extracted Information: {json.dumps(inspection.get('extracted_data', {}), ensure_ascii=False)}",
        '',
        f"Common Problems: {violation_text}",
        '',
        f"Audit Trail: {json.dumps(inspection.get('audit_events', []), ensure_ascii=False)}",
    ]
    for line in summary_lines:
        if y < 80:
            pdf.showPage()
            y = 760
        pdf.drawString(40, y, line[:120])
        y -= 18

    pdf.save()
    return output_path


def get_active_mode():
    mode = session.get('mode')
    if mode in {'consumer', 'officer'}:
        return mode
    if session.get('user_role') == 'officer':
        return 'officer'
    if session.get('user_role') == 'consumer':
        return 'consumer'
    return 'consumer'


def get_rule_catalog():
    return LEGAL_RULES


@app.route('/switch-mode/<mode>')
def switch_mode(mode):
    if mode not in {'consumer', 'officer'}:
        mode = 'consumer'
    session['mode'] = mode
    if mode == 'officer' and session.get('user_role') == 'officer':
        return redirect(url_for('dashboard'))
    if mode == 'consumer':
        return redirect(url_for('consumer_dashboard'))
    return redirect(url_for('dashboard'))


@app.route('/know-rules')
def know_rules():
    return render_template('know_rules.html', rules=get_rule_catalog())


@app.route('/report-problem')
def report_problem_redirect():
    return redirect(url_for('consumer_complaint_new'))


@app.route('/my-complaints')
def my_complaints_redirect():
    return redirect(url_for('consumer_dashboard'))


@app.route('/check-online-product')
@app.route('/ecommerce-checker')
def ecommerce_checker_page():
    return render_template('ecommerce_checker.html', ai_status=get_ai_model_status(), mode=get_active_mode())


@app.route('/ecommerce-checker', methods=['POST'])
def ecommerce_checker_submit():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    language = request.form.get('language', 'eng')
    listing_text = (request.form.get('listing_text') or '').strip()
    listing_url = (request.form.get('listing_url') or '').strip()
    uploaded_file = request.files.get('listing_image')

    if uploaded_file and uploaded_file.filename:
        complaint_folder = os.path.join(UPLOAD_FOLDER, 'ecommerce')
        os.makedirs(complaint_folder, exist_ok=True)
        saved_name = save_uploaded_file(uploaded_file, complaint_folder)
        image_path = os.path.join(complaint_folder, saved_name)
        with open(image_path, 'rb') as fh:
            evidence_hash = hashlib.sha256(fh.read()).hexdigest()
        ocr_result = perform_multilingual_ocr(image_path, language)
        text_source = ocr_result.get('text') or listing_text
        extracted = extract_product_metadata(text_source, 'front')
    elif listing_text:
        text_source = listing_text
        extracted = extract_product_metadata(listing_text, 'front')
        evidence_hash = hashlib.sha256(text_source.encode('utf-8')).hexdigest()
        image_path = ''
    else:
        return render_template('ecommerce_checker.html', error='Please upload a screenshot or paste the listing text before continuing.', ai_status=get_ai_model_status(), mode=get_active_mode()), 400

    analysis = generate_compliance_analysis('front', text_source, extracted, {'confidence': 70.0})
    source_type = 'E_COMMERCE_LISTING'
    inspection_id = generate_inspection_id()
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    record = {
        'id': inspection_id,
        'inspection_id': inspection_id,
        'product': normalize_product_name(extracted.get('product_name') or 'Online Listing', 'front'),
        'inspector': session.get('username', 'system'),
        'status': analysis['status'],
        'result': analysis['summary'],
        'image_type': 'front',
        'filename': os.path.basename(image_path) if image_path else 'listing-text',
        'image_path': os.path.join('uploads', 'ecommerce', os.path.basename(image_path)) if image_path else '',
        'language': language,
        'language_code': get_tesseract_language_code(language),
        'ocr_text': text_source,
        'extracted_data': extracted,
        'violation_details': analysis['findings'],
        'findings': analysis['findings'],
        'score': analysis['score'],
        'evidence_hash': evidence_hash,
        'audit_events': [
            {'event_type': 'E-commerce screenshot uploaded', 'description': 'Listing source captured for review', 'timestamp': timestamp},
            {'event_type': 'OCR completed', 'description': 'Text extracted from listing content', 'timestamp': timestamp},
            {'event_type': 'Information extracted', 'description': 'Product information extracted from listing text', 'timestamp': timestamp},
            {'event_type': 'Rules evaluated', 'description': 'Legal Metrology screening applied', 'timestamp': timestamp},
            {'event_type': 'Result generated', 'description': 'Preliminary compliance result generated', 'timestamp': timestamp},
            {'event_type': 'Inspection submitted', 'description': 'E-commerce inspection saved for follow-up review', 'timestamp': timestamp},
        ],
        'created_at': timestamp,
        'updated_at': timestamp,
        'source_type': source_type,
        'result_summary': analysis['summary'],
        'officer_notes': '',
    }
    save_inspection_to_db(record)
    session.setdefault('inspections', []).append(record)
    return redirect(url_for('inspection_detail', inspection_id=inspection_id))


@app.route('/')
def home():
    return render_template('index.html', mode=get_active_mode())


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if username == 'admin' and password == 'admin123':
            session['logged_in'] = True
            session['username'] = username
            session['user_role'] = 'officer'
            session['mode'] = 'officer'
            session['complaints'] = get_complaint_records(username)
            return redirect(url_for('dashboard'))

        if username == 'consumer' and password == 'consumer123':
            session['logged_in'] = True
            session['username'] = username
            session['user_role'] = 'consumer'
            session['mode'] = 'consumer'
            session['complaints'] = get_complaint_records(username)
            return redirect(url_for('consumer_dashboard'))

        error = 'Invalid credentials. Use demo username: admin/admin123 or consumer/consumer123.'

    return render_template('login.html', error=error)


@app.route('/consumer')
@app.route('/consumer/dashboard')
def consumer_dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('user_role') == 'officer':
        return redirect(url_for('dashboard'))

    consumer_name = session.get('username', 'consumer')
    complaints = get_complaint_records(consumer_name)
    if not complaints:
        complaints = seed_demo_complaints()
    session['complaints'] = complaints
    session['mode'] = 'consumer'
    return render_template('consumer_dashboard.html', complaints=complaints, mode='consumer')


@app.route('/consumer/complaint/new', methods=['GET', 'POST'])
def consumer_complaint_new():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    if request.method == 'POST':
        complaint_id = generate_complaint_id()
        description = (request.form.get('complaint_description') or '').strip()
        product_name = (request.form.get('product_name') or '').strip()
        language = request.form.get('language', 'eng')
        uploaded_file = request.files.get('image')

        if not description:
            return render_template('consumer_complaint.html', error='Please describe the complaint before submitting.'), 400

        image_path = ''
        evidence_hash = ''
        ocr_text = ''
        extracted_data = {}
        compliance_result = {'status': 'SUBMITTED', 'summary': 'Complaint submitted and awaiting review.', 'score': 0}

        if uploaded_file and uploaded_file.filename:
            complaint_folder = os.path.join(UPLOAD_FOLDER, 'complaints')
            os.makedirs(complaint_folder, exist_ok=True)
            saved_name = save_uploaded_file(uploaded_file, complaint_folder)
            image_path = os.path.join('uploads', 'complaints', saved_name)
            with open(os.path.join(complaint_folder, saved_name), 'rb') as fh:
                evidence_hash = hashlib.sha256(fh.read()).hexdigest()
            ocr_result = perform_multilingual_ocr(os.path.join(complaint_folder, saved_name), language)
            ocr_text = ocr_result.get('text', '')
            extracted_data = extract_product_metadata(ocr_text, 'front')
            compliance_result = generate_compliance_analysis('front', ocr_text, extracted_data, ocr_result.get('debug') or {'confidence': ocr_result.get('confidence', 0.0)})
            product_name = product_name or extracted_data.get('product_name') or 'Unknown Product'

        complaint_record = {
            'complaint_id': complaint_id,
            'consumer': session.get('username', 'consumer'),
            'product_name': product_name or 'Unknown Product',
            'complaint_description': description,
            'image_path': image_path,
            'image_filename': os.path.basename(image_path) if image_path else '',
            'ocr_result': ocr_text,
            'extracted_data': extracted_data,
            'compliance_result': compliance_result,
            'status': compliance_result.get('status', 'SUBMITTED') or 'SUBMITTED',
            'evidence_hash': evidence_hash,
            'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'metadata': {
                'language': language,
                'source': 'consumer_submission',
            },
        }
        save_complaint_record(complaint_record)
        session.setdefault('complaints', [])
        complaint_list = get_complaint_records(session.get('username', 'consumer'))
        session['complaints'] = complaint_list
        return redirect(url_for('complaint_detail', complaint_id=complaint_id))

    return render_template('consumer_complaint.html', error=None)


@app.route('/consumer/complaint/<complaint_id>')
def complaint_detail(complaint_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    complaint = get_complaint_by_id(complaint_id)
    if complaint is None:
        return redirect(url_for('consumer_dashboard'))

    if complaint.get('consumer') != session.get('username') and session.get('user_role') != 'officer':
        return redirect(url_for('consumer_dashboard'))

    return render_template('complaint_detail.html', complaint=complaint)


@app.route('/consumer/complaints')
def consumer_complaints():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    complaints = get_complaint_records(session.get('username', 'consumer'))
    session['complaints'] = complaints
    return render_template('consumer_dashboard.html', complaints=complaints)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/officer/complaints')
def officer_complaints():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('user_role') != 'officer':
        return redirect(url_for('consumer_dashboard'))
    complaints = get_complaint_records()
    return render_template('officer_complaints.html', complaints=complaints, mode='officer')


@app.route('/complaints/<complaint_id>/status', methods=['POST'])
def update_complaint_status(complaint_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('user_role') != 'officer':
        return redirect(url_for('consumer_dashboard'))

    new_status = request.form.get('status', 'SUBMITTED').strip().upper()
    allowed = {'SUBMITTED', 'UNDER REVIEW', 'VERIFIED', 'RESOLVED'}
    if new_status not in allowed:
        new_status = 'SUBMITTED'

    conn = get_db_connection()
    conn.execute(
        "UPDATE complaints SET status = ?, updated_at = ? WHERE complaint_id = ?",
        (new_status, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), complaint_id),
    )
    conn.commit()
    conn.close()
    return redirect(url_for('officer_complaints'))


@app.route('/audit-trail')
def audit_trail():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('user_role') != 'officer':
        return redirect(url_for('consumer_dashboard'))
    return render_template('audit_trail.html', recent_inspections=get_inspection_records(), mode='officer')


@app.route('/potential-issues')
def potential_issues():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('user_role') != 'officer':
        return redirect(url_for('consumer_dashboard'))
    items = [item for item in get_inspection_records() if str(item.get('status', 'REVIEW REQUIRED')).upper() != 'COMPLIANT']
    return render_template('potential_issues.html', inspections=items, mode='officer')


@app.route('/reports')
def reports_page():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('user_role') != 'officer':
        return redirect(url_for('consumer_dashboard'))
    return render_template('reports.html', inspections=get_inspection_records(), mode='officer')


@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    if session.get('user_role') != 'officer':
        return redirect(url_for('consumer_dashboard'))

    session_inspections = session.get('inspections', [])
    static_inspections = get_demo_inspection_catalog()
    recent_inspections = list(session_inspections) if session_inspections else static_inspections
    recent_inspections.extend([item for item in get_inspection_records() if item not in recent_inspections])

    for item in recent_inspections:
        item.setdefault('action', 'View Analysis')
        item['status'] = str(item.get('status', 'REVIEW REQUIRED')).upper()
        item.setdefault('date', date.today().isoformat())
        item.setdefault('time', datetime.now().strftime('%H:%M'))
        item.setdefault('language', 'English')
        item.setdefault('language_label', get_language_label(item.get('language', 'eng')))
        item['product'] = normalize_product_name(item.get('product') or item.get('product_name') or 'Unknown Product', item.get('image_type') or 'front')
        item['source_type'] = str(item.get('source_type') or 'PHYSICAL_PRODUCT').upper()
        issue_display = build_violation_display_list(item.get('violation_details') or item.get('findings') or ['Other Issue'])
        item['issue_category'] = issue_display[0]['category'] if issue_display else 'Other Issue'

    total = len(recent_inspections)
    compliant = sum(1 for item in recent_inspections if item.get('status') == 'COMPLIANT')
    review = sum(1 for item in recent_inspections if item.get('status') == 'REVIEW REQUIRED')
    violations = sum(1 for item in recent_inspections if item.get('status') == 'POTENTIAL VIOLATION')
    physical = sum(1 for item in recent_inspections if str(item.get('source_type') or 'PHYSICAL_PRODUCT').upper() == 'PHYSICAL_PRODUCT')
    ecommerce = sum(1 for item in recent_inspections if str(item.get('source_type') or 'PHYSICAL_PRODUCT').upper() == 'E_COMMERCE_LISTING')
    complaint_count = len(get_complaint_records())

    languages_seen = sorted({str(item.get('language_label', item.get('language', 'English'))).strip() for item in recent_inspections if item.get('language') or item.get('language_label')})
    stats = {
        'total': total,
        'compliant': compliant,
        'review': review,
        'violations': violations,
        'physical': physical,
        'ecommerce': ecommerce,
        'complaints': complaint_count,
        'languages': languages_seen,
    }

    chart_data = [
        max(2, review + violations),
        max(1, review),
        max(1, violations),
        max(2, review + 1),
        max(1, violations + 1),
    ]
    ai_status = get_ai_model_status()

    session['mode'] = 'officer'
    return render_template('dashboard.html', stats=stats, recent_inspections=recent_inspections, chart_data=chart_data, ai_status=ai_status, mode='officer')


@app.route('/history')
def history():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    session_inspections = session.get('inspections', [])
    static_history = [
        {'id': 'SMQ-1001', 'date': '2026-09-12', 'product': 'Rice Pack 5kg', 'status': 'COMPLIANT', 'inspector': 'A. Sharma', 'result': 'All mandatory declarations present.', 'language': 'English', 'violation_details': ['Missing Information']},
        {'id': 'SMQ-1002', 'date': '2026-09-12', 'product': 'Tea Masala 250g', 'status': 'REVIEW REQUIRED', 'inspector': 'N. Patel', 'result': 'MRP and net quantity need verification.', 'language': 'English + Hindi', 'violation_details': ['MRP Problem']},
        {'id': 'SMQ-1003', 'date': '2026-09-11', 'product': 'Soap Bar 100g', 'status': 'POTENTIAL VIOLATION', 'inspector': 'K. Rao', 'result': 'Care info and date of manufacture flagged.', 'language': 'Kannada', 'violation_details': ['Date Problem']},
        {'id': 'SMQ-1004', 'date': '2026-09-10', 'product': 'Mustard Oil 1L', 'status': 'COMPLIANT', 'inspector': 'J. Verma', 'result': 'Label meets statutory requirements.', 'language': 'English', 'violation_details': ['Missing Information']},
        {'id': 'SMQ-1005', 'date': '2026-09-08', 'product': 'Wheat Flour 5kg', 'status': 'REVIEW REQUIRED', 'inspector': 'P. Singh', 'result': 'Origin declaration requires review.', 'language': 'Hindi', 'violation_details': ['Country of Origin']},
    ]
    history_items = list(session_inspections) if session_inspections else static_history
    for item in history_items:
        item['status'] = str(item.get('status', 'REVIEW REQUIRED')).upper()
        item.setdefault('language', 'English')
        item.setdefault('language_label', get_language_label(item.get('language', 'eng')))
        item.setdefault('inspector', 'System')
        item['product'] = normalize_product_name(item.get('product') or item.get('product_name') or 'Unknown Product', item.get('image_type') or 'front')
        item.setdefault('result', 'Automated preliminary compliance screening. Final determination requires verification by an authorized officer.')
        issue_display = build_violation_display_list(item.get('violation_details') or item.get('findings') or ['Other Issue'])
        item['issue_category'] = issue_display[0]['category'] if issue_display else 'Other Issue'
    return render_template('history.html', history_items=history_items)


@app.route('/result/<inspection_id>')
@app.route('/inspection/<inspection_id>')
def inspection_detail(inspection_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    inspection = find_inspection_record(inspection_id)
    if inspection is None:
        return render_template('inspection_detail.html', inspection=None, inspection_id=inspection_id)

    inspection = build_result_summary(inspection)
    inspection.setdefault('inspection_id', inspection.get('id'))
    inspection['product'] = normalize_product_name(inspection.get('product') or inspection.get('product_name') or 'Unknown Product', inspection.get('image_type') or 'front')
    inspection.setdefault('language', 'eng')
    inspection.setdefault('language_label', get_language_label(inspection.get('language', 'eng')))
    inspection.setdefault('ai_model_status', get_ai_model_status())
    inspection.setdefault('ocr_text', 'Text could not be clearly detected. Manual verification required.')
    inspection.setdefault('extracted_data', {})
    inspection.setdefault('findings', [])
    inspection.setdefault('violation_details', inspection.get('findings'))
    inspection['violation_display'] = build_violation_display_list(inspection.get('violation_details') or inspection.get('findings') or ['Other Issue'])
    inspection.setdefault('evidence_hash', 'Not available')
    inspection.setdefault('audit_events', [])
    inspection.setdefault('image_path', '')
    inspection.setdefault('filename', '')
    inspection.setdefault('officer_notes', 'No officer notes added.')
    inspection.setdefault('date', date.today().isoformat())
    return render_template('inspection_detail.html', inspection=inspection, inspection_id=inspection_id, ai_status=get_ai_model_status())


@app.route('/report/<inspection_id>')
def generate_report(inspection_id):
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    inspection = find_inspection_record(inspection_id)
    if inspection is None:
        return redirect(url_for('history'))

    try:
        report_path = generate_pdf_report(inspection)
    except RuntimeError:
        return 'PDF report generation requires reportlab to be installed. Install the dependency listed in requirements.txt.', 500

    return send_file(report_path, as_attachment=True, download_name=f'{inspection_id}.pdf')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/scanner')
def scanner():
    return render_template('scanner.html', ai_status=get_ai_model_status())


@app.route('/upload', methods=['POST'])
def upload_image():
    try:
        uploaded_file = request.files.get('image')
        image_type = request.form.get('image_type', 'front')
        language = request.form.get('language', 'eng')

        if uploaded_file is None:
            return jsonify({'success': False, 'message': 'No image file was uploaded.'}), 400

        saved_name = save_uploaded_file(uploaded_file)
        image_path = os.path.join(UPLOAD_FOLDER, saved_name)
        with open(image_path, 'rb') as fh:
            evidence_hash = hashlib.sha256(fh.read()).hexdigest()

        ocr_result = perform_multilingual_ocr(image_path, language)
        extracted_data = extract_product_metadata(ocr_result.get('text', ''), image_type)
        analysis = generate_compliance_analysis(image_type, ocr_result.get('text', ''), extracted_data, ocr_result.get('debug') or {'confidence': ocr_result.get('confidence', 0.0)})
        inspection_id = generate_inspection_id()
        officer_name = session.get('username', 'System')
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        ai_status = get_ai_model_status()
        ml_note = 'AI text detection model used' if ai_status.get('available') else 'AI model not trained — using standard OCR'
        audit_events = [
            {'event_type': 'Inspection Created', 'description': 'Inspection created', 'timestamp': timestamp},
            {'event_type': 'Image Uploaded', 'description': 'Original image preserved for evidence', 'timestamp': timestamp},
            {'event_type': 'Image Processed', 'description': 'Original evidence image saved to uploads', 'timestamp': timestamp},
            {'event_type': 'OCR Completed', 'description': f'OCR completed for {ocr_result.get("language", "English")}', 'timestamp': timestamp},
            {'event_type': 'Data Extracted', 'description': 'Extracted product metadata from OCR output', 'timestamp': timestamp},
            {'event_type': 'Rules Evaluated', 'description': 'Compliance rule engine evaluated the label', 'timestamp': timestamp},
            {'event_type': 'Compliance Result Generated', 'description': f'Compliance result: {analysis["status"]}', 'timestamp': timestamp},
            {'event_type': 'AI Processing', 'description': f'{ml_note}; model version: {ai_status.get("model_version", "N/A")}; dataset: {ai_status.get("dataset", "Standard OCR fallback")}', 'timestamp': timestamp},
        ]

        record_product_name = normalize_product_name(extracted_data.get('product_name') or f"{image_type.replace('_', ' ').title()} Product", image_type)
        inspection_record = {
            'id': inspection_id,
            'inspection_id': inspection_id,
            'date': date.today().isoformat(),
            'time': datetime.now().strftime('%H:%M'),
            'product': record_product_name,
            'status': analysis['status'],
            'inspector': officer_name,
            'result': analysis['summary'],
            'image_type': image_type,
            'filename': saved_name,
            'image_path': os.path.join('uploads', saved_name),
            'language': language,
            'language_label': ocr_result.get('language', get_language_label(language)),
            'language_code': ocr_result.get('language_code', get_tesseract_language_code(language)),
            'ocr_text': ocr_result.get('text', 'Text could not be clearly detected. Manual verification required.'),
            'ocr_debug': ocr_result.get('debug', {}),
            'extracted_data': extracted_data,
            'score': analysis['score'],
            'findings': analysis['findings'],
            'violation_details': analysis['findings'],
            'violation_display': build_violation_display_list(analysis['findings']),
            'officer_notes': '',
            'evidence_hash': evidence_hash,
            'audit_events': audit_events,
            'action': 'View',
            'created_at': timestamp,
            'updated_at': timestamp,
            'result_summary': analysis['summary'],
            'compliance_status': analysis['status'],
            'ai_model_status': ai_status,
            'ai_model_available': ai_status.get('available', False),
        }
        session.setdefault('inspections', []).append(inspection_record)
        save_inspection_to_db(inspection_record)

        redirect_url = url_for('inspection_detail', inspection_id=inspection_id)
        return jsonify({
            'success': True,
            'message': 'Image saved successfully.',
            'filename': saved_name,
            'image_type': image_type,
            'upload_path': os.path.join('uploads', saved_name),
            'redirect_url': redirect_url,
            'analysis': {
                'score': analysis['score'],
                'status': analysis['status'],
                'summary': analysis['summary'],
                'findings': analysis['findings'],
            },
            'inspection': {
                'inspection_id': inspection_id,
                'id': inspection_id,
                'product': inspection_record['product'],
                'language': inspection_record['language'],
                'language_label': inspection_record.get('language_label', get_language_label(inspection_record['language'])),
                'status': inspection_record['status'],
                'evidence_hash': evidence_hash,
                'audit_events': audit_events,
                'ocr_text': inspection_record['ocr_text'],
                'extracted_data': extracted_data,
                'score': analysis['score'],
                'findings': analysis['findings'],
            },
        })

    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception as exc:
        return jsonify({'success': False, 'message': f'An unexpected error occurred while saving the image: {exc}'}), 500


if __name__ == '__main__':
    app.run(debug=True, host='127.0.0.1', port=5000)
