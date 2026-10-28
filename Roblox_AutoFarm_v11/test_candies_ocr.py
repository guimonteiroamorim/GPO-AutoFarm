import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import main
from recplayer import RECORD, WM_MOUSEMOVE
from relogio_manual import RelogioManual
from seguranca_candies import avaliar_leituras


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / 'referencias' / 'candies.png'
REGION = (606, 549, 756, 590)


def reference_frame(region=REGION, size=(1365, 700)):
    frame = Image.new('RGB', size, (0, 0, 0))
    sample = Image.open(REFERENCE).convert('RGB')
    x1, y1, _, _ = region
    scale_x, scale_y = size[0] / 1365, size[1] / 700
    sample = sample.resize(
        (round(sample.width * scale_x), round(sample.height * scale_y)),
        Image.Resampling.NEAREST,
    )
    frame.paste(sample, (round(x1 * scale_x), round(y1 * scale_y)))
    return frame


class TestCandiesOCR(unittest.TestCase):
    def test_leitura_real_da_captura_de_referencia(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))
        result = main.analyze_candies(reference_frame(), REGION)
        self.assertEqual(result.value, 101)
        self.assertEqual(result.reason, 'recognized')
        self.assertIn('101/500', result.raw_texts[0])

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

    def test_resolucao_dupla_e_uma_leitura_exata_bastam(self):
        frame = reference_frame(size=(2730, 1400))
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['371/500 Candies', '0']):
            result = main.analyze_candies(frame, REGION)
        self.assertEqual(result.value, 371)
        self.assertEqual(result.crop_box, (1212, 1098, 1512, 1180))

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
                side_effect=['101/500', '0']):
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
                    'diagnostico.txt'):
                self.assertTrue((folder / name).is_file())
            text = (folder / 'diagnostico.txt').read_text(encoding='utf-8')
            self.assertIn('101/500', text)
            self.assertIn('1365x700', text)
            self.assertIn('Retângulo cliente na tela', text)

    def test_duas_variantes_contraditorias_bloqueiam(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['227/500', '277/500']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'divergent')

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
                return '371/500 Candies'

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
