import ast
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main


class TestRareChests(unittest.TestCase):
    def test_spinbox_manual_e_somente_leitura_mas_botoes_e_atualizacao_funcionam(self):
        source = Path(main.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        app = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == 'App'
        )
        construct = next(
            node for node in app.body
            if isinstance(node, ast.FunctionDef) and node.name == 'construct'
        )
        spinbox = next(
            node for node in ast.walk(construct)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'Spinbox'
        )
        state = next(
            (
                keyword.value.value for keyword in spinbox.keywords
                if keyword.arg == 'state'
            ),
            None,
        )
        self.assertEqual(state, 'readonly')

        try:
            root = main.tk.Tk()
        except main.tk.TclError as exc:
            self.skipTest(f'Tk não está disponível: {exc}')

        try:
            value = main.tk.StringVar(master=root, value='3')
            spin = main.ttk.Spinbox(
                root, from_=0, to=10, width=5, textvariable=value,
                state='readonly',
            )
            spin.pack()
            root.update()
            app = object.__new__(main.App)
            app.rare_chests_spinbox = spin
            app.controller = SimpleNamespace(active=lambda: False)
            app._start_pending = False
            app.record_stage = None
            app._refresh_rare_chests_controls()
            self.assertEqual(spin.instate(['readonly']), True)

            spin.focus_force()
            spin.event_generate('<KeyPress>', keysym='9')
            spin.event_generate('<KeyPress>', keysym='BackSpace')
            spin.event_generate('<KeyPress>', keysym='Delete')
            root.clipboard_clear()
            root.clipboard_append('8')
            root.update()
            spin.event_generate('<Control-v>')
            root.update()
            self.assertEqual(value.get(), '3')

            up_y = next(
                y for y in range(spin.winfo_height())
                if spin.identify(spin.winfo_width() - 4, y)
                == 'Spinbox.uparrow'
            )
            spin.event_generate(
                '<ButtonPress-1>', x=spin.winfo_width() - 4, y=up_y
            )
            spin.event_generate(
                '<ButtonRelease-1>', x=spin.winfo_width() - 4, y=up_y
            )
            root.update()
            self.assertEqual(value.get(), '4')

            down_y = next(
                y for y in range(spin.winfo_height())
                if spin.identify(spin.winfo_width() - 4, y)
                == 'Spinbox.downarrow'
            )
            value.set('7')
            root.update()
            self.assertEqual(spin.get(), '7')

            spin.event_generate(
                '<ButtonPress-1>', x=spin.winfo_width() - 4, y=down_y
            )
            spin.event_generate(
                '<ButtonRelease-1>', x=spin.winfo_width() - 4, y=down_y
            )
            root.update()
            self.assertEqual(value.get(), '6')

            value.set('7')
            for _ in range(3):
                spin.event_generate(
                    '<ButtonPress-1>', x=spin.winfo_width() - 4, y=up_y
                )
                spin.event_generate(
                    '<ButtonRelease-1>', x=spin.winfo_width() - 4, y=up_y
                )
                root.update()
            self.assertEqual(value.get(), '10')

            app.controller = SimpleNamespace(active=lambda: True)
            app._refresh_rare_chests_controls()
            self.assertEqual(spin.instate(['disabled']), True)
            disabled_value = value.get()
            spin.event_generate(
                '<ButtonPress-1>', x=spin.winfo_width() - 4, y=up_y
            )
            spin.event_generate(
                '<ButtonRelease-1>', x=spin.winfo_width() - 4, y=up_y
            )
            root.update()
            self.assertEqual(value.get(), disabled_value)

            app.controller = SimpleNamespace(active=lambda: False)
            app._refresh_rare_chests_controls()
            self.assertEqual(spin.instate(['readonly']), True)
        finally:
            root.destroy()

    def test_configuracao_antiga_inicia_zero_e_persiste_apos_reabrir(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            config.write_text(json.dumps({'hotkey': 'f12'}), encoding='utf-8')
            with patch.object(main, 'CFG', config):
                loaded = main.load()
                self.assertEqual(loaded['rare_chests'], 0)

                controller = main.Controller(lambda *_: None, None)
                self.assertEqual(controller.set_rare_chests(7, loaded), 7)
                self.assertEqual(main.load()['rare_chests'], 7)
                reopened = main.Controller(lambda *_: None, None, main.load()['rare_chests'])
                self.assertEqual(reopened.rare_chests, 7)

    def test_valores_validos_e_invalidos_do_contador(self):
        for value in (0, 7, 10):
            with self.subTest(value=value):
                self.assertEqual(main.validate_rare_chests(value), value)
        for value in (-1, 11, 7.5, '7', True, None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    main.validate_rare_chests(value)

    def test_edicao_manual_persiste_e_nao_permite_editar_em_execucao(self):
        class Variable:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            with patch.object(main, 'CFG', config):
                controller = main.Controller(lambda *_: None, None)
                app = object.__new__(main.App)
                app.controller = controller
                app.data = main.DEFAULT.copy()
                app._start_pending = False
                app.record_stage = None
                app._updating_rare_chests_ui = False
                app.rare_chests = Variable('0/10')
                app.rare_chests_input = Variable('10')

                for value in ('0', '7', '10'):
                    app.rare_chests_input.set(value)
                    self.assertTrue(app._commit_rare_chests())
                    self.assertEqual(app.data['rare_chests'], int(value))
                    self.assertEqual(
                        app.rare_chests.value,
                        main.rare_chests_display(int(value)),
                    )
                    self.assertEqual(main.load()['rare_chests'], int(value))
                self.assertFalse(app._validate_rare_chests_input('11'))
                self.assertFalse(app._validate_rare_chests_input('-1'))
                self.assertFalse(app._validate_rare_chests_input('abc'))

                controller.thread = SimpleNamespace(is_alive=lambda: True)
                app.rare_chests_input.set('3')
                with patch.object(main.messagebox, 'showwarning') as warning:
                    self.assertFalse(app._commit_rare_chests())
                warning.assert_called_once()
                self.assertEqual(controller.rare_chests, 10)

    def test_run_macro_bloqueia_compra_antes_de_carregar_gravacao_no_limite(self):
        controller = main.Controller(lambda *_: None, None, 10)
        controller.cfg = {'compra': 'nao-deve-ser-carregada.rec'}
        with patch.object(main, 'macro_recording') as recording:
            self.assertFalse(controller.run_macro('compra'))
        recording.assert_not_called()

    def test_analise_reproduz_todos_os_eventos_com_contador_no_limite(self):
        from recplayer import RECORD, WM_MOUSEMOVE

        with tempfile.TemporaryDirectory() as temp:
            recording = Path(temp) / 'analise.rec'
            recording.write_bytes(b''.join(
                RECORD.pack(WM_MOUSEMOVE, index, 0, 100000 + index * 10)
                for index in range(4)
            ))
            delivered = []

            class Player:
                position_transform = None

                def event(self, event):
                    delivered.append(event.data1)

                def release_all(self):
                    pass

            controller = main.Controller(lambda *_: None, None, 10)
            controller.cfg = {'analise': str(recording)}
            with patch.object(main, 'activate_roblox_window'), \
                    patch.object(main, 'WindowsInput', return_value=Player()), \
                    patch.object(
                        main, 'roblox_client_bbox',
                        return_value=(0, 0, 1365, 700)
                    ), \
                    patch.object(main, 'carregar_geometria', return_value=None):
                self.assertTrue(controller.run_macro('analise'))
            self.assertEqual(delivered, [0, 1, 2, 3])

    def test_compra_completa_incrementa_de_nove_para_dez_e_persiste(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            controller = main.Controller(lambda *_: None, None)
            controller.cfg = {'rare_chests': 9, 'meta': 250}
            controller._rare_chests = 9
            with patch.object(main, 'CFG', config):
                with patch.object(controller, 'run_macro', return_value=True):
                    self.assertTrue(controller.run_purchase())
                self.assertEqual(controller.rare_chests, 10)
                self.assertEqual(main.load()['rare_chests'], 10)

    def test_compra_cancelada_ou_com_erro_nao_incrementa(self):
        for result in (None, False):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as temp:
                controller = main.Controller(lambda *_: None, None)
                controller.cfg = {'rare_chests': 4}
                controller._rare_chests = 4
                with patch.object(main, 'CFG', Path(temp) / 'config.json'), \
                        patch.object(controller, 'run_macro', return_value=result):
                    self.assertFalse(controller.run_purchase())
                self.assertEqual(controller.rare_chests, 4)

        controller = main.Controller(lambda *_: None, None)
        controller.cfg = {'rare_chests': 4}
        controller._rare_chests = 4
        with patch.object(
                controller, 'run_macro',
                side_effect=RuntimeError('reprodução interrompida')):
            with self.assertRaisesRegex(RuntimeError, 'reprodução interrompida'):
                controller.run_purchase()
        self.assertEqual(controller.rare_chests, 4)

    def test_limite_bloqueia_qualquer_reproducao_de_compra(self):
        emitted = []
        controller = main.Controller(
            lambda key, value: emitted.append((key, value)), None
        )
        controller.cfg = {'rare_chests': 10}
        controller._rare_chests = 10
        with patch.object(controller, 'run_macro') as playback:
            self.assertFalse(controller.run_purchase())
            playback.assert_not_called()
        self.assertEqual(
            emitted[0],
            ('rare_chests', main.rare_chests_display(10)),
        )
        self.assertEqual(sum(key == 'log' for key, _ in emitted), 1)

    def test_limite_mantem_loop_integral_de_coleta_e_analise(self):
        emitted = []
        controller = main.Controller(
            lambda key, value: emitted.append((key, value)), None
        )
        controller.cfg = {'rare_chests': 10}
        controller._rare_chests = 10
        calls = []

        def play(key, inspect=False):
            calls.append((key, inspect))
            if key == 'coleta' and sum(k == 'coleta' for k, _ in calls) == 3:
                controller.stop.set()
            return None if key == 'analise' else True

        with patch.object(controller, 'run_macro', side_effect=play):
            controller.loop()

        self.assertEqual(
            calls,
            [
                ('coleta', False),
                ('analise', True),
                ('coleta', False),
                ('analise', True),
                ('coleta', False),
            ],
        )
        self.assertFalse(any(key == 'compra' for key, _ in calls))
        logs = [value for key, value in emitted if key == 'log']
        self.assertEqual(
            sum('Limite de 10 Rare Chests' in value for value in logs), 1
        )

    def test_reducao_manual_reabilita_compra_e_limita_no_dez(self):
        with tempfile.TemporaryDirectory() as temp:
            controller = main.Controller(lambda *_: None, None)
            controller.cfg = {'rare_chests': 10}
            controller._rare_chests = 10
            with patch.object(main, 'CFG', Path(temp) / 'config.json'):
                self.assertEqual(
                    controller.set_rare_chests(9, controller.cfg), 9
                )
                with patch.object(controller, 'run_macro', return_value=True) as play:
                    self.assertTrue(controller.run_purchase())
                play.assert_called_once_with('compra')
                self.assertEqual(controller.rare_chests, 10)

    def test_demais_validacoes_de_compra_continuam_ativas(self):
        status = SimpleNamespace(
            horario='00:40:00',
            estado='AUSENTE',
            ate_proximo_spawn=300,
        )

        class Clock:
            def __init__(self, authorized):
                self.authorized = authorized

            def pode_comprar(self, *_args, **_kwargs):
                return self.authorized, 'regra de compra', status

        def cycle(verdict, authorized):
            controller = main.Controller(lambda *_: None, Clock(authorized))
            controller.cfg = {
                'rare_chests': 0,
                'meta': 250,
                'duracao_compra_max_segundos': 45,
                'margem_compra_segundos': 35,
            }
            calls = []

            def play(key, inspect=False):
                calls.append(key)
                if key == 'coleta' and calls.count('coleta') == 2:
                    controller.stop.set()
                return verdict if key == 'analise' else True

            with patch.object(controller, 'run_macro', side_effect=play):
                controller.loop()
            return calls

        untrusted = SimpleNamespace(
            valor=300, confiavel_para_compra=False, motivo='leituras divergentes'
        )
        self.assertNotIn('compra', cycle(untrusted, True))
        below_meta = SimpleNamespace(
            valor=249, confiavel_para_compra=True, motivo='leituras válidas'
        )
        self.assertNotIn('compra', cycle(below_meta, True))
        authorized_readings = SimpleNamespace(
            valor=300, confiavel_para_compra=True, motivo='leituras válidas'
        )
        self.assertNotIn('compra', cycle(authorized_readings, False))


if __name__ == '__main__':
    unittest.main()
