// 新闻标题标签:事件类型 / 涉及公司 / 方向(利好、利空、不确定)/ 是否直接相关。
// 只看标题里的关键词,是粗略判断,不是预测。原则:宁可少标,也不标错——
//   · 方向只在标题里有明确用词,并且明确是在说这家公司时才标;其余一律不标。
//   · 公司名对不上就不判断「直接 / 间接」,不乱猜。
// 纯函数,离线测试见 tools/test_newsread.js。
(function (root) {
  // 英文名 → 代码(只收常见的大公司;不在表里的公司只能靠标题里直接写出的代码识别)
  const ALIASES = {
    AAPL: ['Apple'], NVDA: ['Nvidia'], MSFT: ['Microsoft'], GOOGL: ['Google', 'Alphabet'], AMZN: ['Amazon'], META: ['Meta', 'Meta Platforms', 'Facebook', 'Instagram'], TSLA: ['Tesla'],
    AMD: ['Advanced Micro Devices'], AVGO: ['Broadcom'], TSM: ['TSMC', 'Taiwan Semiconductor'], INTC: ['Intel'], QCOM: ['Qualcomm'], MU: ['Micron'], WDC: ['Western Digital'], STX: ['Seagate'],
    SNDK: ['Sandisk'], ORCL: ['Oracle'], NFLX: ['Netflix'], CRM: ['Salesforce'], ADBE: ['Adobe'], PLTR: ['Palantir'], SMCI: ['Super Micro'], DELL: ['Dell'], ANET: ['Arista'], VRT: ['Vertiv'],
    JPM: ['JPMorgan', 'JP Morgan'], GS: ['Goldman Sachs'], MS: ['Morgan Stanley'], BAC: ['Bank of America'], WFC: ['Wells Fargo'], C: ['Citigroup'], V: ['Visa'], MA: ['Mastercard'],
    WMT: ['Walmart'], COST: ['Costco'], HD: ['Home Depot'], MCD: ["McDonald's", 'McDonalds'], NKE: ['Nike'], SBUX: ['Starbucks'], KO: ['Coca-Cola'], PEP: ['PepsiCo'], DIS: ['Disney'],
    XOM: ['Exxon'], CVX: ['Chevron'], LLY: ['Eli Lilly'], PFE: ['Pfizer'], JNJ: ['Johnson & Johnson'], MRK: ['Merck'], ABBV: ['AbbVie'], UNH: ['UnitedHealth'],
    LMT: ['Lockheed'], RTX: ['Raytheon'], NOC: ['Northrop'], BA: ['Boeing'], GD: ['General Dynamics'], UBER: ['Uber'], COIN: ['Coinbase'], SNOW: ['Snowflake'], 'BRK-B': ['Berkshire Hathaway', 'Berkshire']
  };
  const RE = s => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const NAME_RE = Object.entries(ALIASES).map(([t, ns]) => [t, new RegExp('\\b(?:' + ns.map(RE).join('|') + ')\\b', 'i')]);
  const PLAIN = Object.keys(ALIASES).filter(t => t.length >= 3 && !t.includes('-'));
  const PLAIN_RE = new RegExp('\\b(' + PLAIN.map(RE).join('|') + ')\\b', 'g');
  const PAREN_RE = /\(([A-Z]{1,5}(?:[.-][A-Z])?)\)/g;

  // 事件类型:按顺序匹配,先匹配到的生效
  const TYPES = [
    ['opinion', '观点文章', /^(should you|is\b.{0,60}\ba (buy|sell)\b|what (is|are|to)\b|why (is|are|did|does|could|might|may|should)\b|where will\b|how (to|many)\b)/i],
    ['opinion', '观点文章', /(here'?s (why|what|how)|just bought|stocks? to (buy|watch|sell)|\b\d+ [\w\s&$%-]{0,30}stocks?\b|\b(top|best|worst) [\w\s]{0,20}stocks?\b|\ba \d+-year-old\b|\bwith \$[\d.,]+ (million|thousand|billion)\b|\bfavor these\b|prediction|\bfund just (bought|sold)\b)/i],
    ['earnings', '财报', /\b(earnings|quarterly results|q[1-4]\b|fiscal (first|second|third|fourth)|revenue (beats?|misses|tops|falls|rises|jumps|growth)|\beps\b|guidance|results (beat|miss|top))/i],
    ['rating', '评级/目标价', /\b(upgrad\w*|downgrad\w*|price targets?|initiates? coverage|overweight|underweight|outperform|underperform|buy rating|sell rating)\b/i],
    ['mna', '并购', /\b(acqui(re|res|red|sition|ring)|mergers?|buyouts?|takeover|take[- ]private|spin[- ]?offs?)\b/i],
    ['legal', '监管/法律', /\b(lawsuits?|sues?|sued|probe|investigat\w*|antitrust|ftc|doj|fined?|settle(ment|s)?|subpoena|recall\w*|indict\w*|fraud|regulators?)\b/i],
    ['product', '产品/合作', /\b(launch(es|ed)?|unveil\w*|introduc(es|ed)|partnerships?|partners? with|contracts?|wins? (a |the )?(deal|contract|order)|new (product|model|chip|iphone|ai))\b/i],
    ['mgmt', '管理层', /\b(ceo|cfo|chairman|chief \w+ officer)\b.{0,40}\b(resign\w*|steps? down|appoint\w*|named|names|hires?|exits?|replace\w*|retire\w*|fired)\b/i],
    ['capital', '资本动作', /\b(buybacks?|repurchase\w*|dividends?|stock split|share offering|ipo|convertible|bond (sale|offering)|debt (offering|sale))\b/i],
    ['geo', '地缘政治', /\b(war|missiles?|houthis?|iran\w*|israel\w*|gaza|ukraine|russia\w*|sanctions?|military|ceasefire)\b/i],
    ['macro', '宏观/政策', /\b(fed|fomc|powell|rate (cut|hike)s?|interest rates?|inflation|cpi|ppi|jobs report|payrolls|unemployment|gdp|treasury yields?|recession|tariffs?|opec|oil prices?|shutdown|export controls?)\b/i],
    ['market', '大盘行情', /\b(dow|s&p 500|nasdaq|stock market|wall street|futures|bear market|bull market|sell-?off)\b/i]
  ];
  // 方向只认两种高把握情形(其余一律不标):
  //  A. 公司/股票本身紧跟涨跌动词(最多隔 2 个词),如 "Nvidia shares plunge"、"Tesla soars"
  //  B. 明确的财务事件用语,如 beats estimates、raises guidance、downgrades
  const UPV = 'surges?|soars?|jumps?|rall(?:y|ies)|climbs?|rises?|gains?|pops?|spikes?', DOWNV = 'plunges?|plummets?|tumbles?|sinks?|slumps?|falls?|drops?|slides?|crash(?:es)?|tanks?|slips?|dives?|lost|loses';
  const EVENT_UP = /\b(upgrad(?:es|ed)|(?:beats?|tops?) (?:\w+ )?(?:earnings|estimates|expectations|forecasts|revenue)|(?:raises?|boosts?|hikes?) (?:its |the )?(?:guidance|outlook|forecast|price target|dividend)|record (?:revenue|profit|earnings|sales|quarter))\b/i;
  const EVENT_DOWN = /\b(downgrad(?:es|ed)|miss(?:es|ed)? (?:\w+ )?(?:earnings|estimates|expectations|forecasts|revenue)|(?:cuts?|lowers?|slashes) (?:its |the )?(?:guidance|outlook|forecast|price target|dividend)|files? for bankruptcy|lays? off|layoffs|recall(?:s|ed)?|faces? (?:a )?(?:lawsuit|probe|investigation)|under (?:investigation|probe))\b/i;
  const subjectMove = (t, names, verbs) => new RegExp('(?:' + names.join('|') + ')\\W+(?:(?:just|now|stock|shares|share|price|also)\\W+){0,2}(?:' + verbs + ')\\b(?!\\W+(?:through|ship|in love|into|to conclusions|a hint))', 'i').test(t);      // 排除 jumps through hoops、falls in love 之类的习惯用语

  // opts: { sym: 当前个股页的代码(快讯页不传) }
  function newsRead(title, opts) {
    const t = String(title || ''), sym = opts && opts.sym ? String(opts.sym).toUpperCase() : null, r = { type: null, dir: null, tickers: [], direct: null };
    if (!t) return r;
    for (const [key, label, re] of TYPES) if (re.test(t)) { r.type = { key, label }; break; }
    // 涉及的公司
    const seen = [], add = x => { if (x && !seen.includes(x)) seen.push(x); };
    for (const [tk, re] of NAME_RE) if (re.test(t)) add(tk);
    let m; PLAIN_RE.lastIndex = 0; while ((m = PLAIN_RE.exec(t))) add(m[1]);
    PAREN_RE.lastIndex = 0; while ((m = PAREN_RE.exec(t))) add(m[1]);
    r.tickers = seen.slice(0, 3);
    // 是否直接相关:只有知道这家公司在新闻里怎么称呼(在别名表里,或代码直接出现)才判断
    if (sym) {
      const mentioned = seen.includes(sym) || new RegExp('\\b' + RE(sym) + '\\b').test(t);
      r.direct = mentioned ? true : (ALIASES[sym] ? false : null);
    }
    // 方向:见上面的规则 A / B;并且必须明确是在说某一家公司(个股页要求直接相关;快讯页要求标题里恰好只有一家公司)
    const about = sym ? r.direct === true : seen.length === 1;
    if (about) {
      const names = [...(sym ? [RE(sym)] : []), ...seen.map(RE), ...seen.flatMap(tk => (ALIASES[tk] || []).map(RE)), 'stock', 'shares', 'stocks'];
      const up = EVENT_UP.test(t) || subjectMove(t, names, UPV), down = EVENT_DOWN.test(t) || subjectMove(t, names, DOWNV);
      if (up || down) r.dir = up && down ? 'mixed' : up ? 'up' : 'down';
    }
    return r;
  }

  const esc = x => String(x).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const DIRS = { up: ['利好', 'nt-up'], down: ['利空', 'nt-down'], mixed: ['利好利空都有', 'nt-mix'] };
  function newsTagsHTML(r, sym) {
    if (!r) return '';
    const out = [];
    if (r.type) out.push(`<span class="ntag nt-type">${esc(r.type.label)}</span>`);
    if (r.dir) out.push(`<span class="ntag ${DIRS[r.dir][1]}" title="只看标题里的明确用词,不是预测股价">${DIRS[r.dir][0]}</span>`);
    if (sym && r.direct === false) out.push(`<span class="ntag nt-ind" title="标题里没有直接提到 ${esc(sym)}">间接相关</span>`);
    r.tickers.filter(x => x !== sym).forEach(x => out.push(`<span class="ntag nt-co" data-go="${esc(x)}" role="button" tabindex="0" title="打开 ${esc(x)}">${esc(x)}</span>`));
    return out.length ? `<div class="ntags">${out.join('')}</div>` : '';
  }

  const api = { newsRead, newsTagsHTML, ALIASES };
  if (typeof module !== 'undefined' && module.exports) module.exports = api; else Object.assign(root, api);
})(typeof window !== 'undefined' ? window : globalThis);
