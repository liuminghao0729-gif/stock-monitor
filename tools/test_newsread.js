// 新闻标题标签的离线测试。重点:「明确标了方向的不能错」——宁可少标,也不标错。运行:node tools/test_newsread.js
const assert = require('assert');
const { newsRead, newsTagsHTML } = require('../public/newsread.js');
const R = (t, sym) => newsRead(t, sym ? { sym } : {});
const dir = (t, sym) => R(t, sym).dir, typ = (t, sym) => (R(t, sym).type || {}).key || null;

// ---------- 方向:该标的要标对 ----------
assert.strictEqual(dir('Nvidia Just Lost Nearly Half Its Value. A 62-Year-Old With $1 Million', 'NVDA'), 'down');      // 真实标题
assert.strictEqual(dir('Nvidia shares plunge after export curbs', 'NVDA'), 'down');
assert.strictEqual(dir('Apple stock jumps on strong iPhone sales', 'AAPL'), 'up');
assert.strictEqual(dir('Tesla soars as deliveries beat forecasts', 'TSLA'), 'up');
assert.strictEqual(dir('Morgan Stanley upgrades Apple to Overweight', 'AAPL'), 'up');
assert.strictEqual(dir('Goldman downgrades Nvidia, cuts price target', 'NVDA'), 'down');
assert.strictEqual(dir('Micron beats estimates and raises guidance', 'MU'), 'up');
assert.strictEqual(dir('Intel misses earnings expectations, cuts outlook', 'INTC'), 'down');
assert.strictEqual(dir('Boeing files for bankruptcy protection', 'BA'), 'down');
assert.strictEqual(dir('Tesla faces probe over autopilot crashes', 'TSLA'), 'down');
assert.strictEqual(dir('Microsoft hits record revenue, but stock slides on weak cloud guidance', 'MSFT'), 'mixed');   // 利好利空都有
// 快讯页(不传代码):标题里恰好一家公司 + 明确用语
assert.strictEqual(dir('Oracle surges after cloud contract win'), 'up');
assert.strictEqual(dir('Meta shares tumble as ad revenue misses estimates'), 'down');

// ---------- 方向:不该标的不能标(真实误判过的标题) ----------
assert.strictEqual(dir("Apple’s CEO Calls Memory Pricing “Unprecedented.” Its Purchase Obligations Jumped $33 Billion", 'AAPL'), null);   // 成本上升,不是利好
assert.strictEqual(dir('Why is Apple Stock Holding Strong While the Rest of the Market Falls?', 'AAPL'), null);                          // 跌的是大盘
assert.strictEqual(dir('Dow Jones Futures Rise As Oracle, Korea Try To Ease Market Fears', 'NVDA'), null);                                  // 与英伟达无关
assert.strictEqual(dir('Dow Jones Futures Rise As Oracle, Korea Try To Ease Market Fears'), null);                                          // 在说大盘
assert.strictEqual(dir('Apple jumps through hoops to appease EU regulators', 'AAPL'), null);                                                // jumps 不是涨
assert.strictEqual(dir('Nvidia CEO falls in love with new robot', 'NVDA'), null);                                                           // falls 不是跌(后面不是涨跌对象)
assert.strictEqual(dir('Apple sues rival over patents', 'AAPL'), null);                                                                     // 苹果是原告,方向不明
assert.strictEqual(dir('Upstart soars after earnings beat', 'NVDA'), null);                                                                 // 说的是别的公司
assert.strictEqual(dir('Oil surges as Houthis attack refinery'), null);                                                                     // 没有公司
assert.strictEqual(dir('Apple and Microsoft surge while Nvidia falls'), null);                                                              // 好几家公司,说不清
assert.strictEqual(dir('Employees at robot startup lose health benefits'), null);
assert.strictEqual(dir("Israel's Eisenkot condemns arson attacks"), null);

