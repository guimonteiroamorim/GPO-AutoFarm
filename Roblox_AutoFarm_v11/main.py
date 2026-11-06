"""Controlador das gravações originais TinyTask (.rec). Windows / Python 3.10+."""
import json
import errno
import math
import queue
import re
import sys
import subprocess
import threading
import time
import traceback
import uuid
from collections import Counter
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from PIL import ImageGrab, ImageOps, ImageTk, ImageDraw
import shutil
import os
import pytesseract
from PIL import Image
import ctypes
from ctypes import wintypes
from pynput import keyboard
from recplayer import (read_rec, WindowsInput, is_record_stop_key,
                       WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN)
from gravacao_geometria import (salvar_geometria, carregar_geometria,
                                converter_ponto, caminho_metadados)
from relogio_manual import RelogioManual
from gravador import GravadorRec
from seguranca_candies import avaliar_leituras

BUNDLE_ROOT = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent
FROZEN = getattr(sys, 'frozen', False)
LOCAL_APP_DATA = Path(os.environ.get('LOCALAPPDATA', str(ROOT)))
LEGACY_USER_DATA = LOCAL_APP_DATA / 'RobloxAutoFarm'
USER_DATA = LOCAL_APP_DATA / 'GPO_AutoFarm_v11' if FROZEN else ROOT
CUSTOM_RECORDINGS_DIR = LOCAL_APP_DATA / 'GPO_AutoFarm_v11' / 'gravacoes'
USER_DATA.mkdir(parents=True, exist_ok=True)
CFG = USER_DATA / 'config.json'
LEGACY_CFG = LEGACY_USER_DATA / 'config.json'
# Preserve settings when upgrading from the previous EXE installation.
if FROZEN and not CFG.exists() and LEGACY_CFG.is_file():
    shutil.copy2(LEGACY_CFG, CFG)
DEFAULT = {
    'coleta': 'gravacoes/gravacao_coleta_1.rec',
    'analise': 'gravacoes/gravacao_analise_2.rec',
    'compra': 'gravacoes/gravacao_compra_3.rec',
    'hotkey': 'f12',
    'record_hotkey': 'f8',
    'meta': 250,
    'intervalo_ocr': 0.8,
    'margem_compra_segundos': 35,
    'duracao_compra_max_segundos': 45,
    'duracao_analise_min_segundos': 43,
    'duracao_analise_max_segundos': 120,
    'tesseract': '',
    'candies_roi': [580, 535, 790, 610],
    'clock_roi': [1322, 648, 1365, 661],
    'roi_coordinate_space': 'roblox_client_v2',
    'rare_chests': 0,
    'auto_purchases': True,
    'rare_chest_limit_enabled': True,
    'boss_control_enabled': True,
}
RARE_CHEST_LIMIT = 10
RESOURCE_TOGGLE_KEYS = (
    'auto_purchases',
    'rare_chest_limit_enabled',
    'boss_control_enabled',
)


def validate_rare_chests(value):
    if (not isinstance(value, int) or isinstance(value, bool) or
            not 0 <= value <= RARE_CHEST_LIMIT):
        raise ValueError(f'Rare Chests deve ser um número inteiro entre 0 e {RARE_CHEST_LIMIT}.')
    return value


def rare_chests_display(value):
    value = validate_rare_chests(value)
    if value == RARE_CHEST_LIMIT:
        return (
            f'{value}/{RARE_CHEST_LIMIT} — Limite atingido. Compras suspensas; '
            'coleta e análise continuam.'
        )
    return f'{value}/{RARE_CHEST_LIMIT}'


def normalize_hotkey_name(name):
    if not isinstance(name, str):
        return None
    value = name.strip().lower()
    if re.fullmatch(r'f(?:[1-9]|1[0-9]|2[0-4])', value):
        return value
    if re.fullmatch(r'[a-z0-9]', value):
        return value
    return None


def hotkey_name_from_key(key):
    name = getattr(key, 'name', None)
    if name:
        return normalize_hotkey_name(name)
    char = getattr(key, 'char', None)
    if isinstance(char, str) and char.isascii() and len(char) == 1:
        return normalize_hotkey_name(char)
    return None


def validate_clock_input(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{2}:[0-9]{2}:[0-9]{2}', value):
        raise ValueError('Digite o horário completo no formato HH:MM:SS.')
    hours, minutes, seconds = (int(part) for part in value.split(':'))
    if minutes >= 60 or seconds >= 60:
        raise ValueError('Minutos e segundos devem estar entre 00 e 59.')
    return value


# Coordenadas relativas APENAS à área interna do jogo Roblox, sem bordas do Windows.
# Ajustadas com capturas de 1365x700 e 1366x697 (janela 1366x768).
ROIS = {'candies': (580,535,790,610), 'clock': (1322,648,1365,661)}
DEBUG = USER_DATA / 'diagnostico'
CANDIES_OPERATION_LOCK = threading.RLock()
OCR_EXCEPTION_LOG_LOCK = threading.RLock()
DIAGNOSTIC_MAINTENANCE_LOCK = threading.RLock()
RECORDING_STORAGE_LOCK = threading.RLock()
OCR_EXCEPTION_LOG_MAX_BYTES = 1024 * 1024
OCR_DIAGNOSTIC_FOLDER_LIMIT = 5
OCR_AUDIT_IMAGE_LIMIT = 20
OCR_CLOCK_DIAGNOSTIC_LIMIT = 5
OCR_TIMEOUT_SECONDS = 2.5
OCR_TIMEOUT_RETRIES = 1
OCR_RETRY_DELAY_SECONDS = 0.15

def region_from(cfg, kind):
    result = cfg.get(kind+'_roi', ROIS[kind]) if cfg else ROIS[kind]
    if (not isinstance(result, (list, tuple)) or len(result) != 4 or
            not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in result)):
        raise ValueError(f'Região {kind} inválida: use quatro coordenadas numéricas.')
    x1, y1, x2, y2 = result
    if not (0 <= x1 < x2 <= 1365 and 0 <= y1 < y2 <= 700):
        raise ValueError(f'Região {kind} fora da área cliente: {result}. Recalibre-a visualmente.')
    return result

def load():
    data = DEFAULT.copy()
    if CFG.exists():
        try:
            data.update(json.loads(CFG.read_text(encoding='utf-8')))
        except Exception:
            pass
    data['rare_chests'] = validate_rare_chests(data['rare_chests'])
    for key in RESOURCE_TOGGLE_KEYS:
        if not isinstance(data[key], bool):
            raise ValueError(f'A configuração {key} deve ser booleana.')
    # As ROIs antigas eram relativas à TELA COMPLETA e não à área do jogo.
    # Não reaproveitá-las, pois podem incluir a barra de título/tarefas do Windows.
    if data.get('roi_coordinate_space') != 'roblox_client_v2':
        if data.get('intervalo_ocr') == 1.5:
            data['intervalo_ocr'] = 0.8
        for key in ('candies','clock'):
            data[key + '_roi'] = list(ROIS[key])
        data['roi_coordinate_space'] = 'roblox_client_v2'
    if data.get('candies_roi') == [620, 554, 721, 585]:
        data['candies_roi'] = list(ROIS['candies'])
    # Corrigir a ROI padrão v3 por uma ROI ligeiramente mais alta, sem apagar
    # nenhuma seleção personalizada feita na interface.
    if data.get('clock_roi') == [1322, 649, 1365, 662]:
        data['clock_roi'] = list(ROIS['clock'])
    # Migrar configurações criadas na versão antiga que usava .exe compilados.
    for key in ('coleta','analise','compra'):
        old = str(data.get(key,'')).strip()
        if old.lower().endswith('.exe'):
            rec = Path(old).with_suffix('.rec')
            if rec.is_file() or (ROOT / rec).is_file():
                data[key] = str(rec)
            else:
                data[key] = DEFAULT[key]
    return data

def normalize_resource_settings(data):
    normalized = dict(data)
    if not normalized.get('auto_purchases', True):
        normalized['rare_chest_limit_enabled'] = False
        normalized['boss_control_enabled'] = False
    return normalized

def resolve(path):
    p = Path(path).expanduser()
    if p.is_absolute():
        return p
    normalized = p.as_posix().lower()
    if normalized in {
            Path(DEFAULT[key]).as_posix().lower()
            for key in ('coleta', 'analise', 'compra')}:
        return BUNDLE_ROOT / p
    for base in dict.fromkeys((USER_DATA, ROOT, CUSTOM_RECORDINGS_DIR.parent)):
        candidate = base / p
        if candidate.is_file():
            return candidate
    return BUNDLE_ROOT / p

def macro_recording(path):
    p = resolve(path)
    if p.suffix.lower() != '.rec':
        alternative = p.with_suffix('.rec')
        if alternative.is_file():
            return alternative
        raise ValueError('Selecione a gravação original .rec. Os .exe compilados são bloqueados pelo Windows.')
    return p


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f'.{path.name}.{threading.get_ident()}.{time.time_ns()}.tmp'
    )
    try:
        temporary.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish_custom_recording(stage, staged_path, client_bbox, persist_selection):
    """Validates and atomically publishes one user's recording and metadata."""
    filenames = {
        'coleta': 'coleta_personalizada.rec',
        'analise': 'analise_personalizada.rec',
        'compra': 'compra_personalizada.rec',
    }
    if stage not in filenames:
        raise ValueError(f'Categoria de gravação inválida: {stage}')

    staged_path = Path(staged_path)
    destination = CUSTOM_RECORDINGS_DIR / filenames[stage]
    metadata_stage = caminho_metadados(staged_path)
    metadata_destination = caminho_metadados(destination)
    token = uuid.uuid4().hex
    rec_backup = destination.with_name(f'.{destination.name}.{token}.backup')
    metadata_backup = metadata_destination.with_name(
        f'.{metadata_destination.name}.{token}.backup'
    )
    rec_published = False
    metadata_published = False
    committed = False
    rollback_completed = True
    rec_existed = destination.is_file()
    metadata_existed = metadata_destination.is_file()

    with RECORDING_STORAGE_LOCK:
        try:
            read_rec(staged_path)
            if client_bbox is not None:
                salvar_geometria(staged_path, client_bbox)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if rec_existed:
                shutil.copy2(destination, rec_backup)
            if metadata_existed:
                shutil.copy2(metadata_destination, metadata_backup)

            os.replace(staged_path, destination)
            rec_published = True
            if metadata_stage.is_file():
                os.replace(metadata_stage, metadata_destination)
            else:
                metadata_destination.unlink(missing_ok=True)
            metadata_published = True
            persist_selection(destination)
            committed = True
        except Exception:
            try:
                if metadata_published:
                    if metadata_existed and metadata_backup.is_file():
                        os.replace(metadata_backup, metadata_destination)
                    else:
                        metadata_destination.unlink(missing_ok=True)
                if rec_published:
                    if rec_existed and rec_backup.is_file():
                        os.replace(rec_backup, destination)
                    else:
                        destination.unlink(missing_ok=True)
            except OSError:
                rollback_completed = False
                raise
            raise
        finally:
            staged_path.unlink(missing_ok=True)
            metadata_stage.unlink(missing_ok=True)
            if committed or rollback_completed:
                rec_backup.unlink(missing_ok=True)
                metadata_backup.unlink(missing_ok=True)

    return destination


def discard_staged_recording(path):
    path = Path(path)
    for candidate in (
            path, path.with_suffix('.part'), caminho_metadados(path)):
        candidate.unlink(missing_ok=True)


def roi_box(img, region):
    w, h = img.size
    if w <= 0 or h <= 0:
        raise ValueError('A captura do Roblox está vazia.')
    if (not isinstance(region, (list, tuple)) or len(region) != 4 or
            not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in region)):
        raise ValueError('Região OCR inválida: são necessárias quatro coordenadas numéricas.')
    x1, y1, x2, y2 = region
    if not (0 <= x1 < x2 <= 1365 and 0 <= y1 < y2 <= 700):
        raise ValueError(f'Região OCR fora da área cliente: {region}. Recalibre-a visualmente.')
    box = (round(x1*w/1365), round(y1*h/700), round(x2*w/1365), round(y2*h/700))
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError(f'Região OCR pequena demais para a captura {w}x{h}: {box}.')
    return box


def roi(img, region):
    box = roi_box(img, region)
    return img.crop(box)

