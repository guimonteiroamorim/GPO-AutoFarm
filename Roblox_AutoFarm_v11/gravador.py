"""Grava teclado e mouse em .rec COMPATÍVEL com o recplayer do projeto.

Não abre TinyTask.exe: reproduz o formato da gravação fornecida pelo usuário.
A própria janela do AutoFarm registra entradas globais após F8; outro F8 salva.
As mensagens de entrada Win32 são coletadas via filtros de baixo nível do pynput.
"""
from __future__ import annotations

import struct
import threading
import time
from pathlib import Path

RECORD = struct.Struct('<IIIQ')
WM_KEYDOWN, WM_KEYUP = 0x100, 0x101
WM_SYSKEYDOWN, WM_SYSKEYUP = 0x104, 0x105
WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x200, 0x201, 0x202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x204, 0x205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x207, 0x208
WM_STOP = WM_KEYDOWN
KEY_EVENTS = {WM_KEYDOWN, WM_KEYUP, WM_SYSKEYDOWN, WM_SYSKEYUP}
MOUSE_EVENTS = {WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP,
                WM_RBUTTONDOWN, WM_RBUTTONUP, WM_MBUTTONDOWN, WM_MBUTTONUP}
F8_VK = 0x77
F12_VK = 0x7B


class GravadorRec:
    """Registrador thread-safe para os eventos suportados pelo recplayer.

    Captura as coordenadas de mouse em pixels físicos do Windows, não relativas
    ao aplicativo. A resolução e escala devem se manter iguais na reprodução.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._record_vk = F8_VK
        self._recording = False
        self._rows = []
        self._mouse_listener = None
        self._t0 = 0
        self._last_move = None
        self._last_move_ms = -99999
        self._ignored_wheel = 0


    def set_record_hotkey(self, hotkey):
        """Altera apenas a tecla de controle da gravação, não o formato .rec."""
        value = str(hotkey).strip().lower()
        import re
        if not re.fullmatch(r'f(?:[1-9]|1[0-9]|2[0-4])', value):
            raise ValueError('Tecla de gravação inválida.')
        vk = 0x6F + int(value[1:])
        if vk == F12_VK:
            raise ValueError('F12 é reservada para cancelar gravações.')
        with self._lock:
            if self._recording:
                raise RuntimeError('Não é permitido mudar a tecla durante a gravação.')
            self._record_vk = vk

    @property
    def recording(self):
        with self._lock:
            return self._recording

    def _timestamp(self):
        return time.monotonic_ns() // 1_000_000

    def begin(self):
        with self._lock:
            if self._recording:
                raise RuntimeError('Uma gravação já está em andamento.')
            self._rows = []
            self._recording = True
            self._t0 = self._timestamp()
            self._last_move = None
            self._last_move_ms = -99999
            self._ignored_wheel = 0
        try:
            # O listener principal da GUI encaminha eventos de teclado para
            # keyboard_filter. Este listener coleta APENAS mouse, em paralelo.
            from pynput import mouse
            listener = mouse.Listener(win32_event_filter=self.mouse_filter)
            listener.start()
            with self._lock:
                self._mouse_listener = listener
        except Exception:
            self.cancel()
            raise

    def _append(self, message, p1, p2, timestamp=None):
        with self._lock:
            if not self._recording:
                return
            timestamp = self._timestamp() if timestamp is None else int(timestamp)
            if self._rows and timestamp < self._rows[-1][3]:
                timestamp = self._rows[-1][3]
            self._rows.append((int(message), int(p1) & 0xFFFFFFFF,
                               int(p2) & 0xFFFFFFFF, timestamp))

    def keyboard_filter(self, message, data):
        """Recebe KBDLLHOOKSTRUCT via pynput.keyboard.Listener."""
        with self._lock:
            if not self._recording:
                return True
            if message not in KEY_EVENTS:
                return True
            vk = int(data.vkCode) & 0xFF
            if vk in (self._record_vk, F12_VK):
                return True  # teclas de controle nunca entram no .rec
            scan = int(data.scanCode) & 0xFF
            if int(data.flags) & 0x01:  # LLKHF_EXTENDED
                scan |= 0xE000
            # Igual aos .rec do TinyTask: data1 = scanCode << 8 | virtualKey.
            # Para teclas normais, por exemplo E: 0x1245, W: 0x1157.
            self._append(message, ((scan & 0xFF) << 8) | vk, scan)
        return True

    def mouse_filter(self, message, data):
        """Recebe MSLLHOOKSTRUCT via pynput.mouse.Listener."""
        with self._lock:
            if not self._recording:
                return True
            if message not in MOUSE_EVENTS:
                if message in (0x20A, 0x20E):
                    self._ignored_wheel += 1
                return True
            x, y = int(data.pt.x), int(data.pt.y)
            now = self._timestamp()
            # Reduz o tamanho das trilhas do mouse sem perder cliques ou a
            # última posição antes de clicar. Os movimentos continuam suaves.
            if message == WM_MOUSEMOVE:
                if (self._last_move is not None and
                    now-self._last_move_ms < 15 and
                    abs(x-self._last_move[0]) < 3 and
                    abs(y-self._last_move[1]) < 3):
                    return True
                self._last_move = (x,y)
                self._last_move_ms = now
            self._append(message, x, y, now)
        return True

    def finish(self, path):
        """Grava o arquivo somente após F8. Insere F8 final para preservar
        o tempo até o comando de parada; recplayer ignora o evento terminal.
        """
        with self._lock:
            if not self._recording:
                raise RuntimeError('Nenhuma gravação em andamento.')
            self._recording = False
            rows = list(self._rows)
            stop_ms = self._timestamp()
            listener = self._mouse_listener
            self._mouse_listener = None
            wheel_count = self._ignored_wheel
        if listener is not None:
            listener.stop()
        if not rows:
            raise ValueError('Nenhuma ação registrada. Pressione F8, realize as ações e pressione F8 novamente.')
        if stop_ms - rows[0][3] > 3600 * 1000:
            raise ValueError('Gravações com mais de 1 hora não são suportadas.')
        # 0x4277 = scan F8 (0x42) e VK F8 (0x77).
        rows.append((WM_STOP, 0x4277, 0x42, max(stop_ms, rows[-1][3])))
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.part')
        with temporary.open('wb') as fh:
            for row in rows:
                fh.write(RECORD.pack(*row))
        temporary.replace(target)
        return {'path': target, 'events': len(rows),
                'seconds': (rows[-1][3] - rows[0][3]) / 1000,
                'wheel_ignored': wheel_count}

    def cancel(self):
        with self._lock:
            self._recording = False
            self._rows = []
            listener = self._mouse_listener
            self._mouse_listener = None
        if listener is not None:
            listener.stop()
