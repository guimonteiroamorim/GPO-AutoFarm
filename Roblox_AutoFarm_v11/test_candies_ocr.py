import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

import main
from recplayer import RECORD, WM_MOUSEMOVE
from relogio_manual import RelogioManual
from seguranca_candies import avaliar_leituras


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / 'referencias' / 'candies.png'
REGION = tuple(main.ROIS['candies'])
REFERENCE_ORIGIN = (606, 549, 756, 590)
REAL_CAPTURE_VALUES = {
    'candies_20261028_170733_616634200': 50,
    'candies_20261028_171103_434200000': 50,
    'candies_20261028_171432_993846200': 63,
    'candies_20261028_171803_328321700': 62,
    'candies_20261028_171804_462955000': 62,
    'candies_20261028_172134_006960700': 59,
    'candies_20261028_172134_885900600': 59,
    'candies_20261028_172504_386297300': 55,
    'candies_20261028_172834_668647000': 61,
}


def reference_frame(region=REFERENCE_ORIGIN, size=(1365, 700)):
    frame = Image.new('RGB', size, (0, 0, 0))
    with Image.open(REFERENCE) as reference:
        sample = reference.convert('RGB')
    x1, y1, _, _ = region
    scale_x, scale_y = size[0] / 1365, size[1] / 700
    sample = sample.resize(
        (round(sample.width * scale_x), round(sample.height * scale_y)),
        Image.Resampling.NEAREST,
    )
    frame.paste(sample, (round(x1 * scale_x), round(y1 * scale_y)))
    return frame


def diagnostic_frame(name):
    path = ROOT / 'diagnostico' / name / 'area_cliente.png'
    if not path.is_file():
        raise unittest.SkipTest(f'Captura local de diagnóstico ausente: {path}')
    with Image.open(path) as shot:
        return shot.convert('RGB')


