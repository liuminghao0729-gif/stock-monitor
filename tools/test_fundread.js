// 「这家公司怎么样」的离线测试:用构造的财报数据检查每句话里的数字和结论。运行:node tools/test_fundread.js
const assert = require('assert');
const { fundRead, fundReadHTML, termify } = require('../public/fundread.js');
const noBad = r => assert(!/NaN|undefined|Infinity|null/.test(JSON.stringify(r)), '输出里有 NaN/undefined/null:' + JSON.stringify(r).match(/.{20}(NaN|undefined|Infinity|null).{20}/));
const get = (r, k) => r.items.find(i => i.key === k);

const ttm = { end: '2026-09-26', rev: 400e9, gp: 180e9, oi: 120e9, ni: 100e9, fcf: 90e9, eps: 5, rev_yoy: 12, ni_yoy: 20, eps_yoy: 22, gm: 45, om: 30, nm: 25 };
const rows = [{ end: '2025-12-27', rev_yoy: 8 }, { end: '2026-03-28', rev_yoy: 10, est: true }, { end: '2026-06-27', rev_yoy: 11 }, { end: '2026-09-26', rev_yoy: 14 }];
const health = { price: 100, checkup: [{ name: '净现金 / 净债务', val: '净债务 $50.0B(约 0.5 年经营现金流可还清)' }], fscore: { score: 8, of: 9, level: '强' }, zscore: { z: 3.5, zone: '安全区' },
  dcf: { scenarios: [{ name: '保守', value: 60 }, { name: '中性', value: 80 }, { name: '乐观', value: 100 }] } };
const fin = { ttm, rows, years: [] };

// 无数据 → 不输出
assert.strictEqual(fundRead(null), null);
assert.strictEqual(fundRead({ fin: { error: 'no_cik' } }), null);
assert.strictEqual(fundRead({ fin: { ttm: {} } }), null);

// 完整:四项都在,数字对得上
let r = fundRead({ fin, health, stats: { forwardPE: 18, pegRatio: 1.2 }, price: 100 }); noBad(r);
assert.deepStrictEqual(r.items.map(i => i.key), ['profit', 'growth', 'safety', 'value']);
assert.strictEqual(r.asof, '2026-09-26');
let p = get(r, 'profit'); assert(p.verdict === '赚钱能力强' && p.short.includes('25.0 元') && p.text.includes('4000.0 亿美元') || p.text.includes('4000 亿美元'), p.text);
assert(p.text.includes('毛利率 45.0%(较高)') && p.tone === 'ok');
let g = get(r, 'growth'); assert(g.verdict === '稳健增长' && g.short.includes('增长 12.0%'), g.short);
assert(g.text.includes('+8.0%、+10.0%、+11.0%、+14.0%') && g.text.includes('增速在加快') && g.text.includes('快于收入增速'), g.text);
assert(g.lines.join('').includes('含推算'), '推算的季度要标出来');
let s = get(r, 'safety'); assert(s.verdict === '偏稳' && s.text.includes('自由现金流为正(900 亿美元)') && s.text.includes('净债务 $50.0B') && s.text.includes('3.5,处在安全区') && s.text.includes('8/9'), s.text);
let v = get(r, 'value'); assert(v.text.includes('市盈率 20.0 倍') && v.text.includes('20 年') && v.text.includes('18.0 倍') && v.text.includes('PEG 是 1.20'), v.text);   // 100 / 5 = 20
assert(v.text.includes('60 / 80 / 100') && v.text.includes('1.3 倍'), v.text);     // 100 / 80 = 1.25 → 1.3
assert.strictEqual(v.verdict, '中等');                                          // PEG 1.2 → 中,DCF 1.25 → 中

// 估值:两个角度都偏高 / 都偏低 / 不一致
r = fundRead({ fin, health, stats: { pegRatio: 3 }, price: 200 }); assert.strictEqual(get(r, 'value').verdict, '偏高'); assert.strictEqual(get(r, 'value').tone, 'w');   // 200/80=2.5>1.5
r = fundRead({ fin, health, stats: { pegRatio: 0.5 }, price: 50 }); assert.strictEqual(get(r, 'value').verdict, '偏低');                                           // 50/80=0.63<0.8
r = fundRead({ fin, health, stats: { pegRatio: 3 }, price: 50 }); assert.strictEqual(get(r, 'value').verdict, '看法不一致'); assert(get(r, 'value').text.includes('不好下结论'));

// 亏损公司:赚钱写亏损;市盈率写无意义,不能算出一个负的市盈率
const lossTtm = Object.assign({}, ttm, { ni: -20e9, nm: -5, eps: -1, ni_yoy: -50, fcf: -10e9 });
r = fundRead({ fin: { ttm: lossTtm, rows, years: [] }, health: Object.assign({}, health, { dcf: { error: 'n/a' }, zscore: { z: 1.5, zone: '灰色区' } }), stats: { forwardPE: -3, pegRatio: -1 }, price: 30 }); noBad(r);
p = get(r, 'profit'); assert(p.verdict === '亏损' && p.short.includes('亏约 5.0 元') && p.tone === 'bad');
v = get(r, 'value'); assert(v.text.includes('没有意义') && !/市盈率 -/.test(v.text) && v.short.includes('市盈率无意义'), v.text);
assert(!v.text.includes('预期市盈率'), '负的预期市盈率不能当成有效数据');
s = get(r, 'safety'); assert(s.verdict === '风险较高' && s.text.includes('自由现金流为负'), s.verdict + s.text);     // 现金流为负 + 灰色区
assert(!get(r, 'growth').text.includes('快于') && !get(r, 'growth').text.includes('慢于'), '亏损时不比较利润增速和收入增速');

