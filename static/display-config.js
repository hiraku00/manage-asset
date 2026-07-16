(function (root) {
  root.DisplayConfig = {
    fiatDecimals: {
      USD: 2,
      JPY: 0,
    },
    tokenDecimals: {
      defaults: {
        balance: 2,
        change: 4,
      },
      currencyOverrides: {
        stETH: { balance: 4, change: 5 },
        BTC: { balance: 5, change: 6 },
        USDT: { balance: 2, change: 3 },
        ETH: { balance: 4, change: 5 },
      },
    },
    metricDecimals: {
      fxRate: 2,
      apr: 2,
    },
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
