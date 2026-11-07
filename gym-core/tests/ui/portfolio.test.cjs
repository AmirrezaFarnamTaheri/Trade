const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const esc = v => String(v ?? '').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const setup = {symbols:['BTCUSDT','ETHUSDT','XRPUSDT'],resolutions:['1min','15min'],strategies:[{id:'ema-trend'}],defaults:{resolution:'15min',fee_rate:'0.001'}};
const record = {run_id:'a'.repeat(16),inputs:{symbols:['BTCUSDT','ETHUSDT'],to:'2026-10-29T09:30:00Z'},result:{quote:'USDT',end:{equity:'999',net:'-1'},markets:{BTCUSDT:{fills:2,closed_trades:1,realized_pnl:'-1',holding:'0',last_bid:'70000'}},balances:{USDT:'999'},curve:[]},performance:{total_return_pct:'-0.1'}};
function page(api) {
  const nodes = new Map();
  class Node {
    constructor(id) {this.id=id;this.value='';this.disabled=false;this._html='';this.textContent='';}
    set innerHTML(html) {this._html=html;if(this.id==='portfolio-workbench')for(const [,id] of html.matchAll(/\bid="([^"]+)"/g))nodes.set(id,new Node(id));}
    get innerHTML(){return this._html;}
    querySelectorAll(){return [];}
  }
  nodes.set('portfolio-workbench', new Node('portfolio-workbench'));
  const context = {window:{},document:{documentElement:{lang:'en'},getElementById:id=>nodes.get(id)}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../src/gym/ui/portfolio.js'),'utf8'),context);
  const options={api,esc,amount:esc,when:esc,table:(heads,rows)=>heads.concat(rows.flat()).join('|'),keyValues:rows=>rows.flat().join('|'),curveFigure:()=>'<svg></svg>'};
  context.window.gymPortfolio.mount(options);
  return {node:id=>nodes.get(id),context,options};
}
test('portfolio inputs preserve decimal cash, complete market choices and language state',async()=>{
  const calls=[];
  const p=page(async(url,options,timeout)=>{
    if(!options)return setup;
    const body=JSON.parse(options.body);calls.push({body,timeout});
    if(body.action==='portfolio-list')return{runs:[record]};
    if(body.action==='portfolio-replay')return{run_id:record.run_id};
    return record;
  });
  assert.equal(calls.length,0);assert.equal(p.node('portfolio-fields').disabled,true);
  await p.node('portfolio-load').onclick();
  assert.match(p.node('portfolio-markets').innerHTML,/XRPUSDT/);
  for(const [id,value] of Object.entries({'portfolio-symbols':'btcusdt, ethusdt','portfolio-from':'2026-10-29T09:00:00','portfolio-to':'2026-10-29T09:30:00','portfolio-cash':'1000.00000000000000001','portfolio-params':'{"fast":2,"slow":3}','portfolio-strategy':'ema-trend','portfolio-resolution':'1min'}))p.node(id).value=value;
  await p.node('portfolio-form').onsubmit({preventDefault(){}});
  const replay=calls.find(c=>c.body.action==='portfolio-replay');
  assert.equal(replay.body.value.cash,'1000.00000000000000001');assert.equal(replay.timeout,135000);
  assert.deepEqual(replay.body.value.symbols,['BTCUSDT','ETHUSDT']);
  assert.equal(replay.body.value.to,'2026-10-29T09:30:00Z');
  assert.match(p.node('portfolio-result').innerHTML,/999/);
  p.context.document.documentElement.lang='fa';p.context.window.gymPortfolio.mount(p.options);
  assert.equal(p.node('portfolio-cash').value,'1000.00000000000000001');
  assert.match(p.node('portfolio-workbench').innerHTML,/موجودی/);
  const html=p.node('portfolio-workbench').innerHTML;
  for(const [,id] of html.matchAll(/<(?:input|select|textarea) id="([^"]+)"/g))assert.ok(html.includes(`for="${id}"`));
});
test('duplicate requests are fenced and failures leave an actionable saved-state warning',async()=>{
  let fail,calls=0;
  const p=page(()=>{calls++;return new Promise((_,reject)=>{fail=reject;});});
  const pending=p.node('portfolio-load').onclick();await p.node('portfolio-load').onclick();assert.equal(calls,1);
  fail(new Error('<script>private</script>'));await pending;
  assert.equal(p.node('portfolio-fields').disabled,true);
  assert.match(p.node('portfolio-status').textContent,/saved portfolios/);
  assert.doesNotMatch(p.node('portfolio-status').textContent,/<script>|private/);
});
test('portfolio belongs to the workbench panel and follows existing asset hashing',()=>{
  const html=fs.readFileSync(path.join(__dirname,'../../src/gym/ui/index.html'),'utf8');
  const panel=html.match(/<div id="panel-workbench"[\s\S]*?<\/div>/)[0];
  assert.match(panel,/id="portfolio-workbench"/);
  assert.match(html,/<script src="\/portfolio.js" defer><\/script>/);
});
test('invalid setup cannot enable replay inputs',async()=>{
  const p=page(async()=>({}));
  await p.node('portfolio-load').onclick();
  assert.equal(p.node('portfolio-fields').disabled,true);
  assert.match(p.node('portfolio-status').textContent,/Request failed/);
});
test('missing FX stays unavailable and stale FX is visible beside valuation',async()=>{
  const valued=JSON.parse(JSON.stringify(record));
  valued.result.end.net_usdt_eq=null;
  valued.result.valuation={basis:'MID; not executable',start:{status:'UNAVAILABLE'},end:{status:'STALE_CLOSED'},curve:[{at:'2026-10-29T09:00:00Z',equity_usdt_eq:null,fx:{status:'UNAVAILABLE',age_seconds:null}}]};
  const p=page(async(url,options)=>{
    if(!options)return setup;
    const body=JSON.parse(options.body);
    return body.action==='portfolio-list'?{runs:[]}:body.action==='portfolio-replay'?{run_id:record.run_id}:valued;
  });
  await p.node('portfolio-load').onclick();
  p.node('portfolio-symbols').value='BTCTMN,ETHTMN';p.node('portfolio-params').value='{}';
  await p.node('portfolio-form').onsubmit({preventDefault(){}});
  assert.match(p.node('portfolio-result').innerHTML,/UNAVAILABLE \/ STALE_CLOSED/);
  assert.match(p.node('portfolio-result').innerHTML,/Unavailable/);
  assert.match(p.node('portfolio-result').innerHTML,/not executable/);
});
