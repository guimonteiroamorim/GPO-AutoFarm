import ast
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from gravador import GravadorRec, WM_KEYDOWN

ROOT = Path(__file__).resolve().parent

class TestarInterfaceV11(unittest.TestCase):
    def test_tres_abas_e_controles_existentes(self):
        source = (ROOT/'main.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'App')
        ui = next(n for n in app.body if isinstance(n, ast.FunctionDef) and n.name == 'construct')
        strings = [n.value for n in ast.walk(ui) if isinstance(n, ast.Constant) and isinstance(n.value,str)]
        for label in ('  Automação  ', '  Configurações  ', '  Logs  ',
                      '● Gravar agora', '⬇', 'Sincronizar agora',
                      '▶ Iniciar', '■ Parar', 'Testar OCR', 'Calibrar Candies',
        'Verificar gravações', 'Abrir diagnóstico'):
            self.assertIn(label, strings)
        self.assertTrue(any('ESSENCIAL' in s and 'sincronize' in s for s in strings))
        self.assertEqual(sum('tabs.add(' in ast.get_source_segment(source, n) for n in ast.walk(ui) if isinstance(n,ast.Expr)),3)

    def test_tecla_gravacao_configuravel_nao_e_gravada(self):
        gravador = GravadorRec()
        gravador.set_record_hotkey('f9')
        gravador._recording = True
        gravador._t0 = 0
        gravador.keyboard_filter(WM_KEYDOWN, SimpleNamespace(vkCode=0x78,scanCode=0x43,flags=0))
        self.assertEqual(gravador._rows, [])
        gravador.keyboard_filter(WM_KEYDOWN, SimpleNamespace(vkCode=0x41,scanCode=0x1E,flags=0))
        self.assertEqual(len(gravador._rows),1)
        gravador._recording = False
        with self.assertRaises(ValueError):
            gravador.set_record_hotkey('f12')
        with self.assertRaises(ValueError):
            gravador.set_record_hotkey('f25')

    def test_formato_rec_e_motor_preservados(self):
        import hashlib
        base=Path('/mnt/data/Roblox_AutoFarm_v10_Cliques_Exportacao')
        if not base.is_dir(): self.skipTest('versão base indisponível')
        for file in ('recplayer.py','seguranca_candies.py','relogio_manual.py','gravacao_geometria.py'):
            self.assertEqual((base/file).read_bytes(),(ROOT/file).read_bytes())
        for file in ('gravacao_coleta_1.rec','gravacao_analise_2.rec','gravacao_compra_3.rec'):
            self.assertEqual((base/'gravacoes'/file).read_bytes(),(ROOT/'gravacoes'/file).read_bytes())

if __name__ == '__main__': unittest.main()
