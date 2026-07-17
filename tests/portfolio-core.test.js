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

test('previous comparison uses the first capture on the nearest earlier date',()=>{
  const history={snapshots:[
    {wallet_id:'w1',as_of_date:'2026-07-10',captured_at:'2026-07-10T09:00:00Z',total_usd:80},
    {wallet_id:'w1',as_of_date:'2026-07-12',captured_at:'2026-07-12T18:00:00Z',total_usd:120},
    {wallet_id:'w1',as_of_date:'2026-07-12',captured_at:'2026-07-12T08:00:00Z',total_usd:100},
  ],exchange_snapshots:[
    {source_id:'s1',as_of_date:'2026-07-12',captured_at:'2026-07-12T07:00:00Z',totals:{net_asset_usd:25}},
    {source_id:'s1',as_of_date:'2026-07-12',captured_at:'2026-07-12T19:00:00Z',totals:{net_asset_usd:30}},
  ]};
  assert.deepEqual(Core.previousOpeningPoint(history,'2026-07-13'),{date:'2026-07-12',value:125});
  assert.deepEqual(Core.previousOpeningPoint(history,'2026-07-12'),{date:'2026-07-10',value:80});
});

test('currency history aggregates daily balances and differences',()=>{
  const history={snapshots:[
    {wallet_id:'w1',as_of_date:'2026-07-11',captured_at:'2026-07-11T01:00:00Z',protocols:[{panels:[{display_text:'USD Value stETH ETH 1.00 ETH Withdraw $3'}]}]},
    {wallet_id:'w1',as_of_date:'2026-07-12',captured_at:'2026-07-12T01:00:00Z',protocols:[{panels:[{assets:[{asset_symbol:'stETH',amount_value:'1.01',usd_value:'3'}]}]}]},
  ],exchange_snapshots:[]};
  assert.deepEqual(Core.currencyHistory(history,'stETH').map(point=>[point.date,Number(point.value.toFixed(2)),point.delta==null?null:Number(point.delta.toFixed(2))]),[['2026-07-11',1,null],['2026-07-12',1.01,0.01]]);
});

test('generic currency history calculates rate, fiat values and APR',()=>{
  const history={snapshots:[
    {wallet_id:'w1',as_of_date:'2026-07-11',captured_at:'2026-07-11T01:00:00Z',protocols:[{panels:[{assets:[{asset_symbol:'USDT',amount_value:'100',usd_value:'99'}]}]}]},
    {wallet_id:'w1',as_of_date:'2026-07-12',captured_at:'2026-07-12T01:00:00Z',fx_usdjpy:160,protocols:[{panels:[{assets:[{asset_symbol:'USDT',amount_value:'101',usd_value:'100.5'}]}]}]},
  ],exchange_snapshots:[
    {source_id:'s1',as_of_date:'2026-07-12',captured_at:'2026-07-12T02:00:00Z',positions:[{symbol:'USDT',net_quantity:'10',usd_value:'10'}]},
  ]};
  const rows=Core.currencyHistory(history,'USDT',[{date:'2026-07-11',rate:159}]),last=rows.at(-1);
  assert.equal(last.balance,111);
  assert.equal(last.change,11);
  assert.equal(last.balanceUsd,110.5);
  assert.ok(Math.abs(last.price-(110.5/111))<1e-12);
  assert.ok(Math.abs(last.usd-(11*110.5/111))<1e-12);
  assert.equal(last.fx,160);
  assert.equal(last.apr,11/100*365*100);
});

test('stETH history bridges the final CSV balance to the first daily snapshot',()=>{
  const csv=[{date:'2026-07-11T12:00:00Z',type:'reward',change:'0.00721365',change_USD:'12.94',apr:'2.20',balance:'119.70885379510868'}];
  const steth=(wallet,date,captured,amount,usd)=>({wallet_id:wallet,as_of_date:date,captured_at:captured,fx_usdjpy:'162',protocols:[{panels:[{assets:[{asset_symbol:'stETH',amount_value:String(amount),usd_value:String(usd)}]}]}]});
  const snapshots=[
    steth('main','2026-07-11','2026-07-11T23:00:00Z',119.7016,215000),
    steth('main','2026-07-12','2026-07-12T01:00:00Z',119.7088,215000),
    steth('main','2026-07-12','2026-07-12T23:00:00Z',119.7089,215879.37),
    steth('dust','2026-07-12','2026-07-12T22:00:00Z',0,0),
    steth('main','2026-07-13','2026-07-13T23:00:00Z',119.7160,216857.19),
    steth('main','2026-07-14','2026-07-14T23:00:00Z',119.7232,213565.91),
    steth('main','2026-07-15','2026-07-15T23:00:00Z',119.7305,225053.90),
  ];
  const rows=Core.stethRewardHistory(csv,snapshots,[{date:'2026-07-11',rate:162},{date:'2026-07-15',rate:162.22}],'2026-07-12');
  assert.deepEqual(rows.map(row=>row.date),['2026-07-11','2026-07-12','2026-07-13','2026-07-14','2026-07-15']);
  assert.equal(rows[1].balance,119.7089);
  assert.ok(Math.abs(rows[1].change-(119.7089-119.70885379510868))<1e-12);
  assert.ok(Math.abs(rows[2].change-0.0071)<1e-12);
  assert.ok(Math.abs(rows[3].change-0.0072)<1e-12);
  assert.ok(Math.abs(rows[4].change-0.0073)<1e-12);
  assert.ok(Math.abs(rows[4].apr-(0.0073/119.7232*365*100))<1e-12);
  assert.equal(rows[4].balanceUsd,225053.90);
});

test('stETH history excludes transfers and prefers imported rewards over snapshots',()=>{
  const csv=[
    {date:'2026-07-11T12:00:00Z',type:'reward',change:'0.01',change_USD:'20',apr:'2',balance:'100.01'},
    {date:'2026-07-12T03:00:00Z',type:'transfer',direction:'in',change:'50',change_USD:'100000',balance:'150.01'},
    {date:'2026-07-12T12:00:00Z',type:'reward',change:'0.02',change_USD:'40',apr:'2',balance:'150.03'},
  ];
  const snapshots=[{wallet_id:'w1',as_of_date:'2026-07-12',captured_at:'2026-07-12T23:00:00Z',protocols:[{panels:[{assets:[{asset_symbol:'stETH',amount_value:'150.03',usd_value:'300060'}]}]}]}];
  const rows=Core.stethRewardHistory(csv,snapshots,[],'2026-07-12');
  assert.deepEqual(rows.map(row=>[row.date,row.change,row.source]),[
    ['2026-07-11',0.01,'csv'],
    ['2026-07-12',0.02,'csv'],
  ]);
});
