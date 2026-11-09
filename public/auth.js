// Google 登录 + 云端同步自选股(Supabase)。没配置或没登录时,网站照常用浏览器本地存储。
// 连接信息(项目地址、公开 key)由 /api/status 从部署平台的环境变量里下发,不写在代码里。
let CLOUD = { sb: null, user: null, saving: 0, tg: { id: '', on: true, ready: false } };
const cloudBox = () => document.getElementById('authBox');

function paintAuth() {
  const b = cloudBox(); if (!b) return;
  if (!CLOUD.sb) { b.innerHTML = ''; return; }
  const u = CLOUD.user;
  paintTg();
  b.innerHTML = u
    ? `<span class="authme" title="${esc(u.email || '')}">${u.user_metadata && u.user_metadata.avatar_url ? `<img src="${esc(u.user_metadata.avatar_url)}" alt="" referrerpolicy="no-referrer">` : ''}<span>${esc((u.user_metadata && u.user_metadata.name) || u.email || '已登录')}</span></span><button class="authbtn" id="authOut">退出</button>`
    : '<button class="authbtn" id="authIn">Google 登录</button>';
}

// ----- Telegram 盘中每小时摘要:用户自己填 Telegram 编号,开关保存在自己的云端数据里(只有本人和管理员的推送任务能读) -----
function paintTg() {
  const el = document.getElementById('tgBox'); if (!el) return;
  if (!CLOUD.sb) { el.innerHTML = ''; return; }
  if (!CLOUD.user) { el.innerHTML = '<h3 style="margin-top:0">Telegram 盘中提醒</h3><div class="muted small">登录 Google 后,可以把你的自选股和持仓变化,在美股交易时段每小时发到你的 Telegram。</div>'; return; }
  const t = CLOUD.tg;
  el.innerHTML = `<h3 style="margin-top:0">Telegram 盘中提醒</h3>
    <div class="small" style="line-height:1.9">美股交易日每小时(美西 7:30–12:30),把你的自选股和持仓变化发到你的 Telegram。只含信息,不是买卖建议。</div>
    <ol class="small" style="line-height:1.9;margin:8px 0 10px;padding-left:20px;font-family:inherit">
      <li>没有 Telegram 的话,先在手机应用商店搜索“Telegram”,下载并用手机号注册。</li>
      <li>打开我们的机器人:<a href="https://t.me/LeoStockMonitor_bot" target="_blank" rel="noopener"><b>t.me/LeoStockMonitor_bot</b></a>(也可以在 Telegram 里搜索 <b>@LeoStockMonitor_bot</b>)。点下面的 <b>Start</b>(开始),再随便发一句话。</li>
      <li>在 Telegram 里搜索 <b>@userinfobot</b>,点进去,点 <b>Start</b>,它会回复一串数字(Id),长按复制这串数字。</li>
      <li>回到这里,把数字粘贴到下面的框里,点 <b>保存</b>,看到“已保存”就完成。</li>
    </ol>
    <form id="tgForm" class="holdform"><input id="tgId" placeholder="你的 Telegram Id(数字)" inputmode="numeric" autocomplete="off" value="${esc(t.id)}"><label class="small" style="display:flex;align-items:center;gap:6px"><input type="checkbox" id="tgOn" ${t.on ? 'checked' : ''}>开启每小时摘要</label><button type="submit">保存</button></form>
    <div id="tgMsg" class="muted small">${t.ready ? '' : '读取中…'}</div>`;
}

async function loadTg() {                          // 单独读取:数据库还没加这两列时,不影响自选股和持仓同步
  const { data, error } = await CLOUD.sb.from('user_data').select('tg_chat_id,tg_hourly').eq('user_id', CLOUD.user.id).maybeSingle();
  if (error) { CLOUD.tg = { id: '', on: true, ready: true }; paintTg(); const m = document.getElementById('tgMsg'); if (m) m.textContent = '这项功能还没开通(管理员需要先在数据库里加两列)。'; return; }
  CLOUD.tg = { id: (data && data.tg_chat_id) || '', on: !data || data.tg_hourly !== false, ready: true }; paintTg();
}