// 缺数据:没有体检/估值指标时,只写有的;不编造
r = fundRead({ fin, health: null, stats: null, price: 100 }); noBad(r);
assert.deepStrictEqual(r.items.map(i => i.key), ['profit', 'growth', 'safety', 'value']);          // 安全项来自现金流,估值项来自市盈率
assert(get(r, 'value').verdict === '数据不足' && get(r, 'value').text.includes('市盈率 20.0 倍'));
assert(get(r, 'safety').chips.find(c => c[0] === 'Z 分数')[1] === '数据不足');
const noFcf = Object.assign({}, ttm); delete noFcf.fcf;
r = fundRead({ fin: { ttm: noFcf, rows, years: [] }, health: null, stats: null, price: null }); assert(!r.items.find(i => i.key === 'safety'), '完全没有安全相关数据就不写这一项');
// 增速:下滑 / 放缓
r = fundRead({ fin: { ttm: Object.assign({}, ttm, { rev_yoy: -5 }), rows: [{ end: 'a', rev_yoy: 5 }, { end: 'b', rev_yoy: -2 }], years: [] }, price: 100 });
g = get(r, 'growth'); assert(g.verdict === '收入下滑' && g.short.includes('下降 5.0%') && g.text.includes('增速在放缓') && g.tone === 'bad', g.text);
// 每项默认只有一句话
r = fundRead({ fin, health, stats: { forwardPE: 18, pegRatio: 1.2 }, price: 100 });
r.items.forEach(i => assert(i.short.split('。').filter(Boolean).length === 1, i.key + ' 的默认文字不止一句:' + i.short));
// HTML:名词解释、转义、依据
const html = fundReadHTML(r);
assert(html.includes('<abbr class="term"') && html.includes('看依据') && html.includes('报告期 2026-09-26'));
assert.strictEqual(termify('<img onerror=x>市盈率').includes('<img'), false);
assert.strictEqual(fundReadHTML(null), '');

// 「看依据」要简洁:每项 3 个关键数字 + 最多 2 行补充 + 一句解释 + 最多 2 条判断线;每一块都很短
r = fundRead({ fin, health, stats: { forwardPE: 18, pegRatio: 1.2, trailingEps: 9 }, price: 100 });
r.items.forEach(i => {
  assert.strictEqual(i.chips.length, 3, i.key + ' 应有 3 个关键数字');
  assert(i.lines.length <= 3, i.key + ' 补充行太多');
  assert(i.rules.length >= 1 && i.rules.length <= 2, i.key + ' 判断线 1~2 条');
  assert(i.explain.length <= 45, i.key + ' 的解释太长:' + i.explain.length);
  i.lines.forEach(l => assert(l.length <= 80, i.key + ' 的补充行太长:' + l));
  i.rules.forEach(l => assert(l.length <= 80, i.key + ' 的判断线太长:' + l));
  i.chips.forEach(c => assert(c[0].length <= 8 && String(c[1]).length <= 12 && String(c[2]).length <= 8, i.key + ' 的关键数字格子太长:' + c));
});
// 页面上「看依据」展开后的纯文字量要小(不再是一大段文字 + 长表格)
const detailText = (fundReadHTML(r).match(/<details[\s\S]*?<\/details>/g) || []).map(x => x.replace(/<[^>]+>/g, '').length);
console.log('展开后每项的文字量:', detailText.join(' / '));
assert.strictEqual(detailText.length, 4);
detailText.forEach(n => assert(n < 290, '展开后的文字太多:' + n));
// 关键数字直接可见:市盈率、PEG、折现倍数
const vh = fundReadHTML(r); assert(vh.includes('<b>20.0 倍</b>') && vh.includes('<b>1.20</b>') && vh.includes('<b>1.3 倍</b>'), '估值的三个关键数字');

// 财报数据太旧(例如停在 2014 年):不解读,并说明原因
const old = fundRead({ fin: { ttm: Object.assign({}, ttm, { end: '2014-12-31' }), rows, years: [] }, price: 300, now: Date.parse('2026-11-22') });
assert(old && old.stale === true && old.items.length === 0 && old.asof === '2014-12-31');
assert(fundReadHTML(old).includes('2014-12-31') && fundReadHTML(old).includes('太旧') && !fundReadHTML(old).includes('市盈率'));
assert(!fundRead({ fin, price: 100, now: Date.parse('2026-11-22') }).stale, '2026-09-26 的财报不算旧');
assert(fundRead({ fin, price: 100, now: Date.parse('2027-04-30') }).stale === true, '超过 200 天算旧');

// 亏损公司 + Yahoo 给了正的 PEG:不能据此写「估值偏低」
r = fundRead({ fin: { ttm: lossTtm, rows, years: [] }, health: null, stats: { forwardPE: 20, pegRatio: 0.84 }, price: 1 });
assert(get(r, 'value').verdict === '数据不足' && !get(r, 'value').text.includes('PEG') && get(r, 'value').short.includes('估值判断依据不足'), get(r, 'value').short);

// 两个来源的每股盈利差很多:提醒只作粗略参考;差得不多不提醒
r = fundRead({ fin, health: null, stats: { trailingEps: 9 }, price: 100 });
assert(get(r, 'value').text.includes('相差较大'));
r = fundRead({ fin, health: null, stats: { trailingEps: 5.2 }, price: 100 });
assert(!get(r, 'value').text.includes('相差较大'));
console.log('全部通过');
