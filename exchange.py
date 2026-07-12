"""Read-only exchange connectors for the local asset tracker.

Credentials are intentionally kept out of this module's persistent data.  The
caller supplies them from macOS Keychain only for the lifetime of a request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


USER_AGENT = "manage-asset-local/1.0"


class ExchangeError(ValueError):
    """A safe, user-facing error.  It must never include a credential."""


def decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError) as exc:
        raise ExchangeError("取引所から不正な数値を受信しました") from exc


def request_json(url: str, headers: dict[str, str] | None = None, timeout: int = 20) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - hosts are fixed below
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ExchangeError("認証またはAPI権限が確認できません。読取専用キーを確認してください") from exc
        if exc.code == 429:
            raise ExchangeError("取引所のAPIレート制限に達しました。少し待ってから再試行してください") from exc
        raise ExchangeError(f"取引所APIがHTTP {exc.code} を返しました") from exc
    except (URLError, TimeoutError) as exc:
        raise ExchangeError("取引所APIへ接続できませんでした。ネットワークまたは取引所の状態を確認してください") from exc
    except json.JSONDecodeError as exc:
        raise ExchangeError("取引所APIの応答を解析できませんでした") from exc


def public_price(symbol: str) -> Decimal | None:
    """Get a conservative USD reference price from Binance public ticker.

    A missing ticker is normal (for example JPY or an exchange-only asset), and
    is represented by None rather than guessed as zero.
    """
    symbol = symbol.upper()
    if symbol in {"USD", "USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI"}:
        return Decimal("1")
    if symbol == "JPY":
        try:
            data = request_json("https://api.binance.com/api/v3/ticker/price?symbol=USDTJPY")
            return Decimal("1") / decimal(data.get("price"))
        except ExchangeError:
            return None
    try:
        data = request_json(f"https://api.binance.com/api/v3/ticker/price?{urlencode({'symbol': symbol + 'USDT'})}")
        return decimal(data.get("price"))
    except ExchangeError:
        return None


@dataclass
class NormalizedPosition:
    symbol: str
    quantity: Decimal
    available: Decimal
    locked: Decimal
    borrowed: Decimal = Decimal("0")
    account_type: str = "spot"
    source_value_usd: Decimal | None = None

    def as_dict(self, provider: str, account_name: str) -> dict[str, str | bool | None]:
        price = public_price(self.symbol)
        asset_value = self.source_value_usd if self.source_value_usd is not None else (self.quantity * price if price is not None else None)
        liability_value = self.borrowed * price if price is not None else None
        value = asset_value - liability_value if asset_value is not None and liability_value is not None else asset_value
        return {
            "canonical_asset_id": f"fiat:{self.symbol}" if self.symbol == "JPY" else f"coin:{self.symbol}",
            "source_asset_code": self.symbol,
            "symbol": self.symbol,
            "asset_name": self.symbol,
            "location_type": "exchange",
            "location_id": provider,
            "location_name": account_name,
            "account_type": self.account_type,
            "quantity": str(self.quantity),
            "available_quantity": str(self.available),
            "locked_quantity": str(self.locked),
            "borrowed_quantity": str(self.borrowed),
            "net_quantity": str(self.quantity - self.borrowed),
            "price": str(price) if price is not None else None,
            "price_currency": "USD" if price is not None else None,
            "usd_value": str(value) if value is not None else None,
            "asset_usd_value": str(asset_value) if asset_value is not None else None,
            "liability_usd_value": str(liability_value) if liability_value is not None else None,
            "price_source": "binance_public_ticker" if price is not None else None,
            "is_liability": False,
        }


class ExchangeConnector:
    provider = ""
    label = ""

    def fetch(self, credentials: dict[str, str], account_name: str) -> list[dict]:
        raise NotImplementedError


class BinanceConnector(ExchangeConnector):
    provider = "binance"
    label = "Binance Spot"
    host = "https://api.binance.com"

    def fetch(self, credentials: dict[str, str], account_name: str) -> list[dict]:
        api_key, secret = credentials.get("api_key", ""), credentials.get("api_secret", "")
        if not api_key or not secret:
            raise ExchangeError("BinanceのAPI KeyとSecretを登録してください")
        params = {"omitZeroBalances": "true", "timestamp": str(int(time.time() * 1000)), "recvWindow": "5000"}
        query = urlencode(params)
        signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        data = request_json(f"{self.host}/api/v3/account?{query}&signature={signature}", {"X-MBX-APIKEY": api_key})
        return [
            NormalizedPosition(symbol=str(row["asset"]).upper(), quantity=decimal(row.get("free")) + decimal(row.get("locked")), available=decimal(row.get("free")), locked=decimal(row.get("locked"))).as_dict(self.provider, account_name)
            for row in data.get("balances", [])
            if decimal(row.get("free")) + decimal(row.get("locked")) != 0
        ]


class BybitConnector(ExchangeConnector):
    provider = "bybit"
    label = "Bybit Unified Trading Account"
    host = "https://api.bybit.com"

    def fetch(self, credentials: dict[str, str], account_name: str) -> list[dict]:
        api_key, secret = credentials.get("api_key", ""), credentials.get("api_secret", "")
        if not api_key or not secret:
            raise ExchangeError("BybitのAPI KeyとSecretを登録してください")
        timestamp, recv_window = str(int(time.time() * 1000)), "5000"
        query = "accountType=UNIFIED"
        payload = f"{timestamp}{api_key}{recv_window}{query}"
        signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        data = request_json(
            f"{self.host}/v5/account/wallet-balance?{query}",
            {"X-BAPI-API-KEY": api_key, "X-BAPI-TIMESTAMP": timestamp, "X-BAPI-RECV-WINDOW": recv_window, "X-BAPI-SIGN": signature},
        )
        if data.get("retCode") != 0:
            raise ExchangeError(f"Bybit APIエラー: {data.get('retMsg') or '残高を取得できません'}")
        accounts = data.get("result", {}).get("list", [])
        if not accounts:
            return []
        positions = []
        for coin in accounts[0].get("coin", []):
            wallet = decimal(coin.get("walletBalance"))
            borrow = decimal(coin.get("spotBorrow") or coin.get("borrowAmount"))
            if wallet == 0 and borrow == 0:
                continue
            available = decimal(coin.get("availableToWithdraw") or wallet)
            source_value = decimal(coin["usdValue"]) if coin.get("usdValue") not in (None, "") else None
            positions.append(NormalizedPosition(str(coin.get("coin", "")).upper(), wallet, available, max(Decimal("0"), wallet - available), borrow, "unified", source_value).as_dict(self.provider, account_name))
        return positions


class BitflyerConnector(ExchangeConnector):
    provider = "bitflyer"
    label = "bitFlyer"
    host = "https://api.bitflyer.com"

    def fetch(self, credentials: dict[str, str], account_name: str) -> list[dict]:
        api_key, secret = credentials.get("api_key", ""), credentials.get("api_secret", "")
        if not api_key or not secret:
            raise ExchangeError("bitFlyerのAPI KeyとSecretを登録してください")
        timestamp, method, path = str(int(time.time())), "GET", "/v1/me/getbalance"
        signature = hmac.new(secret.encode(), f"{timestamp}{method}{path}".encode(), hashlib.sha256).hexdigest()
        data = request_json(f"{self.host}{path}", {"ACCESS-KEY": api_key, "ACCESS-TIMESTAMP": timestamp, "ACCESS-SIGN": signature})
        return [
            NormalizedPosition(str(row["currency_code"]).upper(), decimal(row.get("amount")), decimal(row.get("available")), max(Decimal("0"), decimal(row.get("amount")) - decimal(row.get("available")))).as_dict(self.provider, account_name)
            for row in data
            if decimal(row.get("amount")) != 0
        ]


class CoincheckConnector(ExchangeConnector):
    provider = "coincheck"
    label = "Coincheck"
    host = "https://coincheck.com"

    def fetch(self, credentials: dict[str, str], account_name: str) -> list[dict]:
        api_key, secret = credentials.get("api_key", ""), credentials.get("api_secret", "")
        if not api_key or not secret:
            raise ExchangeError("CoincheckのAPI KeyとSecretを登録してください")
        nonce, url = str(int(time.time() * 1000)), f"{self.host}/api/accounts/balance"
        signature = hmac.new(secret.encode(), f"{nonce}{url}".encode(), hashlib.sha256).hexdigest()
        data = request_json(url, {"ACCESS-KEY": api_key, "ACCESS-NONCE": nonce, "ACCESS-SIGNATURE": signature})
        if not data.get("success"):
            raise ExchangeError("Coincheck APIが残高を返しませんでした")
        suffixes = ("_reserved", "_lending", "_lend_in_use", "_lent", "_debt", "_tsumitate")
        symbols = {key for key in data if key != "success" and not key.endswith(suffixes)}
        positions = []
        for symbol in symbols:
            base, reserved = decimal(data.get(symbol)), decimal(data.get(f"{symbol}_reserved"))
            earn = decimal(data.get(f"{symbol}_lending")) + decimal(data.get(f"{symbol}_lend_in_use")) + decimal(data.get(f"{symbol}_lent")) + decimal(data.get(f"{symbol}_tsumitate"))
            debt = decimal(data.get(f"{symbol}_debt"))
            if base + reserved + earn == 0 and debt == 0:
                continue
            positions.append(NormalizedPosition(symbol.upper(), base + reserved + earn, base, reserved + earn, debt, "spot").as_dict(self.provider, account_name))
        return positions


class BitbankConnector(ExchangeConnector):
    provider = "bitbank"
    label = "bitbank"
    host = "https://api.bitbank.cc"

    def fetch(self, credentials: dict[str, str], account_name: str) -> list[dict]:
        api_key, secret = credentials.get("api_key", ""), credentials.get("api_secret", "")
        if not api_key or not secret:
            raise ExchangeError("bitbankのAPI KeyとSecretを登録してください")
        nonce, path = str(int(time.time() * 1000)), "/v1/user/assets"
        signature = hmac.new(secret.encode(), f"{nonce}{path}".encode(), hashlib.sha256).hexdigest()
        data = request_json(f"{self.host}{path}", {"ACCESS-KEY": api_key, "ACCESS-NONCE": nonce, "ACCESS-SIGNATURE": signature})
        if data.get("success") != 1:
            raise ExchangeError("bitbank APIが残高を返しませんでした")
        assets = data.get("data", {}).get("assets", data.get("data", []))
        return [
            NormalizedPosition(str(row.get("asset", "")).upper(), decimal(row.get("onhand_amount")), decimal(row.get("free_amount")), decimal(row.get("locked_amount")), account_type="spot").as_dict(self.provider, account_name)
            for row in assets
            if decimal(row.get("onhand_amount")) != 0
        ]


class GmoCoinConnector(ExchangeConnector):
    provider = "gmo_coin"
    label = "GMOコイン"
    host = "https://api.coin.z.com/private"

    def fetch(self, credentials: dict[str, str], account_name: str) -> list[dict]:
        api_key, secret = credentials.get("api_key", ""), credentials.get("api_secret", "")
        if not api_key or not secret:
            raise ExchangeError("GMOコインのAPI KeyとSecretを登録してください")
        timestamp, method, path = str(int(time.time() * 1000)), "GET", "/v1/account/assets"
        signature = hmac.new(secret.encode(), f"{timestamp}{method}{path}".encode(), hashlib.sha256).hexdigest()
        data = request_json(f"{self.host}{path}", {"API-KEY": api_key, "API-TIMESTAMP": timestamp, "API-SIGN": signature})
        if data.get("status") not in (0, None):
            raise ExchangeError("GMOコイン APIが残高を返しませんでした")
        rows = data.get("data", [])
        positions = []
        for row in rows:
            amount, available = decimal(row.get("amount")), decimal(row.get("available"))
            if amount == 0:
                continue
            symbol = str(row.get("symbol", "")).upper()
            jpy_rate = decimal(row.get("conversionRate")) if row.get("conversionRate") not in (None, "") else None
            # conversionRate is JPY; retain it as an exchange valuation only.
            positions.append(NormalizedPosition(symbol, amount, available, max(Decimal("0"), amount - available), account_type="spot").as_dict(self.provider, account_name))
            positions[-1]["exchange_conversion_rate_jpy"] = str(jpy_rate) if jpy_rate is not None else None
        return positions


CONNECTORS: dict[str, ExchangeConnector] = {
    "binance": BinanceConnector(),
    "bybit": BybitConnector(),
    "bitflyer": BitflyerConnector(),
    "coincheck": CoincheckConnector(),
    "bitbank": BitbankConnector(),
    "gmo_coin": GmoCoinConnector(),
}


def supported_providers() -> list[dict[str, str]]:
    return [{"provider": key, "label": value.label} for key, value in CONNECTORS.items()]
