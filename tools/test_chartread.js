// 「这张图在说什么」的离线测试:用构造的K线检查每句话里的数字和结论。运行:node tools/test_chartread.js
const assert = require('assert');
const { chartRead, chartReadHTML, termify } = require('../public/chartread.js');

const mk = (closes, rng = 1) => closes.map((c, i) => ({ t: `2026-01-${String(i % 28 + 1).padStart(2, '0')}`, o: c, h: c + rng, l: c - rng, c, v: 1000 }));
const ramp = (a, b, n) => Array.from({ length: n }, (_, i) => a + (b - a) * i / (n - 1));
const noNaN = r => assert(!/NaN|undefined|Infinity/.test(JSON.stringify(r)), 'NaN/undefined 出现在输出里');
const get = (r, k) => r.items.find(i => i.key === k);

// 数据不够:不解读
assert.strictEqual(chartRead({ bars: mk(ramp(100, 110, 30)), price: 110 }), null);
assert.strictEqual(chartRead({ bars: mk(ramp(100, 110, 60)), price: NaN }), null);

// 上涨:价格 > 20 日 > 50 日 > 200 日
let r = chartRead({ bars: mk(ramp(100, 200, 220)), price: 200 });
noNaN(r);
assert(get(r, 'trend').text.startsWith('上涨趋势') && get(r, 'trend').text.includes('长期趋势同样偏强'), get(r, 'trend').text);
assert.strictEqual(get(r, 'trend').tone, 'ok');
// 均线数字要和手算一致(最后 20 个收盘的平均)
const cl = ramp(100, 200, 220), m20 = cl.slice(-20).reduce((a, b) => a + b) / 20;
assert.strictEqual(get(r, 'trend').basis[1][1], m20.toFixed(2));
// 位置:价格就是最高点 → 高位区
assert(get(r, 'pos').text.includes('接近一年内的高点'), get(r, 'pos').text);

// 下跌
r = chartRead({ bars: mk(ramp(200, 100, 220)), price: 100 });
assert(get(r, 'trend').text.startsWith('下跌趋势') && get(r, 'trend').text.includes('长期趋势同样偏弱'));
assert.strictEqual(get(r, 'trend').tone, 'bad');
assert(get(r, 'pos').text.includes('离高点还很远'), get(r, 'pos').text);       // 比高点低约 50%

// 上市不足 200 天:长期均线写"数据不足",不编造
r = chartRead({ bars: mk(ramp(100, 150, 120)), price: 150 });
assert(get(r, 'trend').basis[3][1].startsWith('数据不足'));
assert(!get(r, 'trend').text.includes('200 日线'));

// 震荡
const wob = Array.from({ length: 120 }, (_, i) => 100 + (i % 2 ? 1 : -1));
r = chartRead({ bars: mk(wob), price: 100 });
assert(get(r, 'trend').text.startsWith('方向不明'));

// 支撑压力:数字、强度、为什么
const base = mk(ramp(100, 100.5, 120));
r = chartRead({ bars: base, price: 100, sr: { all: [{ p: 110, s: 1.9, src: '筹码+高点', kind: 'res' }, { p: 90, s: 1.3, src: '低点', kind: 'sup' }, { p: 120, s: 0.3, src: '高点', kind: 'res' }], tl: [] } });
let sr = get(r, 'sr');
assert(sr.text.includes('110.00(比现价高 10.0%,强度强)') && sr.text.includes('90.00(比现价低 10.0%,强度中)'), sr.text);
assert(sr.basis[0][1].includes('成交量特别大') && sr.basis[1][1].includes('反弹过'), JSON.stringify(sr.basis));
assert(!sr.text.includes('120.00'), '太弱的位置(强度<0.45)不该出现');
// 离压力位/支撑位很近的提醒
r = chartRead({ bars: base, price: 100, sr: { all: [{ p: 101, s: 1.5, src: '高点', kind: 'res' }, { p: 99, s: 1.5, src: '低点', kind: 'sup' }], tl: [] } });
sr = get(r, 'sr'); assert(sr.text.includes('离压力位很近') && sr.text.includes('离支撑位很近'), sr.text);
// 找不到时直接说没有,不硬凑
r = chartRead({ bars: base, price: 100, sr: { all: [], tl: [] } });
assert(get(r, 'sr').text.includes('上方附近没有明显的压力位') && get(r, 'sr').text.includes('下方附近没有明显的支撑位'));

