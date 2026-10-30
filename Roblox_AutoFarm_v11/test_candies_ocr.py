import errno
import tempfile
import threading
import time
import unittest
import subprocess
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
    'candies_20261029_121344_209229400': 319,
    'candies_20261029_123919_648236800': 322,
    'candies_20261029_131202_486410900': 335,
    'candies_20261029_131233_612493900': 335,
    'candies_20261029_131806_346122000': 344,
    'candies_20261029_131855_278207300': 344,
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
        available = [
            (name, expected)
            for name, expected in REAL_CAPTURE_VALUES.items()
            if (ROOT / 'diagnostico' / name / 'area_cliente.png').is_file()
        ]
        if not available:
            self.skipTest('Nenhuma captura local de diagnóstico está disponível.')

        for folder, expected in available:
            with self.subTest(captura=folder):
                shot = diagnostic_frame(folder)
                result = main.analyze_candies(shot, REGION)
                self.assertEqual(result.value, expected)
                self.assertEqual(result.reason, 'recognized')
                self.assertTrue(result.numerator_box or result.ocr_crop_box)

    def test_diagnostico_135445_classifica_09_como_incompleto_e_confirma_109(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))
        shot = diagnostic_frame('candies_20261029_135445_701718100')
        result = main.analyze_candies(shot, (587, 543, 778, 602))
        self.assertEqual(result.raw_texts, ('109', '09'))
        self.assertEqual(result.fallback_raw_texts, ('109/500', '109/500'))
        self.assertEqual(result.value, 109)
        self.assertEqual(result.reason, 'recognized')
        self.assertIn(('numerador_geometrico', '09'), result.leituras_inconclusivas)
        self.assertNotIn(('numerador_geometrico', 9), result.candidatos_validos)
        self.assertEqual(result.contradicoes, ())

    def test_fallback_malformado_500_0_nao_e_candidato_nem_contradicao(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['109', '', '500/0', '500/0']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'inconclusive')
        self.assertEqual(
            result.candidatos_validos,
            (('numerador_geometrico', 109),),
        )
        self.assertEqual(
            result.leituras_malformadas,
            (('linha_completa_500', '500/0'), ('linha_completa_500', '500/0')),
        )
        self.assertEqual(result.contradicoes, ())
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(main, 'DEBUG', Path(temp) / 'diagnostico'):
                folder = main.save_candies_diagnostic(
                    frame, {'candies_roi': list(REGION)}, result,
                    client_bbox=(0, 0, 1365, 700),
                )
            diagnostic = (folder / 'diagnostico.txt').read_text(encoding='utf-8')
        self.assertIn('["linha_completa_500", "500/0"]', diagnostic)
        self.assertIn('Decisão final:', diagnostic)
        self.assertIn('Menos de dois candidatos completos', diagnostic)

    def test_rotas_geometrica_e_fallback_concordantes_sao_aceitas(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['109', '', '109/500', '']):
            result = main.analyze_candies(frame, REGION)
        self.assertEqual(result.value, 109)
        self.assertEqual(result.reason, 'recognized')
        self.assertEqual(result.candidatos_validos, (
            ('numerador_geometrico', 109),
            ('linha_completa_500', 109),
        ))

    def test_rotas_validas_contraditorias_bloqueiam_leitura(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['109', '', '108/500', '']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'divergent')
        self.assertEqual(result.contradicoes, (108, 109))
        self.assertIn('bloqueada', result.motivo_decisao)

    def test_vinte_leituras_confirmadas_nao_sao_contaminadas_por_falha_isolada(self):
        readings = []
        interpretations = []
        for index in range(20):
            accepted = main.accumulate_analysis_result(
                main.CandiesOCRResult(
                    322, (322, 322), ('322', '322'), 'recognized', None, None
                ),
                100.0 + index * 2.0, readings, interpretations,
            )
            self.assertTrue(accepted)
        failed = main.CandiesOCRResult(
            None, (), (), 'ocr_error', None, None, 'falha transitória'
        )
        self.assertFalse(main.accumulate_analysis_result(
            failed, 141.0, readings, interpretations
        ))
        verdict = avaliar_leituras(readings, 142.0, meta=250,
                                   interpretacoes_brutas=interpretations)
        self.assertEqual(len(readings), 20)
        self.assertEqual(interpretations, [])
        self.assertTrue(verdict.confiavel_para_compra)

    def test_fallback_recupera_capturas_de_344_com_ambiguidades_dos_quatros(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))

        for folder in (
                'candies_20261029_131806_346122000',
                'candies_20261029_131855_278207300'):
            with self.subTest(captura=folder):
                shot = diagnostic_frame(folder)
                region = (587, 543, 778, 602)
                result = main.analyze_candies(shot, region)
                self.assertEqual(result.value, 344)
                self.assertEqual(result.reason, 'recognized')
                self.assertIsNone(result.numerator_box)
                self.assertEqual(result.fallback_raw_texts, ('344/500', '344/500'))
                self.assertEqual(result.rejection_stage, 'recognized')
                self.assertEqual(result.locator_trace['stage'], 'separator_ambiguity')
                self.assertEqual(result.counter_box, (623, 563, 744, 576))
                self.assertEqual(
                    result.locator_trace['separator_candidates'],
                    [
                        {'box': (60, 23, 66, 35), 'slope': -4.0},
                        {'box': (44, 25, 51, 35), 'slope': 3.5},
                        {'box': (52, 25, 59, 35), 'slope': 3.5},
                    ],
                )
                retained_boxes = {
                    component['box']
                    for component in result.locator_trace['components']
                    if component['retained']
                }
                self.assertTrue({
                    (36, 24, 43, 35),
                    (44, 25, 51, 35),
                    (52, 25, 59, 35),
                }.issubset(retained_boxes))
                self.assertEqual(
                    result.locator_trace['detail'],
                    'Esperado exatamente um layout numerador/separador/denominador; '
                    '2 layouts passaram pela geometria.',
                )
                self.assertEqual(
                    shot.crop(result.ocr_crop_box).size, (125, 17)
                )

    def test_fallback_recupera_denominador_parcial_sem_aceitar_00(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))

        for folder in (
                'candies_20261029_131202_486410900',
                'candies_20261029_131233_612493900'):
            with self.subTest(captura=folder):
                shot = diagnostic_frame(folder)
                result = main.analyze_candies(shot, (587, 543, 778, 602))
                self.assertEqual(result.value, 335)
                self.assertEqual(result.reason, 'recognized')
                self.assertEqual(
                    result.fallback_raw_texts, ('335/500', '335/500')
                )

    def test_captura_real_nao_corta_o_primeiro_digito_na_roi_padrao(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))
        shot = diagnostic_frame('candies_20261029_131855_278207300')
        region = (587, 543, 778, 602)
        result = main.analyze_candies(shot, region)
        self.assertEqual(result.value, 344)
        self.assertGreater(result.ocr_crop_box[0] - result.crop_box[0], 20)

    def test_primeiro_digito_parcialmente_cortado_fica_inconclusivo(self):
        shot = diagnostic_frame('candies_20261029_131855_278207300')
        clipped_region = (628, 543, 778, 602)
        with patch.object(main.pytesseract, 'image_to_string') as ocr:
            result = main.analyze_candies(shot, clipped_region)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'inconclusive')
        self.assertEqual(result.rejection_stage, 'line_bounds')
        ocr.assert_not_called()

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
        self.assertEqual(result.reason, 'inconclusive')

    def test_ocr_nao_exige_leitura_do_denominador(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['', '', '50/00', '50/00']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'inconclusive')
        self.assertEqual(result.fallback_raw_texts, ('50/00', '50/00'))

    def test_fallback_nao_aceita_denominador_incompleto(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['50', '', '50/00', '50/00']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'inconclusive')
        self.assertEqual(result.fallback_raw_texts, ('50/00', '50/00'))
        self.assertEqual(result.candidates, ())
        self.assertIn(('linha_completa_500', '50/00'), result.leituras_malformadas)

    def test_leitura_primaria_contraditoria_bloqueia_fallback_concordante(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['335', '', '344/500', '344/500']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'divergent')
        self.assertEqual(result.candidates, (335, 344, 344))

    def test_numeradores_de_um_dois_e_tres_digitos(self):
        frame = Image.new('RGB', (1365, 700), (0, 0, 0))
        for expected in (9, 50, 371):
            with self.subTest(valor=expected):
                digits = len(str(expected))
                width = {1: 10, 2: 22, 3: 25}[digits]
                trace = {
                    'stage': 'recognized',
                    'detail': 'mock geométrico',
                    'components': [],
                    'layouts': [{
                        'numerator_box': (20, 20, 20 + width, 31),
                    }],
                }
                with patch.object(
                        main, 'locate_candies_counter',
                        return_value=(
                            'recognized', (10, 15, 150, 40),
                            (20, 20, 20 + width, 31), trace,
                        )), \
                        patch.object(
                            main.pytesseract, 'image_to_string',
                            side_effect=[str(expected), str(expected), '', '']):
                    result = main.analyze_candies(frame, REGION)
                self.assertEqual(result.value, expected)

    def test_captura_real_em_resolucoes_e_escalas_diferentes(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))
        source = diagnostic_frame('candies_20261029_131855_278207300')
        for size in ((1024, 523), (2730, 1400)):
            with self.subTest(resolucao=size):
                shot = source.resize(size, Image.Resampling.LANCZOS)
                result = main.analyze_candies(shot, REGION)
                self.assertEqual(result.value, 344)
                self.assertEqual(result.reason, 'recognized')

    def test_ocr_fallback_funciona_em_escala_reduzida_com_denominador_validado(self):
        shot = diagnostic_frame(
            'candies_20261029_131855_278207300'
        ).resize((683, 348), Image.Resampling.LANCZOS)
        result = main.analyze_candies(shot, REGION)
        self.assertEqual(result.value, 344)
        self.assertEqual(result.reason, 'recognized')
        self.assertEqual(result.fallback_raw_texts, ('344/500', '344/500'))

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
        self.assertEqual(result.failures[0].exception_type, 'TesseractNotFoundError')

    def test_timeout_transitorio_e_recuperado_sem_contar_tentativa_como_leitura(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=[
                    RuntimeError('Tesseract process timeout'), '319', '319', '', ''
                ]) as ocr:
            result = main.analyze_candies(frame, REGION)
        self.assertEqual(result.value, 319)
        self.assertEqual(result.raw_texts, ('319', '319'))
        self.assertEqual(result.candidates, (319, 319))
        self.assertEqual(len(result.failures), 1)
        self.assertEqual(result.failures[0].exception_type, 'RuntimeError')
        self.assertIn('Traceback', result.failures[0].traceback_text)
        self.assertEqual(ocr.call_count, 5)

    def test_timeout_expirado_representado_pelo_subprocess_e_retentado(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=[
                    subprocess.TimeoutExpired('tesseract', 2.5),
                    '319', '319', '', '',
                ]):
            result = main.analyze_candies(frame, REGION)
        self.assertEqual(result.value, 319)
        self.assertEqual(result.failures[0].exception_type, 'TimeoutExpired')

    def test_timeout_esgotado_falha_sem_leitura_valida(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=[
                    RuntimeError('Tesseract process timeout'),
                    RuntimeError('Tesseract process timeout'),
                ]) as ocr:
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'ocr_timeout')
        self.assertEqual(len(result.failures), 2)
        self.assertEqual(ocr.call_count, 2)

    def test_erro_do_processo_tesseract_e_registrado_sem_retry(self):
        frame = reference_frame()
        failure = main.pytesseract.pytesseract.TesseractError(1, 'engine failure')
        with patch.object(
                main.pytesseract, 'image_to_string', side_effect=failure) as ocr:
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'ocr_error')
        self.assertEqual(result.failures[0].exception_type, 'TesseractError')
        self.assertIn('engine failure', result.failures[0].message)
        self.assertEqual(ocr.call_count, 1)

    def test_excecao_inesperada_preserva_traceback(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=ValueError('unexpected OCR issue')):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'ocr_error')
        self.assertEqual(result.failures[0].exception_type, 'ValueError')
        self.assertIn('unexpected OCR issue', result.failures[0].traceback_text)

    def test_traceback_e_gravado_no_diagnostico_e_arquivo_de_excecoes(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=ValueError('unexpected OCR issue')):
            result = main.analyze_candies(frame, REGION)
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(main, 'DEBUG', Path(temp) / 'diagnostico'):
                folder = main.save_candies_diagnostic(
                    frame, {'candies_roi': list(REGION)},
                    result, client_bbox=(0, 0, 1365, 700)
                )
                main.write_ocr_exception_log(result.failures, 'unit test')
            diagnostic = (folder / 'diagnostico.txt').read_text(encoding='utf-8')
            exception_log = (Path(temp) / 'diagnostico' /
                             'ocr_exceptions.log').read_text(encoding='utf-8')
        self.assertIn('Tipo da exceção: ValueError', diagnostic)
        self.assertIn('Tipo: ValueError', exception_log)
        for content in (diagnostic, exception_log):
            self.assertIn('Traceback completo:', content)
            self.assertIn('unexpected OCR issue', content)

    def test_diagnostico_registra_rejeicao_componentes_e_recorte_real(self):
        try:
            main.configure_tesseract({})
        except RuntimeError as exc:
            self.skipTest(str(exc))
        shot = diagnostic_frame('candies_20261029_131855_278207300')
        result = main.analyze_candies(shot, (587, 543, 778, 602))
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(main, 'DEBUG', Path(temp) / 'diagnostico'):
                folder = main.save_candies_diagnostic(
                    shot, {'candies_roi': [587, 543, 778, 602]}, result,
                    client_bbox=(0, 23, 1366, 720),
                )
            text = (folder / 'diagnostico.txt').read_text(encoding='utf-8')
            with Image.open(folder / 'recorte_enviado_tesseract.png') as sent_crop:
                sent_crop_size = sent_crop.size
        self.assertEqual(result.value, 344)
        self.assertEqual(sent_crop_size, (125, 17))
        self.assertIn('Etapa de rejeição geométrica/OCR: recognized', text)
        self.assertIn('"stage": "separator_ambiguity"', text)
        self.assertIn('separator_x', text)
        self.assertIn("['344/500', '344/500']", text)
        self.assertIn(
            'Retângulo enviado ao Tesseract (pixels da captura): '
            '(621, 561, 746, 578)',
            text,
        )

    def test_falha_transitoria_de_captura_recupera_sem_interferir_no_ocr(self):
        frame = reference_frame()
        with patch.object(
                main, 'screenshot_with_bbox',
                side_effect=[
                    OSError(errno.EBUSY, 'capture busy'),
                    (frame, (0, 0, 1365, 700)),
                ]), \
                patch.object(
                    main.pytesseract, 'image_to_string',
                    side_effect=['371', '371', '', '']):
            shot, bbox, result = main.capture_candies_attempt(REGION)
        self.assertIs(shot, frame)
        self.assertEqual(bbox, (0, 0, 1365, 700))
        self.assertEqual(result.value, 371)
        self.assertEqual(result.failures[0].stage, 'screen_capture')
        self.assertEqual(result.failures[0].exception_type, 'OSError')

    def test_falha_permanente_de_captura_nao_e_retentada(self):
        with patch.object(
                main, 'screenshot_with_bbox',
                side_effect=OSError(errno.EACCES, 'capture denied')) as capture, \
                patch.object(
                    main.pytesseract, 'image_to_string') as ocr:
            shot, bbox, result = main.capture_candies_attempt(REGION)
        self.assertIsNone(shot)
        self.assertIsNone(bbox)
        self.assertEqual(result.reason, 'capture_failed')
        self.assertEqual(capture.call_count, 1)
        ocr.assert_not_called()
        self.assertEqual(result.failures[0].exception_type, 'PermissionError')

    def test_operacoes_concorrentes_de_captura_e_ocr_sao_serializadas(self):
        frame = reference_frame()
        active = [0]
        maximum_active = [0]
        active_lock = threading.Lock()
        results = []

        def image_to_string(*args, **kwargs):
            with active_lock:
                active[0] += 1
                maximum_active[0] = max(maximum_active[0], active[0])
            time.sleep(0.02)
            with active_lock:
                active[0] -= 1
            return '371'

        def run_attempt():
            results.append(main.capture_candies_attempt(REGION)[2])

        with patch.object(
                main, 'screenshot_with_bbox',
                return_value=(frame, (0, 0, 1365, 700))), \
                patch.object(
                    main.pytesseract, 'image_to_string',
                    side_effect=image_to_string):
            workers = [threading.Thread(target=run_attempt) for _ in range(2)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=3)

        self.assertTrue(all(not worker.is_alive() for worker in workers))
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.value == 371 for result in results))
        self.assertEqual(maximum_active[0], 1)

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
                side_effect=['101', '101', '', '']):
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
                    'recorte_enviado_tesseract.png',
                    'diagnostico.txt'):
                self.assertTrue((folder / name).is_file())
            text = (folder / 'diagnostico.txt').read_text(encoding='utf-8')
            self.assertIn("'101'", text)
            self.assertIn('Etapa de rejeição geométrica/OCR', text)
            self.assertIn('Componentes de cor', text)
            self.assertIn('Retângulo enviado ao Tesseract', text)
            self.assertIn('Candidatos válidos por caminho', text)
            self.assertIn('Leituras malformadas por caminho', text)
            self.assertIn('Contradições válidas', text)
            self.assertIn('Decisão final', text)
            self.assertIn('1365x700', text)
            self.assertIn('Retângulo cliente na tela', text)

    def test_duas_variantes_contraditorias_bloqueiam(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['227', '277', '', '']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'divergent')

    def test_leitura_do_tesseract_incompleta_nao_inventa_digitos(self):
        frame = reference_frame()
        with patch.object(
                main.pytesseract, 'image_to_string',
                side_effect=['2/500', '', '2/500', '']):
            result = main.analyze_candies(frame, REGION)
        self.assertIsNone(result.value)
        self.assertEqual(result.reason, 'inconclusive')

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

    def test_teste_manual_solicitado_durante_automacao_nao_inicia(self):
        app = object.__new__(main.App)
        app.controller = SimpleNamespace(active=lambda: True)
        app._start_pending = False
        app.record_stage = None
        app.record_state = 'idle'
        app._ocr_test_running = False
        app.root = SimpleNamespace(
            withdraw=lambda: self.fail('não deve ocultar a interface')
        )
        with patch.object(main.messagebox, 'showwarning') as warning, \
                patch.object(threading, 'Thread') as thread:
            app.test_ocr()
        warning.assert_called_once()
        self.assertIn('Pare a automação', warning.call_args.args[1])
        thread.assert_not_called()

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

    def test_falha_ocr_nao_interrompe_coleta_durante_reproducao(self):
        offsets = (0, 1200, 2400, 3600, 4800)
        with tempfile.TemporaryDirectory() as temp:
            rec = Path(temp) / 'analise.rec'
            start_ms = 100000
            rec.write_bytes(b''.join(
                RECORD.pack(WM_MOUSEMOVE, 0, 0, start_ms + offset)
                for offset in offsets
            ))
            frame = reference_frame()
            emitted = []
            player_events = []
            ocr_calls = [0]

            class FakePlayer:
                position_transform = None

                def event(self, event):
                    player_events.append(event.offset)

                def release_all(self):
                    pass

            def flaky_ocr(*args, **kwargs):
                ocr_calls[0] += 1
                if ocr_calls[0] <= 2:
                    raise RuntimeError('Tesseract process timeout')
                return '371'

            controller = main.Controller(
                lambda key, value: emitted.append((key, value)), RelogioManual()
            )
            controller.cfg = {
                'analise': str(rec),
                'intervalo_ocr': 0.8,
                'candies_roi': list(REGION),
                'meta': 250,
            }
            with patch.object(main, 'activate_roblox_window'), \
                    patch.object(main, 'WindowsInput', return_value=FakePlayer()), \
                    patch.object(main, 'roblox_client_bbox',
                                 return_value=(0, 0, 1365, 700)), \
                    patch.object(main, 'carregar_geometria', return_value=None), \
                    patch.object(main, 'screenshot_with_bbox',
                                 return_value=(frame, (0, 0, 1365, 700))), \
                    patch.object(main.pytesseract, 'image_to_string',
                                 side_effect=flaky_ocr), \
                    patch.object(main, 'DEBUG', Path(temp) / 'diagnostico'):
                controller.run_macro('analise', inspect=True)

            exception_log = (
                Path(temp) / 'diagnostico' / 'ocr_exceptions.log'
            ).read_text(encoding='utf-8')

        self.assertEqual(player_events, [offset / 1000 for offset in offsets])
        self.assertGreaterEqual(ocr_calls[0], 4)
        self.assertTrue(any(
            key == 'candies' and value == '371' for key, value in emitted
        ))
        self.assertTrue(any(
            key == 'log' and 'Análise completa:' in value and
            'leituras válidas' in value
            for key, value in emitted
        ))
        self.assertIn('Tesseract process timeout', exception_log)
        self.assertIn('Traceback completo:', exception_log)


if __name__ == '__main__':
    unittest.main()