def roblox_client_bbox():
    """Localiza a área CLIENT do Roblox no monitor (não inclui título/tarefa).

    GetClientRect/ClientToScreen dão a área do jogo em coordenadas físicas,
    mesmo se a janela tiver sido movida no desktop.
    """
    if sys.platform != 'win32':
        raise RuntimeError('A captura automática do Roblox requer Windows.')
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    results = []
    CALLBACK = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [CALLBACK, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.ClientToScreen.restype = wintypes.BOOL

    def check(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n < 3 or n > 128:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        if buf.value.strip().lower() != 'roblox':
            return True
        rect = wintypes.RECT()
        origin = wintypes.POINT(0, 0)
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return True
        if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            return True
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width > 400 and height > 300:
            results.append((origin.x, origin.y, origin.x + width, origin.y + height))
        return True

    callback = CALLBACK(check)
    if not user32.EnumWindows(callback, 0):
        raise RuntimeError('Não foi possível localizar a janela do Roblox no Windows.')
    if not results:
        raise RuntimeError('Janela Roblox não encontrada ou minimizada. Abra o jogo e deixe-o visível.')
    return results[0]


def activate_roblox_window():
    """Restabelece o foco no Roblox antes de enviar os eventos de teclado/mouse.

    Essa chamada acontece somente após ocultar a interface do AutoFarm.
    Nunca altera o tamanho/posição da janela do jogo.
    """
    if sys.platform != 'win32':
        raise RuntimeError('O foco automático do Roblox exige Windows.')
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL
    hwnd = user32.FindWindowW(None, 'Roblox')
    if not hwnd:
        raise RuntimeError('Roblox não encontrado. Abra o jogo antes de iniciar.')
    if user32.IsIconic(hwnd):
        raise RuntimeError('Roblox está minimizado. Restaure a janela do jogo antes de iniciar.')
    if user32.GetForegroundWindow() != hwnd:
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.2)
    if user32.GetForegroundWindow() != hwnd:
        raise RuntimeError('Não consegui colocar o Roblox em primeiro plano. Clique na janela do jogo, deixe o personagem no spawn e pressione F12 novamente.')
    return hwnd


def roblox_em_primeiro_plano():
    """Não enviar cliques caso outra janela esteja recebendo teclado/mouse."""
    if sys.platform != 'win32':
        return False
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.FindWindowW(None, 'Roblox')
    return bool(hwnd and user32.GetForegroundWindow() == hwnd)


def screenshot():
    """Captura SOMENTE a área útil do jogo, com título/tarefa excluídos."""
    return screenshot_with_bbox()[0]


def screenshot_with_bbox():
    if not roblox_em_primeiro_plano():
        raise RuntimeError('Roblox não está em primeiro plano; captura OCR cancelada.')
    bbox = roblox_client_bbox()
    return ImageGrab.grab(bbox=bbox, all_screens=True), bbox


def prepared_images(pil, kind):
    scale = 4 if kind == 'candies' else 7
    im = pil.convert('RGB').resize((pil.width*scale, pil.height*scale), Image.Resampling.LANCZOS)
    if kind == 'candies':
        # Na imagem enviada, os dígitos laranja contrastam melhor no canal vermelho.
        red = im.getchannel('R')
        return [ImageOps.autocontrast(red), ImageOps.grayscale(im)]
    gray = ImageOps.autocontrast(ImageOps.grayscale(im))
    return [gray, ImageOps.invert(gray)]


@dataclass(frozen=True)
class OCRFailure:
    stage: str
    attempt: int
    exception_type: str
    message: str
    traceback_text: str


@dataclass(frozen=True)
class CandiesOCRResult:
    value: int | None
    candidates: tuple[int, ...]
    raw_texts: tuple[str, ...]
    reason: str
    crop_box: tuple[int, int, int, int] | None
    prepared: Image.Image | None
    error: str | None = None
    counter_box: tuple[int, int, int, int] | None = None
    numerator_box: tuple[int, int, int, int] | None = None
    failures: tuple[OCRFailure, ...] = ()
    rejection_stage: str | None = None
    rejection_detail: str | None = None
    components: tuple[dict, ...] = ()
    ocr_crop_box: tuple[int, int, int, int] | None = None
    fallback_raw_texts: tuple[str, ...] = ()
    locator_trace: dict | None = None
    candidatos_validos: tuple[tuple[str, int], ...] = ()
    leituras_malformadas: tuple[tuple[str, str], ...] = ()
    leituras_inconclusivas: tuple[tuple[str, str], ...] = ()
    contradicoes: tuple[int, ...] = ()
    motivo_decisao: str | None = None


def ocr_failure_from_exception(stage, attempt, exc):
    return OCRFailure(
        stage=stage,
        attempt=attempt,
        exception_type=type(exc).__name__,
        message=str(exc),
        traceback_text=traceback.format_exc(),
    )


def technical_ocr_result(reason, stage, exc, *, shot=None, crop_box=None,
                         prepared=None, counter_box=None, numerator_box=None,
                         candidates=(), raw_texts=(), attempt=1,
                         prior_failures=(), rejection_stage=None,
                         rejection_detail=None, components=(),
                         ocr_crop_box=None, locator_trace=None):
    failure = ocr_failure_from_exception(stage, attempt, exc)
    return CandiesOCRResult(
        None, tuple(candidates), tuple(raw_texts), reason, crop_box, prepared,
        str(exc), counter_box, numerator_box, tuple(prior_failures) + (failure,),
        rejection_stage, rejection_detail, tuple(components), ocr_crop_box,
        (), locator_trace,
    )


def _is_tesseract_timeout(exc):
    return (
        isinstance(exc, subprocess.TimeoutExpired) or
        isinstance(exc, RuntimeError) and
        not isinstance(exc, pytesseract.pytesseract.TesseractError) and
        str(exc) == 'Tesseract process timeout'
    )


def run_tesseract_variants(prepared, config_suffix, stage_prefix, *, crop_box,
                           counter_box, numerator_box, rejection_stage,
                           rejection_detail, components, parse_candidate,
                           locator_trace, fallback_crop_box=None,
                           minimum_digits=1):
    raw_texts = []
    candidates = []
    malformed = []
    inconclusive = []
    failures = []
    for psm in (7, 8):
        for attempt in range(1, OCR_TIMEOUT_RETRIES + 2):
            try:
                raw = pytesseract.image_to_string(
                    prepared,
                    config=f'--psm {psm} -c tessedit_char_whitelist={config_suffix}',
                    timeout=OCR_TIMEOUT_SECONDS,
                )
                break
            except pytesseract.pytesseract.TesseractNotFoundError as exc:
                return (raw_texts, candidates, malformed, inconclusive,
                        failures, technical_ocr_result(
                    'tesseract_unavailable', f'{stage_prefix}_psm_{psm}', exc,
                    crop_box=crop_box, prepared=prepared, counter_box=counter_box,
                    numerator_box=numerator_box, candidates=candidates,
                    raw_texts=raw_texts, attempt=attempt,
                    prior_failures=failures, rejection_stage=rejection_stage,
                    rejection_detail=rejection_detail, components=components,
                    ocr_crop_box=fallback_crop_box or numerator_box,
                    locator_trace=locator_trace,
                ))
            except subprocess.TimeoutExpired as exc:
                failures.append(ocr_failure_from_exception(
                    f'{stage_prefix}_psm_{psm}', attempt, exc
                ))
                if attempt <= OCR_TIMEOUT_RETRIES:
                    time.sleep(OCR_RETRY_DELAY_SECONDS)
                    continue
                result = CandiesOCRResult(
                    None, tuple(candidates), tuple(raw_texts), 'ocr_timeout',
                    crop_box, prepared, str(exc), counter_box, numerator_box,
                    tuple(failures), rejection_stage, rejection_detail,
                    tuple(components), fallback_crop_box or numerator_box,
                    (), locator_trace,
                )
                return raw_texts, candidates, malformed, inconclusive, failures, result
            except pytesseract.pytesseract.TesseractError as exc:
                return (raw_texts, candidates, malformed, inconclusive,
                        failures, technical_ocr_result(
                    'ocr_error', f'{stage_prefix}_psm_{psm}', exc,
                    crop_box=crop_box, prepared=prepared, counter_box=counter_box,
                    numerator_box=numerator_box, candidates=candidates,
                    raw_texts=raw_texts, attempt=attempt,
                    prior_failures=failures, rejection_stage=rejection_stage,
                    rejection_detail=rejection_detail, components=components,
                    ocr_crop_box=fallback_crop_box or numerator_box,
                    locator_trace=locator_trace,
                ))
            except RuntimeError as exc:
                if _is_tesseract_timeout(exc):
                    failures.append(ocr_failure_from_exception(
                        f'{stage_prefix}_psm_{psm}', attempt, exc
                    ))
                    if attempt <= OCR_TIMEOUT_RETRIES:
                        time.sleep(OCR_RETRY_DELAY_SECONDS)
                        continue
                    result = CandiesOCRResult(
                        None, tuple(candidates), tuple(raw_texts), 'ocr_timeout',
                        crop_box, prepared, str(exc), counter_box, numerator_box,
                        tuple(failures), rejection_stage, rejection_detail,
                        tuple(components), fallback_crop_box or numerator_box,
                        (), locator_trace,
                    )
                    return raw_texts, candidates, malformed, inconclusive, failures, result
                return (raw_texts, candidates, malformed, inconclusive,
                        failures, technical_ocr_result(
                    'ocr_error', f'{stage_prefix}_psm_{psm}', exc,
                    crop_box=crop_box, prepared=prepared, counter_box=counter_box,
                    numerator_box=numerator_box, candidates=candidates,
                    raw_texts=raw_texts, attempt=attempt,
                    prior_failures=failures, rejection_stage=rejection_stage,
                    rejection_detail=rejection_detail, components=components,
                    ocr_crop_box=fallback_crop_box or numerator_box,
                    locator_trace=locator_trace,
                ))
            except Exception as exc:
                return (raw_texts, candidates, malformed, inconclusive,
                        failures, technical_ocr_result(
                    'ocr_error', f'{stage_prefix}_psm_{psm}', exc,
                    crop_box=crop_box, prepared=prepared, counter_box=counter_box,
                    numerator_box=numerator_box, candidates=candidates,
                    raw_texts=raw_texts, attempt=attempt,
                    prior_failures=failures, rejection_stage=rejection_stage,
                    rejection_detail=rejection_detail, components=components,
                    ocr_crop_box=fallback_crop_box or numerator_box,
                    locator_trace=locator_trace,
                ))

        text = raw.strip()
        raw_texts.append(text)
        candidate = parse_candidate(text)
        if candidate is not None and (
                stage_prefix != 'numerator_tesseract' or
                len(text) >= minimum_digits):
            candidates.append(candidate)
        elif candidate is not None:
            inconclusive.append(text)
        elif text:
            malformed.append(text)
        else:
            inconclusive.append(text)
    return raw_texts, candidates, malformed, inconclusive, failures, None


def _is_transient_capture_error(exc):
    transient_errnos = {
        errno.EAGAIN,
        errno.EINTR,
        errno.EBUSY,
        errno.ETIMEDOUT,
    }
    transient_winerrors = {32, 33, 170}
    return (
        exc.errno in transient_errnos or
        getattr(exc, 'winerror', None) in transient_winerrors
    )


def capture_candies_attempt(region):
    failures = []
    for attempt in range(1, 3):
        shot = None
        client_bbox = None
        try:
            with CANDIES_OPERATION_LOCK:
                shot, client_bbox = screenshot_with_bbox()
                result = analyze_candies(shot, region)
        except OSError as exc:
            failures.append(ocr_failure_from_exception('screen_capture', attempt, exc))
            if attempt == 1 and _is_transient_capture_error(exc):
                time.sleep(OCR_RETRY_DELAY_SECONDS)
                continue
            result = CandiesOCRResult(
                None, (), (), 'capture_failed', None, None, str(exc),
                failures=tuple(failures),
            )
            return shot, None, result
        except Exception as exc:
            result = technical_ocr_result(
                'capture_failed' if shot is None else 'ocr_error',
                'screen_capture' if shot is None else 'ocr_pipeline',
                exc, shot=shot, attempt=attempt, prior_failures=failures,
            )
            return shot, client_bbox, result
        if failures:
            result = replace(result, failures=tuple(failures) + result.failures)
        return shot, client_bbox, result
    raise RuntimeError('Captura OCR terminou sem resultado após as tentativas limitadas.')


def write_ocr_exception_log(failures, context):
    if not failures:
        return None
    path = DEBUG / 'ocr_exceptions.log'
    with OCR_EXCEPTION_LOG_LOCK:
        DEBUG.mkdir(parents=True, exist_ok=True)
        entries = ''.join(
            f'\n[{time.strftime("%Y-%m-%d %H:%M:%S")}] '
            f'Contexto: {context}\n'
            f'Etapa: {failure.stage}\n'
            f'Tentativa: {failure.attempt}\n'
            f'Tipo: {failure.exception_type}\n'
            f'Mensagem: {failure.message}\n'
            f'Traceback completo:\n{failure.traceback_text.rstrip()}\n'
            f'---\n'
            for failure in failures
        ).encode('utf-8')
        backup = path.with_name(path.name + '.1')
        _rotate_ocr_exception_log(path, backup)
        if path.is_file() and path.stat().st_size + len(entries) > OCR_EXCEPTION_LOG_MAX_BYTES:
            backup.unlink(missing_ok=True)
            os.replace(path, backup)
        if len(entries) > OCR_EXCEPTION_LOG_MAX_BYTES:
            entries = entries[-OCR_EXCEPTION_LOG_MAX_BYTES:].decode(
                'utf-8', errors='ignore'
            ).encode('utf-8')
        with path.open('ab') as log:
            log.write(entries)
    return path


def _rotate_ocr_exception_log(path=None, backup=None):
    path = path or DEBUG / 'ocr_exceptions.log'
    backup = backup or path.with_name(path.name + '.1')
    with OCR_EXCEPTION_LOG_LOCK:
        if path.is_file() and path.stat().st_size > OCR_EXCEPTION_LOG_MAX_BYTES:
            data = path.read_bytes()[-OCR_EXCEPTION_LOG_MAX_BYTES:]
            temporary = backup.with_name(f'.{backup.name}.{uuid.uuid4().hex}.tmp')
            try:
                temporary.write_bytes(data)
                backup.unlink(missing_ok=True)
                os.replace(temporary, backup)
                path.unlink()
            finally:
                temporary.unlink(missing_ok=True)
        if backup.is_file() and backup.stat().st_size > OCR_EXCEPTION_LOG_MAX_BYTES:
            data = backup.read_bytes()[-OCR_EXCEPTION_LOG_MAX_BYTES:]
            temporary = backup.with_name(f'.{backup.name}.{uuid.uuid4().hex}.tmp')
            try:
                temporary.write_bytes(data)
                os.replace(temporary, backup)
            finally:
                temporary.unlink(missing_ok=True)


def report_ocr_failures(result, context, emit):
    if not result or not result.failures:
        return
    try:
        path = write_ocr_exception_log(result.failures, context)
        emit('log', f'Exceção técnica OCR registrada em {path}.')
    except OSError as exc:
        emit('log', f'ERRO ao salvar traceback OCR ({context}): {type(exc).__name__}: {exc}')
    for failure in result.failures:
        emit(
            'log',
            f'OCR técnico em {failure.stage}, tentativa {failure.attempt}: '
            f'{failure.exception_type}: {failure.message}',
        )


def locate_candies_counter(crop):
    """Localiza o contador laranja e recorta o numerador antes da barra."""
    width, height = crop.size
    details = {
        'stage': 'color_segmentation',
        'detail': None,
        'components': [],
        'separator_candidates': [],
        'layouts': [],
    }
    if width <= 0 or height <= 0:
        details['detail'] = 'ROI vazio.'
        return 'not_visible', None, None, details

    pixels = crop.load()
    mask = bytearray(width * height)
    row_counts = [0] * height
    for y in range(height):
        offset = y * width
        for x in range(width):
            red, green, blue = pixels[x, y]
            if (red > 115 and green > 25 and red > green * 1.25 and
                    red > blue * 1.35 and red - green > 40):
                mask[offset + x] = 1
                row_counts[y] += 1

    row_threshold = max(3, round(width * 0.035))
    active_rows = [y for y, count in enumerate(row_counts)
                   if count >= row_threshold]
    if not active_rows:
        details['detail'] = 'Nenhuma linha atingiu o limiar de pixels laranja.'
        return 'not_visible', None, None, details

    runs = []
    for y in active_rows:
        if not runs or y > runs[-1][-1] + 2:
            runs.append([y])
        else:
            runs[-1].append(y)
    line_rows = max(runs, key=lambda run: sum(row_counts[y] for y in run))
    line_top, line_bottom = line_rows[0], line_rows[-1] + 1
    line_pixels = [
        (x, y)
        for y in range(line_top, line_bottom)
        for x in range(width)
        if mask[y * width + x]
    ]
    if not line_pixels:
        details['detail'] = 'A máscara de cor não contém pixels na linha selecionada.'
        return 'not_visible', None, None, details

    line_box = (
        min(x for x, _ in line_pixels),
        line_top,
        max(x for x, _ in line_pixels) + 1,
        line_bottom,
    )
    scale = width / 210
    visited = bytearray(width * height)
    components = []
    component_reports = []
    min_area = max(6, round(scale * scale * 8))
    for y in range(line_top, line_bottom):
        for x in range(width):
            index = y * width + x
            if not mask[index] or visited[index]:
                continue
            stack = [(x, y)]
            visited[index] = 1
            points = []
            while stack:
                px, py = stack.pop()
                points.append((px, py))
                for next_y in range(max(line_top, py - 1),
                                    min(line_bottom, py + 2)):
                    for next_x in range(max(0, px - 1),
                                        min(width, px + 2)):
                        next_index = next_y * width + next_x
                        if mask[next_index] and not visited[next_index]:
                            visited[next_index] = 1
                            stack.append((next_x, next_y))
            x0 = min(px for px, _ in points)
            x1 = max(px for px, _ in points) + 1
            y0 = min(py for _, py in points)
            y1 = max(py for _, py in points) + 1
            if len(points) < min_area:
                component_reports.append({
                    'box': (x0, y0, x1, y1),
                    'area': len(points),
                    'retained': False,
                    'discard_reason': f'area menor que {min_area}',
                })
                continue
            edge_rows = max(1, round((y1 - y0) * 0.2))
            top_x = [px for px, py in points if py < y0 + edge_rows]
            bottom_x = [px for px, py in points if py >= y1 - edge_rows]
            slope = (
                sum(bottom_x) / len(bottom_x) - sum(top_x) / len(top_x)
                if top_x and bottom_x else 0
            )
            component = {
                'x0': x0, 'x1': x1, 'y0': y0, 'y1': y1,
                'height': y1 - y0, 'slope': slope, 'area': len(points),
            }
            components.append(component)
            component_reports.append({
                'box': (x0, y0, x1, y1),
                'area': len(points),
                'retained': True,
                'height': y1 - y0,
                'slope': round(slope, 2),
            })
    details['components'] = component_reports
    details['minimum_component_area'] = min_area

    line_height = max((component['height'] for component in components), default=0)
    edge_margin = max(2, round(scale * 2))
    if (line_height <= 0 or line_box[0] <= edge_margin or
            line_box[1] <= edge_margin or
            line_box[2] >= width - edge_margin or
            line_box[3] >= height - edge_margin):
        details['stage'] = 'line_bounds'
        details['detail'] = (
            f'Linha detectada próxima da borda; margem exigida={edge_margin}px, '
            f'caixa={line_box}, tamanho ROI={width}x{height}.'
        )
        return 'unrecognized', line_box, None, details

    separator_candidates = [
        component for component in components
        if component['x1'] - component['x0'] <= line_height * 0.65
        and component['height'] >= line_height * 0.75
        and abs(component['slope']) >= line_height * 0.23
    ]
    details['separator_candidates'] = [
        {
            'box': (item['x0'], item['y0'], item['x1'], item['y1']),
            'slope': round(item['slope'], 2),
        }
        for item in separator_candidates
    ]
    layouts = []
    for separator in separator_candidates:
        before = [
            component for component in components
            if component is not separator and component['x0'] < separator['x0']
            and component['x1'] <= separator['x0'] + 1
        ]
        if not before:
            details['layouts'].append({
                'separator_x': separator['x0'],
                'accepted': False,
                'rejection': 'nenhum componente antes do candidato',
            })
            continue
        number_left = min(component['x0'] for component in before)
        number_width = separator['x0'] - number_left
        if (number_left <= edge_margin or
                number_width < line_height * 0.3 or
                number_width > line_height * 2.5):
            details['layouts'].append({
                'separator_x': separator['x0'],
                'accepted': False,
                'rejection': 'largura/margem do numerador fora do limite',
                'numerator_x_bounds': (number_left, separator['x0']),
                'numerator_width': number_width,
            })
            continue

        after = sorted(
            (component for component in components
             if component is not separator
             and component['x0'] >= separator['x1'] - 1),
            key=lambda component: component['x0'],
        )
        denominator = []
        for component in after:
            if denominator and component['x0'] - denominator[-1]['x1'] > line_height * 0.35:
                break
            denominator.append(component)
        if not denominator:
            details['layouts'].append({
                'separator_x': separator['x0'],
                'accepted': False,
                'rejection': 'nenhum componente após o separador',
            })
            continue
        denominator_width = (
            max(component['x1'] for component in denominator) -
            min(component['x0'] for component in denominator)
        )
        if not line_height * 1.5 <= denominator_width <= line_height * 2.7:
            details['layouts'].append({
                'separator_x': separator['x0'],
                'accepted': False,
                'rejection': 'largura do denominador fora do limite',
                'denominator_box': (
                    min(component['x0'] for component in denominator),
                    min(component['y0'] for component in denominator),
                    max(component['x1'] for component in denominator),
                    max(component['y1'] for component in denominator),
                ),
                'denominator_width': denominator_width,
            })
            continue
        number_top = min(component['y0'] for component in before)
        number_bottom = max(component['y1'] for component in before)
        layouts.append((
            separator,
            number_left,
            number_width,
            number_top,
            number_bottom,
        ))
        details['layouts'].append({
            'separator_x': separator['x0'],
            'accepted': True,
            'numerator_box': (
                number_left, number_top, separator['x0'], number_bottom
            ),
            'denominator_width': denominator_width,
        })

    if len(layouts) != 1:
        if len(layouts) > 1:
            details['stage'] = 'separator_ambiguity'
        elif not separator_candidates:
            details['stage'] = 'separator_not_found'
        else:
            details['stage'] = 'layout_not_valid'
        details['detail'] = (
            f'Esperado exatamente um layout numerador/separador/denominador; '
            f'{len(layouts)} layouts passaram pela geometria.'
        )
        return 'unrecognized', line_box, None, details

    separator, number_left, _, number_top, number_bottom = layouts[0]
    padding = max(1, round(line_height * 0.18))
    numerator_box = (
        max(0, number_left - padding),
        max(0, number_top - padding),
        separator['x0'],
        min(height, number_bottom + padding),
    )
    details['stage'] = 'recognized'
    details['detail'] = 'Um único layout geométrico passou pelas verificações.'
    return 'recognized', line_box, numerator_box, details


def analyze_candies(screenshot_image, region=None):
    with CANDIES_OPERATION_LOCK:
        return _analyze_candies_locked(screenshot_image, region)


def _analyze_candies_locked(screenshot_image, region=None):
    region = region or ROIS['candies']
    try:
        crop_box = roi_box(screenshot_image, region)
    except ValueError as exc:
        return CandiesOCRResult(None, (), (), 'invalid_region', None, None, str(exc))

    try:
        crop = screenshot_image.crop(crop_box).convert('RGB')
        if crop.width < 16 or crop.height < 8:
            return CandiesOCRResult(
                None, (), (), 'invalid_region', crop_box, None,
                f'Recorte insuficiente para OCR: {crop.width}x{crop.height}.'
            )

        visibility, local_counter_box, local_numerator_box, locator_trace = (
            locate_candies_counter(crop)
        )
        counter_box = (
            (crop_box[0] + local_counter_box[0],
             crop_box[1] + local_counter_box[1],
             crop_box[0] + local_counter_box[2],
             crop_box[1] + local_counter_box[3])
            if local_counter_box else None
        )
        numerator_box = (
            (crop_box[0] + local_numerator_box[0],
             crop_box[1] + local_numerator_box[1],
             crop_box[0] + local_numerator_box[2],
             crop_box[1] + local_numerator_box[3])
            if local_numerator_box else None
        )
        components = tuple(locator_trace['components'])
        rejection_stage = locator_trace['stage']
        rejection_detail = locator_trace['detail']
        if visibility == 'not_visible':
            return CandiesOCRResult(
                None, (), (), 'not_visible', crop_box, None,
                counter_box=counter_box, rejection_stage=rejection_stage,
                rejection_detail=rejection_detail, components=components,
                locator_trace=locator_trace,
            )
        if local_counter_box is None:
            return CandiesOCRResult(
                None, (), (), 'inconclusive', crop_box, None,
                'Não foi possível formar a caixa visual completa do contador.',
                counter_box, numerator_box, rejection_stage=rejection_stage,
                rejection_detail=rejection_detail, components=components,
                locator_trace=locator_trace,
            )

        if local_numerator_box is not None:
            numerator = crop.crop(local_numerator_box)
            scaled = numerator.resize(
                (numerator.width * 6, numerator.height * 6),
                Image.Resampling.LANCZOS,
            )
            prepared = ImageOps.autocontrast(scaled.getchannel('R'))
            ocr_crop_box = numerator_box
        else:
            if locator_trace['stage'] == 'line_bounds':
                return CandiesOCRResult(
                    None, (), (), 'inconclusive', crop_box, None,
                    'Contador visível, mas a linha está junto à borda da calibração.',
                    counter_box, None, rejection_stage=rejection_stage,
                    rejection_detail=rejection_detail, components=components,
                    locator_trace=locator_trace,
                )
            prepared = None
            ocr_crop_box = None
    except Exception as exc:
        return technical_ocr_result(
            'ocr_error', 'image_preprocessing', exc, crop_box=crop_box
        )

    primary_raw = []
    primary_candidates = []
    primary_malformed = []
    primary_inconclusive = []
    failures = []
    if prepared is not None:
        layout = (locator_trace.get('layouts') or [{}])[0]
        geometric_numerator = layout.get('numerator_box')
        minimum_digits = 1
        if geometric_numerator:
            width = geometric_numerator[2] - geometric_numerator[0]
            height = max(1, geometric_numerator[3] - geometric_numerator[1])
            # A very short OCR string cannot explain the full visible glyph
            # span. Treat it as incomplete rather than as a second value.
            minimum_digits = max(
                1, min(3, math.ceil((width / height + 0.15) / 1.10))
            )
        (primary_raw, primary_candidates, primary_malformed,
         primary_inconclusive, failures, terminal) = run_tesseract_variants(
            prepared, '0123456789', 'numerator_tesseract', crop_box=crop_box,
            counter_box=counter_box, numerator_box=numerator_box,
            rejection_stage=rejection_stage, rejection_detail=rejection_detail,
            components=components, locator_trace=locator_trace,
            minimum_digits=minimum_digits,
            parse_candidate=lambda text: (
                int(text) if re.fullmatch(r'\d{1,3}', text)
                and 0 <= int(text) <= 500 else None
            ),
        )
        if terminal is not None:
            return replace(
                terminal,
                candidatos_validos=tuple(
                    ('numerador_geometrico', value)
                    for value in primary_candidates
                ),
                leituras_malformadas=tuple(
                    ('numerador_geometrico', text)
                    for text in primary_malformed
                ),
                leituras_inconclusivas=tuple(
                    ('numerador_geometrico', text)
                    for text in primary_inconclusive
                ),
                motivo_decisao='Falha técnica antes da validação final das rotas.',
            )

    if locator_trace['stage'] == 'line_bounds':
        return CandiesOCRResult(
            None, tuple(primary_candidates), tuple(primary_raw), 'inconclusive',
            crop_box, prepared, 'A segmentação indica possível corte pela borda do ROI.',
            counter_box, numerator_box, tuple(failures), rejection_stage,
            rejection_detail, components, ocr_crop_box, (), locator_trace,
            tuple(('numerador_geometrico', value) for value in primary_candidates),
            tuple(('numerador_geometrico', text) for text in primary_malformed),
            tuple(('numerador_geometrico', text) for text in primary_inconclusive),
            (), 'Borda do ROI pode cortar dígitos; fallback bloqueado.',
        )

    line_box = local_counter_box
    line_height = line_box[3] - line_box[1]
    padding = max(2, round(line_height * 0.16))
    line_crop_box = (
        max(0, line_box[0] - padding),
        max(0, line_box[1] - padding),
        min(crop.width, line_box[2] + padding),
        min(crop.height, line_box[3] + padding),
    )
    line_crop = crop.crop(line_crop_box).getchannel('R')
    line_scaled = line_crop.resize(
        (line_crop.width * 4, line_crop.height * 4), Image.Resampling.LANCZOS
    )
    fallback_prepared = ImageOps.autocontrast(line_scaled)
    fallback_ocr_box = (
        crop_box[0] + line_crop_box[0],
        crop_box[1] + line_crop_box[1],
        crop_box[0] + line_crop_box[2],
        crop_box[1] + line_crop_box[3],
    )
    fallback_stage = 'separator_fallback' if prepared is None else 'counter_fallback'
    (fallback_raw, fallback_candidates, fallback_malformed,
     fallback_inconclusive, fallback_failures, terminal) = run_tesseract_variants(
            fallback_prepared, '0123456789/', fallback_stage,
            crop_box=crop_box, counter_box=counter_box,
            numerator_box=numerator_box, rejection_stage=rejection_stage,
            rejection_detail=rejection_detail, components=components,
            locator_trace=locator_trace, fallback_crop_box=fallback_ocr_box,
            parse_candidate=lambda text: (
                int(match.group(1))
                if (match := re.fullmatch(r'\s*(\d{1,3})\s*/\s*500\s*', text))
                and 0 <= int(match.group(1)) <= 500 else None
            ),
        )
    if terminal is not None:
        return replace(
            terminal, raw_texts=tuple(primary_raw),
            candidates=tuple(primary_candidates) + terminal.candidates,
            fallback_raw_texts=tuple(fallback_raw),
            candidatos_validos=tuple(
                [('numerador_geometrico', value) for value in primary_candidates] +
                [('linha_completa_500', value) for value in fallback_candidates]
            ),
            leituras_malformadas=tuple(
                [('numerador_geometrico', text) for text in primary_malformed] +
                [('linha_completa_500', text) for text in fallback_malformed]
            ),
            leituras_inconclusivas=tuple(
                [('numerador_geometrico', text) for text in primary_inconclusive] +
                [('linha_completa_500', text) for text in fallback_inconclusive]
            ),
            motivo_decisao='Falha técnica durante OCR da linha completa.',
        )

    all_candidates = tuple(primary_candidates + fallback_candidates)
    all_distinct = set(all_candidates)
    valid_records = tuple(
        [('numerador_geometrico', value) for value in primary_candidates] +
        [('linha_completa_500', value) for value in fallback_candidates]
    )
    malformed_records = tuple(
        [('numerador_geometrico', text) for text in primary_malformed] +
        [('linha_completa_500', text) for text in fallback_malformed]
    )
    inconclusive_records = tuple(
        [('numerador_geometrico', text) for text in primary_inconclusive] +
        [('linha_completa_500', text) for text in fallback_inconclusive]
    )
    if len(all_distinct) > 1:
        reason = 'divergent'
        contradictions = tuple(sorted(all_distinct))
        decision = (
            'Candidatos completos e válidos discordam entre si: '
            f'{list(contradictions)}; leitura bloqueada.'
        )
        rejection_stage = 'candidate_conflict'
        rejection_detail = decision
        error = decision
        value = None
    elif len(all_candidates) >= 2:
        reason = 'recognized'
        contradictions = ()
        value = all_candidates[0]
        decision = (
            f'{len(all_candidates)} candidatos completos e válidos concordam '
            f'em {value}; leituras malformadas não foram usadas como evidência.'
        )
        rejection_stage = 'recognized'
        rejection_detail = decision
        error = None
    else:
        reason = 'inconclusive'
        contradictions = ()
        value = None
        decision = (
            'Menos de dois candidatos completos e válidos concordantes; '
            'não há evidência suficiente para confirmar o numerador.'
        )
        rejection_stage = 'insufficient_valid_candidates'
        rejection_detail = decision
        error = decision

    return CandiesOCRResult(
        value, all_candidates, tuple(primary_raw), reason, crop_box,
        fallback_prepared, error, counter_box, numerator_box,
        tuple(failures + fallback_failures), rejection_stage, rejection_detail,
        components, fallback_ocr_box, tuple(fallback_raw), locator_trace,
        valid_records, malformed_records, inconclusive_records,
        contradictions, decision,
    )


def read_candies(screenshot_image, region=None, return_candidates=False):
    result = analyze_candies(screenshot_image, region)
    if return_candidates:
        return result.value, result.candidates
    return result.value


def accumulate_analysis_result(result, captured_at, readings, interpretations):
    """Adds only confirmed samples and valid contradictions from this analysis."""
    interpretations.extend(result.contradicoes)
    if result.value is None:
        return False
    readings.append((captured_at, result.value))
    return True


def automatic_diagnostic_samples(verdict, audits, failed_samples):
    selected = []
    if not verdict.confiavel_para_compra and (
            len(verdict.distintos) > 1 or 'contradizem' in verdict.motivo):
        for value in verdict.distintos:
            audit = audits.get(value)
            if audit and len(selected) < 2:
                shot, result, _region, capture_bbox = audit
                selected.append((
                    shot, result, 'divergent', verdict.motivo,
                    capture_bbox, _region,
                ))
    selected.extend(failed_samples[:max(0, 2 - len(selected))])
    return selected[:2]


OCR_REASON_LABELS = {
    'recognized': 'OCR reconhecido',
    'not_visible': 'Contador não visível',
    'invalid_region': 'Região de captura inválida',
    'unrecognized': 'Texto não reconhecido',
    'inconclusive': 'OCR inconclusivo',
    'tesseract_unavailable': 'Tesseract indisponível',
    'ocr_timeout': 'Tempo limite do OCR excedido',
    'divergent': 'OCR reconhecido, mas rejeitado por divergência',
    'capture_failed': 'Falha inesperada de captura',
    'ocr_error': 'Falha inesperada do OCR',
}


def ocr_test_block_reason(automation_active, starting, recording, test_running):
    if recording:
        return 'Interrompa ou cancele a gravação antes de testar o OCR.'
    if test_running:
        return 'Já existe um teste OCR em andamento.'
    if automation_active or starting:
        return 'Pare a automação antes de testar o OCR.'
    return None


def save_candies_diagnostic(shot, cfg, result=None, *, reason=None, error=None,
                            client_bbox=None):
    with DIAGNOSTIC_MAINTENANCE_LOCK:
        return _save_candies_diagnostic_locked(
            shot, cfg, result, reason=reason, error=error,
            client_bbox=client_bbox,
        )


def _save_candies_diagnostic_locked(shot, cfg, result=None, *, reason=None,
                                    error=None, client_bbox=None):
    """Guarda uma amostra completa para diagnóstico visual do contador."""
    DEBUG.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime('%Y%m%d_%H%M%S') + f'_{time.time_ns() % 1_000_000_000:09d}'
    folder = DEBUG / f'candies_{stamp}'
    folder.mkdir()
    region = None
    region_error = None
    try:
        region = region_from(cfg, 'candies')
    except ValueError as exc:
        region_error = str(exc)
    selected_reason = reason or (result.reason if result else 'capture_failed')
    crop_box = result.crop_box if result else None
    dpi_scale = 'indisponível'
    crop_screen_box = None

    if shot is not None:
        if client_bbox is None:
            client_bbox = roblox_client_bbox()
        shot.save(folder / 'area_cliente.png')
        if region is not None:
            crop_box = roi_box(shot, region)
            crop = shot.crop(crop_box)
            scale_x = (client_bbox[2] - client_bbox[0]) / shot.width
            scale_y = (client_bbox[3] - client_bbox[1]) / shot.height
            crop_screen_box = (
                client_bbox[0] + round(crop_box[0] * scale_x),
                client_bbox[1] + round(crop_box[1] * scale_y),
                client_bbox[0] + round(crop_box[2] * scale_x),
                client_bbox[1] + round(crop_box[3] * scale_y),
            )
            crop.save(folder / 'recorte_candies.png')
            prepared = result.prepared if result and result.prepared else prepared_images(crop, 'candies')[0]
            prepared.save(folder / 'preparada_tesseract.png')
            if result and result.counter_box:
                shot.crop(result.counter_box).save(folder / 'contador_localizado.png')
            if result and result.numerator_box:
                shot.crop(result.numerator_box).save(folder / 'numerador.png')
            if result and result.ocr_crop_box:
                shot.crop(result.ocr_crop_box).save(
                    folder / 'recorte_enviado_tesseract.png'
                )
            annotated = shot.copy()
            draw = ImageDraw.Draw(annotated)
            draw.rectangle(
                (crop_box[0], crop_box[1], crop_box[2] - 1, crop_box[3] - 1),
                outline=(255, 0, 0), width=max(2, round(shot.width / 700))
            )
            if result and result.counter_box:
                draw.rectangle(
                    (result.counter_box[0], result.counter_box[1],
                     result.counter_box[2] - 1, result.counter_box[3] - 1),
                    outline=(0, 255, 0), width=max(2, round(shot.width / 700))
                )
            if result and result.numerator_box:
                draw.rectangle(
                    (result.numerator_box[0], result.numerator_box[1],
                     result.numerator_box[2] - 1, result.numerator_box[3] - 1),
                    outline=(255, 255, 0), width=max(2, round(shot.width / 700))
                )
            if result and result.ocr_crop_box:
                draw.rectangle(
                    (result.ocr_crop_box[0], result.ocr_crop_box[1],
                     result.ocr_crop_box[2] - 1, result.ocr_crop_box[3] - 1),
                    outline=(255, 0, 255), width=max(2, round(shot.width / 700))
                )
            annotated.save(folder / 'regiao_analisada.png')
        if client_bbox:
            user32 = ctypes.WinDLL('user32', use_last_error=True)
            user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
            user32.FindWindowW.restype = wintypes.HWND
            hwnd = user32.FindWindowW(None, 'Roblox')
            get_dpi = getattr(user32, 'GetDpiForWindow', None)
            if hwnd and get_dpi:
                get_dpi.argtypes = [wintypes.HWND]
                get_dpi.restype = wintypes.UINT
                dpi_scale = f'{get_dpi(hwnd) / 96:.2f}x'

    raw_texts = result.raw_texts if result else ()
    candidates = result.candidates if result else ()
    value = result.value if result else None
    lines = [
        f'Horário local: {time.strftime("%Y-%m-%d %H:%M:%S")}',
        f'Resultado: {OCR_REASON_LABELS.get(selected_reason, selected_reason)}',
        f'Valor reconhecido: {value if value is not None else "nenhum"}',
        f'Variantes numéricas válidas: {list(candidates)}',
        f'Candidatos válidos por caminho: {json.dumps(result.candidatos_validos if result else (), ensure_ascii=False)}',
        f'Leituras malformadas por caminho: {json.dumps(result.leituras_malformadas if result else (), ensure_ascii=False)}',
        f'Leituras inconclusivas por caminho: {json.dumps(result.leituras_inconclusivas if result else (), ensure_ascii=False)}',
        f'Contradições válidas: {list(result.contradicoes if result else ())}',
        f'Decisão final: {result.motivo_decisao if result and result.motivo_decisao else "não determinada"}',
        f'OCR bruto por variante: {list(raw_texts)!r}',
        f'OCR bruto do fallback /500: {list(result.fallback_raw_texts if result else ())!r}',
        f'Motivo/erro: {error or (result.error if result else None) or region_error or "nenhum"}',
        f'Resolução da captura: {f"{shot.width}x{shot.height}" if shot else "indisponível"}',
        f'Retângulo cliente na tela: {client_bbox or "indisponível"}',
        f'Recorte em coordenadas da tela: {crop_screen_box or "indisponível"}',
        f'Escala DPI da janela: {dpi_scale}',
        f'Região normalizada (área cliente 1365x700): {region or "inválida"}',
        f'Recorte em pixels (imagem capturada): {crop_box or "indisponível"}',
        f'Contador localizado (pixels da captura): {result.counter_box if result and result.counter_box else "não identificado"}',
        f'Numerador isolado (pixels da captura): {result.numerator_box if result and result.numerator_box else "não identificado"}',
        f'Etapa de rejeição geométrica/OCR: {result.rejection_stage if result and result.rejection_stage else "nenhuma"}',
        f'Detalhe da rejeição: {result.rejection_detail if result and result.rejection_detail else "nenhum"}',
        f'Retângulo enviado ao Tesseract (pixels da captura): {result.ocr_crop_box if result and result.ocr_crop_box else "não identificado"}',
        f'Componentes de cor: {json.dumps(result.components if result else (), ensure_ascii=False)}',
        f'Traço do localizador: {json.dumps(result.locator_trace if result else None, ensure_ascii=False)}',
        f'Executável Tesseract: {pytesseract.pytesseract.tesseract_cmd}',
    ]
    if result and result.failures:
        for failure in result.failures:
            lines.extend((
                f'Etapa da exceção: {failure.stage}',
                f'Tentativa: {failure.attempt}',
                f'Tipo da exceção: {failure.exception_type}',
                f'Mensagem da exceção: {failure.message}',
                'Traceback completo:',
                failure.traceback_text.rstrip(),
                '---',
            ))
    (folder / 'diagnostico.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    prune_candies_diagnostics()
    return folder


DIAGNOSTIC_FOLDER_FILES = {
    'area_cliente.png',
    'recorte_candies.png',
    'preparada_tesseract.png',
    'contador_localizado.png',
    'numerador.png',
    'recorte_enviado_tesseract.png',
    'regiao_analisada.png',
    'diagnostico.txt',
}


def _is_owned_diagnostic_folder(path):
    if not re.fullmatch(r'candies_\d{8}_\d{6}_\d{9}', path.name):
        return False
    children = list(path.iterdir())
    return any(child.is_file() and child.name == 'diagnostico.txt'
               for child in children)


def prune_candies_diagnostics():
    with DIAGNOSTIC_MAINTENANCE_LOCK:
        if not DEBUG.is_dir():
            return
        _rotate_ocr_exception_log()
        folders = sorted(
            (path for path in DEBUG.iterdir()
             if path.is_dir() and _is_owned_diagnostic_folder(path)),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old in folders[OCR_DIAGNOSTIC_FOLDER_LIMIT:]:
            for child in old.iterdir():
                if child.is_file() and child.name in DIAGNOSTIC_FOLDER_FILES:
                    child.unlink()
            if not any(old.iterdir()):
                old.rmdir()

        audit_pattern = re.compile(
            r'\d{8}_\d{6}_compra_(?:autorizada|bloqueada)_contador\.png'
        )
        audits = sorted(
            (path for path in DEBUG.iterdir()
             if path.is_file() and audit_pattern.fullmatch(path.name)),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for old in audits[OCR_AUDIT_IMAGE_LIMIT:]:
            old.unlink()

        clock_pattern = re.compile(
            r'(\d{8}_\d{6})_relogio_(?:tela|recorte|ampliado)\.png'
        )
        clock_diagnostics = {}
        for path in DEBUG.iterdir():
            match = clock_pattern.fullmatch(path.name)
            if path.is_file() and match:
                clock_diagnostics.setdefault(match.group(1), []).append(path)
        recent_clock_stamps = set(sorted(clock_diagnostics, reverse=True)[
            :OCR_CLOCK_DIAGNOSTIC_LIMIT
        ])
        for stamp, paths in clock_diagnostics.items():
            if stamp not in recent_clock_stamps:
                for path in paths:
                    path.unlink()


def parse_clock_text(raw):
    """Decodifica somente relogios completos HH:MM:SS, sem chutar numeros parciais."""
    txt = re.sub(r'[^0-9:]', '', raw)
    match = re.fullmatch(r'(\d{1,3}):(\d{2}):(\d{2})', txt)
    if match:
        hh, mm, ss = map(int, match.groups())
    else:
        digits = re.sub(r'[^0-9]', '', txt)
        if not 6 <= len(digits) <= 7:
            return None
        hh, mm, ss = int(digits[:-4]), int(digits[-4:-2]), int(digits[-2:])
    if 0 <= hh < 1000 and 0 <= mm < 60 and 0 <= ss < 60:
        return hh*3600 + mm*60 + ss
    return None


def read_clock(screenshot_image, region=None):
    """Lê HH:MM:SS por OCR usando linha crua (--psm 13).

    O texto é muito pequeno (~6 px), e o PSM 7 normal confunde '4' com '8'.
    Testado nas capturas reais: 00:46:19 e 00:46:47.
    A função retorna UMA leitura candidata; Controller.clock confirma sua
    progressão numa SEGUNDA captura antes de permitir compras.

    Limita o número de chamadas ao Tesseract (tempo baixo, sem 29 segundos
    de espera no relógio quando a leitura falha).
    """
    x1, y1, x2, y2 = region or ROIS['clock']
    # Ajustes mínimos em torno da área selecionada, sem invadir a linha
    # 'Version' que fica logo abaixo do relógio.
    areas = [
        (x1, y1, x2, y2),
        (max(0, x1 - 1), max(0, y1 - 1), x2, min(700, y2 + 1)),
    ]
    for box in dict.fromkeys(areas):
        crop = roi(screenshot_image, box)
        if crop.width < 12 or crop.height < 6:
            continue
        enlarged = crop.convert('RGB').resize(
            (crop.width * 4, crop.height * 4), Image.Resampling.LANCZOS
        )
        gray = ImageOps.grayscale(enlarged)
        try:
            raw = pytesseract.image_to_string(
                gray,
                config='--psm 13 -c tessedit_char_whitelist=0123456789:',
                timeout=1.4,
            ).strip()
            value = parse_clock_text(raw)
            # Rejeitar relógios incompletos ou colagens que perderam separadores.
            # Os dois pontos são visíveis quando a leitura é realmente confiável.
            if value is not None and raw.count(':') == 2 and value < 48 * 3600:
                return value
        except RuntimeError:
            pass
    return None


def save_clock_diagnostic(shot, cfg):
    """Salva so o canto do relogio e a area interna do jogo para calibracao."""
    try:
        DEBUG.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime('%Y%m%d_%H%M%S')
        shot.save(DEBUG / f'{stamp}_relogio_tela.png')
        piece = roi(shot, region_from(cfg, 'clock'))
        piece.save(DEBUG / f'{stamp}_relogio_recorte.png')
        piece.resize((piece.width*8, piece.height*8), Image.Resampling.NEAREST).save(
            DEBUG / f'{stamp}_relogio_ampliado.png')
        threading.Thread(
            target=prune_candies_diagnostics, daemon=True
        ).start()
    except Exception:
        pass

def packaged_tesseract_paths():
    roots = [BUNDLE_ROOT, ROOT]
    if FROZEN:
        roots.append(Path(sys.executable).resolve().parent)
    return tuple(
        root / 'tesseract' / 'tesseract.exe'
        for root in dict.fromkeys(roots)
    )


def packaged_tesseract():
    return next(
        (engine for engine in packaged_tesseract_paths() if engine.is_file()),
        None,
    )


def locate_tesseract():
    candidates = [
        packaged_tesseract(),
        shutil.which('tesseract'),
        r'C:\Program Files\Tesseract-OCR\tesseract.exe',
        r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
        str(Path.home() / 'AppData/Local/Programs/Tesseract-OCR/tesseract.exe'),
    ]
    return next((p for p in candidates if p and Path(p).is_file()), None)


def locate_tessdata(engine):
    candidates = [Path(engine).parent / 'tessdata']
    configured_prefix = os.environ.get('TESSDATA_PREFIX')
    if configured_prefix:
        prefix = Path(configured_prefix).expanduser()
        candidates.extend((prefix, prefix / 'tessdata'))
    return next(
        (path for path in dict.fromkeys(candidates)
         if (path / 'eng.traineddata').is_file()),
        None,
    )


def verify_tesseract(engine):
    version = pytesseract.get_tesseract_version()
    pytesseract.image_to_string(
        Image.new('RGB', (32, 32), 'white'),
        lang='eng',
        config='--psm 7',
        timeout=OCR_TIMEOUT_SECONDS,
    )
    return version


def configure_tesseract(cfg):
    with CANDIES_OPERATION_LOCK:
        configured = str(cfg.get('tesseract', '') or '').strip()
        bundled = packaged_tesseract()
        discovered = locate_tesseract()
        candidates = []
        for engine in (bundled, configured, discovered):
            if engine and Path(engine).is_file() and engine not in candidates:
                candidates.append(engine)

        if not candidates:
            expected = '; '.join(
                str(path) for path in packaged_tesseract_paths()
            )
            configured_note = (
                f' O caminho salvo em config.json não existe: {configured}.'
                if configured else ''
            )
            raise RuntimeError(
                f'Tesseract OCR não encontrado. O executável portátil é esperado '
                f'em um destes locais: '
                f'{expected}.{configured_note} Instale o pacote completo ou configure '
                'um caminho válido para tesseract.exe.'
            )

        errors = []
        for engine in candidates:
            tessdata = locate_tessdata(engine)
            if tessdata is None:
                expected = Path(engine).parent / 'tessdata' / 'eng.traineddata'
                errors.append(
                    f'{engine}: arquivo de idioma eng.traineddata não encontrado '
                    f'(esperado em {expected} ou no TESSDATA_PREFIX configurado)'
                )
                continue

            pytesseract.pytesseract.tesseract_cmd = str(engine)
            os.environ['TESSDATA_PREFIX'] = str(tessdata)
            try:
                version = verify_tesseract(engine)
            except (
                    pytesseract.pytesseract.TesseractNotFoundError,
                    OSError,
                    RuntimeError) as exc:
                errors.append(f'{engine}: não foi possível executar OCR com eng: {exc}')
                continue

            warning = None
            if configured and str(engine) != configured:
                if not Path(configured).is_file():
                    warning = (
                        f'O caminho Tesseract salvo não está disponível; usando '
                        f'{engine}.'
                    )
                elif bundled and Path(engine) == bundled:
                    warning = (
                        f'Usando o Tesseract incluído no aplicativo, com prioridade '
                        f'sobre o caminho salvo em config.json: {engine}.'
                    )
                else:
                    warning = (
                        f'O caminho Tesseract salvo não pôde ser usado; usando '
                        f'{engine}.'
                    )
            return str(engine), str(version), warning

        raise RuntimeError(
            'Tesseract encontrado, mas a validação do motor OCR falhou: '
            + '; '.join(errors)
        )


def boss_status(server_seconds):
    # Primeiro boss: 25:00–34:59. Depois: 60:00–69:59, etc.
    if server_seconds < 25*60:
        return False, 25*60-server_seconds
    phase = (server_seconds - 25*60) % (35*60)
    if phase < 10*60:
        return True, 0
    return False, 35*60-phase

class Controller:
    def __init__(self, emit, relogio, rare_chests=0):
        self.emit = emit
        self.relogio = relogio
        self.stop = threading.Event()
        self.thread = None
        self.cfg = None
        self._run_lock = threading.Lock()
        self._starting = False
        self._rare_chests_lock = threading.RLock()
        self._rare_chests = validate_rare_chests(rare_chests)
        self._limit_log_emitted = False

    @property
    def rare_chests(self):
        with self._rare_chests_lock:
            return self._rare_chests

    def set_rare_chests(self, value, cfg):
        value = validate_rare_chests(value)
        with self._rare_chests_lock:
            if self.active():
                raise RuntimeError('Pare a automação antes de editar Rare Chests.')
            if value == self._rare_chests:
                return value
            updated_cfg = dict(cfg)
            updated_cfg['rare_chests'] = value
            atomic_write_json(CFG, updated_cfg)
            self._rare_chests = value
            if self.cfg is not None:
                self.cfg['rare_chests'] = value
            if value < RARE_CHEST_LIMIT:
                self._limit_log_emitted = False
            if value == RARE_CHEST_LIMIT:
                self._notify_rare_chest_limit()
        return value

    def _notify_rare_chest_limit(self):
        if not self._rare_chest_limit_enabled():
            return
        if self.rare_chests < RARE_CHEST_LIMIT:
            return
        self.emit('rare_chests', rare_chests_display(self.rare_chests))
        if not self._limit_log_emitted:
            self.emit(
                'log',
                'Limite de 10 Rare Chests contabilizados atingido. Compras suspensas; '
                'coleta e análise continuam. O recebimento dos itens no jogo não é '
                'confirmado automaticamente.',
            )
            self._limit_log_emitted = True

    def _rare_chest_limit_enabled(self):
        return (self.cfg or {}).get('rare_chest_limit_enabled', True)

    def _record_completed_purchase(self):
        with self._rare_chests_lock:
            if not self._rare_chest_limit_enabled():
                return self._rare_chests
            if self._rare_chests >= RARE_CHEST_LIMIT:
                self._notify_rare_chest_limit()
                return self._rare_chests
            self._rare_chests += 1
            count = self._rare_chests
            self.cfg['rare_chests'] = count
            self.emit('rare_chests', rare_chests_display(count))
            self.emit(
                'log',
                f'Gravação de compra concluída integralmente; Rare Chests '
                f'contabilizados: {count}/{RARE_CHEST_LIMIT}. Aquisição no jogo '
                'não confirmada.',
            )
            try:
                atomic_write_json(CFG, self.cfg)
            except OSError as exc:
                raise OSError(
                    f'A gravação de compra terminou e o contador foi atualizado para '
                    f'{count}/{RARE_CHEST_LIMIT}, mas não foi possível persistir '
                    f'config.json: {exc}'
                ) from exc
            if count == RARE_CHEST_LIMIT:
                self._notify_rare_chest_limit()
            return count

    def run_purchase(self):
        if not (self.cfg or {}).get('auto_purchases', True):
            return False
        if self._rare_chest_limit_enabled() and self.rare_chests >= RARE_CHEST_LIMIT:
            self._notify_rare_chest_limit()
            return False
        if self.run_macro('compra') is not True:
            return False
        self._record_completed_purchase()
        return True

    def active(self):
        return self._starting or bool(self.thread and self.thread.is_alive())

    def start(self, cfg):
        # A GUI pode receber F12 e clique quase simultaneamente. Só uma
        # validação/inicialização pode acontecer por vez.
        with self._run_lock:
            if self.active():
                return False
            self._starting = True
        try:
            keys = ['coleta', 'analise']
            if cfg.get('auto_purchases', True):
                keys.append('compra')
            for key in keys:
                rec = macro_recording(cfg[key])
                if not rec.is_file():
                    raise FileNotFoundError(f'Não encontrei {rec.name}. Selecione a gravação .rec no aplicativo.')
                read_rec(rec)
            self.cfg = cfg.copy()
            for key in RESOURCE_TOGGLE_KEYS:
                self.cfg.setdefault(key, DEFAULT[key])
            self.cfg = normalize_resource_settings(self.cfg)
            with self._rare_chests_lock:
                self._rare_chests = validate_rare_chests(
                    self.cfg.get('rare_chests', DEFAULT['rare_chests'])
                )
                self.cfg['rare_chests'] = self._rare_chests
                self._limit_log_emitted = False
            if self.cfg['auto_purchases']:
                engine, version, warning = configure_tesseract(self.cfg)
                if warning:
                    self.emit('log', warning)
                self.emit('log', f'Tesseract confirmado: {engine} (versão {version}).')
            else:
                self.emit(
                    'log',
                    'Compras automáticas desativadas; OCR e validações exclusivas '
                    'de compra não serão executados.',
                )
            self.stop.clear()
            self.thread = threading.Thread(target=self.loop, daemon=True)
            self.thread.start()
            return True
        finally:
            self._starting = False

    def request_stop(self):
        self.stop.set()
        self.emit('status','Parando...')

    def _save_diagnostics_async(self, samples):
        if not samples:
            return

        def save_samples():
            saved = []
            for shot, result, reason, error, capture_bbox, _region in samples[:2]:
                try:
                    saved.append(save_candies_diagnostic(
                        shot, self.cfg, result, reason=reason, error=error,
                        client_bbox=capture_bbox,
                    ))
                except Exception as exc:
                    self.emit('log', f'Não consegui salvar o diagnóstico OCR: {exc}')
            if saved:
                self.emit('log', f'Diagnóstico visual do OCR salvo em {DEBUG}.')

        threading.Thread(target=save_samples, daemon=True).start()

    def run_macro(self, key, inspect=False):
        """Executa eventos em ordem com tempos absolutos.

        O OCR usa outra thread: uma chamada lenta ao Tesseract NUNCA adia
        os eventos de teclado/mouse do arquivo .rec.
        """
        if key == 'compra':
            if not (self.cfg or {}).get('auto_purchases', True):
                return False
            if self._rare_chest_limit_enabled() and self.rare_chests >= RARE_CHEST_LIMIT:
                self._notify_rare_chest_limit()
                return False
        rec = macro_recording(self.cfg[key])
        events = read_rec(rec)
        label = {'coleta':'Coletando', 'analise':'Analisando Candies', 'compra':'Comprando'}[key]
        self.emit('status',label)
        self.emit('log',f'Iniciando {rec.name} ({events[-1].offset:.1f}s, {len(events)} eventos).')
        # Conferir foco antes de cada etapa (a interface pode aparecer, ou o usuário
        # pode ter clicado em outro aplicativo durante a análise).
        activate_roblox_window()
        player = WindowsInput()
        client_bbox = roblox_client_bbox()
        source_bbox = carregar_geometria(rec)
        if source_bbox:
            player.position_transform = lambda x, y: converter_ponto(x, y, source_bbox, client_bbox)
            if key == 'compra' and source_bbox != client_bbox:
                self.emit('log', 'COMPRA: coordenadas de mouse ajustadas à posição/tamanho atual da janela Roblox.')
        elif key == 'compra' and any(ev.message == WM_LBUTTONDOWN for ev in events):
            self.emit('log', 'COMPRA: gravação antiga sem metadados de geometria; usando posições originais. '
                             'Se os cliques falharem, regrave a compra nesta versão.')
        cliques_enviados = 0
        start = time.monotonic()
        end_at = start + events[-1].offset
        hard_deadline = end_at + 90
        readings = []  # (instante da captura, valor) desta análise APENAS
        interpretacoes_brutas = []  # TODAS as variantes OCR, inclusive contraditórias
        diagnostic_samples = []
        sampled_reasons = set()
        failure_counts = Counter()
        audit_by_value = {}
        ocr_attempts = [0]
        ocr_finished = threading.Event()
        ocr_thread = None

        def inspect_while_equipped():
            # A gravação 2 equipa o item logo no começo e desequipa no fim.
            # Capturar até ~1 segundo ANTES do desequipamento, reduzindo
            # imagens sem contador e OCR que sobreviva ao fim da gravação.
            next_read = start + 0.9
            reading_deadline = max(start, end_at - 1.3)
            try:
                while not ocr_finished.is_set() and not self.stop.is_set():
                    now = time.monotonic()
                    if now >= reading_deadline:
                        break
                    delay = next_read - now
                    if delay > 0:
                        ocr_finished.wait(min(delay, 0.1))
                        continue
                    ocr_attempts[0] += 1
                    shot = None
                    capture_bbox = None
                    result = None
                    candy_region = None
                    try:
                        try:
                            candy_region = region_from(self.cfg, 'candies')
                        except ValueError as exc:
                            result = CandiesOCRResult(
                                None, (), (), 'invalid_region', None, None, str(exc)
                            )
                        else:
                            shot, capture_bbox, result = capture_candies_attempt(
                                candy_region
                            )
                        report_ocr_failures(
                            result, f'análise automática, tentativa {ocr_attempts[0]}',
                            self.emit,
                        )
                        # Falhas e amostras inconclusivas não contam como leituras.
                        accumulate_analysis_result(
                            result, time.monotonic(), readings, interpretacoes_brutas
                        )
                        value = result.value
                        if value is not None:
                            if value not in audit_by_value and len(audit_by_value) < 5:
                                audit_by_value[value] = (
                                    shot.copy(), result, candy_region, capture_bbox
                                )
                            self.emit('candies', str(value))
                            if len(readings) == 1:
                                self.emit('log', f'Candies detectados durante a análise: {value}. Aguardando o fim da gravação.')
                        else:
                            failure_counts[result.reason] += 1
                            if result.reason not in sampled_reasons and len(diagnostic_samples) < 2:
                                sampled_reasons.add(result.reason)
                                diagnostic_samples.append((
                                    shot, result, result.reason, result.error,
                                    capture_bbox, candy_region
                                ))
                    except Exception as exc:
                        reason = 'capture_failed' if shot is None else 'ocr_error'
                        result = technical_ocr_result(
                            reason, 'candies_analysis', exc, shot=shot,
                            attempt=ocr_attempts[0],
                        )
                        report_ocr_failures(
                            result, f'análise automática, tentativa {ocr_attempts[0]}',
                            self.emit,
                        )
                        failure_counts[reason] += 1
                        if reason not in sampled_reasons and len(diagnostic_samples) < 2:
                            sampled_reasons.add(reason)
                            diagnostic_samples.append((
                                shot, result, reason, str(exc), capture_bbox,
                                candy_region
                            ))
                    next_read = time.monotonic() + max(0.7, float(self.cfg['intervalo_ocr']))
            finally:
                ocr_finished.set()

        if inspect:
            ocr_thread = threading.Thread(target=inspect_while_equipped, daemon=True)
            ocr_thread.start()
        try:
            # Mesmo em gravações de vários minutos, não existe corte por
            # duração fixa: sempre reproduzimos ATÉ o último evento.
            for i, event in enumerate(events):
                deadline = start + event.offset
                while not self.stop.is_set():
                    now = time.monotonic()
                    if now > hard_deadline:
                        raise TimeoutError(f'Gravação {key} excedeu a duração registrada com tolerância.')
                    if now >= deadline:
                        break
                    self.stop.wait(min(0.02,deadline-now))
                if self.stop.is_set():
                    return None
                if is_record_stop_key(events,i):
                    # Último F8 é o botão para terminar a gravação TinyTask,
                    # não uma ação a enviar ao jogo.
                    continue
                if key == 'compra' and event.message in (
                    WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                    # Bloquear cliques em outras janelas e mudanças de geometria
                    # durante a compra, evitando alvos deslocados.
                    if not roblox_em_primeiro_plano():
                        raise RuntimeError('Roblox perdeu o foco durante a compra. '
                                           'Interrompido antes de clicar em outra janela.')
                    if roblox_client_bbox() != client_bbox:
                        raise RuntimeError('A janela Roblox mudou de posição/tamanho durante a compra. '
                                           'Interrompido para não clicar em lugar incorreto.')
                    x = ctypes.c_int32(event.data1).value
                    y = ctypes.c_int32(event.data2).value
                    if player.position_transform:
                        x,y = player.position_transform(x,y)
                    if not (client_bbox[0] <= x < client_bbox[2] and
                            client_bbox[1] <= y < client_bbox[3]):
                        raise RuntimeError('Um clique da compra cairia fora do Roblox '
                                           f'({x}, {y}). Regrave a compra nesta versão.')
                player.event(event)
                if key == 'compra' and event.message in (
                    WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                    cliques_enviados += 1
            elapsed = time.monotonic()-start
            if key == 'compra':
                self.emit('log', f'Compra: {cliques_enviados} cliques enviados ao Windows '
                         '(o recebimento pelo jogo não pode ser confirmado automaticamente).')
            self.emit('log', f'{label}: concluído em {elapsed:.1f}s (gravação inteira).')
        finally:
            # Liberar quaisquer teclas/mouse antes de começar outra gravação.
            # Parar a automação com F12 funciona inclusive durante o OCR.
            player.release_all()
            ocr_finished.set()
            if ocr_thread:
                ocr_thread.join(timeout=7.0)

        if not inspect:
            return True
        if ocr_thread and ocr_thread.is_alive():
            self.emit('log','OCR não terminou a tempo: compra bloqueada.')
            return None
        veredito = avaliar_leituras(readings, time.monotonic(), meta=int(self.cfg['meta']),
                                     interpretacoes_brutas=interpretacoes_brutas)
        self.emit('log', f'Análise completa: {ocr_attempts[0]} tentativas OCR; '
                         f'{veredito.total} leituras válidas; {veredito.motivo}')
        for reason, count in failure_counts.items():
            label = OCR_REASON_LABELS.get(reason, reason)
            self.emit('log', f'OCR Candies: {label} ({count} tentativa(s)).')

        if not veredito.confiavel_para_compra and (
                len(veredito.distintos) > 1 or 'contradizem' in veredito.motivo):
            self.emit('log', f'OCR Candies: {OCR_REASON_LABELS["divergent"]}. '
                             f'{veredito.motivo}')
        selected_diagnostics = automatic_diagnostic_samples(
            veredito, audit_by_value, diagnostic_samples
        )
        self._save_diagnostics_async(selected_diagnostics)
        if len(veredito.distintos) > 1:
            self.emit('log', f'Leituras contraditórias bloqueadas; amostras salvas em {DEBUG}.')
        return veredito

    def clock(self):
        """Confirmacao temporal em capturas distintas.

        Um frame com OCR ilegivel nao mata o ciclo: compras continuam
        proibidas ate que pelo menos duas leituras concordem no tempo.
        """
        samples = []
        snapshots = []
        for _ in range(3):
            if self.stop.is_set():
                return None
            try:
                shot = screenshot()
                snapshots.append(shot)
                result = read_clock(shot, region_from(self.cfg, 'clock'))
                if result is not None:
                    samples.append((time.monotonic(), result))
                    if len(samples) >= 2:
                        first_time, first_val = samples[-2]
                        current_time, current_val = samples[-1]
                        elapsed = current_time - first_time
                        delta = current_val - first_val
                        # Um relogio de servidor anda aprox. um segundo por segundo.
                        # Tolera pequenas variacoes no momento de captura e OCR.
                        if -1 <= delta <= elapsed + 3:
                            return current_val
            except Exception as exc:
                self.emit('log', f'Leitura do relogio indisponivel: {exc}')
            if self.stop.wait(0.4):
                return None
        if snapshots:
            save_clock_diagnostic(snapshots[-1], self.cfg)
            self.emit('log', f'Relogio nao confirmado; imagem salva em {DEBUG}.')
        return None

    def loop(self):
        try:
            self.emit('log','Automação iniciada. Acompanhe o log e teste com segurança.')
            if (self.cfg.get('auto_purchases', True)
                    and self._rare_chest_limit_enabled()):
                self._notify_rare_chest_limit()
            while not self.stop.is_set():
                self.emit('candies_reset', '— / 250 (aguardando nova análise)')
                if not self.run_macro('coleta'):
                    break
                if self.stop.is_set():
                    break
                veredito = self.run_macro(
                    'analise',
                    inspect=self.cfg.get('auto_purchases', True),
                )
                if self.stop.is_set():
                    break
                if not self.cfg.get('auto_purchases', True):
                    continue
                if (self._rare_chest_limit_enabled()
                        and self.rare_chests >= RARE_CHEST_LIMIT):
                    self._notify_rare_chest_limit()
                    continue
                if veredito is None:
                    self.emit('log', 'Análise não concluída: compra bloqueada; repetindo coleta.')
                    continue
                if veredito.valor is None:
                    self.emit('candies_inconclusivos', '— / 250 (leitura divergente/inconclusiva)')
                    self.emit('log', 'Candies não confirmados: ' + veredito.motivo +
                             ' Voltando à coleta SEM COMPRAR.')
                    continue
                candies = veredito.valor
                self.emit('candies_confirmed', f'{candies} / {int(self.cfg["meta"])} (confirmado)')
                self.emit('log', f'Candies reconhecidos nesta análise: {candies}')
                if candies < int(self.cfg['meta']):
                    self.emit('log', 'Abaixo da meta: repetir coleta, sem comprar.')
                    continue
                # BLOQUEIO INDEPENDENTE do relógio: a compra só pode ocorrer
                # com amostras recentes e 100% concordantes da análise atual.
                if not veredito.confiavel_para_compra:
                    self.emit('log', 'Compra bloqueada pela verificação rigorosa dos Candies: '
                             + veredito.motivo)
                    continue
                if self.cfg.get('boss_control_enabled', True):
                    # O horário do servidor NÃO é mais lido por OCR.
                    # O contador manual avança mesmo enquanto os macros executam.
                    safety = (int(self.cfg['duracao_compra_max_segundos'])
                              + int(self.cfg['margem_compra_segundos']))
                    autorizado, motivo, status = self.relogio.pode_comprar(
                        candies, meta=int(self.cfg['meta']), margem_segundos=safety)
                    if status.horario:
                        self.emit('clock', status.horario + ' (manual)')
                    self.emit('boss', {'PRESENTE':'Presente', 'AUSENTE':'Ausente',
                                       'DESCONHECIDO':'Desconhecido'}[status.estado])
                    if status.estado == 'DESCONHECIDO':
                        self.emit('log','Relógio manual não sincronizado: compra bloqueada. '
                                        'Pare com F12, sincronize o horário e reinicie; continuando a coleta.')
                        continue
                    self.emit('log',f'Relógio manual: {status.horario} (sem OCR). '
                                     f'Boss {status.estado.lower()}; próximo spawn em '
                                     f'{status.ate_proximo_spawn:.0f}s.')
                    if not autorizado:
                        self.emit('log',f'Compra adiada: {motivo}. Voltando à coleta.')
                        continue
                    # Segunda conferência instantânea e sem OCR, no instante da compra.
                    autorizado, motivo, status = self.relogio.pode_comprar(
                        candies, meta=int(self.cfg['meta']), margem_segundos=safety)
                    if not autorizado:
                        self.emit('log',f'Compra não iniciada: {motivo}.')
                        continue
                if (self._rare_chest_limit_enabled()
                        and self.rare_chests >= RARE_CHEST_LIMIT):
                    self._notify_rare_chest_limit()
                    continue
                if not self.run_purchase():
                    if self.stop.is_set():
                        break
                    continue
                self.emit('candies_reset', '— / 250 (precisa de nova análise após compra)')
                self.emit('log', 'Gravação de compra reproduzida. A compra NO JOGO não foi confirmada: '
                                 'confira os itens e os cliques na primeira execução. '
                                 'Contador anterior invalidado; próxima análise lerá novamente.')
        except Exception as e:
            self.emit('error',str(e))
        finally:
            self.emit('status','Parado')
            self.emit('stopped',None)

class ClockTimeInput(ttk.Frame):
   """Three editable clock segments with fixed separators and bounded input."""

   def __init__(self, master, variable):
       super().__init__(master)
       self.variable = variable
       self._units = ['00', '00', '00']
       self._updating = False
       self._all_units_selected = False
       self._typed_digit_count = [0, 0, 0]
       self._unit_vars = []
       self.entries = []

       for index in range(3):
           if index:
               ttk.Label(self, text=':', font=('Consolas', 11)).pack(
                   side='left'
               )
           unit_var = tk.StringVar(master=self, value=self._units[index])
           self._unit_vars.append(unit_var)
           entry = ttk.Entry(
               self, textvariable=unit_var, width=3, justify='center',
               font=('Consolas', 11), validate='key',
           )
           entry.pack(side='left')
           entry.configure(validatecommand=(
               entry.register(lambda proposed, unit=index:
                              self._validate_unit(unit, proposed)),
               '%P',
           ))
           entry.bind(
               '<FocusIn>',
               lambda _event, unit=index: self._select_unit(unit),
           )
           entry.bind('<Control-a>', self._select_all_units)
           entry.bind('<Control-A>', self._select_all_units)
           entry.bind(
               '<KeyPress>',
               lambda event, unit=index: self._on_keypress(unit, event),
           )
           entry.bind('<<Paste>>', self._paste)
           entry.bind('<Control-v>', self._paste)
           entry.bind('<Control-V>', self._paste)
           unit_var.trace_add(
               'write',
               lambda *_args, unit=index: self._unit_changed(unit),
           )
           self.entries.append(entry)

       self.variable.trace_add('write', self._external_value_changed)
       try:
           self.set_time(validate_clock_input(self.variable.get()))
       except ValueError:
           self._publish_value()

   @staticmethod
   def _validate_unit(index, proposed):
       if (len(proposed) > 2 or not proposed.isascii()
               or (proposed and not proposed.isdigit())):
           return False
       return not (
           index > 0 and len(proposed) == 2 and int(proposed) >= 60
       )

   def _select_unit(self, index):
       was_all_selected = self._all_units_selected
       self._all_units_selected = False
       self._typed_digit_count[index] = 0
       if was_all_selected:
           for other_index, entry in enumerate(self.entries):
               if other_index != index:
                   entry.selection_clear()
       entry = self.entries[index]

       def select():
           try:
               if entry.winfo_exists() and self.focus_get() == entry:
                   entry.selection_range(0, 'end')
           except tk.TclError:
               pass

       self.after_idle(select)

   def _select_all_units(self, _event=None):
       self._all_units_selected = True
       for entry in self.entries:
           entry.selection_range(0, 'end')
       return 'break'

   def _on_keypress(self, index, event):
       if (self._all_units_selected
               and event.keysym not in ('BackSpace', 'Delete')):
           self._all_units_selected = False
           for other_index, entry in enumerate(self.entries):
               if other_index != index:
                   entry.selection_clear()
       if event.keysym == 'BackSpace':
           self._delete_at_cursor(index, backward=True)
           return 'break'
       if event.keysym == 'Delete':
           self._delete_at_cursor(index, backward=False)
           return 'break'
       if (event.keysym == 'Left' and index > 0
               and event.widget.index('insert') <= 0):
           self.entries[index - 1].focus_set()
           self.entries[index - 1].icursor('end')
           return 'break'
       if (event.keysym == 'Right' and index < 2
               and event.widget.index('insert') >= len(
                   self._unit_vars[index].get()
               )):
           self.entries[index + 1].focus_set()
           self.entries[index + 1].icursor(0)
           return 'break'
       if event.keysym in ('Left', 'Right', 'Home', 'End'):
           self._typed_digit_count[index] = 2
           return None
       if event.char == ':' and index < 2:
           self.entries[index + 1].focus_set()
           return 'break'
       if event.char and event.char.isascii() and event.char.isdigit():
           self._insert_digit(index, event.char)
           return 'break'
       if event.char and event.char.isprintable():
           self.bell()
           return 'break'
       return None

   def _delete_at_cursor(self, index, backward):
       entry = self.entries[index]
       if self._all_units_selected:
           self.set_time('00:00:00')
           self.entries[0].focus_set()
           self.entries[0].icursor(0)
           return

       current = self._unit_vars[index].get()
       try:
           start = entry.index('sel.first')
           end = entry.index('sel.last')
       except tk.TclError:
           start = end = entry.index('insert')
       if start != end:
           candidate = current[:start] + current[end:]
           cursor = start
       elif backward and start > 0:
           candidate = current[:start - 1] + current[start:]
           cursor = start - 1
       elif not backward and start < len(current):
           candidate = current[:start] + current[start + 1:]
           cursor = start
       else:
           adjacent = index - 1 if backward else index + 1
           if 0 <= adjacent < len(self.entries):
               self.entries[adjacent].focus_set()
               self.entries[adjacent].icursor(
                   'end' if backward else 0
               )
           return

       current = current.ljust(2, '0')[:2]
       if start != end:
           candidate = current[:start] + ('0' * (end - start)) + current[end:]
       else:
           digit_index = start - 1 if backward else start
           candidate = (
               current[:digit_index] + '0' + current[digit_index + 1:]
           )
       self._unit_vars[index].set(candidate)
       self._all_units_selected = False
       self._typed_digit_count[index] = 0
       entry.selection_clear()
       entry.icursor(cursor)

   @staticmethod
   def parse_paste(pasted):
       pasted = pasted.strip()
       if re.fullmatch(r'[0-9]{2}:[0-9]{2}:[0-9]{2}', pasted):
           value = pasted
       elif re.fullmatch(r'[0-9]{6}', pasted):
           value = f'{pasted[:2]}:{pasted[2:4]}:{pasted[4:]}'
       else:
           raise ValueError('Cole um horário no formato HH:MM:SS ou HHMMSS.')
       return validate_clock_input(value)

   def _insert_digit(self, index, digit):
       entry = self.entries[index]
       current = self._unit_vars[index].get()
       try:
           selection_start = entry.index('sel.first')
           selection_end = entry.index('sel.last')
       except tk.TclError:
           selection_start = selection_end = entry.index('insert')

       typed_count = self._typed_digit_count[index]
       has_selection = selection_start != selection_end
       full_selection = has_selection and selection_start == 0 and selection_end == 2
       if typed_count == 0 and not (
               has_selection and not full_selection):
           candidate = digit + '0'
           next_typed_count = 1
           cursor = 1
       elif (typed_count == 1 and not has_selection
             and selection_start == 1):
           candidate = current[0] + digit
           next_typed_count = 2
           cursor = 2
       elif has_selection:
           candidate = (
               current[:selection_start] + digit + current[selection_end:]
           )
           candidate = candidate.ljust(2, '0')[:2]
           next_typed_count = 2
           cursor = min(selection_start + 1, 2)
       elif index == 2 and selection_start == 2:
           candidate = current[1] + digit
           next_typed_count = 2
           cursor = 2
       elif selection_start < len(current):
           candidate = (
               current[:selection_start] + digit
               + current[selection_start + 1:]
           )
           candidate = candidate.ljust(2, '0')[:2]
           next_typed_count = 2
           cursor = min(selection_start + 1, 2)
       else:
           candidate = current[:1] + digit
           next_typed_count = 2
           cursor = 2

       if not self._validate_unit(index, candidate):
           self.bell()
           return
       self._unit_vars[index].set(candidate)
       self._typed_digit_count[index] = next_typed_count
       entry.selection_clear()
       entry.icursor(cursor)
       if next_typed_count == 2 and index < 2:
           self.entries[index + 1].focus_set()

   def _paste(self, _event=None):
       try:
           pasted = self.clipboard_get().strip()
       except tk.TclError:
           self.bell()
           return 'break'
       try:
           self.set_time(self.parse_paste(pasted))
       except ValueError:
           self.bell()
           return 'break'
       self.entries[2].focus_set()
       self._typed_digit_count[2] = 2
       self.entries[2].icursor('end')
       return 'break'

   def _unit_changed(self, index):
       if self._updating:
           return
       self._units[index] = self._unit_vars[index].get()
       self._publish_value()

   def _publish_value(self):
       self._updating = True
       try:
           self.variable.set(':'.join(self._units))
       finally:
           self._updating = False

   def _external_value_changed(self, *_args):
       if self._updating:
           return
       try:
           value = validate_clock_input(self.variable.get())
       except ValueError:
           return
       if self.focus_get() in self.entries:
           return
       self.set_time(value)

   def set_time(self, value):
       value = validate_clock_input(value)
       self._units = value.split(':')
       self._all_units_selected = False
       self._typed_digit_count = [0, 0, 0]
       self._updating = True
       try:
           for variable, unit in zip(self._unit_vars, self._units):
               variable.set(unit)
           for entry in self.entries:
               entry.selection_clear()
           self.variable.set(value)
       finally:
           self._updating = False


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('GPO_AutoFarm_v11')
        self.root.geometry('870x570')
        self.root.minsize(790,500)
        loaded_data = load()
        self.data = normalize_resource_settings(loaded_data)
        if self.data != loaded_data:
            atomic_write_json(CFG, self.data)
        self.events = queue.Queue()
        self.relogio = RelogioManual()
        self.controller = Controller(
            lambda k,v:self.events.put((k,v)),
            self.relogio,
            self.data['rare_chests'],
        )
        self.fields = {}
        self.hotkey = tk.StringVar(value=self.data['hotkey'].upper())
        self.record_hotkey = tk.StringVar(value=self.data.get('record_hotkey','f8').upper())
        self.status = tk.StringVar(value='Parado')
        self.candies = tk.StringVar(value='—')
        self.rare_chests = tk.StringVar(
            value=rare_chests_display(self.data['rare_chests'])
        )
        self.rare_chests_input = tk.StringVar(
            value=str(self.data['rare_chests'])
        )
        self.boss = tk.StringVar(value='—')
        self.clock_var = tk.StringVar(value='Não sincronizado')
        self.clock_input = tk.StringVar(value='00:00:00')
        self.resource_vars = {
            key: tk.BooleanVar(value=self.data[key])
            for key in RESOURCE_TOGGLE_KEYS
        }
        self.resource_switches = {}
        self._resource_controls_disabled = False
        self._hotkey_name = self.data['hotkey'].strip().lower()
        self._record_hotkey_name = self.data.get('record_hotkey','f8').strip().lower()
        self._hotkey_pressed = False
        self._start_pending = False
        self._hotkey_capture_lock = threading.Lock()
        self._hotkey_capture_target = None
        self._hotkey_capture_pending = False
        self._hotkey_capture_suppressed = set()
        self._hotkey_capture_dialog = None
        self._hotkey_capture_status = None
        self._hidden_during_run = False
        self._pending_error = None
        self._ocr_test_running = False
        self._updating_rare_chests_ui = False
        self.recorder = GravadorRec()
        self.recorder.set_record_hotkey(self._record_hotkey_name)
        self.record_stage = None  # None | coleta | analise | compra
        self.record_state = 'idle'  # idle | armed | recording
        self.recording_client_bbox = None
        self._record_key_pressed = False
        self.construct()
        self.listener = keyboard.Listener(
            on_press=self.on_key, on_release=self.on_release,
            win32_event_filter=self.recorder.keyboard_filter)
        self.listener.start()
        self.root.after(100, self.poll)
        self.root.after(0, self._schedule_diagnostic_cleanup)
        self.root.protocol('WM_DELETE_WINDOW', self.close)

    def _schedule_diagnostic_cleanup(self):
        def cleanup():
            try:
                prune_candies_diagnostics()
            except OSError as exc:
                self.events.put((
                    'log',
                    f'Não consegui limpar diagnósticos antigos: '
                    f'{type(exc).__name__}: {exc}',
                ))

        threading.Thread(target=cleanup, daemon=True).start()

    def construct(self):
        """Create compact tabs for automation, monitoring, settings and logs."""
        pad = ttk.Frame(self.root, padding=14)
        pad.pack(fill='both', expand=True)
        ttk.Label(pad, text='GPO_AutoFarm_v11',
                  font=('Segoe UI', 17, 'bold')).pack(anchor='w')
        ttk.Label(pad, text='TinyTask .rec + OCR Candies • controle de automação').pack(
            anchor='w', pady=(0, 10))

        tabs = ttk.Notebook(pad)
        tabs.pack(fill='both', expand=True)
        automation_tab = ttk.Frame(tabs, padding=12)
        monitor_tab = ttk.Frame(tabs, padding=12)
        configs = ttk.Frame(tabs, padding=16)
        logs = ttk.Frame(tabs, padding=12)
        tabs.add(automation_tab, text='  Automação  ')
        tabs.add(monitor_tab, text='  Monitoramento  ')
        tabs.add(configs, text='  Configurações  ')
        tabs.add(logs, text='  Logs  ')
        self.tabs = tabs
        self.automation_tab = automation_tab
        self.automation_canvas = None

        recordings = ttk.LabelFrame(automation_tab, text='Gravações', padding=9)
        recordings.pack(fill='x')
        self.recording_rows = {}
        for key, label in (
                ('coleta', '1 · Coleta'),
                ('analise', '2 · Análise (leitura durante execução)'),
                ('compra', '3 · Compra')):
            line = ttk.Frame(recordings)
            line.pack(fill='x', pady=(3, 6))
            self.recording_rows[key] = line
            ttk.Label(line, text=label, width=32).pack(side='left', padx=(0, 6))
            self.fields[key] = tk.StringVar(value=self.data[key])
            ttk.Entry(line, textvariable=self.fields[key], state='readonly').pack(
                side='left', fill='x', expand=True)
            ttk.Button(line, text='Selecionar',
                       command=lambda k=key: self.choose(k)).pack(
                side='left', padx=(7, 0))
            ttk.Button(line, text='● Gravar agora',
                       command=lambda k=key: self.arm_recording(k)).pack(
                side='left', padx=(7, 0))
            ttk.Button(line, text='⬇', width=3,
                       command=lambda k=key: self.export_recording(k)).pack(
                side='left', padx=(5, 0))
        self.restore_automation_button = ttk.Button(
            recordings, text='↺ Restaurar padrão',
            command=self.restore_automation_defaults,
        )
        self.restore_automation_button.pack(anchor='e', pady=(0, 2))

        stats = ttk.LabelFrame(monitor_tab, text='Estado e métricas', padding=9)
        stats.pack(fill='x')
        for label, variable in (('Estado', self.status), ('Candies', self.candies)):
            line = ttk.Frame(stats)
            line.pack(fill='x', pady=1)
            ttk.Label(line, text=label).pack(side='left')
            ttk.Label(line, textvariable=variable,
                      font=('Segoe UI', 10, 'bold'),
                      wraplength=620, justify='right').pack(side='right')

        self.rare_chests_group = ttk.Frame(stats)
        self.rare_chests_group.pack(fill='x', pady=(4, 1))
        rare_line = ttk.Frame(self.rare_chests_group)
        rare_line.pack(fill='x', pady=1)
        ttk.Label(rare_line, text='Rare Chests:').pack(side='left')
        ttk.Label(rare_line, textvariable=self.rare_chests,
                  font=('Segoe UI', 10, 'bold'), wraplength=620,
                  justify='right').pack(side='right')
        rare_chests_line = ttk.Frame(self.rare_chests_group)
        rare_chests_line.pack(fill='x', pady=(4, 1))
        ttk.Label(
            rare_chests_line,
            text='Quantidade manual de RC (Rare Chest) — edite com a automação parada:',
        ).pack(side='left')
        validate_rare_chests = self.root.register(
            self._validate_rare_chests_input
        )
        self.rare_chests_spinbox = ttk.Spinbox(
            rare_chests_line,
            from_=0,
            to=RARE_CHEST_LIMIT,
            width=5,
            textvariable=self.rare_chests_input,
            state='readonly',
            validate='key',
            validatecommand=(validate_rare_chests, '%P'),
            command=self._commit_rare_chests,
        )
        self.rare_chests_spinbox.pack(side='right')
        self.rare_chests_input.trace_add(
            'write', self._on_rare_chests_input_change
        )
        self.rare_chests_spinbox.bind(
            '<Return>', lambda _event: self._commit_rare_chests()
        )
        self.rare_chests_spinbox.bind(
            '<FocusOut>', lambda _event: self._commit_rare_chests()
        )

        self.boss_group = ttk.LabelFrame(stats, text='Boss', padding=8)
        self.boss_group.pack(fill='x', pady=(4, 1))
        for label, variable in (
                ('Tempo do servidor', self.clock_var),
                ('Boss', self.boss)):
            line = ttk.Frame(self.boss_group)
            line.pack(fill='x', pady=1)
            ttk.Label(line, text=label).pack(side='left')
            ttk.Label(line, textvariable=variable,
                      font=('Segoe UI', 10, 'bold')).pack(side='right')

        manual = ttk.LabelFrame(
            automation_tab,
            text='Relógio do servidor — sincronização manual',
            padding=8,
        )
        self.clock_warning = ttk.Label(
            manual,
            text='⚠ ESSENCIAL: sincronize o tempo do servidor antes de iniciar. '
                 'Sem isso, a compra será bloqueada.',
            foreground='#a34b00', wraplength=790,
            font=('Segoe UI', 9, 'bold'),
        )
        self.clock_warning.pack(anchor='w', pady=(0, 8))
        mline = ttk.Frame(manual)
        mline.pack(fill='x')
        self.clock_input_line = mline
        ttk.Label(mline, text='HH:MM:SS').pack(side='left')
        self.clock_time_input = ClockTimeInput(mline, self.clock_input)
        self.clock_time_input.pack(side='left', padx=8)
        ttk.Button(mline, text='Sincronizar agora',
                   command=self.sync_clock).pack(side='left')
        ttk.Button(mline, text='Invalidar',
                   command=self.invalidate_clock).pack(side='left', padx=(8, 0))
        ttk.Label(
            manual,
            text='Leia o relógio no Roblox e sincronize imediatamente. '
                 'Ressincronize ao mudar de servidor.',
            wraplength=790,
        ).pack(anchor='w', pady=(6, 0))
        self.clock_controls = manual
        manual.pack(fill='x', pady=(4, 0))

        actions = ttk.LabelFrame(monitor_tab, text='Ferramentas', padding=8)
        actions.pack(fill='x', pady=(8, 0))
        self.ocr_test_button = ttk.Button(
            actions, text='Testar OCR', command=self.test_ocr
        )
        self.ocr_test_button.grid(row=0, column=0, sticky='ew', padx=3, pady=3)
        ttk.Button(actions, text='Calibrar Candies',
                   command=lambda: self.calibrate('candies')).grid(
            row=0, column=1, sticky='ew', padx=3, pady=3)
        ttk.Button(actions, text='Verificar gravações',
                   command=self.inspect_macros).grid(
            row=1, column=0, sticky='ew', padx=3, pady=3)
        ttk.Button(actions, text='Abrir diagnóstico',
                   command=self.open_diagnostics).grid(
            row=1, column=1, sticky='ew', padx=3, pady=3)
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)
        self.monitor_actions = actions

        keys = ttk.LabelFrame(configs, text='Atalhos de teclado', padding=16)
        resources = ttk.LabelFrame(configs, text='Recursos', padding=10)
        resources.pack(fill='x', pady=(0, 10))
        resource_labels = {
            'auto_purchases': 'Compras automáticas',
            'rare_chest_limit_enabled': 'Limite de Rare Chests',
            'boss_control_enabled': 'Controle do Boss',
        }
        self.resource_rows = {}
        for key, label_text in resource_labels.items():
            row = ttk.Frame(resources)
            row.pack(fill='x', pady=3)
            ttk.Label(row, text=label_text).pack(side='left', anchor='w')
            switch = tk.Canvas(
                row, width=68, height=28, highlightthickness=0,
                takefocus=True, cursor='hand2',
            )
            switch.pack(side='right')
            switch.bind(
                '<Button-1>',
                lambda _event, resource=key: self._toggle_resource_switch(resource),
            )
            switch.bind(
                '<space>',
                lambda _event, resource=key: self._toggle_resource_switch(resource),
            )
            switch.bind(
                '<Return>',
                lambda _event, resource=key: self._toggle_resource_switch(resource),
            )
            self.resource_rows[key] = row
            self.resource_switches[key] = switch
        keys.pack(fill='x')
        row_play = ttk.Frame(keys)
        row_play.pack(fill='x', pady=(0, 12))
        ttk.Label(row_play, text='Iniciar / parar automação', width=26).pack(side='left')
        ttk.Label(
            row_play, textvariable=self.hotkey, width=8, anchor='center',
            font=('Segoe UI', 9, 'bold'),
        ).pack(side='left')
        self.hotkey_capture_buttons = {}
        self.hotkey_capture_buttons['hotkey'] = ttk.Button(
            row_play, text='Definir tecla',
            command=lambda: self.capture_hotkey('hotkey'),
        )
        self.hotkey_capture_buttons['hotkey'].pack(side='left', padx=(6, 0))
        ttk.Label(row_play, text='Padrão: F12').pack(side='left', padx=(8, 0))
        row_rec = ttk.Frame(keys)
        row_rec.pack(fill='x', pady=(0, 8))
        ttk.Label(row_rec, text='Começar / terminar gravação', width=26).pack(side='left')
        ttk.Label(
            row_rec, textvariable=self.record_hotkey, width=8, anchor='center',
            font=('Segoe UI', 9, 'bold'),
        ).pack(side='left')
        self.hotkey_capture_buttons['record_hotkey'] = ttk.Button(
            row_rec, text='Definir tecla',
            command=lambda: self.capture_hotkey('record_hotkey'),
        )
        self.hotkey_capture_buttons['record_hotkey'].pack(
            side='left', padx=(6, 0)
        )
        ttk.Label(row_rec, text='Padrão: F8').pack(side='left', padx=(8, 0))
        ttk.Label(
            keys,
            text='Defina teclas diferentes para cada atalho. F12 continua '
                 'reservado para cancelar uma gravação.',
            wraplength=700,
        ).pack(anchor='w', pady=(5, 10))
        key_actions = ttk.Frame(keys)
        key_actions.pack(anchor='w')
        ttk.Button(key_actions, text='Salvar configurações',
                   command=self.save).pack(side='left')
        ttk.Button(key_actions, text='↺ Restaurar padrão',
                   command=self.restore_key_defaults).pack(
            side='left', padx=(10, 0))

        log_frame = ttk.LabelFrame(logs, text='Log de execução', padding=8)
        log_frame.pack(fill='both', expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient='vertical')
        scrollbar.pack(side='right', fill='y')
        self.logbox = tk.Text(log_frame, height=12, state='disabled',
                              wrap='word', font=('Consolas', 9),
                              yscrollcommand=scrollbar.set)
        self.logbox.pack(side='left', fill='both', expand=True)
        scrollbar.configure(command=self.logbox.yview)
        self._refresh_resource_visibility()
        self._refresh_resource_controls(force=True)
        self._log_startup_information()

    def _log_startup_information(self):
        self.log('v11: interface organizada em Automação, Monitoramento, Configurações e Logs.')
        self.log('v10: antes de comprar, verificamos foco, área do Roblox e posicionamento do cursor.')
        self.log('v10: o ícone ⬇ ao lado de Gravar agora exporta uma cópia do .rec selecionado.')
        self.log('v9: COMPRA exige leituras recentes e 100% concordantes da análise atual.')
        self.log(f'Gravador integrado: {self._record_hotkey_name.upper()} grava; F12 cancela a gravação.')
        self.log('v7: OCR dos Candies em thread separada; relógio manual sem OCR.')
        self.log(f'{self._hotkey_name.upper()} restaura a interface após parar a automação.')
        self.log('Captura da área interna do Roblox (sem barra de título/tarefas).')
        self.log('Teste o OCR com o item equipado; sincronize o relógio antes de iniciar.')

    def _on_resource_toggle(self, key):
        requested = self.resource_vars[key].get()
        previous = self.data[key]
        if requested == previous:
            return
        if (self.controller.active() or self._start_pending
                or self.record_stage is not None):
            self.resource_vars[key].set(previous)
            messagebox.showwarning(
                'Operação em andamento',
                'Pare a automação ou a gravação antes de alterar os recursos.',
            )
            return
        if (key in ('rare_chest_limit_enabled', 'boss_control_enabled')
                and not self.resource_vars['auto_purchases'].get()):
            self.resource_vars[key].set(False)
            self._refresh_resource_switch(key)
            return

        confirmations = {
            'auto_purchases': (
                'Desativar Compras automáticas também desligará o Limite de '
                'Rare Chests e o Controle do Boss. Deseja continuar?'
            ),
            'rare_chest_limit_enabled': (
                'Desativar o Limite de Rare Chests mantém o contador salvo, '
                'mas ele não bloqueará compras. Continuar?'
            ),
            'boss_control_enabled': (
                'Desativar o Controle do Boss ignora o relógio e a janela do '
                'boss. Continuar?'
            ),
        }
        if not requested and not messagebox.askyesno(
                'Desativar recurso', confirmations[key]):
            self.resource_vars[key].set(previous)
            self._refresh_resource_switch(key)
            return

        updated = dict(self.data)
        updated[key] = requested
        if key == 'auto_purchases' and not requested:
            updated['rare_chest_limit_enabled'] = False
            updated['boss_control_enabled'] = False
        try:
            atomic_write_json(CFG, updated)
        except OSError as exc:
            self.resource_vars[key].set(previous)
            if key == 'auto_purchases':
                self.resource_vars['rare_chest_limit_enabled'].set(
                    self.data['rare_chest_limit_enabled']
                )
            self._refresh_resource_controls(force=True)
            messagebox.showerror(
                'Não foi possível salvar o recurso',
                f'A configuração não foi alterada: {exc}',
            )
            return

        boss_control_changed = (
            self.data.get('boss_control_enabled', True)
            != updated.get('boss_control_enabled', True)
        )
        self.data = updated
        for resource_key in RESOURCE_TOGGLE_KEYS:
            self.resource_vars[resource_key].set(updated[resource_key])
        if boss_control_changed:
            self.relogio.invalidar()
            self.clock_var.set('Não sincronizado')
            self.boss.set('Desconhecido')
        if self.controller.cfg is not None:
            self.controller.cfg.update({
                resource_key: updated[resource_key]
                for resource_key in RESOURCE_TOGGLE_KEYS
            })
        self._refresh_resource_visibility()
        self._refresh_resource_controls(force=True)
        self.log(
            f'{key}: {"ativado" if requested else "desativado"}. '
            + (
                'Limite de Rare Chests e Controle do Boss também desativados. '
                if key == 'auto_purchases' and not requested else ''
            )
            + 'Configuração salva.'
        )

    def _refresh_resource_visibility(self):
        if not hasattr(self, 'recording_rows'):
            return
        purchases = self.resource_vars['auto_purchases'].get()
        if purchases:
            if not self.recording_rows['compra'].winfo_manager():
                self.recording_rows['compra'].pack(
                    fill='x', pady=(3, 6), before=self.restore_automation_button
                )
        else:
            self.recording_rows['compra'].pack_forget()
        self.clock_warning.configure(
            text=(
                '⚠ ESSENCIAL: sincronize o tempo do servidor antes de iniciar. '
                'Sem isso, a compra será bloqueada.'
                if purchases else
                'Sincronize o relógio para acompanhar o tempo do servidor. '
                'Compras automáticas estão desativadas.'
            )
        )

        if (purchases
                and self.resource_vars['rare_chest_limit_enabled'].get()):
            if not self.rare_chests_group.winfo_manager():
                self.rare_chests_group.pack(fill='x', pady=(4, 1))
        else:
            self.rare_chests_group.pack_forget()

        if (purchases
                and self.resource_vars['boss_control_enabled'].get()):
            if not self.boss_group.winfo_manager():
                self.boss_group.pack(fill='x', pady=(4, 1))
            if not self.clock_controls.winfo_manager():
                self.clock_controls.pack(fill='x', pady=(9, 0))
        else:
            self.boss_group.pack_forget()
            self.clock_controls.pack_forget()

    def _refresh_resource_switch(self, key):
        switch = self.resource_switches.get(key)
        if switch is None:
            return
        switch.delete('all')
        enabled = self.resource_vars[key].get()
        interaction_enabled = (
            not self._resource_controls_disabled
            and (
                key == 'auto_purchases'
                or self.resource_vars['auto_purchases'].get()
            )
        )
        track_color = '#829888' if enabled else '#b8bdc2'
        if not interaction_enabled:
            track_color = '#d1d4d6'
        switch.create_rectangle(
            13, 3, 55, 25, fill=track_color, outline=track_color
        )
        switch.create_oval(
            2, 3, 24, 25, fill=track_color, outline=track_color
        )
        switch.create_oval(
            44, 3, 66, 25, fill=track_color, outline=track_color
        )
        if enabled:
            switch.create_text(
                23, 14, text='ON', fill='#ffffff',
                font=('Segoe UI', 7, 'bold'),
            )
            knob_x = 54
        else:
            switch.create_text(
                47, 14, text='OFF', fill='#50565a',
                font=('Segoe UI', 7, 'bold'),
            )
            knob_x = 13
        switch.create_oval(
            knob_x - 8, 6, knob_x + 8, 22,
            fill='#ffffff', outline='#ffffff',
        )
        switch.configure(
            cursor='hand2' if interaction_enabled else 'arrow',
            takefocus=interaction_enabled,
        )

    def _toggle_resource_switch(self, key):
        if self._resource_controls_disabled:
            return
        if (key == 'rare_chest_limit_enabled'
                and not self.resource_vars['auto_purchases'].get()):
            return
        if (key == 'boss_control_enabled'
                and not self.resource_vars['auto_purchases'].get()):
            return
        self.resource_vars[key].set(not self.resource_vars[key].get())
        self._on_resource_toggle(key)

    def refresh_resource_widgets(self):
        self._refresh_resource_visibility()
        self._refresh_resource_controls(force=True)
        self.root.update_idletasks()

    def _refresh_resource_controls(self, force=False):
        if not self.resource_switches:
            return
        disabled = (
            self.controller.active()
            or self._start_pending
            or self.record_stage is not None
        )
        changed = disabled != self._resource_controls_disabled
        self._resource_controls_disabled = disabled
        if force or changed:
            for key in self.resource_switches:
                self._refresh_resource_switch(key)

    def _on_automation_mousewheel(self, event):
        """Roda do mouse rola apenas o conteúdo da aba Automação."""
        try:
            if self.tabs.select() != str(self.automation_tab):
                return
            canvas = self.automation_canvas
            x, y = event.x_root, event.y_root
            if not (canvas.winfo_rootx() <= x < canvas.winfo_rootx() + canvas.winfo_width()
                    and canvas.winfo_rooty() <= y < canvas.winfo_rooty() + canvas.winfo_height()):
                return
            amount = -1 if event.delta > 0 else 1
            canvas.yview_scroll(amount * 2, 'units')
        except tk.TclError:
            pass

    def restore_automation_defaults(self):
        """Restaura caminhos e calibração, sem apagar gravações pessoais."""
        if self.controller.active() or self._start_pending or self.record_stage is not None:
            messagebox.showwarning('Operação em andamento',
                                   'Pare a automação ou a gravação antes de restaurar os padrões.')
            return
        if not messagebox.askyesno('Restaurar padrões da Automação',
                                   'Voltar às três gravações originais e à região padrão do OCR?\n\n'
                                   'O relógio será invalidado e precisará ser sincronizado novamente. '
                                   'Os seus arquivos .rec NÃO serão apagados.'):
            return
        for key in ('coleta', 'analise', 'compra'):
            self.fields[key].set(DEFAULT[key])
            self.data[key] = DEFAULT[key]
        for key in ('candies_roi', 'clock_roi', 'roi_coordinate_space'):
            value = DEFAULT[key]
            self.data[key] = value.copy() if isinstance(value, list) else value
        self.clock_input.set('00:00:00')
        if hasattr(self, 'clock_time_input'):
            self.clock_time_input.set_time('00:00:00')
        self.invalidate_clock()
        atomic_write_json(CFG, self.data)
        self.log('Automação restaurada: gravações e calibração padrão; relógio invalidado. '
                 'As gravações personalizadas foram preservadas.')

    def restore_key_defaults(self):
        """Restaura F12 (executar/parar) e F8 (gravar), mantendo demais ajustes."""
        if self.controller.active() or self._start_pending or self.record_stage is not None:
            messagebox.showwarning('Operação em andamento',
                                   'Pare a automação ou a gravação antes de restaurar os atalhos.')
            return
        self.hotkey.set(DEFAULT['hotkey'].upper())
        self.record_hotkey.set(DEFAULT['record_hotkey'].upper())
        if self.save():
            self.log('Teclas restauradas: F12 para iniciar/parar e F8 para gravar.')

    def sync_clock(self):
        if self.controller.active() or self._start_pending:
            messagebox.showwarning('Automação ativa','Pare a automação antes de sincronizar o relógio.')
            return
        try:
            horario = validate_clock_input(self.clock_input.get())
            horario = self.relogio.sincronizar(horario)
            status = self.relogio.status_boss()
        except ValueError as exc:
            messagebox.showerror('Horário inválido',str(exc))
            return
        self.clock_var.set(horario + ' (manual)')
        self.boss.set('Presente' if status.estado == 'PRESENTE' else 'Ausente')
        self.log(f'Relógio sincronizado: {horario}. Boss {status.estado.lower()}; '
                 f'próximo spawn em {status.ate_proximo_spawn:.0f}s.')

    def invalidate_clock(self):
        if self.controller.active() or self._start_pending:
            messagebox.showwarning('Automação ativa','Pare com F12 antes de invalidar o relógio.')
            return
        self.relogio.invalidar()
        self.clock_var.set('Não sincronizado')
        self.boss.set('Desconhecido')
        self.log('Relógio invalidado. Sincronize novamente antes de comprar.')

    def capture_hotkey(self, setting):
        if self.controller.active() or self._start_pending or self.record_stage is not None:
            messagebox.showwarning(
                'Operação em andamento',
                'Pare a automação ou a gravação antes de alterar os atalhos.',
            )
            return
        if setting not in ('hotkey', 'record_hotkey'):
            raise ValueError(f'Configuração de atalho inválida: {setting}')
        if self._hotkey_capture_dialog is not None:
            return

        dialog = tk.Toplevel(self.root)
        dialog.title('Definir tecla')
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.protocol('WM_DELETE_WINDOW', self._cancel_hotkey_capture)
        self._hotkey_capture_status = tk.StringVar(
            master=dialog, value='Pressione a tecla desejada... Esc cancela.'
        )
        ttk.Label(
            dialog, textvariable=self._hotkey_capture_status,
            padding=(18, 14), justify='center',
        ).pack()
        self._hotkey_capture_dialog = dialog
        dialog.grab_set()
        self._arm_hotkey_capture(setting)

    def _arm_hotkey_capture(self, setting):
        with self._hotkey_capture_lock:
            self._hotkey_capture_target = setting
            self._hotkey_capture_pending = False
        self._hotkey_capture_status.set(
            'Pressione a tecla desejada... Esc cancela.'
        )

    def _cancel_hotkey_capture(self):
        with self._hotkey_capture_lock:
            self._hotkey_capture_target = None
            self._hotkey_capture_pending = False
        dialog = self._hotkey_capture_dialog
        self._hotkey_capture_dialog = None
        self._hotkey_capture_status = None
        if dialog is not None:
            try:
                dialog.grab_release()
                dialog.destroy()
            except tk.TclError:
                pass

    def _handle_hotkey_capture(self, setting, name):
        if self._hotkey_capture_dialog is None:
            return
        with self._hotkey_capture_lock:
            self._hotkey_capture_pending = False
        other = 'record_hotkey' if setting == 'hotkey' else 'hotkey'
        other_value = getattr(self, other).get().strip().lower()
        if name == 'f12' and setting == 'record_hotkey':
            reason = 'F12 é reservada para cancelar gravações; escolha outra tecla.'
        elif name == other_value:
            reason = 'Essa tecla já está atribuída ao outro atalho.'
        else:
            variable = getattr(self, setting)
            previous = variable.get()
            variable.set(name.upper())
            if self.save():
                self._cancel_hotkey_capture()
                return
            variable.set(previous)
            reason = 'Não foi possível salvar o atalho. O valor anterior foi mantido.'
        self._arm_hotkey_capture(setting)
        self._hotkey_capture_status.set(
            f'{reason} Pressione outra tecla ou Esc para cancelar.'
        )

    @staticmethod
    def _key_fingerprint(key):
        name = getattr(key, 'name', None)
        if name:
            return name.lower()
        char = getattr(key, 'char', None)
        if isinstance(char, str):
            return char.lower()
        return str(key).lower()

    def inspect_macros(self):
        for k in ('coleta','analise','compra'):
            try:
                events=read_rec(macro_recording(self.fields[k].get()))
                clicks = sum(ev.message in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN)
                             for ev in events)
                caminho = macro_recording(self.fields[k].get())
                possui_geometria = carregar_geometria(caminho) is not None
                self.log(f'{k.upper()}: {events[-1].offset:.1f}s; {len(events)} eventos; '
                         f'{clicks} cliques gravados; ajuste de janela: '
                         f'{"sim" if possui_geometria else "não (arquivo antigo)"}.')
                if k == 'compra' and clicks == 0:
                    self.log('ATENÇÃO: a gravação de compra não tem cliques. Regrave a etapa.')
                if k=='coleta' and events[-1].offset < 15:
                    self.log('ATENÇÃO: coleta dura menos de 15s neste arquivo; confirme que é a gravação COMPLETA.')
            except Exception as e:
                self.log(f'Erro na gravação {k}: {e}')

    def calibrate(self, kind):
        if (self.controller.active() or self._start_pending or
                self.record_stage is not None or self._ocr_test_running):
            messagebox.showwarning(
                'Operação em andamento',
                'Pare a automação, encerre a gravação ou aguarde o teste OCR antes de calibrar.'
            )
            return
        self.root.withdraw()
        self.root.after(700, lambda: self._capture_calibration(kind))

    def _capture_calibration(self, kind):
        try:
            activate_roblox_window()
            shot = screenshot()
        except Exception as e:
            self.root.deiconify()
            messagebox.showerror('Captura indisponível', str(e))
            return
        self.root.deiconify()
        win=tk.Toplevel(self.root)
        win.title('Selecione com o mouse APENAS o contador' if kind=='candies' else 'Selecione com o mouse APENAS o relógio')
        win.transient(self.root)
        win.grab_set()
        sw,sh=shot.size
        scale=min(1100/sw, 660/sh, 1.0)
        width,height=round(sw*scale),round(sh*scale)
        view=shot.resize((width,height),Image.Resampling.LANCZOS)
        win._photo=ImageTk.PhotoImage(view)
        ttk.Label(win,text='Arraste um retângulo ao redor dos números. A janela foi ocultada durante a captura.').pack(padx=12,pady=8)
        canvas=tk.Canvas(win,width=width,height=height,cursor='cross',highlightthickness=0)
        canvas.pack(padx=10,pady=(0,8))
        canvas.create_image(0,0,anchor='nw',image=win._photo)
        selected={'start':None,'rect':None}
        def down(ev):
            selected['start']=(ev.x,ev.y)
            if selected['rect'] is not None:
                canvas.delete(selected['rect'])
            selected['rect']=canvas.create_rectangle(ev.x,ev.y,ev.x,ev.y,outline='#00d8ff',width=2)
        def move(ev):
            if selected['start'] and selected['rect']:
                x,y=selected['start']
                canvas.coords(selected['rect'], x,y,ev.x,ev.y)
        def up(ev):
            if not selected['start']: return
            x1,y1=selected['start'];x2,y2=ev.x,ev.y
            left,right=sorted([max(0,x1),min(width,x2)])
            top,bottom=sorted([max(0,y1),min(height,y2)])
            if right-left<12 or bottom-top<8:
                messagebox.showwarning('Seleção pequena','Selecione a área completa do número.',parent=win)
                return
            region=[round(left/width*1365), round(top/height*700),
                    round(right/width*1365),round(bottom/height*700)]
            if kind == 'candies':
                region = [
                    max(0, region[0] - 30),
                    max(0, region[1] - 16),
                    min(1365, region[2] + 30),
                    min(700, region[3] + 16),
                ]
            self.data[kind+'_roi']=region
            self.save()
            self.log(f'Região {kind} calibrada: {region}; '
                     'a captura inclui margem de segurança.')
            win.destroy()
        canvas.bind('<ButtonPress-1>',down)
        canvas.bind('<B1-Motion>',move)
        canvas.bind('<ButtonRelease-1>',up)
        ttk.Button(win,text='Cancelar',command=win.destroy).pack(pady=(0,8))

    def open_diagnostics(self):
        try:
            DEBUG.mkdir(parents=True, exist_ok=True)
            os.startfile(str(DEBUG))
        except (AttributeError, OSError) as exc:
            messagebox.showerror('Diagnóstico indisponível', str(exc))

    def _ocr_test_block_reason(self):
        return ocr_test_block_reason(
            self.controller.active(),
            self._start_pending,
            self.record_stage is not None or self.record_state != 'idle',
            self._ocr_test_running,
        )

    def _refresh_ocr_test_button(self):
        if not hasattr(self, 'ocr_test_button'):
            return
        reason = self._ocr_test_block_reason()
        if reason is None:
            self.ocr_test_button.configure(state='normal', text='Testar OCR')
        elif self._ocr_test_running:
            self.ocr_test_button.configure(state='disabled', text='Teste OCR em andamento')
        elif self.record_stage is not None or self.record_state != 'idle':
            self.ocr_test_button.configure(
                state='disabled', text='Interrompa a gravação para testar OCR'
            )
        else:
            self.ocr_test_button.configure(
                state='disabled', text='Pare a automação para testar OCR'
            )

    def test_ocr(self):
        block_reason = self._ocr_test_block_reason()
        if block_reason:
            messagebox.showwarning('Teste OCR indisponível', block_reason)
            return
        self._ocr_test_running = True
        self._refresh_ocr_test_button()
        # Ocultar a janela do próprio AutoFarm: ela cobre parte dos Candies.
        self.root.withdraw()
        def task():
            result_message = ''
            shot = None
            capture_bbox = None
            result = None
            folder = None
            stage = 'roblox_focus'
            try:
                time.sleep(0.65)
                activate_roblox_window()
                stage = 'candies_region'
                try:
                    candy_region = region_from(self.data, 'candies')
                except ValueError as exc:
                    result = CandiesOCRResult(
                        None, (), (), 'invalid_region', None, None, str(exc)
                    )
                else:
                    stage = 'tesseract_setup'
                    try:
                        engine, version, warning = configure_tesseract(self.data)
                    except RuntimeError as exc:
                        result = technical_ocr_result(
                            'tesseract_unavailable', stage, exc
                        )
                    else:
                        if warning:
                            self.events.put(('log', warning))
                        self.events.put(('log', f'Tesseract confirmado: {engine} (versão {version}).'))
                        stage = 'screen_capture'
                        shot, capture_bbox, result = capture_candies_attempt(
                            candy_region
                        )
                        if shot is not None:
                            self.events.put(('log', f'Área interna do Roblox: {shot.width}x{shot.height} px (sem barra de título/tarefas).'))
                        stage = 'image_to_text'
                report_ocr_failures(result, 'teste manual', self.events.put)
                folder = save_candies_diagnostic(
                    shot, self.data, result, client_bbox=capture_bbox
                )
                label = OCR_REASON_LABELS[result.reason]
                self.events.put(('log', f'Teste OCR: {label}; '
                                 f'Candies: {result.value if result.value is not None else "não identificado"}; '
                                 f'diagnóstico salvo em {folder}.'))
                if result.value is not None:
                    self.events.put(('candies', str(result.value)))
                result_message = (
                    f'Leitura {"válida" if result.value is not None else "inconclusiva"}\n'
                    f'Numerador: {result.value if result.value is not None else "não identificado"}\n'
                    f'Região da captura: {result.crop_box or "não identificada"}\n\n'
                    f'Etapa: {result.rejection_stage or "nenhuma"}\n'
                    f'Detalhe: {result.rejection_detail or "nenhum"}\n'
                    f'Recorte enviado ao Tesseract: '
                    f'{result.ocr_crop_box or "não identificado"}\n'
                    f'Candidatos válidos por caminho: {result.candidatos_validos}\n'
                    f'Leituras malformadas: {result.leituras_malformadas}\n'
                    f'Contradições válidas: {result.contradicoes}\n'
                    f'Decisão: {result.motivo_decisao or "não determinada"}\n'
                    f'Leituras fallback /500: {result.fallback_raw_texts}\n\n'
                    f'Diagnóstico visual: {folder}'
                )
            except Exception as e:
                reason = 'capture_failed' if stage == 'screen_capture' else 'ocr_error'
                result = technical_ocr_result(
                    reason, stage, e, shot=shot,
                )
                report_ocr_failures(result, 'teste manual', self.events.put)
                try:
                    folder = save_candies_diagnostic(
                        shot, self.data, result, reason=reason,
                        error=str(e), client_bbox=capture_bbox
                    )
                    self.events.put(('log', f'OCR Candies: {OCR_REASON_LABELS[reason]}: '
                                     f'{e}. Diagnóstico salvo em {folder}.'))
                    result_message = (
                        f'{OCR_REASON_LABELS[reason]}\n{e}\n\n'
                        f'Diagnóstico: {folder}'
                    )
                except Exception as diagnostic_error:
                    self.events.put(('log', f'Teste OCR: {e}; falha ao salvar diagnóstico: '
                                     f'{diagnostic_error}'))
                    result_message = f'Falha no teste OCR: {e}\nFalha no diagnóstico: {diagnostic_error}'
            finally:
                self.events.put(('restore_window', None))
                self.events.put((
                    'ocr_test_result', (result_message, shot, result, folder)
                ))
        worker = threading.Thread(target=task, daemon=True)
        try:
            worker.start()
        except RuntimeError as exc:
            self._ocr_test_running = False
            self.root.deiconify()
            self._refresh_ocr_test_button()
            messagebox.showerror('Teste OCR indisponível', str(exc))

    def _show_ocr_test_result(self, payload):
        message, shot, result, _folder = payload
        win = tk.Toplevel(self.root)
        win.title('Resultado do teste OCR dos Candies')
        win.transient(self.root)
        win.grab_set()
        ttk.Label(win, text=message, justify='left', wraplength=650).pack(
            padx=14, pady=(12, 8), anchor='w'
        )
        if shot is not None and result is not None and result.crop_box:
            preview = shot.crop(result.crop_box)
            draw = ImageDraw.Draw(preview)
            roi_left, roi_top = result.crop_box[:2]
            if result.counter_box:
                box = (
                    result.counter_box[0] - roi_left,
                    result.counter_box[1] - roi_top,
                    result.counter_box[2] - roi_left,
                    result.counter_box[3] - roi_top,
                )
                draw.rectangle(box, outline=(0, 255, 0), width=2)
            if result.numerator_box:
                box = (
                    result.numerator_box[0] - roi_left,
                    result.numerator_box[1] - roi_top,
                    result.numerator_box[2] - roi_left,
                    result.numerator_box[3] - roi_top,
                )
                draw.rectangle(box, outline=(255, 255, 0), width=2)
            if result.ocr_crop_box:
                box = (
                    result.ocr_crop_box[0] - roi_left,
                    result.ocr_crop_box[1] - roi_top,
                    result.ocr_crop_box[2] - roi_left,
                    result.ocr_crop_box[3] - roi_top,
                )
                draw.rectangle(box, outline=(255, 0, 255), width=2)
            preview_scale = min(640 / preview.width, 240 / preview.height, 6)
            preview = preview.resize(
                (max(1, round(preview.width * preview_scale)),
                 max(1, round(preview.height * preview_scale))),
                Image.Resampling.LANCZOS,
            )
            win._region_photo = ImageTk.PhotoImage(preview)
            ttk.Label(
                win,
                text='Região analisada (verde: contador; amarelo: numerador; roxo: OCR)',
            ).pack(anchor='w', padx=14)
            ttk.Label(win, image=win._region_photo).pack(padx=14, pady=(4, 8))
            if result.ocr_crop_box and result.ocr_crop_box != result.numerator_box:
                sent_crop = shot.crop(result.ocr_crop_box)
                crop_scale = min(
                    480 / sent_crop.width, 120 / sent_crop.height, 6
                )
                sent_crop = sent_crop.resize(
                    (max(1, round(sent_crop.width * crop_scale)),
                     max(1, round(sent_crop.height * crop_scale))),
                    Image.Resampling.LANCZOS,
                )
                win._ocr_crop_photo = ImageTk.PhotoImage(sent_crop)
                ttk.Label(
                    win, text='Recorte efetivamente enviado ao Tesseract:'
                ).pack(anchor='w', padx=14)
                ttk.Label(win, image=win._ocr_crop_photo).pack(
                    padx=14, pady=(4, 8)
                )
            if result.numerator_box:
                numerator = shot.crop(result.numerator_box)
                numerator_scale = min(
                    360 / numerator.width, 120 / numerator.height, 10
                )
                numerator = numerator.resize(
                    (max(1, round(numerator.width * numerator_scale)),
                     max(1, round(numerator.height * numerator_scale))),
                    Image.Resampling.LANCZOS,
                )
                win._numerator_photo = ImageTk.PhotoImage(numerator)
                ttk.Label(win, text='Numerador isolado:').pack(
                    anchor='w', padx=14
                )
                ttk.Label(win, image=win._numerator_photo).pack(
                    padx=14, pady=(4, 10)
                )
        ttk.Button(win, text='Fechar', command=win.destroy).pack(pady=(0, 12))

    def arm_recording(self, stage):
        """Seleciona a etapa, oculta a janela e aguarda a tecla configurada."""
        if self._ocr_test_running:
            messagebox.showwarning('Teste OCR em andamento',
                                   'Aguarde o teste OCR terminar antes de iniciar uma gravação.')
            return
        if self.controller.active() or self._start_pending:
            messagebox.showwarning('Automação ativa', 'Pare a automação antes de gravar uma nova etapa.')
            return
        if self.record_stage is not None:
            messagebox.showinfo('Gravador', f'Já existe uma gravação preparada ou em andamento. Use {self._record_hotkey_name.upper()} para salvar ou F12 para cancelar.')
            return
        if not self.save():
            return
        self.record_stage = stage
        self.record_state = 'armed'
        self.log(f'Preparando gravação de {stage.upper()}. {self._record_hotkey_name.upper()} começa, {self._record_hotkey_name.upper()} salva; F12 cancela.')
        self.status.set(f'Aguardando {self._record_hotkey_name.upper()} para gravar {stage}')
        self._hidden_during_run = True
        self.root.withdraw()
        self.root.after(500, self._focus_for_recording)

    def _focus_for_recording(self):
        if self.record_state != 'armed':
            return
        try:
            activate_roblox_window()
        except Exception as exc:
            self._cancel_recording()
            messagebox.showerror('Roblox não encontrado', str(exc))

    def _record_f8(self):
        if self.record_stage is None:
            return
        if self.record_state == 'armed':
            try:
                self.recording_client_bbox = roblox_client_bbox()
                self.recorder.begin()
            except Exception as exc:
                self._cancel_recording()
                messagebox.showerror('Falha ao gravar', str(exc))
                return
            self.record_state = 'recording'
            self.status.set(f'GRAVANDO {self.record_stage.upper()} — {self._record_hotkey_name.upper()} para salvar')
            self.log(f'GRAVAÇÃO INICIADA: {self.record_stage}. Pressione {self._record_hotkey_name.upper()} novamente ao terminar.')
            return
        if self.record_state != 'recording':
            return
        stage = self.record_stage
        staged_path = CUSTOM_RECORDINGS_DIR / (
            f'.{stage}_{uuid.uuid4().hex}.staging.rec'
        )
        previous_selection = self.fields[stage].get()
        previous_data_selection = self.data.get(stage, DEFAULT[stage])
        try:
            CUSTOM_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
            result = self.recorder.finish(staged_path)
            events = read_rec(staged_path)

            def persist_selection(destination):
                self.fields[stage].set(str(destination))
                if not self.save():
                    raise RuntimeError('Não foi possível salvar a seleção da gravação.')

            destination = publish_custom_recording(
                stage, staged_path, self.recording_client_bbox,
                persist_selection,
            )
            self.recording_client_bbox = None
            self.record_stage = None
            self.record_state = 'idle'
            self._restore_interface()
            self.status.set('Parado')
            self.log(f'Nova gravação {stage.upper()} salva: {destination.name} | '
                     f'{events[-1].offset:.1f}s | {len(events)} eventos.')
            if result['wheel_ignored']:
                self.log(f'AVISO: {result["wheel_ignored"]} rolagens de mouse foram ignoradas. Evite usar a roda nas gravações.')
        except Exception as exc:
            self.fields[stage].set(previous_selection)
            self.data[stage] = previous_data_selection
            try:
                discard_staged_recording(staged_path)
            except OSError as cleanup_error:
                self.log(
                    f'Não consegui remover arquivo temporário de gravação: '
                    f'{cleanup_error}'
                )
            self._cancel_recording()
            messagebox.showerror('Falha ao salvar gravação', str(exc))

    def _cancel_recording(self):
        self.recorder.cancel()
        self.recording_client_bbox = None
        self.record_stage = None
        self.record_state = 'idle'
        self.status.set('Parado')
        self._restore_interface()
        self.log('Gravação cancelada. Nenhum arquivo selecionado.')

    def choose(self,key):
        name=filedialog.askopenfilename(title='Escolher gravação',filetypes=[('Gravação TinyTask (.rec)','*.rec'),('Todos','*.*')],initialdir=str(ROOT/'gravacoes'))
        if name:
            if self.controller.active() or self.record_stage is not None:
                messagebox.showwarning('Operação em andamento', 'Pare a automação ou a gravação antes de escolher um arquivo.')
                return
            self.fields[key].set(name)
            self.save()

    def export_recording(self, stage):
        """Ícone ⬇: salva uma cópia .rec e sua geometria, se disponível."""
        if self.record_stage is not None:
            messagebox.showinfo('Gravação em andamento',
                                'Encerre ou cancele a gravação antes de exportar.')
            return
        try:
            origem = macro_recording(self.fields[stage].get().strip() or DEFAULT[stage])
            if not origem.is_file():
                raise FileNotFoundError(f'Gravação não encontrada: {origem}')
            read_rec(origem)  # validar antes de copiar
            nome = origem.name
            destino = filedialog.asksaveasfilename(
                title=f'Exportar gravação de {stage}',
                defaultextension='.rec',
                initialfile=nome,
                filetypes=[('Gravação TinyTask (.rec)', '*.rec')])
            if not destino:
                return
            destino = Path(destino)
            if destino.suffix.lower() != '.rec':
                raise ValueError('Use a extensão .rec.')
            if origem.resolve() == destino.resolve():
                messagebox.showinfo('Arquivo original', 'Você selecionou o próprio arquivo. '                                    'Nenhuma cópia foi necessária.')
                return
            shutil.copy2(origem, destino)
            metadata = caminho_metadados(origem)
            if metadata.is_file():
                shutil.copy2(metadata, caminho_metadados(destino))
            self.log(f'Gravação de {stage} exportada para {destino}.')
            messagebox.showinfo('Gravação exportada',
                                f'Arquivo salvo:\n{destino}\n\n'
                                'Se houver metadados de posição da janela, eles foram copiados junto.')
        except Exception as exc:
            messagebox.showerror('Falha na exportação', str(exc))

    def save(self):
        hk = self.hotkey.get().strip().lower()
        rh = self.record_hotkey.get().strip().lower()
        if normalize_hotkey_name(hk) is None or normalize_hotkey_name(rh) is None:
            messagebox.showerror(
                'Tecla inválida',
                'Use uma tecla F1–F24, uma letra de A a Z ou um número de 0 a 9.',
            )
            return False
        if rh == 'f12':
            messagebox.showerror('Tecla reservada', 'F12 é reservada para cancelar gravações. Escolha outra tecla para gravar.')
            return False
        if hk == rh:
            messagebox.showerror('Teclas iguais', 'Escolha teclas diferentes para iniciar/parar e para gravar.')
            return False
        for k, v in self.fields.items():
            self.data[k] = v.get().strip() or DEFAULT[k]
        self.data['hotkey'] = hk
        self.data['record_hotkey'] = rh
        self.data['rare_chests'] = self.controller.rare_chests
        for key in RESOURCE_TOGGLE_KEYS:
            self.data[key] = self.resource_vars[key].get()
        self._hotkey_name = hk
        self._record_hotkey_name = rh
        self.recorder.set_record_hotkey(rh)
        atomic_write_json(CFG, self.data)
        self.log('Configurações salvas.')
        return True

    def _validate_rare_chests_input(self, proposed):
        return (
            proposed == ''
            or (
                proposed.isascii()
                and proposed.isdigit()
                and int(proposed) <= RARE_CHEST_LIMIT
            )
        )

    def _on_rare_chests_input_change(self, *_args):
        if self._updating_rare_chests_ui:
            return
        value = self.rare_chests_input.get()
        if value and self._validate_rare_chests_input(value):
            self._commit_rare_chests()

    def _commit_rare_chests(self, show_error=True):
        value = self.rare_chests_input.get().strip()
        try:
            parsed = validate_rare_chests(int(value))
        except (ValueError, TypeError):
            if show_error:
                messagebox.showerror(
                    'Rare Chests inválido',
                    f'Informe um número inteiro entre 0 e {RARE_CHEST_LIMIT}.',
                )
            parsed = self.controller.rare_chests
            self._updating_rare_chests_ui = True
            try:
                self.rare_chests_input.set(str(parsed))
            finally:
                self._updating_rare_chests_ui = False
            return False

        if (self.controller.active() or self._start_pending or
                self.record_stage is not None):
            if show_error:
                messagebox.showwarning(
                    'Automação em andamento',
                    'Pare a automação ou a gravação antes de editar Rare Chests.',
                )
            self._updating_rare_chests_ui = True
            try:
                self.rare_chests_input.set(str(self.controller.rare_chests))
            finally:
                self._updating_rare_chests_ui = False
            return False

        try:
            self.controller.set_rare_chests(parsed, self.data)
        except (OSError, RuntimeError, ValueError) as exc:
            if show_error:
                messagebox.showerror(
                    'Não foi possível salvar Rare Chests', str(exc)
                )
            parsed = self.controller.rare_chests
            self._updating_rare_chests_ui = True
            try:
                self.rare_chests_input.set(str(parsed))
            finally:
                self._updating_rare_chests_ui = False
            return False

        self.data['rare_chests'] = parsed
        self.rare_chests.set(rare_chests_display(parsed))
        self._updating_rare_chests_ui = True
        try:
            self.rare_chests_input.set(str(parsed))
        finally:
            self._updating_rare_chests_ui = False
        return True

    def _refresh_rare_chests_controls(self):
        if not hasattr(self, 'rare_chests_spinbox'):
            return
        disabled = (
            self.controller.active()
            or self._start_pending
            or self.record_stage is not None
        )
        self.rare_chests_spinbox.configure(
            state='disabled' if disabled else 'readonly'
        )

    def on_key(self, key):
        name = hotkey_name_from_key(key)
        fingerprint = self._key_fingerprint(key)
        with self._hotkey_capture_lock:
            if fingerprint in self._hotkey_capture_suppressed:
                return
            capture_target = self._hotkey_capture_target
            capture_pending = self._hotkey_capture_pending
            if capture_target is not None:
                self._hotkey_capture_suppressed.add(fingerprint)
                if fingerprint == 'esc':
                    self._hotkey_capture_target = None
                    self._hotkey_capture_pending = True
                    capture_event = ('hotkey_capture_cancel', capture_target)
                elif name is None:
                    capture_event = (
                        'hotkey_capture_invalid',
                        (capture_target, fingerprint),
                    )
                else:
                    self._hotkey_capture_target = None
                    self._hotkey_capture_pending = True
                    capture_event = ('hotkey_captured', (capture_target, name))
            else:
                capture_event = None
        if capture_target is not None:
            self.events.put(capture_event)
            return
        if capture_pending:
            with self._hotkey_capture_lock:
                self._hotkey_capture_suppressed.add(fingerprint)
            return
        if name is None:
            return
        if self.record_stage is not None:
            if name == self._record_hotkey_name and not self._record_key_pressed:
                self._record_key_pressed = True
                self.events.put(('record_f8', None))
            elif name == 'f12' and not self._hotkey_pressed:
                self._hotkey_pressed = True
                self.events.put(('record_cancel', None))
            return
        if name == self._hotkey_name and not self._hotkey_pressed:
            self._hotkey_pressed = True
            self.events.put(('toggle', None))

    def on_release(self, key):
        fingerprint = self._key_fingerprint(key)
        with self._hotkey_capture_lock:
            self._hotkey_capture_suppressed.discard(fingerprint)
        name = hotkey_name_from_key(key)
        if name is None:
            return
        if name == self._record_hotkey_name:
            self._record_key_pressed = False
        if name == self._hotkey_name or name == 'f12':
            self._hotkey_pressed = False

    def start(self):
        if self._ocr_test_running:
            messagebox.showwarning('Teste OCR em andamento',
                                   'Aguarde o teste OCR terminar antes de iniciar a automação.')
            return
        if self.record_stage is not None:
            messagebox.showinfo('Gravador ativo',f'Pressione {self._record_hotkey_name.upper()} para salvar ou F12 para cancelar antes de iniciar.')
            return
        if self.controller.active() or self._start_pending:
            return
        if not self.save():
            return
        # CRÍTICO: a janela cobria o contador de Candies na posição central
        # inferior do Roblox. Esconder ANTES de tocar qualquer tecla do macro.
        self._start_pending = True
        self._hidden_during_run = True
        self._pending_error = None
        self.log('Ocultando o AutoFarm. O Roblox terá foco; pressione F12 para parar.')
        self.root.withdraw()
        self.root.after(550, self._start_with_game_visible)

    def _start_with_game_visible(self):
        if not self._start_pending:
            return
        self._start_pending = False
        try:
            activate_roblox_window()
            self.controller.start(self.data)
        except Exception as e:
            self._restore_interface()
            self.log('ERRO ao iniciar: ' + str(e))
            messagebox.showerror('Não foi possível iniciar', str(e))

    def _restore_interface(self):
        if self._hidden_during_run:
            self._hidden_during_run = False
            self.root.deiconify()
            self.root.lift()
            try:
                self.root.focus_force()
            except tk.TclError:
                pass

    def log(self,text):
        self.logbox.configure(state='normal')
        self.logbox.insert('end',f'[{time.strftime("%H:%M:%S")}] {text}\n')
        self.logbox.see('end')
        self.logbox.configure(state='disabled')

    def poll(self):
        try:
            while True:
                key,value=self.events.get_nowait()
                if key=='restore_window':
                    self.root.deiconify()
                elif key=='record_f8':
                    self._record_f8()
                elif key=='record_cancel':
                    self._cancel_recording()
                elif key=='toggle':
                    if self.controller.active():
                        self.controller.request_stop()
                    elif self._start_pending:
                        self._start_pending=False
                        self._restore_interface()
                        self.log('Início cancelado pelo F12.')
                    else:
                        self.start()
                elif key=='status':self.status.set(value)
                elif key=='candies':self.candies.set(value + ' / 250 (provisório)')
                elif key in ('candies_reset', 'candies_inconclusivos', 'candies_confirmed'):
                    self.candies.set(value)
                elif key=='rare_chests':
                    self.rare_chests.set(value)
                    self.data['rare_chests'] = self.controller.rare_chests
                    self._updating_rare_chests_ui = True
                    try:
                        self.rare_chests_input.set(
                            str(self.controller.rare_chests)
                        )
                    finally:
                        self._updating_rare_chests_ui = False
                elif key=='boss':self.boss.set(value)
                elif key=='clock':self.clock_var.set(value)
                elif key=='log':self.log(value)
                elif key=='hotkey_captured':
                    self._handle_hotkey_capture(*value)
                elif key=='hotkey_capture_invalid':
                    setting, fingerprint = value
                    if self._hotkey_capture_status is not None:
                        if fingerprint in (
                                'ctrl', 'ctrl_l', 'ctrl_r', 'shift',
                                'shift_l', 'shift_r', 'alt', 'alt_l',
                                'alt_r', 'alt_gr'):
                            detail = 'Modificadores isolados não são aceitos.'
                        else:
                            detail = (
                                'Tecla não suportada. Use F1–F24, A–Z ou 0–9.'
                            )
                        self._hotkey_capture_status.set(
                            f'{detail} Pressione outra tecla ou Esc para cancelar.'
                        )
                elif key=='hotkey_capture_cancel':
                    self._cancel_hotkey_capture()
                elif key=='ocr_test_result':
                    self._ocr_test_running = False
                    self._show_ocr_test_result(value)
                elif key=='error':
                    self.log('ERRO: '+value)
                    # Exibir o erro somente DEPOIS de restaurar a interface.
                    self._pending_error = value
                elif key=='stopped':
                    self._restore_interface()
                    if self._pending_error:
                        msg = self._pending_error
                        self._pending_error = None
                        self.root.after(100, lambda m=msg: messagebox.showerror('Automação interrompida',m))
        except queue.Empty:
            pass
        self._refresh_ocr_test_button()
        self._refresh_rare_chests_controls()
        self._refresh_resource_controls()
        self.root.after(100,self.poll)

    def refresh_clock(self):
        try:
            if not self.data.get('boss_control_enabled', True):
                self.root.after(1000, self.refresh_clock)
                return
            status = self.relogio.status_boss()
            if status.horario is not None:
                self.clock_var.set(status.horario + ' (manual)')
                self.boss.set('Presente' if status.estado == 'PRESENTE' else 'Ausente')
            else:
                self.clock_var.set('Não sincronizado')
                self.boss.set('Desconhecido')
            self.root.after(1000, self.refresh_clock)
        except tk.TclError:
            pass

    def close(self):
        if self.record_stage is not None:
            self.recorder.cancel()
        self._start_pending = False
        self.controller.request_stop()
        self.listener.stop()
        self.root.destroy()

if sys.platform == 'win32':
    try:
        ctypes.WinDLL('user32').SetProcessDPIAware()
    except Exception:
        pass

if __name__ == '__main__':
    if sys.platform != 'win32':
        print('Este aplicativo precisa ser executado no Windows.')
    else:
        # Evita que duas instâncias diferentes controlem o mesmo Roblox.
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        mutex = kernel32.CreateMutexW(None, False, 'Local\\GPO_AutoFarm_v11_Mutex')
        if not mutex:
            raise OSError(ctypes.get_last_error(), 'Não foi possível criar o bloqueio de instância.')
        try:
            if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
                ctypes.windll.user32.MessageBoxW(
                    None, 'O GPO_AutoFarm_v11 já está aberto. Use a janela existente.',
                    'GPO_AutoFarm_v11 já em execução', 0x40)
            else:
                App().root.mainloop()
        finally:
            kernel32.CloseHandle(mutex)
