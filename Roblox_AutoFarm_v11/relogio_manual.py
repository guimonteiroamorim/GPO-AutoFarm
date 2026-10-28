"""Sincronização manual do relógio do servidor, sem OCR.

Este relógio mantém a fase informada enquanto o usuário permanece no mesmo
servidor. Ao trocar de servidor, o usuário deve invalidá-lo e sincronizar.
"""
import re
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class SituacaoBoss:
    estado: str  # AUSENTE, PRESENTE, DESCONHECIDO
    ate_proximo_spawn: float | None
    horario: str | None


class RelogioManual:
    PRIMEIRO_SPAWN = 25 * 60
    PERIODO_SPAWN = 35 * 60
    DURACAO_BOSS = 10 * 60

    def __init__(self, clock=None):
        self._clock = clock or time.monotonic
        self._lock = threading.RLock()
        self._base = None
        self._inicio = None

    @staticmethod
    def parse_horario(horario):
        if not isinstance(horario, str) or not re.fullmatch(r'\d{1,4}:\d{2}:\d{2}', horario.strip()):
            raise ValueError('Digite o horário no formato HH:MM:SS (ex.: 00:46:47).')
        horas, minutos, segundos = (int(i) for i in horario.strip().split(':'))
        if minutos >= 60 or segundos >= 60:
            raise ValueError('Os minutos e os segundos precisam estar entre 00 e 59.')
        return horas * 3600 + minutos * 60 + segundos

    @staticmethod
    def formatar(segundos):
        total = max(0, int(segundos))
        return f'{total // 3600:02d}:{(total // 60) % 60:02d}:{total % 60:02d}'

    def sincronizar(self, horario):
        tempo_servidor = self.parse_horario(horario)
        with self._lock:
            self._base = tempo_servidor
            self._inicio = self._clock()
        return self.formatar(tempo_servidor)

    def invalidar(self):
        with self._lock:
            self._base = None
            self._inicio = None

    def sincronizado(self):
        with self._lock:
            return self._inicio is not None

    def segundos_atual(self):
        with self._lock:
            if self._inicio is None:
                return None
            return self._base + max(0.0, self._clock() - self._inicio)

    def horario_atual(self):
        segundos = self.segundos_atual()
        return self.formatar(segundos) if segundos is not None else None

    def status_boss(self, server_seconds=None):
        if server_seconds is None:
            server_seconds = self.segundos_atual()
        if server_seconds is None:
            return SituacaoBoss('DESCONHECIDO', None, None)
        if server_seconds < self.PRIMEIRO_SPAWN:
            return SituacaoBoss('AUSENTE', self.PRIMEIRO_SPAWN - server_seconds, self.formatar(server_seconds))
        fase = (server_seconds - self.PRIMEIRO_SPAWN) % self.PERIODO_SPAWN
        ate = self.PERIODO_SPAWN - fase
        estado = 'PRESENTE' if fase < self.DURACAO_BOSS else 'AUSENTE'
        return SituacaoBoss(estado, ate, self.formatar(server_seconds))

    def pode_comprar(self, candies, *, meta=250, margem_segundos=80):
        if candies is None or candies < meta:
            return False, 'Candies insuficientes ou não identificados', self.status_boss()
        status = self.status_boss()
        if status.estado == 'DESCONHECIDO':
            return False, 'Relógio não sincronizado', status
        if status.estado == 'PRESENTE':
            return False, 'Boss presente', status
        if status.ate_proximo_spawn <= margem_segundos:
            return False, 'Próximo spawn muito próximo', status
        return True, 'Compra autorizada', status
