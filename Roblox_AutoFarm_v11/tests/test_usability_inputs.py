import ast
import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from gravador import GravadorRec, WM_KEYDOWN


class Variable:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeEntry:
    def __init__(self, cursor=0, selection=None):
        self.cursor = cursor
        self.selection = selection
        self.focused = False

    def index(self, index):
        if index == 'sel.first' and self.selection is None:
            raise main.tk.TclError()
        if index == 'sel.first':
            return self.selection[0]
        if index == 'sel.last':
            return self.selection[1]
        if index == 'insert':
            return self.cursor
        if index == 'end':
            return 2
        return int(index)

    def icursor(self, cursor):
        self.cursor = 2 if cursor == 'end' else cursor
        self.selection = None

    def selection_clear(self):
        self.selection = None

    def selection_range(self, start, end):
        self.selection = (start, 2 if end == 'end' else end)

    def focus_set(self):
        self.focused = True


class FakeDialog:
    def grab_release(self):
        pass

    def destroy(self):
        pass


class TestClockTimeInput(unittest.TestCase):
    def make_input(self, values=('00', '00', '00'), cursors=(0, 0, 0)):
        clock = object.__new__(main.ClockTimeInput)
        clock._unit_vars = [Variable(value) for value in values]
        clock.entries = [
            FakeEntry(cursor=cursor) for cursor in cursors
        ]
        clock._units = list(values)
        clock._updating = False
        clock._all_units_selected = False
        clock._typed_digit_count = [0, 0, 0]
        clock.variable = Variable(':'.join(values))
        clock.bell = lambda: None
        return clock

    @staticmethod
    def select_all(clock, index):
        clock.entries[index].selection = (0, len(clock._unit_vars[index].get()))

    def test_seis_digitos_consecutivos_formam_horario(self):
        clock = self.make_input()
        for index, pair in enumerate(('12', '34', '56')):
            self.select_all(clock, index)
            clock._insert_digit(index, pair[0])
            clock._insert_digit(index, pair[1])

        self.assertEqual(
            ':'.join(variable.get() for variable in clock._unit_vars),
            '12:34:56',
        )
        self.assertTrue(clock.entries[1].focused)
        self.assertTrue(clock.entries[2].focused)

    def test_widget_tk_real_processa_seis_digitos_e_substitui_segundos(self):
        try:
            root = main.tk.Tk()
        except main.tk.TclError as exc:
            self.skipTest(f'Tk não está disponível: {exc}')

        try:
            variable = main.tk.StringVar(master=root, value='00:00:00')
            clock = main.ClockTimeInput(root, variable)
            clock.pack()
            root.update()

            for index, pair in enumerate(('12', '34', '56')):
                entry = clock.entries[index]
                entry.focus_force()
                root.update()
                entry.selection_range(0, 'end')
                for digit in pair:
                    entry.event_generate('<KeyPress>', keysym=digit)
                    root.update()

            self.assertEqual(variable.get(), '12:34:56')

            clock.set_time('12:34:00')
            seconds = clock.entries[2]
            seconds.focus_force()
            root.update()
            seconds.selection_range(0, 'end')
            for digit in '123':
                seconds.event_generate('<KeyPress>', keysym=digit)
                root.update()

            self.assertEqual(variable.get(), '12:34:23')

            clock.set_time('12:34:56')
            minutes = clock.entries[1]
            minutes.focus_force()
            root.update()
            minutes.selection_range(1, 2)
            minutes.event_generate('<KeyPress>', keysym='BackSpace')
            root.update()
            self.assertEqual(variable.get(), '12:30:56')

            seconds.focus_force()
            root.update()
            seconds.selection_range(0, 'end')
            seconds.event_generate('<KeyPress>', keysym='Delete')
            root.update()
            self.assertEqual(variable.get(), '12:30:00')

            minutes.event_generate('<Control-a>')
            root.update()
            minutes.event_generate('<KeyPress>', keysym='Delete')
            root.update()
            self.assertEqual(variable.get(), '00:00:00')
        finally:
            root.destroy()

    def test_widget_tk_real_nao_avanca_apos_primeiro_digito(self):
        try:
            root = main.tk.Tk()
        except main.tk.TclError as exc:
            self.skipTest(f'Tk não está disponível: {exc}')

        try:
            variable = main.tk.StringVar(master=root, value='00:00:00')
            clock = main.ClockTimeInput(root, variable)
            clock.pack()
            root.update()

            hours = clock.entries[0]
            hours.focus_force()
            root.update()
            hours.event_generate('<KeyPress>', keysym='1')
            root.update()

            self.assertEqual(variable.get(), '10:00:00')
            self.assertIs(root.focus_get(), hours)

            hours.event_generate('<KeyPress>', keysym='2')
            root.update()
            self.assertEqual(variable.get(), '12:00:00')
            self.assertIs(root.focus_get(), clock.entries[1])

            for entry, pair in zip(clock.entries[1:], ('34', '56')):
                for digit in pair:
                    entry.event_generate('<KeyPress>', keysym=digit)
                    root.update()

            self.assertEqual(variable.get(), '12:34:56')
        finally:
            root.destroy()

    def test_widget_tk_real_ordem_convencional_e_avanco(self):
        try:
            root = main.tk.Tk()
        except main.tk.TclError as exc:
            self.skipTest(f'Tk não está disponível: {exc}')

        try:
            variable = main.tk.StringVar(master=root, value='00:00:00')
            clock = main.ClockTimeInput(root, variable)
            clock.pack()
            root.update()

            minutes = clock.entries[1]
            minutes.focus_force()
            root.update()
            minutes.event_generate('<KeyPress>', keysym='4')
            root.update()
            self.assertEqual(variable.get(), '00:40:00')
            self.assertIs(root.focus_get(), minutes)

            minutes.event_generate('<KeyPress>', keysym='7')
            root.update()
            self.assertEqual(variable.get(), '00:47:00')
            self.assertIs(root.focus_get(), clock.entries[2])

            clock.set_time('00:00:00')
            hours = clock.entries[0]
            hours.focus_force()
            root.update()
            hours.event_generate('<KeyPress>', keysym='0')
            root.update()
            self.assertEqual(variable.get(), '00:00:00')
            self.assertIs(root.focus_get(), hours)

            hours.event_generate('<KeyPress>', keysym='7')
            root.update()
            self.assertEqual(variable.get(), '07:00:00')
            self.assertIs(root.focus_get(), clock.entries[1])
        finally:
            root.destroy()

    def test_widget_tk_real_rejeita_minuto_invalido_sem_avancar(self):
        try:
            root = main.tk.Tk()
        except main.tk.TclError as exc:
            self.skipTest(f'Tk não está disponível: {exc}')

        try:
            variable = main.tk.StringVar(master=root, value='00:00:00')
            clock = main.ClockTimeInput(root, variable)
            clock.pack()
            root.update()

            hours = clock.entries[0]
            hours.focus_force()
            root.update()
            for digit in '12':
                hours.event_generate('<KeyPress>', keysym=digit)
                root.update()

            minutes = clock.entries[1]
            minutes.event_generate('<KeyPress>', keysym='6')
            root.update()
            self.assertEqual(variable.get(), '12:00:00')
            self.assertIs(root.focus_get(), minutes)

            minutes.event_generate('<KeyPress>', keysym='9')
            root.update()
            self.assertEqual(variable.get(), '12:00:00')
            self.assertIs(root.focus_get(), minutes)

            for digit in '59':
                minutes.event_generate('<KeyPress>', keysym=digit)
                root.update()
            self.assertEqual(variable.get(), '12:59:00')
            self.assertIs(root.focus_get(), clock.entries[2])
        finally:
            root.destroy()

    def test_segundos_substituem_progressivamente_sem_exceder_dois_digitos(self):
        clock = self.make_input()
        self.select_all(clock, 2)
        for digit, expected in zip('123', ('10', '12', '23')):
            clock._insert_digit(2, digit)
            self.assertEqual(clock._unit_vars[2].get(), expected)
            self.assertLessEqual(len(clock._unit_vars[2].get()), 2)
        clock._insert_digit(2, '9')
        self.assertEqual(clock._unit_vars[2].get(), '39')

    def test_edicao_intermediaria_backspace_e_delete(self):
        clock = self.make_input(values=('12', '34', '56'), cursors=(1, 1, 1))
        clock._typed_digit_count[1] = 2
        clock._insert_digit(1, '5')
        self.assertEqual(clock._unit_vars[1].get(), '35')

        clock.entries[1].cursor = 2
        clock._delete_at_cursor(1, backward=True)
        self.assertEqual(clock._unit_vars[1].get(), '30')
        self.assertEqual(clock.entries[1].cursor, 1)

        clock.entries[1].cursor = 0
        clock._delete_at_cursor(1, backward=False)
        self.assertEqual(clock._unit_vars[1].get(), '00')
        self.assertEqual(len(clock._unit_vars[1].get()), 2)

    def test_apagar_digito_selecionado_substitui_por_zero(self):
        clock = self.make_input(values=('12', '34', '56'))
        clock.entries[0].selection = (1, 2)
        clock._delete_at_cursor(0, backward=True)
        self.assertEqual(clock._unit_vars[0].get(), '10')
        self.assertEqual(clock.entries[0].cursor, 1)

    def test_apagar_unidade_inteira_mantem_dois_zeros(self):
        clock = self.make_input(values=('12', '34', '56'))
        self.select_all(clock, 2)
        clock._delete_at_cursor(2, backward=False)
        self.assertEqual(clock._unit_vars[2].get(), '00')
        self.assertEqual(
            ':'.join(variable.get() for variable in clock._unit_vars),
            '12:34:00',
        )

    def test_apagar_horario_inteiro_e_digitar_novamente(self):
        clock = self.make_input(values=('12', '34', '56'))
        for entry in clock.entries:
            entry.selection_range(0, 'end')
        clock._all_units_selected = True
        clock._delete_at_cursor(1, backward=True)
        self.assertEqual(clock.variable.get(), '00:00:00')
        self.assertEqual(
            [variable.get() for variable in clock._unit_vars],
            ['00', '00', '00'],
        )
        self.assertTrue(clock.entries[0].focused)

        clock.entries[0].cursor = 0
        clock._insert_digit(0, '1')
        clock._insert_digit(0, '2')
        self.assertEqual(
            ':'.join(variable.get() for variable in clock._unit_vars),
            '12:00:00',
        )

    def test_colagem_com_e_sem_separadores_e_validacao_de_limites(self):
        self.assertEqual(main.ClockTimeInput.parse_paste('12:34:56'), '12:34:56')
        self.assertEqual(main.ClockTimeInput.parse_paste('123456'), '12:34:56')
        for invalid in (
                '12:60:00', '12:00:60', '126000', '12:3:45', '１２３４５６'):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                main.ClockTimeInput.parse_paste(invalid)

    def test_horario_incompleto_ou_invalido_nao_pode_ser_sincronizado(self):
        for invalid in ('1:23:45', '12:60:00', '12:34:60', '123456'):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                main.validate_clock_input(invalid)

    def test_digitacao_nao_sincroniza_ate_acao_explicita(self):
        clock = self.make_input()
        self.select_all(clock, 0)
        clock._insert_digit(0, '1')
        clock._insert_digit(0, '2')
        self.assertEqual(clock._unit_vars[0].get(), '12')

        calls = []
        app = object.__new__(main.App)
        app.controller = SimpleNamespace(active=lambda: False)
        app._start_pending = False
        app.clock_input = Variable('12:34:56')
        app.relogio = SimpleNamespace(
            sincronizar=lambda value: calls.append(value) or value,
            status_boss=lambda: SimpleNamespace(
                estado='AUSENTE', ate_proximo_spawn=30
            ),
        )
        app.clock_var = Variable('')
        app.boss = Variable('')
        app.log = lambda _message: None
        self.assertEqual(calls, [])
        app.sync_clock()
        self.assertEqual(calls, ['12:34:56'])

    def test_sincronizacao_invalida_nao_altera_estado_do_relogio(self):
        calls = []
        app = object.__new__(main.App)
        app.controller = SimpleNamespace(active=lambda: False)
        app._start_pending = False
        app.clock_input = Variable('12:60:00')
        app.relogio = SimpleNamespace(
            sincronizar=lambda value: calls.append(value),
        )
        with patch.object(main.messagebox, 'showerror') as show_error:
            app.sync_clock()
        self.assertEqual(calls, [])
        show_error.assert_called_once()