class TestCandiesOCR(unittest.TestCase):
    def test_leitura_real_da_captura_de_referencia(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))
        result = main.analyze_candies(reference_frame(), REGION)
        self.assertEqual(result.value, 101)
        self.assertEqual(result.reason, 'recognized')
        self.assertEqual(result.raw_texts, ('101', '101'))
        self.assertIsNotNone(result.counter_box)
        self.assertIsNotNone(result.numerator_box)

    def test_capturas_reais_do_diagnostico_recuperam_o_numerador(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))
        missing = [
            name for name in REAL_CAPTURE_VALUES
            if not (ROOT / 'diagnostico' / name / 'area_cliente.png').is_file()
        ]
        if missing:
            self.skipTest('Capturas locais de diagnóstico ausentes: ' + ', '.join(missing))

        for folder, expected in REAL_CAPTURE_VALUES.items():
            with self.subTest(captura=folder):
                shot = diagnostic_frame(folder)
                result = main.analyze_candies(shot, REGION)
                self.assertEqual(result.value, expected)
                self.assertEqual(result.reason, 'recognized')
                self.assertIsNotNone(result.numerator_box)

    def test_captura_real_nao_corta_o_primeiro_digito_na_roi_padrao(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))
        shot = diagnostic_frame('candies_20261028_170733_616634200')
        result = main.analyze_candies(shot, REGION)
        self.assertEqual(result.value, 50)
        self.assertGreater(result.numerator_box[0] - result.crop_box[0], 10)

    def test_primeiro_digito_parcialmente_cortado_fica_inconclusivo(self):
        shot = diagnostic_frame('candies_20261028_170733_616634200')
        clipped_region = (628, 535, 790, 610)
        result = main.analyze_candies(shot, clipped_region)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'unrecognized')

    def test_contador_ausente(self):
        blank = Image.new('RGB', (1365, 700), (20, 20, 20))
        with patch.object(main.pytesseract, 'image_to_string', return_value=''):
            result = main.analyze_candies(blank, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'not_visible')

    def test_texto_sem_o_formato_n_500_nao_e_estimado(self):
        frame = reference_frame()
        with patch.object(main.pytesseract, 'image_to_string', return_value='Candies'):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'unrecognized')

    def test_ocr_nao_exige_leitura_do_denominador(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['50/00', '50/00']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'unrecognized')

    def test_numeradores_de_um_dois_e_tres_digitos(self):
        frame = reference_frame()
        for expected in (9, 50, 371):
            with self.subTest(valor=expected), patch.object(
                    main.pytesseract, 'image_to_string',
                    side_effect=[str(expected), str(expected)]):
                result = main.analyze_candies(frame, REGION)
                self.assertEqual(result.value, expected)

    def test_captura_real_em_resolucoes_e_escalas_diferentes(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))
        source = diagnostic_frame('candies_20261028_171432_993846200')
        for size in ((1024, 523), (2730, 1400)):
            with self.subTest(resolucao=size):
                shot = source.resize(size, Image.Resampling.LANCZOS)
                result = main.analyze_candies(shot, REGION)
                self.assertEqual(result.value, 63)
                self.assertEqual(result.reason, 'recognized')

    def test_escala_com_detalhe_insuficiente_falha_fechado(self):
        shot = diagnostic_frame(
            'candies_20261028_171432_993846200'
        ).resize((683, 348), Image.Resampling.LANCZOS)
        result = main.analyze_candies(shot, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'unrecognized')

    def test_regiao_invalida_e_rejeitada(self):
        frame = Image.new('RGB', (1365, 700), (0, 0, 0))
        result = main.analyze_candies(frame, (1200, 650, 1400, 690))
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'invalid_region')

    def test_tesseract_indisponivel_fica_explicito(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=main.pytesseract.pytesseract.TesseractNotFoundError()):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'tesseract_unavailable')

    def test_caminho_tesseract_salvo_invalido_usa_instalacao_detectada(self):
        with patch.object(main, 'locate_tesseract', return_value=r'C:\Tesseract\tesseract.exe'), \
                patch.object(main.pytesseract, 'get_tesseract_version', return_value='5.4.0'), \
                patch.object(main.pytesseract.pytesseract, 'tesseract_cmd', 'tesseract'):
            engine, version, warning = main.configure_tesseract({
                'tesseract': r'C:\antigo\tesseract.exe'
            })
        self.assertEqual(engine, r'C:\Tesseract\tesseract.exe')
        self.assertEqual(version, '5.4.0')
        self.assertIn('não está disponível', warning)

    def test_salva_captura_recorte_preparacao_e_metadados(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['101', '101']):
            result = main.analyze_candies(frame, REGION)
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(main, 'DEBUG', Path(temp) / 'diagnostico'):
                folder = main.save_candies_diagnostic(
                    frame, {'candies_roi': list(REGION)}, result,
                    client_bbox=(10, 20, 1375, 720),
                )
            for name in (
                    'area_cliente.png', 'recorte_candies.png',
                    'preparada_tesseract.png', 'regiao_analisada.png',
                    'contador_localizado.png', 'numerador.png',
                    'diagnostico.txt'):
                self.assertTrue((folder / name).is_file())
            text = (folder / 'diagnostico.txt').read_text(encoding='utf-8')
            self.assertIn("'101'", text)
            self.assertIn('Separador e denominador validados visualmente', text)
            self.assertIn('1365x700', text)
            self.assertIn('Retângulo cliente na tela', text)

    def test_duas_variantes_contraditorias_bloqueiam(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['227', '277']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'divergent')

    def test_leitura_do_tesseract_incompleta_nao_inventa_digitos(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['2/500', '']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'unrecognized')

    def test_configuracao_padrao_antiga_migra_para_roi_ampla(self):
        old_config = {
            'candies_roi': [620, 554, 721, 585],
            'roi_coordinate_space': 'roblox_client_v2',
        }
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'config.json'
            config.write_text(__import__('json').dumps(old_config), encoding='utf-8')
            with patch.object(main, 'CFG', config):
                loaded = main.load()
        self.assertEqual(loaded['candies_roi'], list(REGION))

    def test_botao_de_ocr_bloqueia_durante_gravacao(self):
        app = object.__new__(main.App)
        app.controller = SimpleNamespace(active=lambda: False)
        app._start_pending = False
        app.record_stage = 'analise'
        app.record_state = 'recording'
        app._ocr_test_running = False
        app.root = SimpleNamespace(withdraw=lambda: self.fail('não deve ocultar a interface'))
        with patch.object(main.messagebox, 'showwarning') as warning, \
                patch.object(threading, 'Thread') as thread:
            app.test_ocr()
        warning.assert_called_once()
        self.assertIn('Interrompa ou cancele a gravação', warning.call_args.args[1])
        thread.assert_not_called()
        self.assertEqual(
            main.ocr_test_block_reason(False, False, True, False),
            'Interrompa ou cancele a gravação antes de testar o OCR.',
        )

    def test_botao_de_ocr_desabilitado_durante_reproducao(self):
        calls = []
        app = object.__new__(main.App)
        app.controller = SimpleNamespace(active=lambda: True)
        app._start_pending = False
        app.record_stage = None
        app.record_state = 'idle'
        app._ocr_test_running = False
        app.ocr_test_button = SimpleNamespace(
            configure=lambda **kwargs: calls.append(kwargs)
        )
        app._refresh_ocr_test_button()
        self.assertEqual(calls[-1]['state'], 'disabled')
        self.assertIn('Pare a automação', calls[-1]['text'])

    def test_teste_manual_bloqueia_reproducao_e_nova_gravacao(self):
        app = object.__new__(main.App)
        app._ocr_test_running = True
        with patch.object(main.messagebox, 'showwarning') as warning:
            app.start()
            app.arm_recording('analise')
        self.assertEqual(warning.call_count, 2)

    def test_compra_depende_de_leituras_confirmadas_e_relogio(self):
        fim = 112.0
        amostras = [(100.0 + i * 3.0, 277) for i in range(5)]
        validacao = avaliar_leituras(amostras, fim)
        self.assertTrue(validacao.confiavel_para_compra)

        incompletas = avaliar_leituras([], fim)
        divergentes = avaliar_leituras(
            [(100.0 + i * 2.0, value) for i, value in enumerate([227, 277, 277, 277, 277])],
            fim,
        )
        self.assertFalse(incompletas.confiavel_para_compra)
        self.assertFalse(divergentes.confiavel_para_compra)

        relogio = RelogioManual()
        self.assertFalse(relogio.pode_comprar(validacao.valor)[0])
        relogio.sincronizar('00:46:47')
        self.assertTrue(relogio.pode_comprar(validacao.valor, margem_segundos=185)[0])
        self.assertFalse(relogio.pode_comprar(validacao.valor, margem_segundos=800)[0])

    def test_ocr_nao_atraso_os_eventos_rec(self):
        offsets = (0, 800, 1600, 2400, 3200, 4000, 5000)
        with tempfile.TemporaryDirectory() as temp:
            rec = Path(temp) / 'analise.rec'
            start_ms = 100000
            rec.write_bytes(b''.join(
                RECORD.pack(WM_MOUSEMOVE, 0, 0, start_ms + offset)
                for offset in offsets
            ))
            frame = Image.new('RGB', (1365, 700), (0, 0, 0))
            seen = []

            class FakePlayer:
                position_transform = None

                def event(self, event):
                    seen.append((event.offset, time.monotonic()))

                def release_all(self):
                    pass

            def slow_ocr(*args, **kwargs):
                time.sleep(0.7)
                return '371'

            controller = main.Controller(lambda *_: None, RelogioManual())
            controller.cfg = {
                'analise': str(rec),
                'intervalo_ocr': 0.8,
                'candies_roi': list(REGION),
                'meta': 250,
            }
            with patch.object(main, 'activate_roblox_window'), \
                    patch.object(main, 'WindowsInput', return_value=FakePlayer()), \
                    patch.object(main, 'roblox_client_bbox', return_value=(0, 0, 1365, 700)), \
                    patch.object(main, 'carregar_geometria', return_value=None), \
                    patch.object(main, 'screenshot_with_bbox', return_value=(frame, (0, 0, 1365, 700))), \
                    patch.object(main.pytesseract, 'image_to_string', side_effect=slow_ocr), \
                    patch.object(main, 'DEBUG', Path(temp) / 'diagnostico'):
                controller.run_macro('analise', inspect=True)

        self.assertEqual(len(seen), len(offsets))
        start = seen[0][1]
        lateness = [actual - (start + expected) for expected, actual in seen]
        self.assertLess(max(lateness), 0.25)


if __name__ == '__main__':
    unittest.main()
