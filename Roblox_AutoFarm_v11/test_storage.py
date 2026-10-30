import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from gravacao_geometria import carregar_geometria, caminho_metadados
from recplayer import RECORD, WM_MOUSEMOVE


ROOT = Path(__file__).resolve().parent


def write_recording(path, timestamp=1000):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(RECORD.pack(WM_MOUSEMOVE, 10, 20, timestamp))
    return path


class TestCustomRecordingStorage(unittest.TestCase):
    def test_categoria_so_troca_personalizada_preservando_outras_e_externas(self):
        with tempfile.TemporaryDirectory() as temp:
            custom = Path(temp) / 'persistente' / 'gravacoes'
            external = Path(temp) / 'Downloads' / 'doce.rec'
            external_bytes = write_recording(external).read_bytes()
            with patch.object(main, 'CUSTOM_RECORDINGS_DIR', custom):
                collect = write_recording(custom / 'coleta_personalizada.rec')
                main.salvar_geometria(collect, (1, 2, 101, 202))
                analysis = write_recording(custom / 'analise_personalizada.rec', 2000)
                purchase = write_recording(custom / 'compra_personalizada.rec', 3000)
                main.salvar_geometria(analysis, (5, 6, 105, 206))
                main.salvar_geometria(purchase, (7, 8, 107, 208))
                main.salvar_geometria(external, (9, 10, 109, 210))
                analysis_bytes = analysis.read_bytes()
                purchase_bytes = purchase.read_bytes()
                analysis_meta = caminho_metadados(analysis).read_bytes()
                purchase_meta = caminho_metadados(purchase).read_bytes()
                external_meta = caminho_metadados(external).read_bytes()
                old_rec = collect.read_bytes()
                staged = write_recording(custom / '.coleta-new.staging.rec', 4000)
                selected = []

                result = main.publish_custom_recording(
                    'coleta', staged, (11, 22, 111, 222),
                    lambda path: selected.append(path),
                )

                self.assertEqual(result, collect)
                self.assertEqual(selected, [collect])
                self.assertNotEqual(collect.read_bytes(), old_rec)
                self.assertEqual(analysis.read_bytes(), analysis_bytes)
                self.assertEqual(purchase.read_bytes(), purchase_bytes)
                self.assertEqual(caminho_metadados(analysis).read_bytes(), analysis_meta)
                self.assertEqual(caminho_metadados(purchase).read_bytes(), purchase_meta)
                self.assertEqual(carregar_geometria(collect), (11, 22, 111, 222))
                self.assertEqual(external.read_bytes(), external_bytes)
                self.assertEqual(caminho_metadados(external).read_bytes(), external_meta)
                self.assertFalse(staged.exists())

    def test_falha_ao_persistir_selecao_restaura_rec_e_metadados_anteriores(self):
        with tempfile.TemporaryDirectory() as temp:
            custom = Path(temp) / 'gravacoes'
            with patch.object(main, 'CUSTOM_RECORDINGS_DIR', custom):
                target = write_recording(custom / 'coleta_personalizada.rec')
                main.salvar_geometria(target, (1, 2, 101, 202))
                old_rec = target.read_bytes()
                old_meta = caminho_metadados(target).read_bytes()
                staged = write_recording(custom / '.failed.staging.rec', 5000)

                with self.assertRaisesRegex(OSError, 'config indisponível'):
                    main.publish_custom_recording(
                        'coleta', staged, (3, 4, 103, 204),
                        lambda _path: (_ for _ in ()).throw(
                            OSError('config indisponível')
                        ),
                    )

                self.assertEqual(target.read_bytes(), old_rec)
                self.assertEqual(caminho_metadados(target).read_bytes(), old_meta)
                self.assertEqual(carregar_geometria(target), (1, 2, 101, 202))
                self.assertFalse(staged.exists())

    def test_selecao_personalizada_persiste_apos_reabrir_configuracao(self):
        with tempfile.TemporaryDirectory() as temp:
            custom = write_recording(
                Path(temp) / 'gravacoes' / 'analise_personalizada.rec'
            )
            config = Path(temp) / 'config.json'
            with patch.object(main, 'CFG', config):
                main.atomic_write_json(config, {'analise': str(custom)})
                loaded = main.load()
            self.assertEqual(loaded['analise'], str(custom))
            self.assertEqual(main.resolve(loaded['analise']), custom)

    def test_resolve_separa_recursos_padrao_dados_legados_e_customizados(self):
        with tempfile.TemporaryDirectory() as temp:
            bundle = Path(temp) / '_internal'
            user_data = Path(temp) / 'localappdata' / 'GPO_AutoFarm_v11'
            custom_data = Path(temp) / 'localappdata' / 'GPO_AutoFarm_v11'
            standard = write_recording(
                bundle / 'gravacoes' / 'gravacao_coleta_1.rec'
            )
            legacy = write_recording(
                user_data / 'gravacoes' / 'gravacao_compra_20261029_182556.rec'
            )
            custom = write_recording(
                custom_data / 'gravacoes' / 'coleta_personalizada.rec'
            )
            with patch.multiple(
                    main, FROZEN=True, BUNDLE_ROOT=bundle,
                    USER_DATA=user_data, ROOT=Path(temp) / 'source',
                    CUSTOM_RECORDINGS_DIR=custom_data / 'gravacoes'):
                self.assertEqual(
                    main.resolve(main.DEFAULT['coleta']), standard
                )
                self.assertEqual(
                    main.resolve('gravacoes/gravacao_compra_20261029_182556.rec'),
                    legacy,
                )
                self.assertEqual(main.resolve(str(custom)), custom)
                self.assertNotIn('_internal', str(main.resolve(str(custom))))

    def test_f8_salva_em_nome_personalizado_e_persiste_selecao(self):
        class Field:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        class Recorder:
            def finish(self, path):
                write_recording(path, 5000)
                return {'wheel_ignored': 0}

            def cancel(self):
                pass

        with tempfile.TemporaryDirectory() as temp:
            custom = Path(temp) / 'localappdata' / 'GPO_AutoFarm_v11' / 'gravacoes'
            config = Path(temp) / 'config.json'
            app = object.__new__(main.App)
            app.record_state = 'recording'
            app.record_stage = 'coleta'
            app.recording_client_bbox = (10, 20, 810, 620)
            app.recorder = Recorder()
            app.fields = {'coleta': Field(main.DEFAULT['coleta'])}
            app.data = {'coleta': main.DEFAULT['coleta']}
            app.status = SimpleNamespace(set=lambda _value: None)
            app._restore_interface = lambda: None
            app.log = lambda _message: None

            def save():
                main.atomic_write_json(config, {
                    **app.data, 'coleta': app.fields['coleta'].get()
                })
                return True

            app.save = save
            with patch.object(main, 'CUSTOM_RECORDINGS_DIR', custom):
                app._record_f8()

            selected = custom / 'coleta_personalizada.rec'
            self.assertEqual(app.fields['coleta'].get(), str(selected))
            self.assertTrue(selected.is_file())
            self.assertEqual(carregar_geometria(selected), (10, 20, 810, 620))
            with patch.object(main, 'CFG', config):
                self.assertEqual(main.load()['coleta'], str(selected))
            self.assertEqual(app.record_state, 'idle')

    def test_cancelar_gravacao_nao_toca_na_personalizada_existente(self):
        with tempfile.TemporaryDirectory() as temp:
            custom = Path(temp) / 'coleta_personalizada.rec'
            original = write_recording(custom).read_bytes()
            app = object.__new__(main.App)
            app.recorder = SimpleNamespace(cancel=lambda: None)
            app.recording_client_bbox = (0, 0, 1, 1)
            app.record_stage = 'coleta'
            app.record_state = 'recording'
            app.status = SimpleNamespace(set=lambda _value: None)
            app._restore_interface = lambda: None
            app.log = lambda _message: None

            app._cancel_recording()

            self.assertEqual(custom.read_bytes(), original)

    def test_restaurar_padrao_nao_exclui_personalizada(self):
        class Field:
            def __init__(self, value):
                self.value = value

            def get(self):
                return self.value

            def set(self, value):
                self.value = value

        with tempfile.TemporaryDirectory() as temp:
            custom = write_recording(
                Path(temp) / 'coleta_personalizada.rec'
            )
            original = custom.read_bytes()
            app = object.__new__(main.App)
            app.controller = SimpleNamespace(active=lambda: False)
            app._start_pending = False
            app.record_stage = None
            app.fields = {
                key: Field(str(custom) if key == 'coleta' else 'external.rec')
                for key in ('coleta', 'analise', 'compra')
            }
            app.data = {}
            app.clock_input = SimpleNamespace(set=lambda _value: None)
            app.clock_var = SimpleNamespace(set=lambda _value: None)
            app.boss = SimpleNamespace(set=lambda _value: None)
            app.relogio = SimpleNamespace(invalidar=lambda: None)
            app.log = lambda _message: None

            with patch.object(main.messagebox, 'askyesno', return_value=True), \
                    patch.object(main, 'CFG', Path(temp) / 'config.json'):
                app.restore_automation_defaults()

            self.assertEqual(app.fields['coleta'].get(), main.DEFAULT['coleta'])
            self.assertEqual(custom.read_bytes(), original)

    def test_compilacao_empacota_apenas_as_tres_gravacoes_padrao(self):
        command = (ROOT / 'COMPILAR_APLICATIVO.cmd').read_text(encoding='utf-8')
        for stage in ('coleta_1', 'analise_2', 'compra_3'):
            self.assertIn(f'gravacoes\\gravacao_{stage}.rec;gravacoes', command)
        self.assertNotIn('"gravacoes;gravacoes"', command)
        self.assertNotIn('"referencias;referencias"', command)


