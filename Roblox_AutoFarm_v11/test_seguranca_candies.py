import unittest
from seguranca_candies import avaliar_leituras


class TestarSegurancaCandies(unittest.TestCase):
    def setUp(self):
        self.fim = 130.0

    def leituras(self, valores):
        return [(100.0 + i * 2.0, v) for i, v in enumerate(valores)]

    def test_caso_real_227_contra_277_bloqueia(self):
        r = avaliar_leituras(self.leituras([227] + [277]*8), self.fim)
        self.assertIsNone(r.valor)
        self.assertFalse(r.confiavel_para_compra)
        self.assertIn('DIVERGENTES', r.motivo)

    def test_249_bloqueia(self):
        r = avaliar_leituras(self.leituras([249]*10), self.fim)
        self.assertFalse(r.confiavel_para_compra)
        self.assertEqual(r.valor, 249)

    def test_250_confirma(self):
        r = avaliar_leituras(self.leituras([250]*12), self.fim)
        self.assertTrue(r.confiavel_para_compra)
        self.assertEqual(r.valor, 250)

    def test_371_confirma(self):
        r = avaliar_leituras(self.leituras([371]*12), self.fim)
        self.assertTrue(r.confiavel_para_compra)

    def test_divergencias_mesmo_acima_da_meta_bloqueiam(self):
        r = avaliar_leituras(self.leituras([280] + [277]*10), self.fim)
        self.assertFalse(r.confiavel_para_compra)

    def test_tres_leituras_nao_autorizam(self):
        r = avaliar_leituras(self.leituras([350]*3), self.fim)
        self.assertFalse(r.confiavel_para_compra)

    def test_leitura_antiga_nao_autoriza(self):
        r = avaliar_leituras([(80+i*2, 371) for i in range(6)], self.fim)
        self.assertFalse(r.confiavel_para_compra)

    def test_ausencia_nao_autoriza(self):
        r = avaliar_leituras([], self.fim)
        self.assertFalse(r.confiavel_para_compra)

    def test_variantes_contraditorias_bloqueiam(self):
        r = avaliar_leituras(self.leituras([277]*10), self.fim,
                             interpretacoes_brutas=[277]*20 + [227])
        self.assertFalse(r.confiavel_para_compra)
        self.assertIn('contradizem', r.motivo)

    def test_analise_atual_nao_reusa_valor_anterior(self):
        primeira = avaliar_leituras(self.leituras([371]*12), self.fim)
        segunda = avaliar_leituras(self.leituras([18]*12), self.fim)
        self.assertTrue(primeira.confiavel_para_compra)
        self.assertFalse(segunda.confiavel_para_compra)


if __name__ == '__main__':
    unittest.main()
