import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from monitor import classify, money, offer_from_html


class TestMonitor(unittest.TestCase):
    def test_money(self):
        self.assertEqual(str(money("R$ 1.234,90")), "1234.90")
        self.assertEqual(str(money("449.90")), "449.90")

    def test_classify(self):
        self.assertEqual(classify("Pokémon Celebração 30 anos Coleção com Miniatura Mewtwo"), "mewtwo")
        self.assertEqual(classify("Pokémon 30 anos Coleção com Miniatura Mew"), "mew")
        self.assertEqual(classify("Pokémon Celebração de 30 anos Treinador Avançado ETB"), "etb")
        self.assertIsNone(classify("Kit Pokemon 30 anos ETB e poster"))
        self.assertIsNone(classify("Pokémon Celebrações de 25 anos ETB"))
        self.assertIsNone(classify("Pokemon 30 anos miniatura Mew ou Mewtwo"))

    def test_json_ld(self):
        page = '''<html><script type="application/ld+json">{
          "@context":"https://schema.org","@type":"Product",
          "name":"Pokémon Celebração 30 anos Coleção com Miniatura Mewtwo",
          "offers":{"@type":"Offer","price":"244.90", "priceCurrency":"BRL",
          "availability":"https://schema.org/InStock","seller":{"@type":"Organization","name":"Amazon"}}}
        </script></html>'''
        config = {"trusted_marketplace_sellers":["Amazon"]}
        store = {"name":"Amazon Brasil", "domain":"amazon.com.br", "marketplace":True}
        offer = offer_from_html(page,"https://www.amazon.com.br/dp/XYZ",store,config)
        self.assertIsNotNone(offer)
        self.assertEqual(offer["category"], "mewtwo")
        self.assertEqual(str(offer["price"]), "244.90")
        self.assertIsNone(offer_from_html(page.replace('"name":"Amazon"', '"name":"Desconhecido"'),
                                           "https://www.amazon.com.br/dp/XYZ",store,config))

if __name__ == "__main__":
    unittest.main()
