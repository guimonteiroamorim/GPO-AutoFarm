import unittest
from pathlib import Path
from relogio_manual import RelogioManual
from recplayer import read_rec

class TestRelogioManual(unittest.TestCase):
    def setUp(self):
        self.clock = [100.0]
        self.relogio = RelogioManual(clock=lambda: self.clock[0])

    def test_avanca_monotonicamente(self):
        self.assertEqual(self.relogio.sincronizar('00:46:47'), '00:46:47')
        self.clock[0] += 300
        self.assertEqual(self.relogio.horario_atual(), '00:51:47')

    def test_boss_presente_nos_limites(self):
        self.relogio.sincronizar('00:25:00')
        self.assertEqual(self.relogio.status_boss().estado, 'PRESENTE')
        self.clock[0] += 599
        self.assertEqual(self.relogio.status_boss().estado, 'PRESENTE')
        self.clock[0] += 1
        self.assertEqual(self.relogio.status_boss().estado, 'AUSENTE')
        self.clock[0] += 25*60
        self.assertEqual(self.relogio.status_boss().estado, 'PRESENTE')

    def test_compra_segura(self):
        self.relogio.sincronizar('00:46:47')
        ok, _, status = self.relogio.pode_comprar(371, meta=250, margem_segundos=80)
        self.assertTrue(ok)
        self.assertAlmostEqual(status.ate_proximo_spawn, 793)
        ok, _, _ = self.relogio.pode_comprar(249)
        self.assertFalse(ok)

    def test_faltando_sessenta_segundos(self):
        self.relogio.sincronizar('00:59:00')
        ok, _, _ = self.relogio.pode_comprar(371, margem_segundos=80)
        self.assertFalse(ok)

    def test_sem_sincronizacao(self):
        ok, msg, status = self.relogio.pode_comprar(371)
        self.assertFalse(ok)
        self.assertEqual(status.estado, 'DESCONHECIDO')
        self.assertEqual(msg, 'Relógio não sincronizado')

    def test_invalida_ao_trocar_servidor(self):
        self.relogio.sincronizar('01:10:00')
        self.relogio.invalidar()
        self.assertIsNone(self.relogio.horario_atual())

    def test_formatos_invalidos(self):
        for valor in ('00:60:00', '00:59:60', 'abc', '00:11', '123456', '-1:22:33'):
            with self.subTest(valor=valor), self.assertRaises(ValueError):
                self.relogio.sincronizar(valor)

    def test_gravacoes_originais_completas(self):
        base = Path(__file__).parent / 'gravacoes'
        esperado = {
            'gravacao_coleta_1.rec': (89, 161.750),
            'gravacao_analise_2.rec': (5, 46.796),
            'gravacao_compra_3.rec': (193, 14.546),
        }
        for nome, (qtd, dur) in esperado.items():
            with self.subTest(nome=nome):
                ev = read_rec(base / nome)
                self.assertEqual(len(ev), qtd)
                self.assertAlmostEqual(ev[-1].offset, dur, places=3)

if __name__ == '__main__':
    unittest.main()
