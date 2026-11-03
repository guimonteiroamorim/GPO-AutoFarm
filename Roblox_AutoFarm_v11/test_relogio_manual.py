import unittest
import json
from pathlib import Path
from gravacao_geometria import carregar_geometria, caminho_metadados
from relogio_manual import RelogioManual
from recplayer import (
    RECORD,
    SUPPORTED,
    WM_KEYDOWN,
    WM_SYSKEYDOWN,
    is_record_stop_key,
    read_rec,
)

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
        nomes = (
            'gravacao_coleta_1.rec',
            'gravacao_analise_2.rec',
            'gravacao_compra_3.rec',
        )
        for nome in nomes:
            with self.subTest(nome=nome):
                path = base / nome
                raw = path.read_bytes()
                self.assertTrue(raw)
                self.assertEqual(len(raw) % RECORD.size, 0)
                records = list(RECORD.iter_unpack(raw))
                self.assertTrue(all(row[0] in SUPPORTED for row in records))

                timestamps = [row[3] for row in records]
                self.assertTrue(all(
                    later >= earlier
                    for earlier, later in zip(timestamps, timestamps[1:])
                ))
                self.assertLessEqual(
                    timestamps[-1] - timestamps[0], 60 * 60 * 1000
                )

                events = read_rec(path)
                self.assertEqual(len(events), len(records))
                self.assertEqual(events[0].offset, 0)
                self.assertTrue(all(
                    later.offset >= earlier.offset
                    for earlier, later in zip(events, events[1:])
                ))
                duration = (timestamps[-1] - timestamps[0]) / 1000
                self.assertAlmostEqual(events[-1].offset, duration, places=6)
                self.assertTrue(is_record_stop_key(events, len(events) - 1))
                self.assertIn(
                    events[-1].message, (WM_KEYDOWN, WM_SYSKEYDOWN)
                )

                if nome == 'gravacao_compra_3.rec':
                    metadata_path = caminho_metadados(path)
                    self.assertTrue(metadata_path.is_file())
                    metadata = json.loads(
                        metadata_path.read_text(encoding='utf-8')
                    )
                    self.assertEqual(metadata['versao'], 1)
                    geometry = carregar_geometria(path)
                    self.assertIsNotNone(geometry)
                    self.assertEqual(
                        tuple(metadata['area_cliente_tela']), geometry
                    )

if __name__ == '__main__':
    unittest.main()
