const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const rule = {symbol:'BTCUSDT',min_risk_coef:'1',max_risk_coef:'10',risk_coef_step:'0.5',max_age:1814400};
const catalogue = {schema:'wallex-margin/1',kind:'MARKETS',funded_authority:false,order_submitted:false,run_id:'a'.repeat(16),received_at:'2026-11-06T00:00:00.000000Z',markets:[rule]};
const money = (currency,value) => ({currency,value});
const preview = {schema:'wallex-margin/1',kind:'PREVIEW',funded_authority:false,order_submitted:false,run_id:'b'.repeat(16),received_at:'2026-11-06T00:00:00.123456Z',collateral_limits:{min:'50',max:'850'},terms:{loan:money('BTC','0.002'),collateral:money('USDT','100'),open_fee:money('BTC','0.0000004'),extend_fee:money('BTC','0.0000004'),trade_fee:money('USDT','0.5'),extend_time:14400,max_age:1814400,call_price:'102000',liquidity_price:'107000'}};
const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function page(api, demo = false, stamp) {
  const nodes = new Map();
  class Node {
    constructor(id) {this.id=id;this.value=id==='margin-side'?'long':'';this.disabled=false;this.attributes={};this._html='';this.textContent='';}
    setAttribute(key,value) {this.attributes[key]=String(value);}
    set innerHTML(value) {
      this._html=value;
      if (this.id==='margin-workbench') for (const [,id] of value.matchAll(/\bid="([^"]+)"/g)) nodes.set(id,new Node(id));
      if (this.id==='margin-market') this.value=value.match(/<option>([^<]*)<\/option>/)?.[1] || '';
    }
    get innerHTML() {return this._html;}
  }
  nodes.set('margin-workbench',new Node('margin-workbench'));
  const context = {T: require('./vocabulary.cjs').T, window:{},document:{documentElement:{lang:'en'},getElementById:id=>nodes.get(id)}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../../src/gym/ui/margin.js'),'utf8'),context);
  const options = {api,esc,demo,stamp,when:esc,amount:esc,keyValues:rows=>rows.flat().join('|'),table:(headings,rows)=>headings.concat(rows.flat()).join('|')};
  context.window.gymMargin.mount(options);
  return {node:id=>nodes.get(id),context,options};
}
test('opening and DEMO never perform network reads; forms wait for real receipts', async () => {
  const calls=[];
  const p=page((...args)=>calls.push(args),true);
  assert.equal(calls.length,0);
  assert.equal(p.node('margin-load').disabled,true);
  assert.equal(p.node('margin-preview-fields').disabled,true);
  assert.equal(p.node('margin-replay-fields').disabled,true);
  await p.node('margin-load').onclick();
  assert.equal(calls.length,0);
  const html=p.node('margin-workbench').innerHTML;
  for (const [,id] of html.matchAll(/<(?:input|select) id="([^"]+)"/g)) assert.ok(html.includes(`for="${id}"`));
});
test('venue grids, exact request strings, preview identity and replay connect through one API', async () => {
  const calls=[];
  const p=page(async (url,options)=>{
    const body=JSON.parse(options.body);calls.push({url,body});
    if(body.action==='margin-markets')return catalogue;
    if(body.action==='margin-preview')return preview;
    return {result:{state:'OPEN',cash_quote:'100',base_units:'0',debt_quote:'0',debt_base:'0.002',equity_quote:null,mark:{status:'STALE'},events:[]}};
  });
  await p.node('margin-load').onclick();
  assert.deepEqual(p.node('margin-risk').attributes,{min:'1',max:'10',step:'0.5'});
  assert.equal(p.node('margin-preview-fields').disabled,false);
  for(const [id,value] of Object.entries({'margin-side':'short','margin-collateral':'100.000000000000000001','margin-risk':'2.5','margin-price':'76000.123456789012345678'}))p.node(id).value=value;
  await p.node('margin-preview-form').onsubmit({preventDefault(){}});
  assert.equal(calls[1].body.value.request.collateral,'100.000000000000000001');
  assert.equal(calls[1].body.value.request.open_price,'76000.123456789012345678');
  assert.equal(calls[1].body.value.request.side,'short');
  assert.equal(calls[1].body.value.catalogue_id,catalogue.run_id);
  assert.equal(p.node('margin-replay-fields').disabled,false);
  assert.ok(p.node('margin-preview').innerHTML.includes('0.0000004'));
  assert.equal(p.node('margin-from').value,'2026-11-06T00:00:01');
  p.node('margin-to').value='2026-11-06T00:01:00';p.node('margin-exit-fee').value='0.001';
  await p.node('margin-replay-form').onsubmit({preventDefault(){}});
  assert.equal(calls[2].body.value.preview_id,preview.run_id);
  assert.equal(calls[2].body.value.holding_seconds,null);
  assert.equal(calls[2].body.value.from,'2026-11-06T00:00:01Z');
  assert.ok(p.node('margin-result').innerHTML.includes('STALE'));
  p.context.document.documentElement.lang='fa';p.context.window.gymMargin.mount(p.options);
  assert.equal(p.node('margin-collateral').value,'100.000000000000000001');
  assert.equal(p.node('margin-replay-fields').disabled,false);
  assert.match(p.node('margin-workbench').innerHTML,/وثیقه/);
  p.node('margin-preview-form').oninput();
  assert.equal(p.node('margin-replay-fields').disabled,true);
});
test('duplicate pending requests are fenced and failed reads never enable preview', async () => {
  let reject;
  const calls=[];
  const p=page((...args)=>{calls.push(args);return new Promise((_,fail)=>{reject=fail;});});
  const pending=p.node('margin-load').onclick();
  await p.node('margin-load').onclick();assert.equal(calls.length,1);
  reject(new Error('upstream <script>private</script>'));await pending;
  assert.equal(p.node('margin-preview-fields').disabled,true);
  assert.doesNotMatch(p.node('margin-status').textContent,/<script>|private/);
});
test('a malformed receipt cannot enable the paper workflow', async () => {
  for (const response of [{...catalogue,schema:'unknown'},{}]) {
    const p=page(async()=>response);
    await p.node('margin-load').onclick();
    assert.equal(p.node('margin-preview-fields').disabled,true);
    assert.equal(p.node('margin-replay-fields').disabled,true);
  }
});
test('collateral rejection displays actual limits and keeps replay unavailable', async () => {
  const p=page(async (_url,options)=>JSON.parse(options.body).action==='margin-markets' ? catalogue :
    {...catalogue,kind:'COLLATERAL_LIMITS',state:'OUTSIDE_LIMITS',collateral_limits:{min:'50',max:'850',currency:'USDT'}});
  await p.node('margin-load').onclick();
  p.node('margin-collateral').value='10';p.node('margin-price').value='76000';
  await p.node('margin-preview-form').onsubmit({preventDefault(){}});
  assert.match(p.node('margin-preview').innerHTML,/50 – 850 USDT/);
  assert.equal(p.node('margin-replay-fields').disabled,true);
});

test('zone and language refresh receipts and replay events while preserving drafts and one pending replay',async()=>{
  let zone='Tehran', resolve, replays=0;
  const p=page(async (_url,options)=>{
    const {action}=JSON.parse(options.body);
    if(action==='margin-markets')return catalogue;
    if(action==='margin-preview')return preview;
    replays++;if(replays===2)await new Promise(done=>{resolve=done;});
    return {result:{state:'OPEN',mark:{status:'FRESH'},events:[{at:catalogue.received_at,action:'OPEN',price:'10'}]}};
  },false,value=>`${zone}:${value}`);
  await p.node('margin-load').onclick();
  p.node('margin-collateral').value='123.456';
  await p.node('margin-preview-form').onsubmit({preventDefault(){}});
  await p.node('margin-replay-form').onsubmit({preventDefault(){}});
  zone='UTC';p.context.window.gymMargin.mount(p.options);
  assert.match(p.node('margin-rules').innerHTML,/UTC:2026/);
  assert.match(p.node('margin-result').innerHTML,/UTC:2026/);
  assert.match(p.node('margin-result').innerHTML,/Time · selected zone/);
  assert.equal(p.node('margin-collateral').value,'123.456');assert.equal(replays,1);
  const pending=p.node('margin-replay-form').onsubmit({preventDefault(){}});
  zone='Tehran';p.context.window.gymMargin.mount(p.options);
  assert.match(p.node('margin-rules').innerHTML,/Tehran:2026/);
  assert.doesNotMatch(p.node('margin-result').innerHTML,/Time · UTC/);
  assert.equal(p.node('margin-replay-fields').disabled,true);
  p.context.document.documentElement.lang='fa';p.context.window.gymMargin.mount(p.options);
  resolve();await pending;
  p.context.document.documentElement.lang='fa';p.context.window.gymMargin.mount(p.options);
  assert.match(p.node('margin-result').innerHTML,/Tehran:2026/);
  assert.ok(p.node('margin-result').innerHTML.includes(require('./vocabulary.cjs').T.fa.mgTimeSelectedZone));
  assert.equal(p.node('margin-collateral').value,'123.456');assert.equal(replays,2);
});
