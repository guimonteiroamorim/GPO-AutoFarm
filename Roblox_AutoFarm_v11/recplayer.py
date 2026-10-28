"""Reprodução local de gravações binárias TinyTask .rec.

Suporta os eventos registrados nos arquivos fornecidos: teclado e mouse.
A estrutura foi identificada pelos eventos e pelos intervalos destas gravações:
blocos de 20 bytes, <IIIQ (mensagem Win32, dados1, dados2, ms).

Não requer nem inicia os executáveis compilados do TinyTask.
Não executa outros tipos de arquivos. A janela precisa estar em foco.
"""
from dataclasses import dataclass
from pathlib import Path
import ctypes
from ctypes import wintypes
import struct
import sys
import time

RECORD = struct.Struct('<IIIQ')
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
SUPPORTED = {WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP,
             WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP,
             WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP}

@dataclass(frozen=True)
class Event:
    offset: float  # segundos relativos à primeira ação
    message: int
    data1: int
    data2: int


def read_rec(path):
    data = Path(path).read_bytes()
    if not data or len(data) % RECORD.size:
        raise ValueError('Gravação .rec vazia ou com formato desconhecido.')
    rows = list(RECORD.iter_unpack(data))
    if any(m not in SUPPORTED for m, *_ in rows):
        types = sorted({hex(m) for m, *_ in rows if m not in SUPPORTED})
        raise ValueError('A gravação possui eventos ainda não suportados: ' + ', '.join(types))
    start = rows[0][3]
    if any(t < start for _,_,_,t in rows) or any(b[3] < a[3] for a,b in zip(rows, rows[1:])):
        raise ValueError('Marcações de tempo inválidas na gravação.')
    if (rows[-1][3] - start) > 60*60*1000:
        raise ValueError('A gravação parece ter duração inválida (>1 h).')
    return [Event((t-start)/1000, m, p1, p2) for m,p1,p2,t in rows]


