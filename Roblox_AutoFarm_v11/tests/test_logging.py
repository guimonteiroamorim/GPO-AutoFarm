import queue
import ast
import unittest
from types import SimpleNamespace
from pathlib import Path

import main


class Logbox:
    def __init__(self):
        self.lines = []

    def configure(self, **_options):
        pass

    def insert(self, _position, text):
        self.lines.append(text)

    def see(self, _position):
        pass


class TestLogFlow(unittest.TestCase):
    def make_app(self):
        app = object.__new__(main.App)
        app.events = queue.Queue()
        app.logbox = Logbox()
        app.root = SimpleNamespace(after=lambda *_args: None)
        app.controller = SimpleNamespace(active=lambda: False)
        app._start_pending = False
        app.record_stage = None
        app.resource_switches = {'auto_purchases': object()}
        app._resource_controls_disabled = False
        app._ocr_test_running = False
        app._pending_error = None
        app._refresh_resource_switch = lambda _key: None
        app._refresh_ocr_test_button = lambda: None
        app._refresh_rare_chests_controls = lambda: None
        return app

    def test_informacoes_iniciais_nao_reaparecem_em_atualizacoes_periodicas(self):
        app = self.make_app()
        app._record_hotkey_name = 'f8'
        app._hotkey_name = 'f12'

        tree = ast.parse(Path(main.__file__).read_text(encoding='utf-8'))
        app_class = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == 'App'
        )
        callers = [
            node.name
            for node in app_class.body
            if isinstance(node, ast.FunctionDef)
            and any(
                isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == '_log_startup_information'
                for call in ast.walk(node)
            )
        ]
        self.assertEqual(callers, ['construct'])

        app._log_startup_information()
        startup_lines = list(app.logbox.lines)
        for _ in range(100):
            app._refresh_resource_controls()
            app.poll()

        self.assertEqual(len(startup_lines), 9)
        self.assertEqual(app.logbox.lines, startup_lines)

    def test_evento_novo_e_repeticao_apos_resolucao_sao_exibidos(self):
        app = self.make_app()

        app.events.put(('log', 'Conexão restabelecida.'))
        app.poll()
        app.poll()
        self.assertEqual(len(app.logbox.lines), 1)

        app.events.put(('log', 'Conexão restabelecida.'))
        app.poll()
        self.assertEqual(len(app.logbox.lines), 2)

    def test_nova_instancia_nao_reexibe_historico_da_instancia_anterior(self):
        first = self.make_app()
        first.events.put(('log', 'Compra autorizada na sessão anterior.'))
        first.poll()

        reopened = self.make_app()
        reopened._record_hotkey_name = 'f8'
        reopened._hotkey_name = 'f12'
        reopened._log_startup_information()

        self.assertEqual(len(first.logbox.lines), 1)
        self.assertEqual(len(reopened.logbox.lines), 9)
        self.assertFalse(any(
            'Compra autorizada na sessão anterior.' in line
            for line in reopened.logbox.lines
        ))

    def test_erros_e_alertas_sao_processados_sem_deduplicacao(self):
        app = self.make_app()

        app.events.put(('log', 'AVISO: leitura inconclusiva.'))
        app.events.put(('error', 'Falha ao validar a gravação.'))
        app.events.put(('error', 'Falha ao validar a gravação.'))
        app.poll()

        self.assertEqual(len(app.logbox.lines), 3)
        self.assertIn('AVISO: leitura inconclusiva.', app.logbox.lines[0])
        self.assertIn('ERRO: Falha ao validar a gravação.', app.logbox.lines[1])
        self.assertIn('ERRO: Falha ao validar a gravação.', app.logbox.lines[2])

    def test_eventos_de_estado_e_novos_logs_continuam_chegando_em_execucao(self):
        app = self.make_app()
        app.controller.active = lambda: True

        for message in ('Automação iniciada.', 'Coletando', 'Analisando Candies'):
            app.events.put(('log', message))
            app.poll()

        self.assertEqual(len(app.logbox.lines), 3)
        self.assertTrue(all(message in line for message, line in zip(
            ('Automação iniciada.', 'Coletando', 'Analisando Candies'),
            app.logbox.lines,
        )))


if __name__ == '__main__':
    unittest.main()