// 趋势线:最后一根上的线值要等于构造值(yp 取 ln(95),斜率 0 → 线值 95)
r = chartRead({ bars: base, price: 100, sr: { all: [], tl: [{ low: true, p: 10, q: 60, yp: Math.log(95), slope: 0, touches: 3 }] } });
assert(get(r, 'tl').text.includes('上升趋势线') && get(r, 'tl').text.includes('约在 95.00') && get(r, 'tl').text.includes('上方 5.3%') && get(r, 'tl').text.includes('3 次'), get(r, 'tl') && get(r, 'tl').text);
r = chartRead({ bars: base, price: 100, sr: { all: [], tl: [{ low: false, p: 10, q: 60, yp: Math.log(105), slope: 0, touches: 2 }] } });
assert(get(r, 'tl').text.includes('下降趋势线') && get(r, 'tl').text.includes('下方 4.8%'), get(r, 'tl').text);

// 成交量
r = chartRead({ bars: base, price: 100, volRatio: 1.5, pct: 2 });
assert(get(r, 'vol').text.includes('放量') && get(r, 'vol').text.includes('价格上涨'));
r = chartRead({ bars: base, price: 100, volRatio: 1.5, pct: -2, marketOpen: true });
assert(get(r, 'vol').text.includes('卖出的压力偏大') && get(r, 'vol').text.includes('盘中成交量还没走完'));
r = chartRead({ bars: base, price: 100, volRatio: 0.5 });
assert(get(r, 'vol').text.includes('缩量'));
r = chartRead({ bars: base, price: 100, volRatio: 1.0 });
assert(get(r, 'vol').text.includes('成交量正常'));
assert(!chartRead({ bars: base, price: 100, volRatio: 1.5, isIdx: true }).items.find(i => i.key === 'vol'), '指数没有量比');
assert(!chartRead({ bars: base, price: 100 }).items.find(i => i.key === 'vol'), '没有量比数据就不写');

// 波动:每天高低差 2、收盘不变 → ATR=2 → 占 2%
r = chartRead({ bars: mk(Array(60).fill(100)), price: 100 });
assert(get(r, 'vola').text.includes('2.0%') && get(r, 'vola').text.includes('波动中等'), get(r, 'vola').text);

// 摘要最多两条;HTML 里有名词解释且转义安全
r = chartRead({ bars: mk(ramp(100, 200, 220)), price: 200, sr: { all: [], tl: [] } });
assert(r.summary.length <= 2);
const html = chartReadHTML(r);
assert(html.includes('<abbr class="term"') && html.includes('再看') && html.includes('看依据'));
assert.strictEqual((html.match(/class="cr-/g) || []).length + (html.match(/class="cri"/g) || []).length, r.items.length, '每一项只出现一次,不重复');
// 默认显示的两句话要短:趋势取第一句,支撑压力不带「离得很近」的补充句
r = chartRead({ bars: base, price: 100, sr: { all: [{ p: 101, s: 1.5, src: '高点', kind: 'res' }], tl: [] } });
assert(!r.summary.find(i => i.key === 'sr').short.includes('离压力位很近') && get(r, 'sr').text.includes('离压力位很近'));
assert(r.summary.find(i => i.key === 'trend').short.split('。').length === 2);
assert.strictEqual(termify('<script>均线</script>').includes('<script>'), false);
assert(chartReadHTML(null).includes('数据不足'));
console.log('全部通过');
