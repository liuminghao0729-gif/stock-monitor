// Google 登录 + 云端同步自选股(Supabase)。没配置或没登录时,网站照常用浏览器本地存储。
// 连接信息(项目地址、公开 key)由 /api/status 从部署平台的环境变量里下发,不写在代码里。
let CLOUD = { sb: null, user: null, saving: 0 };
const cloudBox = () => document.getElementById('authBox');

function paintAuth() {
  const b = cloudBox(); if (!b) return;
  if (!CLOUD.sb) { b.innerHTML = ''; return; }
  const u = CLOUD.user;
  b.innerHTML = u
    ? `<span class="authme" title="${esc(u.email || '')}">${u.user_metadata && u.user_metadata.avatar_url ? `<img src="${esc(u.user_metadata.avatar_url)}" alt="" referrerpolicy="no-referrer">` : ''}<span>${esc((u.user_metadata && u.user_metadata.name) || u.email || '已登录')}</span></span><button class="authbtn" id="authOut">退出</button>`
    : '<button class="authbtn" id="authIn">Google 登录</button>';
}

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