class TestHotkeyCapture(unittest.TestCase):
    def test_suporta_funcionais_letras_numeros_e_rejeita_modificadores(self):
        self.assertEqual(main.normalize_hotkey_name('F12'), 'f12')
        self.assertEqual(main.normalize_hotkey_name('a'), 'a')
        self.assertEqual(main.normalize_hotkey_name('7'), '7')
        self.assertIsNone(main.normalize_hotkey_name('ctrl'))
        self.assertEqual(
            main.hotkey_name_from_key(SimpleNamespace(char='Q')), 'q'
        )
        self.assertEqual(
            main.hotkey_name_from_key(SimpleNamespace(name='f8')), 'f8'
        )
        self.assertIsNone(
            main.hotkey_name_from_key(SimpleNamespace(name='shift'))
        )

    def test_captura_persiste_tecla_sem_criar_listener_novo(self):
        with tempfile.TemporaryDirectory() as temp:
            app = object.__new__(main.App)
            app.hotkey = Variable('F12')
            app.record_hotkey = Variable('F8')
            app.fields = {}
            app.data = {}
            app.controller = SimpleNamespace(rare_chests=3)
            app.resource_vars = {
                key: Variable(False) for key in main.RESOURCE_TOGGLE_KEYS
            }
            app.recorder = SimpleNamespace(set_record_hotkey=lambda _key: None)
            app.log = lambda _message: None
            app._hotkey_capture_dialog = FakeDialog()
            app._hotkey_capture_status = Variable('')
            app._hotkey_capture_lock = threading.Lock()
            app._hotkey_capture_pending = False
            app._hotkey_capture_target = None

            with patch.object(main, 'CFG', Path(temp) / 'config.json'):
                app._handle_hotkey_capture('record_hotkey', 'a')
                saved = json.loads(
                    (Path(temp) / 'config.json').read_text(encoding='utf-8')
                )

            self.assertEqual(app.record_hotkey.get(), 'A')
            self.assertEqual(saved['record_hotkey'], 'a')
            self.assertEqual(saved['hotkey'], 'f12')
            self.assertIsNone(app._hotkey_capture_dialog)

    def test_cancelar_com_escape_preserva_atalho_e_nao_dispara_acao(self):
        app = object.__new__(main.App)
        app.events = queue.Queue()
        app._hotkey_capture_lock = threading.Lock()
        app._hotkey_capture_target = 'hotkey'
        app._hotkey_capture_pending = False
        app._hotkey_capture_suppressed = set()
        app._hotkey_name = 'f12'
        app._record_hotkey_name = 'f8'
        app._hotkey_pressed = False
        app._record_key_pressed = False
        app.record_stage = None

        app.on_key(SimpleNamespace(name='esc'))
        event = app.events.get_nowait()

        self.assertEqual(event, ('hotkey_capture_cancel', 'hotkey'))
        self.assertTrue(app._hotkey_capture_pending)
        self.assertTrue(app._hotkey_capture_suppressed)
        self.assertTrue(app.events.empty())

    def test_tecla_capturada_nao_aciona_atalho_e_duplicatas_sao_rejeitadas(self):
        app = object.__new__(main.App)
        app.events = queue.Queue()
        app._hotkey_capture_lock = threading.Lock()
        app._hotkey_capture_target = 'hotkey'
        app._hotkey_capture_pending = False
        app._hotkey_capture_suppressed = set()
        app._hotkey_name = 'x'
        app._record_hotkey_name = 'f8'
        app._hotkey_pressed = False
        app._record_key_pressed = False
        app.record_stage = None

        app.on_key(SimpleNamespace(char='x'))
        self.assertEqual(app.events.get_nowait(), ('hotkey_captured', ('hotkey', 'x')))
        app.on_key(SimpleNamespace(char='x'))
        self.assertTrue(app.events.empty())

        app._hotkey_capture_dialog = FakeDialog()
        app._hotkey_capture_status = Variable('')
        app._hotkey_capture_target = None
        app._hotkey_capture_pending = False
        app._hotkey_capture_lock = threading.Lock()
        app.hotkey = Variable('F12')
        app.record_hotkey = Variable('F8')
        app._arm_hotkey_capture = lambda setting: setattr(
            app, '_hotkey_capture_target', setting
        )
        app._handle_hotkey_capture('hotkey', 'f8')
        self.assertEqual(app.hotkey.get(), 'F12')
        self.assertEqual(app._hotkey_capture_target, 'hotkey')
        self.assertIn('já está atribuída', app._hotkey_capture_status.get())

    def test_atalho_global_continua_ativo_fora_da_captura(self):
        for configured, key in (
                ('q', SimpleNamespace(char='q')),
                ('f12', SimpleNamespace(name='f12'))):
            with self.subTest(configured=configured):
                app = object.__new__(main.App)
                app.events = queue.Queue()
                app._hotkey_capture_lock = threading.Lock()
                app._hotkey_capture_target = None
                app._hotkey_capture_pending = False
                app._hotkey_capture_suppressed = set()
                app._hotkey_name = configured
                app._record_hotkey_name = 'f8'
                app._hotkey_pressed = False
                app._record_key_pressed = False
                app.record_stage = None

                app.on_key(key)
                self.assertEqual(app.events.get_nowait(), ('toggle', None))

    def test_f12_despacha_inicio_ou_parada_sem_widgets_de_botoes(self):
        for is_active, expected in ((False, 'start'), (True, 'stop')):
            with self.subTest(is_active=is_active):
                actions = []
                app = object.__new__(main.App)
                app.events = queue.Queue()
                app._hotkey_capture_lock = threading.Lock()
                app._hotkey_capture_target = None
                app._hotkey_capture_pending = False
                app._hotkey_capture_suppressed = set()
                app._hotkey_name = 'f12'
                app._record_hotkey_name = 'f8'
                app._hotkey_pressed = False
                app._record_key_pressed = False
                app.record_stage = None
                app._start_pending = False
                app.controller = SimpleNamespace(
                    active=lambda: is_active,
                    request_stop=lambda: actions.append('stop'),
                )
                app.start = lambda: actions.append('start')
                app._refresh_ocr_test_button = lambda: None
                app._refresh_rare_chests_controls = lambda: None
                app._refresh_resource_controls = lambda: None
                app.root = SimpleNamespace(after=lambda *_args: None)

                app.on_key(SimpleNamespace(name='f12'))
                app.poll()
                self.assertEqual(actions, [expected])

    def test_gravador_exclui_a_tecla_configurada_alfanumerica_do_rec(self):
        recorder = GravadorRec()
        recorder.set_record_hotkey('a')
        recorder._recording = True
        key_a = SimpleNamespace(vkCode=ord('A'), flags=0, scanCode=30)
        key_b = SimpleNamespace(vkCode=ord('B'), flags=0, scanCode=48)

        recorder.keyboard_filter(WM_KEYDOWN, key_a)
        self.assertEqual(recorder._rows, [])
        recorder.keyboard_filter(WM_KEYDOWN, key_b)
        self.assertEqual(len(recorder._rows), 1)
        recorder._recording = False


class TestUsabilityLayout(unittest.TestCase):
    def test_layout_usa_widget_segmentado_e_botoes_de_captura_compactos(self):
        source = Path(main.__file__).read_text(encoding='utf-8')
        tree = ast.parse(source)
        app_class = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == 'App'
        )
        construct = next(
            node for node in app_class.body
            if isinstance(node, ast.FunctionDef) and node.name == 'construct'
        )
        body = ast.get_source_segment(source, construct)

        self.assertIn('ClockTimeInput(mline, self.clock_input)', body)
        self.assertEqual(body.count("text='Definir tecla'"), 2)
        self.assertNotIn('ttk.Entry(row_play', body)
        self.assertNotIn('ttk.Entry(row_rec', body)
        self.assertIn("self.root.geometry('870x570')", source)
        self.assertIn("self.root.minsize(790,500)", source)


if __name__ == '__main__':
    unittest.main()
