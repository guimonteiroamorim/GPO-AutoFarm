import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self):
        self.manager = 'pack'
        self.options = None

    def winfo_manager(self):
        return self.manager

    def pack(self, **options):
        before = options.get('before')
        if before is not None and not before.winfo_manager():
            raise AssertionError('pack-before target must be managed')
        self.manager = 'pack'
        self.options = options

    def pack_forget(self):
        self.manager = ''

    def configure(self, **options):
        self.options = options

    def delete(self, _tag):
        pass

    def create_rectangle(self, *_args, **_kwargs):
        pass

    def create_oval(self, *_args, **_kwargs):
        pass

    def create_text(self, *_args, **_kwargs):
        pass

class TestResourceToggles(unittest.TestCase):
    def test_configuracao_antiga_habilita_recursos_por_padrao(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            config.write_text(json.dumps({'hotkey': 'f12'}), encoding='utf-8')
            with patch.object(main, 'CFG', config):
                loaded = main.load()
            self.assertTrue(loaded['auto_purchases'])
            self.assertTrue(loaded['rare_chest_limit_enabled'])
            self.assertTrue(loaded['boss_control_enabled'])

    def test_toggles_e_contador_persistem_apos_reabrir(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            config.write_text(json.dumps({
                'rare_chests': 6,
                'auto_purchases': False,
                'rare_chest_limit_enabled': False,
                'boss_control_enabled': False,
            }), encoding='utf-8')
            with patch.object(main, 'CFG', config):
                loaded = main.load()
            self.assertEqual(loaded['rare_chests'], 6)
            self.assertFalse(loaded['auto_purchases'])
            self.assertFalse(loaded['rare_chest_limit_enabled'])
            self.assertFalse(loaded['boss_control_enabled'])

    def test_configuracao_reaberta_normaliza_limite_se_compras_estao_desligadas(self):
        configured = {
            **main.DEFAULT,
            'auto_purchases': False,
            'rare_chest_limit_enabled': True,
            'boss_control_enabled': True,
            'rare_chests': 5,
        }
        normalized = main.normalize_resource_settings(configured)
        self.assertFalse(normalized['rare_chest_limit_enabled'])
        self.assertFalse(normalized['boss_control_enabled'])
        self.assertEqual(normalized['rare_chests'], 5)
        self.assertTrue(configured['rare_chest_limit_enabled'])
        self.assertTrue(configured['boss_control_enabled'])

    def test_desativar_recursos_esconde_e_reativar_reexibe_elementos(self):
        app = object.__new__(main.App)
        app.resource_vars = {
            'auto_purchases': Variable(False),
            'rare_chest_limit_enabled': Variable(False),
            'boss_control_enabled': Variable(False),
        }
        app._resource_controls_disabled = False
        app.resource_switches = {}
        app.recording_rows = {'compra': Widget()}
        app.restore_automation_button = Widget()
        app.rare_chests_group = Widget()
        app.boss_group = Widget()
        app.monitor_actions = Widget()
        app.clock_warning = Widget()
        app.clock_controls = Widget()

        app._refresh_resource_visibility()
        self.assertEqual(app.recording_rows['compra'].winfo_manager(), '')
        self.assertEqual(app.rare_chests_group.winfo_manager(), '')
        self.assertEqual(app.boss_group.winfo_manager(), '')
        self.assertEqual(app.clock_controls.winfo_manager(), '')

        app.resource_vars['boss_control_enabled'].set(True)
        app._refresh_resource_visibility()
        self.assertEqual(app.boss_group.winfo_manager(), '')
        self.assertEqual(app.clock_controls.winfo_manager(), '')
        app.resource_vars['auto_purchases'].set(True)
        app._refresh_resource_visibility()
        self.assertEqual(app.boss_group.winfo_manager(), 'pack')
        self.assertEqual(app.clock_controls.winfo_manager(), 'pack')
        app.resource_vars['rare_chest_limit_enabled'].set(True)
        app._refresh_resource_visibility()
        self.assertEqual(app.rare_chests_group.winfo_manager(), 'pack')
        self.assertEqual(app.recording_rows['compra'].winfo_manager(), 'pack')
        self.assertEqual(app.boss_group.winfo_manager(), 'pack')

    def test_switches_estao_em_configuracoes_sem_botao_refresh(self):
        source = (Path(main.__file__).parent / 'main.py').read_text(encoding='utf-8')
        tree = __import__('ast').parse(source)
        app_class = next(
            node for node in tree.body
            if isinstance(node, __import__('ast').ClassDef) and node.name == 'App'
        )
        construct = next(
            node for node in app_class.body
            if isinstance(node, __import__('ast').FunctionDef)
            and node.name == 'construct'
        )
        ui = __import__('ast').get_source_segment(source, construct)
        self.assertIn("resources = ttk.LabelFrame(configs, text='Recursos'", ui)
        self.assertNotIn("resources = ttk.LabelFrame(automation_tab", ui)
        self.assertNotIn("text='↻'", ui)
        toggle = next(
            node for node in app_class.body
            if isinstance(node, __import__('ast').FunctionDef)
            and node.name == '_on_resource_toggle'
        )
        toggle_source = __import__('ast').get_source_segment(source, toggle)
        self.assertIn('self._refresh_resource_visibility()', toggle_source)
        self.assertIn('self._refresh_resource_controls(force=True)', toggle_source)

    def test_desativar_compras_desativa_limite_e_mantem_contador(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            app = object.__new__(main.App)
            app.resource_vars = {
                'auto_purchases': Variable(False),
                'rare_chest_limit_enabled': Variable(True),
                'boss_control_enabled': Variable(True),
            }
            app.resource_switches = {}
            app._resource_controls_disabled = False
            app.data = main.DEFAULT.copy()
            app.data['rare_chests'] = 8
            app.controller = SimpleNamespace(active=lambda: False, cfg=dict(app.data))
            app.relogio = SimpleNamespace(invalidar=lambda: None)
            app.clock_var = Variable('00:12:34 (manual)')
            app.boss = Variable('Ausente')
            app._start_pending = False
            app.record_stage = None
            app._refresh_resource_visibility = lambda: None
            app._refresh_resource_controls = lambda **_kwargs: None
            app.log = lambda _message: None

            with patch.object(main, 'CFG', config), \
                    patch.object(main.messagebox, 'askyesno', return_value=True) as confirm:
                app._on_resource_toggle('auto_purchases')

            self.assertIn('Rare Chests e o Controle do Boss', confirm.call_args.args[1])
            self.assertFalse(app.data['auto_purchases'])
            self.assertFalse(app.data['rare_chest_limit_enabled'])
            self.assertFalse(app.data['boss_control_enabled'])
            self.assertFalse(app.resource_vars['rare_chest_limit_enabled'].get())
            self.assertFalse(app.resource_vars['boss_control_enabled'].get())
            self.assertEqual(app.clock_var.get(), 'Não sincronizado')
            self.assertEqual(app.boss.get(), 'Desconhecido')
            persisted = json.loads(config.read_text(encoding='utf-8'))
            self.assertEqual(persisted['rare_chests'], 8)
            self.assertFalse(persisted['rare_chest_limit_enabled'])
            self.assertFalse(persisted['boss_control_enabled'])

    def test_reativar_boss_exige_nova_sincronizacao_sem_apagar_horario_digitado(self):
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            invalidations = []
            app = object.__new__(main.App)
            app.resource_vars = {
                'auto_purchases': Variable(True),
                'rare_chest_limit_enabled': Variable(False),
                'boss_control_enabled': Variable(True),
            }
            app.resource_switches = {}
            app.data = main.DEFAULT.copy()
            app.controller = SimpleNamespace(active=lambda: False, cfg=dict(app.data))
            app.relogio = SimpleNamespace(
                invalidar=lambda: invalidations.append(True)
            )
            app.clock_var = Variable('00:10:00 (manual)')
            app.boss = Variable('Ausente')
            app.clock_input = Variable('00:10:00')
            app._start_pending = False
            app.record_stage = None
            app._refresh_resource_visibility = lambda: None
            app._refresh_resource_controls = lambda **_kwargs: None
            app.log = lambda _message: None

            with patch.object(main, 'CFG', config), \
                    patch.object(main.messagebox, 'askyesno', return_value=True) as confirm:
                app.resource_vars['boss_control_enabled'].set(False)
                app._on_resource_toggle('boss_control_enabled')
                self.assertEqual(len(invalidations), 1)
                self.assertEqual(app.clock_var.get(), 'Não sincronizado')
                self.assertEqual(app.clock_input.get(), '00:10:00')
                confirm.assert_called_once()

                app.resource_vars['boss_control_enabled'].set(True)
                app._on_resource_toggle('boss_control_enabled')
                self.assertEqual(len(invalidations), 2)
                self.assertEqual(app.clock_var.get(), 'Não sincronizado')
                self.assertEqual(app.clock_input.get(), '00:10:00')
                confirm.assert_called_once()

    def test_switches_dependentes_ficam_inativos_sem_compras(self):
        app = object.__new__(main.App)
        app.resource_vars = {
            'auto_purchases': Variable(False),
            'rare_chest_limit_enabled': Variable(False),
            'boss_control_enabled': Variable(False),
        }
        app._resource_controls_disabled = False
        app.resource_switches = {
            key: Widget()
            for key in main.RESOURCE_TOGGLE_KEYS
        }

        for key in app.resource_switches:
            app._refresh_resource_switch(key)

        self.assertEqual(
            app.resource_switches['auto_purchases'].options['cursor'], 'hand2'
        )
        self.assertEqual(
            app.resource_switches['rare_chest_limit_enabled'].options['cursor'],
            'arrow',
        )
        self.assertFalse(
            app.resource_switches['rare_chest_limit_enabled'].options['takefocus']
        )
        self.assertEqual(
            app.resource_switches['boss_control_enabled'].options['cursor'],
            'arrow',
        )
        self.assertFalse(
            app.resource_switches['boss_control_enabled'].options['takefocus']
        )

    def test_cancelar_desativacao_nao_altera_estado_ou_persistencia(self):
        with tempfile.TemporaryDirectory() as temp:
            app = object.__new__(main.App)
            app.resource_vars = {'auto_purchases': Variable(False)}
            app.resource_switches = {}
            app.data = main.DEFAULT.copy()
            app.controller = SimpleNamespace(
                active=lambda: False, cfg=dict(app.data)
            )
            app.relogio = SimpleNamespace(invalidar=lambda: None)
            app.clock_var = Variable('Não sincronizado')
            app.boss = Variable('Desconhecido')
            app._start_pending = False
            app.record_stage = None
            app._refresh_resource_visibility = lambda: None
            logged = []
            app.log = logged.append
            config = Path(temp) / 'config.json'

            with patch.object(main, 'CFG', config), \
                    patch.object(main.messagebox, 'askyesno', return_value=False):
                app._on_resource_toggle('auto_purchases')

            self.assertTrue(app.resource_vars['auto_purchases'].get())
            self.assertTrue(app.data['auto_purchases'])
            self.assertFalse(config.exists())

    def test_confirmar_desativacao_persiste_imediatamente(self):
        with tempfile.TemporaryDirectory() as temp:
            app = object.__new__(main.App)
            app.resource_vars = {
                'auto_purchases': Variable(True),
                'rare_chest_limit_enabled': Variable(False),
                'boss_control_enabled': Variable(True),
            }
            app.resource_switches = {}
            app.data = main.DEFAULT.copy()
            app.data['rare_chests'] = 7
            app.controller = SimpleNamespace(active=lambda: False, cfg=dict(app.data))
            app.relogio = SimpleNamespace(invalidar=lambda: None)
            app.clock_var = Variable('Não sincronizado')
            app.boss = Variable('Desconhecido')
            app._start_pending = False
            app.record_stage = None
            app._refresh_resource_visibility = lambda: None
            logged = []
            app.log = logged.append
            config = Path(temp) / 'config.json'

            with patch.object(main, 'CFG', config), \
                    patch.object(main.messagebox, 'askyesno', return_value=True):
                app._on_resource_toggle('rare_chest_limit_enabled')

            persisted = json.loads(config.read_text(encoding='utf-8'))
            self.assertFalse(persisted['rare_chest_limit_enabled'])
            self.assertEqual(persisted['rare_chests'], 7)
            self.assertFalse(app.controller.cfg['rare_chest_limit_enabled'])
            self.assertEqual(len(logged), 1)
            self.assertIn('rare_chest_limit_enabled: desativado', logged[0])

    def test_sem_compras_loopa_coleta_e_analise_sem_validar_candies(self):
        controller = main.Controller(lambda *_: None, None)
        controller.cfg = {'auto_purchases': False, 'rare_chests': 0}
        calls = []

        def play(key, inspect=False):
            calls.append((key, inspect))
            if key == 'coleta' and calls.count(('coleta', False)) == 2:
                controller.stop.set()
            return None if key == 'analise' else True

        with patch.object(controller, 'run_macro', side_effect=play):
            controller.loop()

        self.assertEqual(
            calls,
            [('coleta', False), ('analise', False), ('coleta', False)],
        )

    def test_sem_compras_nao_exige_validar_gravacao_de_compra_ao_iniciar(self):
        controller = main.Controller(lambda *_: None, None)
        config = {
            **main.DEFAULT,
            'auto_purchases': False,
        }
        with tempfile.TemporaryDirectory() as temp:
            recording = Path(temp) / 'stage.rec'
            recording.touch()
            with patch.object(main, 'macro_recording', return_value=recording) as macro, \
                    patch.object(main, 'read_rec'), \
                    patch.object(main, 'configure_tesseract') as configure_tesseract, \
                    patch.object(main.threading, 'Thread') as thread:
                self.assertTrue(controller.start(config))
        self.assertEqual(macro.call_count, 2)
        configure_tesseract.assert_not_called()
        self.assertFalse(controller.cfg['rare_chest_limit_enabled'])
        self.assertFalse(controller.cfg['boss_control_enabled'])
        thread.return_value.start.assert_called_once()

    def test_boss_desativado_nao_consulta_relogio_e_compra_validada_pelos_candies(self):
        class Clock:
            def pode_comprar(self, *_args, **_kwargs):
                raise AssertionError('o relógio não deve ser consultado')

        with tempfile.TemporaryDirectory() as temp:
            controller = main.Controller(lambda *_: None, Clock())
            controller.cfg = {
                'auto_purchases': True,
                'rare_chest_limit_enabled': True,
                'boss_control_enabled': False,
                'rare_chests': 0,
                'meta': 250,
            }
            verdict = SimpleNamespace(
                valor=300, confiavel_para_compra=True, motivo='leituras válidas'
            )
            calls = []

            def play(key, inspect=False):
                calls.append(key)
                if key == 'compra':
                    controller.stop.set()
                    return True
                return verdict if key == 'analise' else True

            with patch.object(main, 'CFG', Path(temp) / 'config.json'), \
                    patch.object(controller, 'run_macro', side_effect=play):
                controller.loop()

            self.assertIn('compra', calls)
            self.assertEqual(calls[:3], ['coleta', 'analise', 'compra'])

    def test_boss_reativado_volta_a_exigir_relogio_sincronizado(self):
        status = SimpleNamespace(
            horario=None, estado='DESCONHECIDO', ate_proximo_spawn=0
        )

        class Clock:
            calls = 0

            def pode_comprar(self, *_args, **_kwargs):
                self.calls += 1
                return False, 'relógio não sincronizado', status

        controller_clock = Clock()
        controller = main.Controller(lambda *_: None, controller_clock)
        controller.cfg = {
            'auto_purchases': True,
            'rare_chest_limit_enabled': True,
            'boss_control_enabled': True,
            'rare_chests': 0,
            'meta': 250,
            'duracao_compra_max_segundos': 45,
            'margem_compra_segundos': 35,
        }
        verdict = SimpleNamespace(
            valor=300, confiavel_para_compra=True, motivo='leituras válidas'
        )
        calls = []

        def play(key, inspect=False):
            calls.append(key)
            if key == 'coleta' and calls.count('coleta') == 2:
                controller.stop.set()
            return verdict if key == 'analise' else True

        with patch.object(controller, 'run_macro', side_effect=play):
            controller.loop()

        self.assertEqual(controller_clock.calls, 1)
        self.assertNotIn('compra', calls)

    def test_limite_desativado_nao_bloqueia_nem_altera_contador_salvo(self):
        controller = main.Controller(lambda *_: None, None, 10)
        controller.cfg = {
            'auto_purchases': True,
            'rare_chest_limit_enabled': False,
            'rare_chests': 10,
        }
        with patch.object(controller, 'run_macro', return_value=True) as playback:
            self.assertTrue(controller.run_purchase())
        playback.assert_called_once_with('compra')
        self.assertEqual(controller.rare_chests, 10)


if __name__ == '__main__':
    unittest.main()
