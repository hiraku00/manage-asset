import ssl
from decimal import Decimal
from unittest import TestCase
from unittest.mock import patch
from urllib.error import URLError

from exchange import BitflyerConnector, BitbankConnector, BybitConnector, BinanceConnector, CoincheckConnector, ExchangeError, GmoCoinConnector, NormalizedPosition, request_json


class ExchangeConnectorTests(TestCase):
    @patch("exchange.urlopen")
    def test_request_json_reports_certificate_verification_errors(self, urlopen):
        urlopen.side_effect = URLError(ssl.SSLCertVerificationError("certificate verify failed"))

        with self.assertRaisesRegex(ExchangeError, "HTTPS証明書を検証できませんでした"):
            request_json("https://api.example.test/private?signature=secret")

    @patch("exchange.usd_jpy_rate", return_value=Decimal("160"))
    @patch("exchange.public_price")
    def test_jpy_uses_usd_jpy_rate_without_binance(self, public_price, _fx):
        result = NormalizedPosition("JPY", Decimal("160.45"), Decimal("160.45"), Decimal("0")).as_dict("bitbank", "bitbank")
        self.assertEqual(Decimal(result["price"]), Decimal("0.00625"))
        self.assertEqual(Decimal(result["usd_value"]), Decimal("1.0028125"))
        public_price.assert_not_called()

    @patch("exchange.public_price", return_value=Decimal("2000"))
    @patch("exchange.request_json")
    def test_binance_combines_free_and_locked(self, request_json, _price):
        request_json.return_value = {"balances": [{"asset": "ETH", "free": "1.25", "locked": "0.75"}, {"asset": "BTC", "free": "0", "locked": "0"}]}
        result = BinanceConnector().fetch({"api_key": "key", "api_secret": "secret"}, "Binance Main")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["net_quantity"], "2.00")
        self.assertEqual(result[0]["available_quantity"], "1.25")
        self.assertEqual(result[0]["locked_quantity"], "0.75")

    @patch("exchange.public_price", return_value=Decimal("2"))
    @patch("exchange.request_json")
    def test_bybit_separates_borrowed_quantity(self, request_json, _price):
        request_json.return_value = {"retCode": 0, "result": {"list": [{"coin": [{"coin": "USDT", "walletBalance": "10", "spotBorrow": "3", "availableToWithdraw": "7", "usdValue": "10"}]}]}}
        result = BybitConnector().fetch({"api_key": "key", "api_secret": "secret"}, "Bybit Main")
        self.assertEqual(result[0]["quantity"], "10")
        self.assertEqual(result[0]["borrowed_quantity"], "3")
        self.assertEqual(result[0]["net_quantity"], "7")
        self.assertEqual(result[0]["liability_usd_value"], "6")

    @patch("exchange.public_price", return_value=Decimal("3000"))
    @patch("exchange.request_json")
    def test_bitflyer_preserves_available_and_total(self, request_json, _price):
        request_json.return_value = [{"currency_code": "ETH", "amount": 2, "available": 1.5}]
        result = BitflyerConnector().fetch({"api_key": "key", "api_secret": "secret"}, "bitFlyer")
        self.assertEqual(result[0]["quantity"], "2")
        self.assertEqual(result[0]["available_quantity"], "1.5")
        self.assertEqual(result[0]["locked_quantity"], "0.5")

    @patch("exchange.public_price", return_value=Decimal("1"))
    @patch("exchange.request_json")
    def test_coincheck_includes_reserved_and_debt(self, request_json, _price):
        request_json.return_value = {"success": True, "btc": "1", "btc_reserved": "0.5", "btc_lent": "0.25", "btc_debt": "0.1"}
        result = CoincheckConnector().fetch({"api_key": "key", "api_secret": "secret"}, "Coincheck")
        self.assertEqual(result[0]["quantity"], "1.75")
        self.assertEqual(result[0]["borrowed_quantity"], "0.1")

    @patch("exchange.public_price", return_value=Decimal("100"))
    @patch("exchange.request_json")
    def test_bitbank_uses_onhand_total(self, request_json, _price):
        request_json.return_value = {"success": 1, "data": {"assets": [{"asset": "btc", "onhand_amount": "2", "free_amount": "1.5", "locked_amount": "0.5"}]}}
        result = BitbankConnector().fetch({"api_key": "key", "api_secret": "secret"}, "bitbank")
        self.assertEqual(result[0]["quantity"], "2")
        self.assertEqual(result[0]["locked_quantity"], "0.5")

    @patch("exchange.public_price", return_value=Decimal("100"))
    @patch("exchange.request_json")
    def test_gmo_coin_preserves_amount_and_available(self, request_json, _price):
        request_json.return_value = {"status": 0, "data": [{"symbol": "BTC", "amount": "2", "available": "1.25", "conversionRate": "10000000"}]}
        result = GmoCoinConnector().fetch({"api_key": "key", "api_secret": "secret"}, "GMO")
        self.assertEqual(result[0]["quantity"], "2")
        self.assertEqual(result[0]["available_quantity"], "1.25")
        self.assertEqual(result[0]["exchange_conversion_rate_jpy"], "10000000")