# API Win32 SendInput: a entrada de teclado é enviada por scancode, preservando
# a tecla física e os tempos registrados, inclusive letras com SHIFT.
ULONG_PTR = wintypes.WPARAM

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG),
                ('mouseData', wintypes.DWORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                ('dwExtraInfo', ULONG_PTR)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [('uMsg', wintypes.DWORD), ('wParamL', wintypes.WORD),
                ('wParamH', wintypes.WORD)]

class INPUTUNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT), ('hi', HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _anonymous_ = ('u',)
    _fields_ = [('type', wintypes.DWORD), ('u', INPUTUNION)]

class WindowsInput:
    def __init__(self):
        if sys.platform != 'win32':
            raise OSError('A reprodução de arquivos .rec requer Windows.')
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
        self.user32.SendInput.restype = wintypes.UINT
        self.user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        self.user32.SetCursorPos.restype = wintypes.BOOL
        self.user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
        self.user32.GetCursorPos.restype = wintypes.BOOL
        self.user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.user32.GetSystemMetrics.restype = ctypes.c_int
        # Usar coordenadas físicas, como as capturadas pelo TinyTask.
        try:
            self.user32.SetProcessDPIAware()
        except Exception:
            pass
        self.held_keys = set()
        self.held_mouse = set()
        self.position_transform = None
        self.last_mouse_down_at = {}
        # Região total da área de trabalho, inclusive segundo monitor.
        self.desktop = (
            self.user32.GetSystemMetrics(76),  # SM_XVIRTUALSCREEN
            self.user32.GetSystemMetrics(77),  # SM_YVIRTUALSCREEN
            self.user32.GetSystemMetrics(78),  # SM_CXVIRTUALSCREEN
            self.user32.GetSystemMetrics(79),  # SM_CYVIRTUALSCREEN
        )
        if self.desktop[2] < 2 or self.desktop[3] < 2:
            self.desktop = (0, 0, self.user32.GetSystemMetrics(0),
                            self.user32.GetSystemMetrics(1))

    def _send(self, input_obj):
        if self.user32.SendInput(1, ctypes.byref(input_obj), ctypes.sizeof(INPUT)) != 1:
            raise OSError(ctypes.get_last_error(), 'O Windows não aceitou o evento de teclado/mouse.')

    def key(self, scancode, down):
        flags = 0x0008 | (0 if down else 0x0002)  # SCANCODE|KEYUP
        if scancode & 0xE000:
            flags |= 0x0001  # EXTENDEDKEY
        key = scancode & 0xFF
        self._send(INPUT(type=1, ki=KEYBDINPUT(0, key, flags, 0, 0)))
        if down:
            self.held_keys.add(key)
        else:
            self.held_keys.discard(key)

    def mouse(self, flag):
        self._send(INPUT(type=0, mi=MOUSEINPUT(0, 0, 0, flag, 0, 0)))

    def _position_mouse_for_click(self, x, y):
        """Movimento real SendInput para GUI do jogo detectar hover antes do clique.

        SetCursorPos sozinho reposiciona o cursor, mas pode não ser visto como
        uma movimentação de mouse por determinadas GUIs do Roblox.
        Não repete nem duplica o clique: um DOWN e um UP, nos tempos do .rec.
        """
        if not self.user32.SetCursorPos(x, y):
            raise OSError(ctypes.get_last_error(), 'Não foi possível posicionar o cursor.')
        left, top, width, height = self.desktop
        if not (left <= x < left + width and top <= y < top + height):
            raise ValueError(f'Clique fora da área de trabalho: ({x}, {y})')
        nx = round((x - left) * 65535 / max(1, width - 1))
        ny = round((y - top) * 65535 / max(1, height - 1))
        # MOVE | ABSOLUTE | VIRTUALDESK
        flags = 0x0001 | 0x8000 | 0x4000
        self._send(INPUT(type=0, mi=MOUSEINPUT(nx, ny, 0, flags, 0, 0)))
        # Pequeno intervalo de hover antes do botão (sem reenviar clique).
        time.sleep(0.025)
        point = wintypes.POINT()
        if self.user32.GetCursorPos(ctypes.byref(point)):
            if abs(point.x - x) > 8 or abs(point.y - y) > 8:
                raise RuntimeError(f'O cursor saiu do alvo de clique ({x}, {y}). '
                                   'Confira escala, câmera e posição da janela.')

    def event(self, e):
        m, p1, p2 = e.message, e.data1, e.data2
        if m in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
            # Arquivos do TinyTask usam os scancodes no campo data2.
            # F8 final, quando gravado como evento isolado de parada, é ignorado.
            self.key(p2, m in (WM_KEYDOWN, WM_SYSKEYDOWN))
        else:
            x, y = ctypes.c_int32(p1).value, ctypes.c_int32(p2).value
            if self.position_transform is not None:
                x, y = self.position_transform(x, y)
            if m in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                self._position_mouse_for_click(x, y)
            elif not self.user32.SetCursorPos(x, y):
                raise OSError(ctypes.get_last_error(), 'Não foi possível mover o mouse.')
            flags = {WM_MOUSEMOVE:0, WM_LBUTTONDOWN:0x0002, WM_LBUTTONUP:0x0004,
                     WM_RBUTTONDOWN:0x0008, WM_RBUTTONUP:0x0010,
                     WM_MBUTTONDOWN:0x0020, WM_MBUTTONUP:0x0040}
            flag = flags[m]
            # Garantir duração mínima do botão pressionado. Algumas gravações
            # rápidas produzem down/up com menos de 25 ms e o jogo não vê clique.
            # Não altera os cliques já gravados com pressão suficiente.
            press_to_release = {WM_LBUTTONUP: WM_LBUTTONDOWN,
                                WM_RBUTTONUP: WM_RBUTTONDOWN,
                                WM_MBUTTONUP: WM_MBUTTONDOWN}
            if m in press_to_release:
                instante = self.last_mouse_down_at.get(press_to_release[m])
                if instante is not None:
                    restante = 0.08 - (time.monotonic() - instante)
                    if restante > 0:
                        time.sleep(restante)
            if flag:
                self.mouse(flag)
            if m in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                self.last_mouse_down_at[m] = time.monotonic()
            elif m in press_to_release:
                self.last_mouse_down_at.pop(press_to_release[m], None)
            if m in (WM_LBUTTONDOWN, WM_RBUTTONDOWN, WM_MBUTTONDOWN):
                self.held_mouse.add(m)
            elif m in (WM_LBUTTONUP, WM_RBUTTONUP, WM_MBUTTONUP):
                self.held_mouse.discard({WM_LBUTTONUP:WM_LBUTTONDOWN,
                                         WM_RBUTTONUP:WM_RBUTTONDOWN,
                                         WM_MBUTTONUP:WM_MBUTTONDOWN}[m])

    def release_all(self):
        # Quando uma gravação termina no meio de uma tecla pressionada,
        # liberá-la evita que o próximo ciclo fique com a tecla travada.
        for key in list(self.held_keys):
            try: self.key(key, False)
            except OSError: pass
        for down in list(self.held_mouse):
            flags = {WM_LBUTTONDOWN:0x0004, WM_RBUTTONDOWN:0x0010, WM_MBUTTONDOWN:0x0040}
            try: self.mouse(flags[down])
            except OSError: pass
        self.held_mouse.clear()
        self.last_mouse_down_at.clear()


def is_record_stop_key(events, i):
    """O botão de fim da gravação pode deixar um F8 isolado na trilha.
    Só desconsidera F8 sem KEYUP quando for o ÚLTIMO evento.
    O tempo total da gravação permanece inalterado.
    """
    e = events[i]
    return i == len(events)-1 and e.message in (WM_KEYDOWN,WM_SYSKEYDOWN) and (e.data1 & 0xFF) == 0x77