class TestDiagnosticRetention(unittest.TestCase):
    def test_salvar_seis_pastas_diagnosticas_retem_as_cinco_mais_novas(self):
        with tempfile.TemporaryDirectory() as temp:
            debug = Path(temp)
            timestamps = iter(range(1, 7))
            with patch.object(main, 'DEBUG', debug), \
                    patch.object(main.time, 'strftime',
                                 return_value='20261030_080000'), \
                    patch.object(main.time, 'time_ns',
                                 side_effect=lambda: next(timestamps)):
                for _ in range(6):
                    main.save_candies_diagnostic(
                        None, {}, reason='ocr_error'
                    )

            folders = sorted(debug.glob('candies_*'))
            self.assertEqual(len(folders), 5)
            self.assertTrue(all((folder / 'diagnostico.txt').is_file()
                                for folder in folders))

    def test_seis_diagnosticos_retem_os_cinco_mais_recentes_e_preserva_outros(self):
        with tempfile.TemporaryDirectory() as temp:
            debug = Path(temp)
            diagnostic_paths = []
            for index in range(6):
                folder = debug / f'candies_20261030_08000{index}_000000000'
                folder.mkdir()
                (folder / 'diagnostico.txt').write_text(
                    str(index), encoding='utf-8'
                )
                os.utime(folder, (index + 1, index + 1))
                diagnostic_paths.append(folder)
            unrelated_folder = debug / 'candies_user_notes'
            unrelated_folder.mkdir()
            (unrelated_folder / 'keep.txt').write_text('keep', encoding='utf-8')
            unrelated_image = debug / 'personal.png'
            unrelated_image.write_bytes(b'keep')

            with patch.object(main, 'DEBUG', debug):
                main.prune_candies_diagnostics()

            self.assertFalse(diagnostic_paths[0].exists())
            self.assertTrue(all(path.is_dir() for path in diagnostic_paths[1:]))
            self.assertEqual(
                len([path for path in debug.glob('candies_20261030_*')
                     if path.is_dir()]),
                5,
            )
            self.assertTrue((unrelated_folder / 'keep.txt').is_file())
            self.assertTrue(unrelated_image.is_file())

    def test_retencao_nao_apaga_arquivos_adicionais_na_pasta_de_diagnostico(self):
        with tempfile.TemporaryDirectory() as temp:
            debug = Path(temp)
            folders = []
            for index in range(6):
                folder = debug / f'candies_20261030_09000{index}_000000000'
                folder.mkdir()
                (folder / 'diagnostico.txt').write_text(str(index), encoding='utf-8')
                os.utime(folder, (index + 1, index + 1))
                folders.append(folder)
            personal = folders[0] / 'anotacoes_do_usuario.txt'
            personal.write_text('preservar', encoding='utf-8')
            os.utime(folders[0], (1, 1))

            with patch.object(main, 'DEBUG', debug):
                main.prune_candies_diagnostics()

            self.assertTrue(personal.is_file())
            self.assertFalse((folders[0] / 'diagnostico.txt').exists())
            self.assertEqual(
                sum((folder / 'diagnostico.txt').is_file() for folder in folders),
                5,
            )

    def test_imagens_soltas_tem_limite_e_diagnostico_de_relogio_tem_retencao(self):
        with tempfile.TemporaryDirectory() as temp:
            debug = Path(temp)
            for index in range(main.OCR_AUDIT_IMAGE_LIMIT + 2):
                image = debug / (
                    f'20261030_{index:06d}_compra_bloqueada_contador.png'
                )
                image.write_bytes(b'audit')
                os.utime(image, (index + 1, index + 1))
            unrelated = debug / 'unrelated_contador.png'
            unrelated.write_bytes(b'keep')
            for index in range(main.OCR_CLOCK_DIAGNOSTIC_LIMIT + 1):
                stamp = f'20261030_{index:06d}'
                for kind in ('tela', 'recorte', 'ampliado'):
                    (debug / f'{stamp}_relogio_{kind}.png').write_bytes(b'clock')

            with patch.object(main, 'DEBUG', debug):
                main.prune_candies_diagnostics()

            self.assertEqual(
                len(list(debug.glob('*_compra_*_contador.png'))), 20
            )
            self.assertTrue(unrelated.is_file())
            self.assertEqual(len(list(debug.glob('*_relogio_tela.png'))), 5)
            self.assertEqual(len(list(debug.glob('*_relogio_recorte.png'))), 5)
            self.assertEqual(len(list(debug.glob('*_relogio_ampliado.png'))), 5)

    def test_log_de_excecoes_rotaciona_com_limite_de_tamanho(self):
        failure = main.OCRFailure(
            'ocr', 1, 'RuntimeError', 'example', 'traceback text'
        )
        with tempfile.TemporaryDirectory() as temp:
            with patch.object(main, 'DEBUG', Path(temp)), \
                    patch.object(main, 'OCR_EXCEPTION_LOG_MAX_BYTES', 256):
                path = main.write_ocr_exception_log((failure,), 'test')
                main.write_ocr_exception_log((failure,), 'test')
                backup = path.with_name(path.name + '.1')
                self.assertTrue(path.is_file())
                self.assertTrue(backup.is_file())
                self.assertLessEqual(path.stat().st_size, 256)
                self.assertLessEqual(backup.stat().st_size, 256)

    def test_diagnostico_automatico_so_e_agendado_quando_ha_falha(self):
        controller = object.__new__(main.Controller)
        valid = main.avaliar_leituras(
            [(100 + index * 2, 300) for index in range(5)], 110
        )
        audit = {300: ('shot', 'result', 'region', 'bbox')}
        self.assertTrue(valid.confiavel_para_compra)
        self.assertEqual(
            main.automatic_diagnostic_samples(valid, audit, []), []
        )

        failure_sample = ('shot', 'result', 'inconclusive', 'bad read', 'bbox', 'region')
        inconclusive = main.avaliar_leituras([], 110)
        self.assertEqual(
            main.automatic_diagnostic_samples(
                inconclusive, {}, [failure_sample]
            ),
            [failure_sample],
        )

        with patch.object(main.threading, 'Thread') as worker:
            controller._save_diagnostics_async([])
        worker.assert_not_called()

        controller.cfg = {}
        with patch.object(main.threading, 'Thread') as worker:
            controller._save_diagnostics_async([(
                None, None, 'inconclusive', 'bad read', None, None
            )])
        worker.assert_called_once()


if __name__ == '__main__':
    unittest.main()