// ---------- 事件类型 ----------
const T = [
  ['Apple reports Q4 earnings, revenue tops estimates', 'earnings'], ['Nvidia raises guidance for next quarter', 'earnings'],
  ['Morgan Stanley upgrades Apple', 'rating'], ['Citi raises Tesla price target to $400', 'rating'],
  ['Broadcom to acquire software maker in $60 billion deal', 'mna'], ['Chipmaker merger gets approval', 'mna'],
  ['FTC opens antitrust investigation into Microsoft', 'legal'], ['Tesla recalls 100,000 vehicles', 'legal'],
  ['Apple unveils new iPhone with AI features', 'product'], ['AMD announces partnership with OpenAI', 'product'],
  ['Intel CEO steps down after board dispute', 'mgmt'], ['Nvidia announces $50 billion buyback', 'capital'], ['Apple raises dividend by 4%', 'capital'],
  ['Houthis say they attacked Saudi Rabigh oil refinery - Reuters', 'geo'], ["Israel's Eisenkot condemns arson attacks by Jewish settlers", 'geo'],
  ['Fed signals rate cut as inflation cools', 'macro'], ['Trump tariffs on chips take effect', 'macro'], ['Wall Street ends lower as Nasdaq slides', 'market'],
  // 观点/荐股文章要优先识别(它们的标题常带「财报」「分红」「合并」等词,但并不是事件)
  ['Should You Buy Tesla or SpaceX Stock Before Their Potential Merger?', 'opinion'], ['A $6.4 Billion Fund Just Bought These 3 Stocks', 'opinion'],
  ["Procter & Gamble Has Raised Its Dividend 70 Straight Years. Here's Why I'd Buy Before 2027.", 'opinion'],
  ['3 AI Hardware Stocks Down More Than 30% From Their Records to Buy Now', 'opinion'], ['Top Wall Street analysts favor these 3 dividend stocks for strong returns', 'opinion'],
  ['Nvidia Just Lost Nearly Half Its Value. A 62-Year-Old With $1 Million in an S&P 500 Index Fund', 'opinion'], ['What Is Apple (AAPL) Planning With Its New Autonomous AI Agent?', 'opinion']
];
T.forEach(([t, k]) => assert.strictEqual(typ(t), k, `${t} → ${typ(t)}(期望 ${k})`));
assert.strictEqual(typ('Pizza chains are under pressure. GLP-1 use is only one part of the problem'), null);                              // 没把握就不标类型
assert.strictEqual(typ('Director of National Intelligence warns Americans of bumps in the road'), null);

// ---------- 涉及公司 / 直接相关 ----------
let r = R("Apple Is Now 25% of Berkshire Hathaway's Stock Portfolio", 'NVDA'); assert.deepStrictEqual(r.tickers, ['AAPL', 'BRK-B']); assert.strictEqual(r.direct, false);
r = R('What Is Apple (AAPL) Planning With Its New AI Agent?', 'AAPL'); assert.strictEqual(r.direct, true); assert.deepStrictEqual(r.tickers, ['AAPL']);
assert.strictEqual(R('AAPL slips as iPhone orders slow', 'AAPL').direct, true);                       // 标题里直接写了代码
assert.strictEqual(R('Some unknown small cap rallies', 'ZZZZ').direct, null);                          // 不知道这家公司怎么称呼:不判断直接还是间接
assert.strictEqual(R('Apple unveils new Mac', 'ZZZZ').direct, null);
assert.strictEqual(R('Microsoft (MSFT) and Alphabet (GOOGL) lead rally').tickers.length, 2);
assert.strictEqual(R('A B C D E F G').tickers.length, 0);                                              // 单个字母不乱识别
assert.deepStrictEqual(R('Nike (NKE) and Visa (V) and Citi (C) and Meta Platforms and Amazon news').tickers.length, 3);   // 最多 3 个
assert.deepStrictEqual(R('Visa and Mastercard settle').tickers.sort(), ['MA', 'V']);
assert.deepStrictEqual(R('').tickers, []); assert.strictEqual(R(null).dir, null); assert.strictEqual(R(undefined).type, null);

// ---------- HTML ----------
let h = newsTagsHTML(R('Goldman downgrades Nvidia, cuts price target', 'NVDA'), 'NVDA');
assert(h.includes('评级/目标价') && h.includes('利空') && h.includes('不是预测股价'));
h = newsTagsHTML(R("Apple Is Now 25% of Berkshire Hathaway's Stock Portfolio", 'NVDA'), 'NVDA');
assert(h.includes('间接相关') && h.includes('data-go="AAPL"') && h.includes('data-go="BRK-B"') && !h.includes('data-go="NVDA"'));
assert.strictEqual(newsTagsHTML(R('Pizza chains are under pressure'), null), '', '什么都没识别出来就不输出任何标签');
assert.strictEqual(newsTagsHTML(null), '');
h = newsTagsHTML({ type: null, dir: null, tickers: ['<img onerror=x>'], direct: null }, null); assert(!h.includes('<img'), '转义');
console.log('全部通过');
