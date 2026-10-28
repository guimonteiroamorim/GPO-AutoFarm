"""Metadados opcionais para ajustar coordenadas de cliques ao mover janela Roblox.

Arquivos .rec existentes continuam suportados. Gravações feitas na v10+ acompanham
um .meta.json que informa o retângulo de cliente usado durante a gravação.
"""
import json
import math
from pathlib import Path


def caminho_metadados(rec_path):
    return Path(str(rec_path) + '.meta.json')


def _retangulo(rect):
    if not isinstance(rect, (list, tuple)) or len(rect) != 4:
        raise ValueError('Retângulo inválido')
    vals = [int(v) for v in rect]
    if vals[2] <= vals[0] or vals[3] <= vals[1]:
        raise ValueError('Dimensões inválidas')
    return tuple(vals)


def salvar_geometria(rec_path, retangulo_cliente):
    box = _retangulo(retangulo_cliente)
    info = {'versao': 1, 'area_cliente_tela': list(box)}
    caminho = caminho_metadados(rec_path)
    caminho.write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding='utf-8')
    return caminho


def carregar_geometria(rec_path):
    caminho = caminho_metadados(rec_path)
    if not caminho.is_file():
        return None
    try:
        data = json.loads(caminho.read_text(encoding='utf-8'))
        if data.get('versao') != 1:
            return None
        return _retangulo(data['area_cliente_tela'])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def converter_ponto(x, y, origem, destino):
    """Mapeia posição absoluta registrada à geometria atual da janela.

    O ponto só é convertido se estava dentro da área cliente original.
    Pontos fora do jogo continuam inalterados, para permitir inspeção/erro seguro.
    """
    sx1, sy1, sx2, sy2 = _retangulo(origem)
    tx1, ty1, tx2, ty2 = _retangulo(destino)
    if not (sx1 <= x < sx2 and sy1 <= y < sy2):
        return x, y
    fx = (x - sx1) / (sx2 - sx1)
    fy = (y - sy1) / (sy2 - sy1)
    return round(tx1 + fx * (tx2 - tx1)), round(ty1 + fy * (ty2 - ty1))