document.addEventListener('submit', async e => {
  if (e.target.id !== 'tgForm' || !CLOUD.sb || !CLOUD.user) return;
  e.preventDefault();
  const id = document.getElementById('tgId').value.trim(), on = document.getElementById('tgOn').checked, msg = document.getElementById('tgMsg');
  if (id && !/^-?\d{5,15}$/.test(id)) { msg.textContent = 'Id 是一串数字,请从 @userinfobot 复制'; return; }
  msg.textContent = '保存中…';
  const { error } = await CLOUD.sb.from('user_data').upsert({ user_id: CLOUD.user.id, tg_chat_id: id || null, tg_hourly: on, updated_at: new Date().toISOString() });
  if (error) { msg.textContent = '保存失败:' + error.message; return; }
  CLOUD.tg = { id, on, ready: true }; msg.textContent = id ? '已保存。下一个交易时段整点前后,你会在 Telegram 收到摘要。' : '已清除,不再发送。';
});

async function cloudLoad() {                       // 登录后:云端有数据就用云端;云端没有的部分,把本机的传上去
  const { data, error } = await CLOUD.sb.from('user_data').select('watch,holdings').eq('user_id', CLOUD.user.id).maybeSingle();
  if (error) { console.warn('cloud load', error.message); return; }
  let upload = !data;
  if (data && Array.isArray(data.watch) && data.watch.length) {
    state.watch = data.watch.filter(s => typeof s === 'string').slice(0, 100); store.set('watch', state.watch, true);
    if (!state.watch.includes(state.sel)) state.sel = state.watch[0];
  } else upload = true;
  if (data && Array.isArray(data.holdings) && data.holdings.length) {
    state.holdings = data.holdings.filter(h => h && typeof h.sym === 'string' && h.qty > 0 && h.cost > 0).slice(0, 200); store.set('holdings', state.holdings, true);
  } else if (state.holdings.length) upload = true;
  loadTg();
  renderWatch(); renderDetail(); Data.refreshQuotes(coreSymbols()).then(() => renderWatch()).catch(() => { });
  if (upload) cloudSave();
}

function cloudSave() {                             // 自选股或持仓变化后 1 秒内同步到云端
  if (!CLOUD.sb || !CLOUD.user) return;
  clearTimeout(CLOUD.saving);
  CLOUD.saving = setTimeout(async () => {
    const { error } = await CLOUD.sb.from('user_data').upsert({ user_id: CLOUD.user.id, watch: state.watch, holdings: state.holdings, updated_at: new Date().toISOString() });
    if (error) console.warn('cloud save', error.message);
  }, 1000);
}

async function initAuth(cfg) {
  if (!cfg || !cfg.url || !cfg.key || !window.supabase) return;
  CLOUD.sb = window.supabase.createClient(cfg.url, cfg.key, { auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true } });
  const { data } = await CLOUD.sb.auth.getSession();
  CLOUD.user = data.session ? data.session.user : null; paintAuth(); if (typeof renderHold === 'function') renderHold();
  if (CLOUD.user) cloudLoad();
  CLOUD.sb.auth.onAuthStateChange((ev, session) => {
    const was = CLOUD.user && CLOUD.user.id; CLOUD.user = session ? session.user : null; paintAuth(); if (typeof renderHold === 'function') renderHold();
    if (CLOUD.user && CLOUD.user.id !== was) setTimeout(cloudLoad, 0);
  });
}

document.addEventListener('click', async e => {
  if (!CLOUD.sb) return;
  if (e.target.id === 'authIn') await CLOUD.sb.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: location.origin + location.pathname } });
  if (e.target.id === 'authOut') { await CLOUD.sb.auth.signOut(); CLOUD.user = null; paintAuth(); }
});
