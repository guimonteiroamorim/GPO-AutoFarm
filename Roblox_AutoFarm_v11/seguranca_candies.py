"""Validação conservadora de OCR em automação: uma divergência bloqueia compra.

A leitura do OCR é uma estimativa, não uma prova absoluta do valor no jogo.
As decisões de compra só são permitidas com leituras uniformes, recentes e
obtidas em quadros distintos durante a análise.
"""
from dataclasses import dataclass
from collections import Counter
import math


@dataclass(frozen=True)
class VereditoCandies:
    valor: int | None
    confiavel_para_compra: bool
    motivo: str
    total: int
    distintos: tuple[int, ...]


def avaliar_leituras(amostras, final_da_analise, meta=250,
                     minimo_leituras=5, duracao_minima=4.0,
                     idade_maxima=12.0, interpretacoes_brutas=None) -> VereditoCandies:
    """amostras: [(instante_monotonic, inteiro), ...] da análise atual.

    Nunca aproveita medições de análises anteriores. Falha fechada em
    conflitos, quantidade insuficiente de quadros ou dados não recentes.
    """
    leituras = []
    for instante, valor in amostras:
        if not isinstance(valor, int) or isinstance(valor, bool) or not 0 <= valor <= 500:
            continue
        if not isinstance(instante, (int, float)) or not math.isfinite(instante):
            continue
        if instante > final_da_analise + 0.5:
            continue
        leituras.append((float(instante), int(valor)))
    if not leituras:
        return VereditoCandies(None, False, 'Nenhuma leitura válida nesta análise.', 0, ())
    instantes_distintos = {instante for instante, _ in leituras}
    if len(instantes_distintos) < minimo_leituras:
        return VereditoCandies(
            None, False,
            f'Somente {len(instantes_distintos)} instantes distintos; '
            f'mínimo para compra: {minimo_leituras}.',
            len(leituras), tuple(sorted({valor for _, valor in leituras})),
        )

    valores = [valor for _, valor in leituras]
    distintos = tuple(sorted(set(valores)))
    # Não mostrar como 'confirmado' um número extraído de leituras conflitantes.
    if len(distintos) != 1:
        detalhe = ', '.join(f'{v} ({n}x)' for v, n in sorted(Counter(valores).items()))
        return VereditoCandies(None, False,
            f'LEITURAS DIVERGENTES: {detalhe}. Compra bloqueada.', len(valores), distintos)

    valor = distintos[0]
    # Mesmo que uma leitura divergente tenha sido rejeitada em uma das duas
    # transformações da imagem, ela continua sendo evidência para VETAR compra.
    # Isso evita que 227 (uma variante) + 277 (outra) vire 277 por maioria.
    if interpretacoes_brutas is not None:
        candidatos = [int(x) for x in interpretacoes_brutas
                      if isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 500]
        contradicoes = sorted(set(candidatos) - {valor})
        if contradicoes:
            return VereditoCandies(None, False,
                f'Variantes OCR contradizem {valor}: {contradicoes}. Compra bloqueada.',
                len(leituras), tuple(sorted(set(candidatos))))
    if valor < meta:
        return VereditoCandies(valor, False,
            f'{valor} Candies, abaixo da meta de {meta}.', len(valores), distintos)

    if len(leituras) < minimo_leituras:
        return VereditoCandies(None, False,
            f'Somente {len(leituras)} leituras; mínimo para compra: {minimo_leituras}.',
            len(leituras), distintos)

    instante_mais_antigo = min(t for t, _ in leituras)
    instante_mais_recente = max(t for t, _ in leituras)
    if instante_mais_recente - instante_mais_antigo < duracao_minima:
        return VereditoCandies(None, False,
            'As leituras não cobrem tempo suficiente da gravação de análise.',
            len(leituras), distintos)

    if final_da_analise - instante_mais_recente > idade_maxima:
        return VereditoCandies(None, False,
            'A última leitura é antiga demais para autorizar compra.',
            len(leituras), distintos)

    return VereditoCandies(valor, True,
        f'{len(leituras)} leituras concordantes de {valor} Candies.', len(leituras), distintos)
