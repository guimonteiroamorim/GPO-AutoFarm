"""Verificações estruturais das alterações VISUAIS da v11."""
import ast
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent


class TestarAjustesUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.texto = (BASE / 'main.py').read_text(encoding='utf-8')
        cls.arvore = ast.parse(cls.texto)
        cls.app = next(n for n in cls.arvore.body if isinstance(n, ast.ClassDef) and n.name == 'App')

    def metodo(self, nome):
        return next(n for n in self.app.body if isinstance(n, ast.FunctionDef) and n.name == nome)

    def test_nome_exato_da_janela(self):
        self.assertIn("self.root.title('Roblox AutoFarm v11')", self.texto)
        self.assertNotIn('v11 Interface em Abas', self.texto)

    def test_tres_campos_readonly(self):
        ui = ast.get_source_segment(self.texto, self.metodo('construct'))
        self.assertIn("ttk.Entry(line, textvariable=self.fields[key], state='readonly')", ui)
        self.assertIn('command=lambda k=key:self.choose(k)', ui)
        self.assertIn('command=lambda k=key:self.arm_recording(k)', ui)
        self.assertIn('command=lambda k=key:self.export_recording(k)', ui)

    def test_rolagem_e_monitoramento(self):
        ui = ast.get_source_segment(self.texto, self.metodo('construct'))
        self.assertIn("canvas = tk.Canvas(automation_tab", ui)
        self.assertIn("text='Monitoramento'", ui)
        self.assertIn('self._on_automation_mousewheel', ui)

    def test_botoes_restauracao(self):
        ui = ast.get_source_segment(self.texto, self.metodo('construct'))
        self.assertEqual(ui.count('↺ Restaurar padrão'), 2)
        self.assertIn('command=self.restore_automation_defaults', ui)
        self.assertIn('command=self.restore_key_defaults', ui)
        auto = ast.get_source_segment(self.texto, self.metodo('restore_automation_defaults'))
        self.assertIn('self.invalidate_clock()', auto)
        self.assertIn('self.fields[key].set(DEFAULT[key])', auto)
        teclas = ast.get_source_segment(self.texto, self.metodo('restore_key_defaults'))
        self.assertIn("self.hotkey.set(DEFAULT['hotkey'].upper())", teclas)
        self.assertIn("self.record_hotkey.set(DEFAULT['record_hotkey'].upper())", teclas)

    def test_componentes_criticos_sem_alteracoes(self):
        anterior = Path('/mnt/data/Roblox_AutoFarm_v11_Abas')
        if not anterior.is_dir():
            self.skipTest('Versão anterior não presente (teste local opcional)')
        for name in ('gravador.py', 'recplayer.py', 'seguranca_candies.py',
                     'relogio_manual.py', 'gravacao_geometria.py'):
            self.assertEqual((anterior / name).read_bytes(), (BASE / name).read_bytes())
        for name in ('gravacao_coleta_1.rec', 'gravacao_analise_2.rec',
                     'gravacao_compra_3.rec'):
            self.assertEqual((anterior / 'gravacoes' / name).read_bytes(),
                             (BASE / 'gravacoes' / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
