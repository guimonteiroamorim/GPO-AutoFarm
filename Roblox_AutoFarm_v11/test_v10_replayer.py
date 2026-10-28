"""Verifica eventos e teclas sem clicar de verdade no jogo."""
from unittest.mock import Mock, patch
import unittest
import time

from recplayer import (WindowsInput, Event, WM_LBUTTONDOWN,
                       WM_LBUTTONUP, WM_MOUSEMOVE)


class ReprodutorSimulado(unittest.TestCase):
    def criar(self):
        p=WindowsInput.__new__(WindowsInput)
        p.position_transform=lambda x,y:(x+100,y+50)
        p.last_mouse_down_at={}
        p.held_mouse=set()
        p.held_keys=set()
        p.user32=Mock()
        p.user32.SetCursorPos.return_value=True
        p._position_mouse_for_click=Mock()
        p.mouse=Mock()
        return p

    def test_um_clique_uma_vez_e_na_posicao_transformada(self):
        p=self.criar()
        p.event(Event(0, WM_LBUTTONDOWN, 620, 378))
        p.event(Event(.12, WM_LBUTTONUP, 620, 378))
        p._position_mouse_for_click.assert_called_once_with(720,428)
        self.assertEqual(p.mouse.call_count,2)
        self.assertEqual(p.mouse.call_args_list[0].args,(0x0002,))
        self.assertEqual(p.mouse.call_args_list[1].args,(0x0004,))
        self.assertEqual(p.held_mouse,set())

    def test_movimentos_nao_viram_cliques(self):
        p=self.criar()
        p.event(Event(0, WM_MOUSEMOVE, 700, 400))
        p.user32.SetCursorPos.assert_called_once_with(800,450)
        p._position_mouse_for_click.assert_not_called()
        p.mouse.assert_not_called()

    def test_clique_muito_curto_alongado_para_80ms(self):
        p=self.criar()
        with patch('recplayer.time.sleep') as sleep:
            p.event(Event(0, WM_LBUTTONDOWN, 620, 378))
            p.event(Event(.01, WM_LBUTTONUP, 620, 378))
        self.assertTrue(sleep.called)
        self.assertGreater(sleep.call_args.args[0], 0)

if __name__=='__main__':
    unittest.main()
