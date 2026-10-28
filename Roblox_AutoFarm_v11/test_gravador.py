"""Teste de compatibilidade dos registros sem acesso ao teclado real do Windows."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from gravador import GravadorRec
from recplayer import read_rec, is_record_stop_key, WM_KEYDOWN, WM_KEYUP, WM_LBUTTONDOWN

r=GravadorRec()
r._recording=True
r._t0=r._timestamp()
keyboard_1=SimpleNamespace(vkCode=0x31, scanCode=2, flags=0)
keyboard_2=SimpleNamespace(vkCode=0x77, scanCode=0x42, flags=0)
mouse=SimpleNamespace(pt=SimpleNamespace(x=530,y=420))
assert r.keyboard_filter(WM_KEYDOWN,keyboard_1)
assert r.keyboard_filter(WM_KEYUP,keyboard_1)
assert r.keyboard_filter(WM_KEYDOWN,keyboard_2)  # F8 nunca é gravado
assert r.mouse_filter(WM_LBUTTONDOWN,mouse)
with TemporaryDirectory() as temp:
    f=Path(temp)/'teste.rec'
    result=r.finish(f)
    events=read_rec(f)
    assert len(events)==4
    assert events[0].data1==0x0231 and events[0].data2==2
    assert events[1].message==WM_KEYUP
    assert events[2].message==WM_LBUTTONDOWN
    assert (events[2].data1,events[2].data2)==(530,420)
    assert is_record_stop_key(events,3)
    assert result['events']==4
    print('PASS: arquivo .rec gerado, teclas, mouse e marcador final de F8 válidos')
