"""Testes puros: não enviam teclas/cliques reais ao Windows."""
import tempfile
from pathlib import Path
from collections import Counter
from unittest.mock import patch
import unittest

from gravacao_geometria import (converter_ponto, salvar_geometria,
                                carregar_geometria, caminho_metadados)
from recplayer import read_rec, WM_LBUTTONDOWN, WM_LBUTTONUP, WM_MOUSEMOVE
from seguranca_candies import avaliar_leituras


class TestV10(unittest.TestCase):
    def test_mouse_coords_no_moved_window(self):
        self.assertEqual(converter_ponto(700, 400, (0, 24, 1366, 721),
                                         (0, 24, 1366, 721)), (700, 400))

    def test_mouse_coords_window_shift(self):
        self.assertEqual(converter_ponto(700, 400, (0, 24, 1366, 721),
                                         (100, 74, 1466, 771)), (800, 450))

    def test_mouse_coords_resize(self):
        self.assertEqual(converter_ponto(500, 250, (0,0,1000,500),
                                         (50,60,550,310)), (300,185))

    def test_outside_kept_as_is(self):
        self.assertEqual(converter_ponto(1500, 900, (0,0,1000,500),
                                         (50,60,550,310)), (1500,900))

    def test_metadata_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec=Path(tmp)/'my.rec'
            self.assertIsNone(carregar_geometria(rec))
            path=salvar_geometria(rec,(0,24,1366,721))
            self.assertTrue(path.is_file())
            self.assertEqual(path,caminho_metadados(rec))
            self.assertEqual(carregar_geometria(rec),(0,24,1366,721))

    def test_recorded_purchase_click_pairs(self):
        path=Path(__file__).parent/'gravacoes'/'gravacao_compra_3.rec'
        events=read_rec(path)
        counts=Counter(e.message for e in events)
        self.assertEqual(counts[WM_LBUTTONDOWN],3)
        self.assertEqual(counts[WM_LBUTTONUP],3)
        self.assertAlmostEqual(events[-1].offset,14.546,places=2)

    def test_candies_conflict_blocks(self):
        result=avaliar_leituras([(t,277) for t in [1,3,5,7,9]], 10,
                                interpretacoes_brutas=[277,227])
        self.assertFalse(result.confiavel_para_compra)

if __name__ == '__main__':
    unittest.main()
