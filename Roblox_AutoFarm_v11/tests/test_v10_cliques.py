"""Testes puros: não enviam teclas/cliques reais ao Windows."""
import json
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch
import unittest
import main

PROJECT_ROOT = Path(__file__).resolve().parents[1]

from gravacao_geometria import (converter_ponto, salvar_geometria,
                                carregar_geometria, caminho_metadados)
from recplayer import (
    WM_LBUTTONDOWN,
    WM_LBUTTONUP,
    WM_MBUTTONDOWN,
    WM_MBUTTONUP,
    WM_RBUTTONDOWN,
    WM_RBUTTONUP,
    is_record_stop_key,
    read_rec,
)
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

    def test_recorded_purchase_click_pairs_and_metadata(self):
        path = PROJECT_ROOT / 'gravacoes' / 'gravacao_compra_3.rec'
        events = read_rec(path)
        geometry = carregar_geometria(path)
        self.assertIsNotNone(geometry)

        with caminho_metadados(path).open(encoding='utf-8') as metadata_file:
            metadata = json.load(metadata_file)
        self.assertEqual(metadata['versao'], 1)
        self.assertEqual(tuple(metadata['area_cliente_tela']), geometry)

        down_to_up = {
            WM_LBUTTONDOWN: WM_LBUTTONUP,
            WM_RBUTTONDOWN: WM_RBUTTONUP,
            WM_MBUTTONDOWN: WM_MBUTTONUP,
        }
        up_to_down = {up: down for down, up in down_to_up.items()}
        held_buttons = set()
        click_count = 0
        x1, y1, x2, y2 = geometry
        for event in events:
            if event.message in down_to_up:
                self.assertNotIn(event.message, held_buttons)
                self.assertGreaterEqual(event.data1, x1)
                self.assertLess(event.data1, x2)
                self.assertGreaterEqual(event.data2, y1)
                self.assertLess(event.data2, y2)
                held_buttons.add(event.message)
                click_count += 1
            elif event.message in up_to_down:
                button_down = up_to_down[event.message]
                self.assertIn(button_down, held_buttons)
                held_buttons.remove(button_down)
        self.assertFalse(held_buttons, 'A gravação terminou com um botão pressionado.')
        self.assertGreater(click_count, 0)
        self.assertTrue(is_record_stop_key(events, len(events) - 1))

    def test_current_purchase_recording_plays_all_events_without_real_input(self):
        path = PROJECT_ROOT / 'gravacoes' / 'gravacao_compra_3.rec'
        events = read_rec(path)
        expected = [
            event for index, event in enumerate(events)
            if not is_record_stop_key(events, index)
        ]
        geometry = carregar_geometria(path)
        self.assertIsNotNone(geometry)
        delivered = []
        clock = [100.0]

        class FakePlayer:
            position_transform = None

            def event(self, event):
                delivered.append(event)

            def release_all(self):
                pass

        def wait_until_next_event(timeout):
            clock[0] += timeout
            return False

        controller = main.Controller(lambda *_: None, None)
        controller.cfg = {'compra': str(path)}
        controller.stop.wait = Mock(side_effect=wait_until_next_event)
        focus_check = Mock(return_value=True)
        client_bbox = Mock(return_value=geometry)
        with patch.object(main.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(main, 'activate_roblox_window'), \
                patch.object(main, 'WindowsInput', return_value=FakePlayer()), \
                patch.object(main, 'roblox_em_primeiro_plano', focus_check), \
                patch.object(main, 'roblox_client_bbox', client_bbox):
            self.assertTrue(controller.run_macro('compra'))

        self.assertEqual(delivered, expected)
        click_count = sum(event.message == WM_LBUTTONDOWN for event in events)
        self.assertEqual(focus_check.call_count, click_count)
        self.assertEqual(client_bbox.call_count, 1 + click_count)

    def test_candies_conflict_blocks(self):
        result=avaliar_leituras([(t,277) for t in [1,3,5,7,9]], 10,
                                interpretacoes_brutas=[277,227])
        self.assertFalse(result.confiavel_para_compra)

if __name__ == '__main__':
    unittest.main()
