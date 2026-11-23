// 经济日历展示逻辑的离线测试。运行:node tools/test_econcal.js
const assert = require('assert');
const { econGroups, econHTML } = require('../public/econcal.js');

const it = (date, key, name, imp, desc) => ({ date, key, name, imp, desc: desc || name + '的说明', src: 'x' });
const items = [it('2026-12-10', 'cpi', 'CPI 通胀数据', 3), it('2026-12-09', 'fomc', 'FOMC 利率决议', 3), it('2026-12-09', 'ppi', 'PPI 生产者物价', 2), it('2026-11-22', 'jolts', 'JOLTS 职位空缺', 2),
  it('2026-12-30', 'fomc_min', 'FOMC 会议纪要', 2), it('2026-11-20', 'old', '已经过去的', 3)];

// ---------- 分组 ----------
let g = econGroups(items, '2026-11-22');
assert.deepStrictEqual(g.map(x => x.date), ['2026-11-22', '2026-12-09', '2026-12-10', '2026-12-30'], '按日期排序,过去的不显示');
assert.deepStrictEqual(g.map(x => x.label), ['今天', '17 天后', '18 天后', '38 天后']);
assert.strictEqual(g[0].md, '11/22'); assert.strictEqual(g[0].wk, '周日');                      // 2026-11-22 是周日
assert.strictEqual(g[1].wk, '周三'); assert.strictEqual(g[2].wk, '周四');                        // 12-09 周三,12-10 周四
assert.deepStrictEqual(g[1].items.map(i => i.key), ['fomc', 'ppi'], '同一天里重要的在前');
assert.strictEqual(econGroups(items, '2026-11-23')[0].date, '2026-12-09', '昨天的事件不显示');
assert.strictEqual(econGroups([it('2026-11-23', 'x', 'x', 3)], '2026-11-22')[0].label, '明天');
// 跨月、跨年、闰日也要算对天数
assert.strictEqual(econGroups([it('2027-01-05', 'x', 'x', 3)], '2026-12-30')[0].label, '6 天后');
assert.strictEqual(econGroups([it('2028-03-01', 'x', 'x', 3)], '2028-02-27')[0].label, '3 天后');                // 2028 闰年:2/28、2/29、3/1
// 坏数据不报错
assert.deepStrictEqual(econGroups(null, '2026-11-22'), []); assert.deepStrictEqual(econGroups([{ date: '乱码' }, null, {}], '2026-11-22'), []); assert.deepStrictEqual(econGroups(items, '乱码'), []);

// ---------- HTML ----------
let h = econHTML({ items, fred: true }, '2026-11-22');
assert(h.includes('未来 30 天重要经济事件') && h.includes('只有日期,没有具体发布时间'), '要写明没有具体时间');
assert(h.includes('FOMC 利率决议') && h.includes('CPI 通胀数据') && h.includes('重要') && h.includes('一般') && h.includes('17 天后'));
assert(!h.includes('已经过去的'), '过去的不出现');
assert(!h.includes('暂时取不到'), 'FRED 正常时不提示');
assert(h.indexOf('JOLTS') < h.indexOf('FOMC 利率决议'), '日期早的在前');
assert(h.includes('数据来源') && h.includes('FRED') && h.includes('美联储官网'));
// FRED 取不到:只有 FOMC,要说明
h = econHTML({ items: [it('2026-12-09', 'fomc', 'FOMC 利率决议', 3)], fred: false }, '2026-11-22');
assert(h.includes('暂时取不到') && h.includes('FOMC 利率决议'));
// 没有事件、加载失败、演示模式
assert(econHTML({ items: [], fred: true }, '2026-11-22').includes('没有收录的重要经济事件'));
assert(econHTML(null, '2026-11-22').includes('加载失败'));
assert(econHTML({ mock: true, items: [] }, '2026-11-22').includes('演示模式'));
// 转义
h = econHTML({ items: [it('2026-12-09', 'x', '<img onerror=x>', 3, '<script>alert(1)</script>')], fred: true }, '2026-11-22');
assert(!h.includes('<img') && !h.includes('<script>'), '事件名和说明要转义');
// 重要程度未知也不崩
assert(econHTML({ items: [it('2026-12-09', 'x', '未知', 9)], fred: true }, '2026-11-22').includes('未知'));
console.log('全部通过');
