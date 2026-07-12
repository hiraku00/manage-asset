const test=require('node:test');
const assert=require('node:assert/strict');
const Core=require('../static/portfolio-core.js');

const walletSnapshot={
  wallet_id:'wallet_lido',wallet_name:'Lido2',address:'0x123',captured_at:'2026-07-12T10:00:00Z',total_usd:'216232.72',
  tokens:[{symbol:'ETH',amount_value:'0.02',usd_value_display:'36.14'}],
  protocols:[
    {name:'Lido',panels:[{assets:[{asset_symbol:'stETH',amount_value:'119.7089',usd_value:'216196.58'}]}]},
    {name:'Aave',panels:[{display_text:'USD Value USDT 5,174.3572 USDT Withdraw $5,171.10'}]},
  ],
};
const exchangeSnapshot={source_id:'binance',account_name:'Binance',captured_at:'2026-07-12T11:00:00Z',totals:{net_asset_usd:'12970.87'},positions:[{symbol:'BTC',net_quantity:'0.20271302',usd_value:'12970.87'}]};

test('legacy DeFi text extracts USDT quantity and value',()=>{
  assert.deepEqual(Core.legacyDeFiAsset({display_text:'USD Value USDT 5,174.3572 USDT Withdraw $5,171.10'}),{symbol:'USDT',quantity:5174.3572,value:5171.1,unpriced:false});
});

test('wallet positions keep wallet as location and include stETH and USDT',()=>{
  const positions=Core.walletPositions([walletSnapshot]);
  assert.deepEqual(positions.map(item=>item.symbol),['ETH','stETH','USDT']);
  assert.ok(positions.every(item=>item.location==='Lido2'));
});

test('holdings aggregate wallet and exchange quantities and calculate unit price',()=>{
  const state={snapshots:[walletSnapshot],exchange_snapshots:[exchangeSnapshot]};
  const holdings=Core.holdings(state),steth=holdings.find(item=>item.symbol==='stETH'),btc=holdings.find(item=>item.symbol==='BTC');
  assert.equal(steth.quantity,119.7089);
  assert.ok(Math.abs(steth.unitPrice-(216196.58/119.7089))<1e-9);
  assert.equal(btc.quantity,0.20271302);
  assert.ok(Math.abs(btc.unitPrice-(12970.87/0.20271302))<1e-9);
});

test('only latest snapshot per source contributes to totals and holdings',()=>{
  const old={...exchangeSnapshot,captured_at:'2026-07-11T11:00:00Z',totals:{net_asset_usd:'999'},positions:[{symbol:'BTC',net_quantity:'99',usd_value:'999'}]};
  const state={snapshots:[walletSnapshot],exchange_snapshots:[exchangeSnapshot,old]};
  assert.equal(Core.total(state),216232.72+12970.87);
  assert.equal(Core.holdings(state).find(item=>item.symbol==='BTC').quantity,0.20271302);
});

test('locations are sorted by value and asset locations are value ordered',()=>{
  const second={wallet_id:'wallet_small',wallet_name:'Small',captured_at:'2026-07-12T12:00:00Z',total_usd:'10',tokens:[{symbol:'ETH',amount_value:'1',usd_value_display:'10'}],protocols:[]};
  const state={snapshots:[second,walletSnapshot],exchange_snapshots:[exchangeSnapshot]};
  assert.deepEqual(Core.locations(state).map(item=>item.name),['Lido2','Binance','Small']);
  assert.deepEqual(Core.holdings(state).find(item=>item.symbol==='ETH').locations,['Lido2','Small']);
});

test('unpriced assets remain distinguishable from priced zero',()=>{
  const snapshot={wallet_id:'unknown',wallet_name:'Unknown',captured_at:'2026-07-12T12:00:00Z',total_usd:'0',tokens:[{symbol:'HEX',amount_value:'1',usd_value_display:null}],protocols:[]};
  const item=Core.holdings({snapshots:[snapshot],exchange_snapshots:[]})[0];
  assert.equal(item.value,0);
  assert.equal(item.unpriced,1);
  assert.equal(item.unitPrice,null);
});

test('history uses newest record for each source and date',()=>{
  const history={snapshots:[{wallet_id:'w1',as_of_date:'2026-07-11',captured_at:'2026-07-11T01:00:00Z',total_usd:10},{wallet_id:'w1',as_of_date:'2026-07-11',captured_at:'2026-07-11T02:00:00Z',total_usd:20}],exchange_snapshots:[{source_id:'s1',as_of_date:'2026-07-11',captured_at:'2026-07-11T03:00:00Z',totals:{net_asset_usd:5}}]};
  assert.deepEqual(Core.historyPoints(history),[{date:'2026-07-11',value:25}]);
});
