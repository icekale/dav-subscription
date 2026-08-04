const $ = (sel) => document.querySelector(sel);

const PLATFORM_LABELS = { xueqiu: "雪球", weibo: "微博", twitter: "X" };
const APP_VERSION = "v1.3 · 后台风格";
const state = {
  token: localStorage.getItem("dav_token") || "",
  user: null,
  catalog: [],
  platform: "",
};

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const resp = await fetch(path, { ...options, headers });
  if (resp.status === 401) {
    logout();
    throw new Error("登录已过期，请重新登录");
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.detail || resp.statusText);
  return data;
}

function logout() {
  state.token = "";
  state.user = null;
  localStorage.removeItem("dav_token");
  location.hash = "#/home";
  $("#app-view").classList.add("hidden");
  $("#auth-view").classList.remove("hidden");
}

function avatarText(name) {
  return (name || "?").trim().slice(0, 1).toUpperCase();
}

// ---------- 壳 ----------
const NAV = [
  { group: "订阅", items: [
    { route: "home", icon: "◎", label: "订阅广场" },
    { route: "mysubs", icon: "▤", label: "我的订阅" },
    { route: "timeline", icon: "☰", label: "动态" },
    { route: "settings", icon: "⚙", label: "推送设置" },
  ]},
  { group: "管理", admin: true, items: [
    { route: "admin/kols", icon: "◇", label: "大V管理" },
    { route: "admin/requests", icon: "✚", label: "求添加" },
    { route: "admin/categories", icon: "▣", label: "分类管理" },
    { route: "admin/posts", icon: "▤", label: "帖子" },
    { route: "admin/logs", icon: "☰", label: "推送记录" },
    { route: "admin/users", icon: "◉", label: "用户" },
  ]},
];

function renderSidebar(user) {
  const html = NAV.filter((g) => !g.admin || user.is_admin)
    .map((group) => `
      <div class="nav-group-label">${group.group}</div>
      ${group.items.map((item) => `
        <button class="nav-item" data-route="${item.route}" onclick="location.hash='#/${item.route}'">
          <span class="nav-icon">${item.icon}</span>
          <span class="nav-label">${item.label}</span>
        </button>`).join("")}
    `).join("");
  $("#sidebar-nav").innerHTML = html;
  $("#sidebar-user").textContent = `${user.username}${user.is_admin ? " · 管理员" : ""} · ${APP_VERSION}`;
}

function renderTopbar(user) {
  $("#topbar-user").innerHTML = `
    <div class="user-chip">
      <div class="user-avatar">${escapeHtml(avatarText(user.username))}</div>
      <div class="user-meta">
        <span class="user-name">${escapeHtml(user.username)}</span>
        <span class="user-role">${user.is_admin ? "管理员" : "订阅用户"}</span>
      </div>
    </div>
    <button class="topbar-logout" onclick="logout()">退出</button>`;
}

function setPageTitle(title, back = false) {
  $("#page-title").textContent = title;
  $("#btn-back").classList.toggle("hidden", !back);
}

function heroPanel(eyebrow, title, subtitle = "", pills = []) {
  return `
    <section class="hero-panel">
      <div>
        <p class="hero-eyebrow">${escapeHtml(eyebrow)}</p>
        <h2 class="hero-title">${escapeHtml(title)}</h2>
        ${subtitle ? `<p class="hero-subtitle">${escapeHtml(subtitle)}</p>` : ""}
      </div>
      ${pills.length ? `<div class="hero-pills">${pills.map((p) => `<span class="hero-pill">${escapeHtml(p)}</span>`).join("")}</div>` : ""}
    </section>`;
}

function emptyState(text, actionHtml = "") {
  return `<div class="empty">${escapeHtml(text)}${actionHtml}</div>`;
}

// ---------- 订阅广场 ----------
async function renderHome() {
  setPageTitle("订阅广场");
  $("#main").innerHTML = `
    ${heroPanel("DaV Catalog", "订阅广场", "浏览大V目录，点击卡片查看动态，一键订阅你关注的人。",
      ["雪球", "微博", "X / RSS"])}
    <section class="section-panel">
      <header class="section-head">
        <div>
          <p class="section-eyebrow">Catalog</p>
          <h3 class="section-title">全部大V</h3>
          <p class="section-meta" id="catalog-meta">加载中…</p>
        </div>
        <div class="toolbar" style="margin-top:12px">
          <div class="search-bar" style="flex:1;min-width:220px">
            <span>🔍</span>
            <input id="home-search" placeholder="搜索昵称或 ID，回车确认" onkeydown="if(event.key==='Enter')location.hash='#/search?q='+encodeURIComponent(this.value)">
          </div>
          <div class="platform-tabs" id="platform-tabs"></div>
        </div>
      </header>
      <div id="kol-list"></div>
    </section>`;
  state.platform = "";
  renderPlatformTabs();
  await loadHomeKols();
}

function renderPlatformTabs() {
  $("#platform-tabs").innerHTML = ["", "xueqiu", "weibo", "twitter"].map((p) => `
    <button class="platform-tab ${p === state.platform ? "selected" : ""}"
      onclick="switchPlatform('${p}')">${p ? PLATFORM_LABELS[p] : "全部"}</button>`).join("");
}

async function loadHomeKols() {
  try {
    const params = state.platform ? `?platform=${state.platform}` : "";
    state.catalog = await api(`/api/catalog${params}`);
    $("#catalog-meta").textContent = `共 ${state.catalog.length} 个大V`;
    $("#kol-list").innerHTML = state.catalog.length
      ? state.catalog.map(kolCard).join("")
      : emptyState("暂无大V，管理员可在管理后台添加");
  } catch (err) {
    $("#kol-list").innerHTML = emptyState("加载失败: " + err.message);
  }
}

async function switchPlatform(platform) {
  state.platform = platform;
  renderPlatformTabs();
  await loadHomeKols();
}

function kolCard(kol) {
  return `
    <div class="kol-item">
      <div class="kol-avatar">${escapeHtml(avatarText(kol.name))}</div>
      <div class="kol-info" onclick="location.hash='#/kol/${kol.id}'">
        <div class="base">
          <span class="name">${escapeHtml(kol.name)}</span>
          <span class="tag">${PLATFORM_LABELS[kol.platform] || kol.platform}</span>
          ${kol.category_name ? `<span class="tag">${escapeHtml(kol.category_name)}</span>` : ""}
        </div>
        <div class="desc">外部 ID：${escapeHtml(kol.external_id)}${kol.enabled ? "" : " · 已停用"}</div>
      </div>
      <button class="btn-sub ${kol.subscribed ? "subscribed" : ""}" onclick="toggleSubscribe(${kol.id}, this)">
        ${kol.subscribed ? "已订阅" : "订阅"}
      </button>
      ${state.user?.is_admin ? `<button class="btn-sm danger" onclick="adminDeleteKolFromHome(${kol.id})" title="删除该大V">删除</button>` : ""}
    </div>`;
}

async function adminDeleteKolFromHome(kolId) {
  if (!confirm("确认删除该大V？其订阅关系会一并移除。")) return;
  try {
    await api(`/api/kols/${kolId}`, { method: "DELETE" });
    await loadHomeKols();
  } catch (err) {
    alert("删除失败: " + err.message);
  }
}

async function toggleSubscribe(kolId, btn) {
  try {
    const kol = state.catalog.find((k) => k.id === kolId);
    if (kol && kol.subscribed) {
      await api(`/api/subscriptions/${kolId}`, { method: "DELETE" });
    } else {
      await api("/api/subscriptions", { method: "POST", body: JSON.stringify({ kol_id: kolId }) });
    }
    if (kol) {
      kol.subscribed = !kol.subscribed;
      btn.textContent = kol.subscribed ? "已订阅" : "订阅";
      btn.classList.toggle("subscribed", kol.subscribed);
    }
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

// ---------- 我的订阅 / 动态 ----------
async function renderMySubs() {
  setPageTitle("我的订阅");
  $("#main").innerHTML = `
    ${heroPanel("My Subscriptions", "我的订阅", "管理你关注的大V，随时取消订阅。", ["自助订阅", "分类管理"])}
    <section class="section-panel">
      <header class="section-head">
        <div>
          <p class="section-eyebrow">Subscriptions</p>
          <h3 class="section-title">已订阅大V</h3>
        </div>
      </header>
      <div id="mysubs-list"></div>
    </section>`;
  try {
    const subs = await api("/api/my/subscriptions");
    state.catalog = subs.map((k) => ({ ...k, subscribed: true }));
    $("#mysubs-list").innerHTML = subs.length
      ? subs.map(kolCard).join("")
      : emptyState("还没有订阅任何大V", `<div><button class="btn-normal btn-add" onclick="location.hash='#/home'">去发现大V</button></div>`);
  } catch (err) {
    $("#mysubs-list").innerHTML = emptyState(err.message);
  }
}

async function renderTimeline() {
  setPageTitle("动态");
  $("#main").innerHTML = `
    ${heroPanel("Timeline", "动态", "你订阅大V的最新动态，按时间倒序。", ["实时抓取", "去重推送"])}
    <section class="section-panel">
      <header class="section-head">
        <div>
          <p class="section-eyebrow">Feed</p>
          <h3 class="section-title">最新动态</h3>
        </div>
      </header>
      <div id="feed"></div>
    </section>`;
  try {
    const posts = await api("/api/my/feed?limit=100");
    $("#feed").innerHTML = posts.length
      ? posts.map(postCard).join("")
      : emptyState("还没有订阅任何大V", `<div><button class="btn-normal btn-add" onclick="location.hash='#/home'">去订阅</button></div>`);
  } catch (err) {
    $("#feed").innerHTML = emptyState(err.message);
  }
}

function postCard(post) {
  return `
    <div class="post-item">
      <div class="p-header">
        <div class="kol-avatar">${escapeHtml(avatarText(post.kol_name))}</div>
        <div>
          <div class="p-name">${escapeHtml(post.kol_name)}</div>
          <div class="p-time">${escapeHtml(post.published_at)}</div>
        </div>
      </div>
      ${post.title ? `<div class="p-title">${escapeHtml(post.title)}</div>` : ""}
      <div class="p-content">${escapeHtml(post.content || "（无正文）")}</div>
      <div class="p-meta">
        ${post.category_name ? `<span class="cat">${escapeHtml(post.category_name)}</span>` : ""}
        <span>${PLATFORM_LABELS[post.platform] || post.platform}</span>
        <a href="${escapeHtml(post.url)}" target="_blank" rel="noopener">查看原文 →</a>
      </div>
    </div>`;
}

// ---------- 搜索 ----------
async function renderSearch() {
  setPageTitle("搜索", true);
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const query = params.get("q") || "";
  $("#main").innerHTML = `
    ${heroPanel("Search", "搜索大V", "按昵称或外部 ID（雪球 UID / 微博 UID / RSS 地址）查找。")}
    <section class="section-panel">
      <div class="search-bar" style="margin-bottom:16px">
        <span>🔍</span>
        <input id="search-input" placeholder="输入昵称或 ID，回车搜索" value="${escapeHtml(query)}" onkeydown="if(event.key==='Enter')doSearch()">
        <button class="btn-ghost" onclick="doSearch()">搜索</button>
      </div>
      <div id="search-result"></div>
    </section>`;
  if (query) doSearch();
  else $("#search-input").focus();
}

async function doSearch() {
  const keyword = $("#search-input").value.trim().toLowerCase();
  if (!keyword) return;
  try {
    const kols = await api("/api/catalog");
    const hits = kols.filter(
      (k) => k.name.toLowerCase().includes(keyword) || k.external_id.toLowerCase().includes(keyword)
    );
    $("#search-result").innerHTML = hits.length
      ? hits.map(kolCard).join("")
      : emptyState("没有找到匹配的大V，可联系管理员添加");
  } catch (err) {
    $("#search-result").innerHTML = emptyState("搜索失败: " + err.message);
  }
}

// ---------- 大V动态页 ----------
async function renderKolPage(kolId) {
  setPageTitle("大V动态", true);
  $("#main").innerHTML = `<div class="empty">加载中…</div>`;
  try {
    const kol = await api(`/api/kols/${kolId}`);
    const posts = await api(`/api/kols/${kolId}/posts?limit=50`);
    $("#main").innerHTML = `
      ${heroPanel("Kol Profile", kol.name, `外部 ID：${kol.external_id} · ${PLATFORM_LABELS[kol.platform] || kol.platform}${kol.category_name ? " · " + kol.category_name : ""}`, ["查看动态"])}
      <section class="section-panel">
        <header class="section-head">
          <div>
            <p class="section-eyebrow">Posts</p>
            <h3 class="section-title">最近动态</h3>
          </div>
          <div class="toolbar" style="margin-top:12px">
            <button class="btn-sub ${kol.subscribed ? "subscribed" : ""}" id="kol-sub-btn" onclick="toggleKolPageSubscribe(${kol.id})">
              ${kol.subscribed ? "已订阅" : "订阅"}
            </button>
          </div>
        </header>
        <div id="kol-posts">${posts.length ? posts.map(postCard).join("") : emptyState("暂无动态")}</div>
      </section>`;
  } catch (err) {
    $("#main").innerHTML = emptyState("加载失败: " + err.message);
  }
}

async function toggleKolPageSubscribe(kolId) {
  const btn = $("#kol-sub-btn");
  await toggleSubscribe(kolId, btn);
}

// ---------- 推送设置 ----------
async function renderSettings() {
  setPageTitle("推送设置");
  try {
    state.user = await api("/api/me");
    const tg = state.user.telegram_chat_id;
    const fsOpen = state.user.feishu_open_id;
    const fsChat = state.user.feishu_chat_id;
    const fsOk = !!(fsOpen && fsChat);
    $("#main").innerHTML = `
      ${heroPanel("Push Settings", "推送设置", "新帖按订阅关系逐人推送：先与机器人建立会话，再用绑定码合并到当前账号。", ["Telegram", "飞书"])}
      <section class="section-panel">
        <header class="section-head">
          <div>
            <p class="section-eyebrow">Channels</p>
            <h3 class="section-title">推送渠道</h3>
            <p class="section-meta">当前账号绑定的接收渠道状态。</p>
          </div>
        </header>
        <div class="row" style="gap:16px;flex-wrap:wrap">
          <div class="channel-card">
            <div class="channel-head">
              <b>Telegram</b>
              <span class="${tg ? "status-ok" : "status-fail"}">${tg ? "已绑定" : "未绑定"}</span>
            </div>
            <p class="muted" style="margin:8px 0 12px">${tg ? "chat_id：" + escapeHtml(tg) : "给机器人发一条消息即可自动绑定"}</p>
            ${tg ? "<button class=\"btn-sm danger\" onclick=\"unbindChannel('telegram_chat_id')\">解绑</button>" : ""}
          </div>
          <div class="channel-card">
            <div class="channel-head">
              <b>飞书</b>
              <span class="${fsOk ? "status-ok" : (fsOpen ? "status-warn" : "status-fail")}">${fsOk ? "已绑定" : (fsOpen ? "未完成" : "未绑定")}</span>
            </div>
            <p class="muted" style="margin:8px 0 12px">
              ${fsOk ? "已建立单聊会话，推送正常"
                : (fsOpen ? "已填 open_id 但未与机器人建立单聊，推送会失败，请先给机器人发消息"
                : "给机器人发一条消息即可自动绑定")}
            </p>
            ${fsOpen ? "<button class=\"btn-sm danger\" onclick=\"unbindChannel('feishu')\">解绑</button>" : ""}
          </div>
        </div>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <p class="section-eyebrow">Bind</p>
            <h3 class="section-title">绑定方法</h3>
            <p class="section-meta">机器人账号与网页账号合并后，新帖才会推送到你的渠道。</p>
          </div>
        </header>
        <ol style="padding-left:20px;line-height:2">
          <li>在 Telegram / 飞书里搜索并打开机器人，发送任意一条消息（如 <code>/start</code>），系统自动记录你的会话。</li>
          <li>回到本页点「生成绑定码」，把 <code>/bind 6位码</code> 发给机器人。</li>
          <li>绑定完成后，机器人账号会合并到当前网页账号，订阅与推送同步。</li>
        </ol>
        <div class="row">
          <button class="btn-ghost" onclick="genBindCode()">生成绑定码</button>
        </div>
        <div id="bind-result" class="muted" style="margin-top:14px"></div>
      </section>
      <section class="section-panel">
        <div class="form-row">
          <label for="set-notify">新帖推送开关</label>
          <select id="set-notify" class="form-control" onchange="saveNotify()">
            <option value="1" ${state.user.notify_enabled ? "selected" : ""}>开启</option>
            <option value="0" ${!state.user.notify_enabled ? "selected" : ""}>关闭</option>
          </select>
        </div>
        <p class="muted">关闭后不会向任何渠道推送新帖，订阅关系保留。</p>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <p class="section-eyebrow">Security</p>
            <h3 class="section-title">修改密码</h3>
            <p class="section-meta">定期更换密码，保护你的账号安全。</p>
          </div>
        </header>
        <div class="form-row">
          <label for="pw-old">原密码</label>
          <input id="pw-old" class="form-control" type="password" placeholder="输入当前密码" autocomplete="current-password">
        </div>
        <div class="form-row">
          <label for="pw-new">新密码</label>
          <input id="pw-new" class="form-control" type="password" placeholder="至少 6 位" autocomplete="new-password">
        </div>
        <div class="form-row">
          <label for="pw-confirm">确认新密码</label>
          <input id="pw-confirm" class="form-control" type="password" placeholder="再次输入新密码" autocomplete="new-password">
        </div>
        <button class="btn-normal" onclick="savePassword()">修改密码</button>
      </section>`;
  } catch (err) {
    $("#main").innerHTML = emptyState(err.message);
  }
}

async function saveNotify() {
  try {
    await api("/api/me", {
      method: "PUT",
      body: JSON.stringify({ notify_enabled: $("#set-notify").value === "1" }),
    });
  } catch (err) {
    alert("保存失败: " + err.message);
  }
}

async function unbindChannel(channel) {
  const label = channel === "telegram_chat_id" ? "Telegram" : "飞书";
  if (!confirm(`确认解绑 ${label}？解绑后将不再往该渠道推送。`)) return;
  try {
    const body = channel === "feishu"
      ? { feishu_open_id: "", feishu_chat_id: "" }
      : { telegram_chat_id: "" };
    await api("/api/me", { method: "PUT", body: JSON.stringify(body) });
    renderSettings();
  } catch (err) {
    alert("解绑失败: " + err.message);
  }
}

async function savePassword() {
  const oldPw = $("#pw-old").value;
  const newPw = $("#pw-new").value;
  const confirmPw = $("#pw-confirm").value;
  if (!oldPw || newPw.length < 6) {
    alert("请填写原密码，新密码至少 6 位");
    return;
  }
  if (newPw !== confirmPw) {
    alert("两次输入的新密码不一致");
    return;
  }
  try {
    await api("/api/me/password", {
      method: "POST",
      body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
    });
    $("#pw-old").value = $("#pw-new").value = $("#pw-confirm").value = "";
    alert("密码已修改");
  } catch (err) {
    alert("修改失败: " + err.message);
  }
}

async function genBindCode() {
  try {
    const data = await api("/api/me/bind-code", { method: "POST" });
    $("#bind-result").innerHTML =
      `绑定码：<b style="font-size:20px;letter-spacing:3px">${escapeHtml(data.code)}</b>` +
      `（${Math.floor(data.expires_in_seconds / 60)} 分钟内有效）<br>` +
      `发给机器人：<code>/bind ${escapeHtml(data.code)}</code>`;
  } catch (err) {
    alert("生成失败: " + err.message);
  }
}

// ---------- 管理后台 ----------
const ADMIN_TABS = [
  ["stats", "状态"],
  ["kols", "大V管理"],
  ["requests", "求添加"],
  ["categories", "分类管理"],
  ["posts", "帖子"],
  ["logs", "推送记录"],
  ["users", "用户"],
];

async function renderAdmin(tab) {
  setPageTitle("管理后台");
  $("#main").innerHTML = `
    ${heroPanel("Admin Console", "管理后台", "维护大V目录、分类与推送记录，查看注册用户。", ["大V", "分类", "推送"])}
    <div class="module-nav">
      ${ADMIN_TABS.map(([key, label]) => `
        <button class="module-tab ${key === tab ? "active" : ""}" onclick="location.hash='#/admin/${key}'">${label}</button>`).join("")}
    </div>
    <div id="admin-body"></div>`;
  const loaders = { stats: loadAdminStats, kols: loadAdminKols, requests: loadAdminRequests, categories: loadAdminCategories, posts: loadAdminPosts, logs: loadAdminLogs, users: loadAdminUsers };
  await loaders[tab]();
}

async function loadAdminStats() {
  const s = await api("/api/stats");
  const fmtTime = (ts) => (ts ? new Date(Number(ts) * 1000).toLocaleString() : "尚未抓取");
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">Runtime</p><h3 class="section-title">运行状态</h3>
      <p class="section-meta">抓取频率与时效性一览</p></div></header>
      <div class="row" style="gap:16px;flex-wrap:wrap">
        ${statCard("轮询间隔", `${s.polling_interval_seconds} 秒`)}
        ${statCard("最近抓取", fmtTime(s.last_poll_at))}
        ${statCard("抓取耗时", s.last_poll_duration_ms ? `${(Number(s.last_poll_duration_ms) / 1000).toFixed(1)} 秒` : "-")}
        ${statCard("大V / 启用", `${s.kols} / ${s.enabled_kols}`)}
        ${statCard("优先大V", s.priority_kols)}
        ${statCard("用户", s.users)}
        ${statCard("帖子", s.posts)}
      </div>
      ${s.last_poll_error ? `<div class="notice" style="margin-top:16px">最近轮询异常：${escapeHtml(s.last_poll_error)}</div>` : ""}
      <div style="margin-top:16px">
        <button class="btn-normal" onclick="startWeiboQr()">微博扫码登录</button>
        <span class="muted" style="margin-left:10px">用微博 App 扫码后自动保存 Cookie，无需手动复制</span>
      </div>
      <div id="wb-qr-box" style="margin-top:16px"></div>
    </section>`;
}

let wbQrTimer = null;

async function startWeiboQr() {
  try {
    const data = await api("/api/admin/weibo-qr/start", { method: "POST" });
    $("#wb-qr-box").innerHTML = `
      <div style="display:inline-block;padding:16px;background:#fff;border-radius:var(--radius-control)">
        <img src="${escapeHtml(data.qrurl)}" alt="微博登录二维码" style="width:220px;height:220px">
      </div>
      <p class="muted" id="wb-qr-status" style="margin-top:10px">等待扫码…</p>`;
    if (wbQrTimer) clearInterval(wbQrTimer);
    wbQrTimer = setInterval(() => pollWeiboQr(data.qrid), 2000);
  } catch (err) {
    alert("获取二维码失败: " + err.message);
  }
}

async function pollWeiboQr(qrid) {
  try {
    const data = await api(`/api/admin/weibo-qr/status?qrid=${encodeURIComponent(qrid)}`);
    const statusEl = $("#wb-qr-status");
    if (!statusEl) {
      if (wbQrTimer) clearInterval(wbQrTimer);
      return;
    }
    if (data.status === "pending") {
      statusEl.textContent = "等待扫码…";
    } else if (data.status === "scanned") {
      statusEl.textContent = "已扫描，请在手机上确认登录";
    } else if (data.status === "ok") {
      if (wbQrTimer) clearInterval(wbQrTimer);
      statusEl.textContent = "✅ 登录成功，微博 Cookie 已自动保存";
      alert("微博登录成功，Cookie 已保存，可直接添加微博大V了");
    }
  } catch (err) {
    if (wbQrTimer) clearInterval(wbQrTimer);
    const statusEl = $("#wb-qr-status");
    if (statusEl) statusEl.textContent = "登录失败：" + err.message;
  }
}

function statCard(label, value) {
  return `
    <div style="flex:1;min-width:150px;background:var(--color-bg-muted);border-radius:var(--radius-control);padding:16px 18px">
      <div style="font-size:12px;color:var(--color-text-muted)">${escapeHtml(label)}</div>
      <div style="font-size:20px;font-weight:700;color:var(--color-text-strong);margin-top:6px">${escapeHtml(String(value))}</div>
    </div>`;
}

async function loadAdminKols() {
  const [kols, categories] = await Promise.all([api("/api/kols"), api("/api/categories")]);
  const catOptions = categories.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><p class="section-eyebrow">Create</p><h3 class="section-title">添加大V</h3></div>
        <div class="toolbar" style="margin-top:12px">
          <select id="ad-platform" class="form-control" style="margin:0;width:auto">
            <option value="xueqiu">雪球</option>
            <option value="weibo">微博</option>
            <option value="twitter">X (RSS)</option>
          </select>
          <select id="ad-category" class="form-control" style="margin:0;width:auto"><option value="">未分类</option>${catOptions}</select>
          <input id="ad-name" class="form-control" style="margin:0;width:200px" placeholder="昵称">
          <input id="ad-external" class="form-control" style="margin:0;width:300px" placeholder="user_id / uid / RSS链接 / 雪球主页链接">
          <button class="btn-normal" onclick="adminAddKol()">添加</button>
        </div>
      </header>
    </section>
    <section class="section-panel">
      <header class="section-head">
        <div><p class="section-eyebrow">Batch</p><h3 class="section-title">批量导入大V</h3>
        <p class="section-meta">每行一个：昵称 + 雪球主页链接/UID（昵称可省略），如：<code>段永平 https://xueqiu.com/u/12345</code></p></div>
      </header>
      <textarea id="ad-batch-lines" class="form-control" rows="6" style="font-family:monospace" placeholder="https://xueqiu.com/u/12345&#10;段永平 12345&#10;https://xueqiu.com/67890"></textarea>
      <div class="toolbar" style="margin-top:12px">
        <select id="ad-batch-platform" class="form-control" style="margin:0;width:auto">
          <option value="xueqiu">雪球</option>
          <option value="weibo">微博</option>
          <option value="twitter">X (RSS)</option>
        </select>
        <select id="ad-batch-category" class="form-control" style="margin:0;width:auto"><option value="">未分类</option>${catOptions}</select>
        <button class="btn-normal" onclick="adminBatchAddKols()">批量导入</button>
        <span id="ad-batch-result" class="muted"></span>
      </div>
    </section>
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">List</p><h3 class="section-title">大V列表</h3></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>平台</th><th>昵称</th><th>分类</th><th>外部ID</th><th>优先</th><th>可见性</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>${kols.map((k) => `
            <tr>
              <td>${k.id}</td><td>${PLATFORM_LABELS[k.platform] || k.platform}</td>
              <td>${escapeHtml(k.name)}</td><td>${escapeHtml(k.category_name || "")}</td>
              <td>${escapeHtml(k.external_id)}</td>
              <td>${k.priority ? '<span class="status-ok">是</span>' : "否"}</td>
              <td>${k.is_private ? '<span class="status-ok">私有</span>' : "公开"}</td>
              <td class="${k.enabled ? "status-ok" : "status-fail"}">${k.enabled ? "启用" : "停用"}</td>
              <td>
                <button class="btn-sm" onclick="adminTogglePriority(${k.id}, ${!k.priority})">${k.priority ? "取消优先" : "设为优先"}</button>
                <button class="btn-sm" onclick="adminToggleKol(${k.id}, ${k.enabled ? 0 : 1})">${k.enabled ? "停用" : "启用"}</button>
                <button class="btn-sm" onclick="adminEditKol(${k.id})">编辑</button>
                <button class="btn-sm danger" onclick="adminDeleteKol(${k.id})">删除</button>
              </td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
}

async function adminBatchAddKols() {
  const lines = $("#ad-batch-lines").value;
  if (!lines.trim()) {
    alert("请先粘贴要导入的大V链接/ID");
    return;
  }
  try {
    const data = await api("/api/kols/batch", {
      method: "POST",
      body: JSON.stringify({
        platform: $("#ad-batch-platform").value,
        lines,
        category_id: $("#ad-batch-category").value ? Number($("#ad-batch-category").value) : null,
      }),
    });
    const failLines = data.failed.map((f) => `${f.line} — ${f.error}`).join("\n");
    $("#ad-batch-result").textContent = `成功 ${data.ok}/${data.total}`;
    if (failLines) alert(`导入完成：成功 ${data.ok}/${data.total}\n\n失败：\n${failLines}`);
    loadAdminKols();
  } catch (err) {
    alert("批量导入失败: " + err.message);
  }
}

async function adminAddKol() {
  try {
    await api("/api/kols", {
      method: "POST",
      body: JSON.stringify({
        platform: $("#ad-platform").value,
        name: $("#ad-name").value.trim(),
        external_id: $("#ad-external").value.trim(),
        category_id: $("#ad-category").value ? Number($("#ad-category").value) : null,
      }),
    });
    loadAdminKols();
  } catch (err) {
    alert("添加失败: " + err.message);
  }
}

async function adminToggleKol(id, enabled) {
  await api(`/api/kols/${id}`, { method: "PUT", body: JSON.stringify({ enabled: !!enabled }) });
  loadAdminKols();
}

async function adminTogglePriority(id, priority) {
  await api(`/api/kols/${id}`, { method: "PUT", body: JSON.stringify({ priority: !!priority }) });
  loadAdminKols();
}

async function adminDeleteKol(id) {
  if (!confirm("确认删除该大V？")) return;
  await api(`/api/kols/${id}`, { method: "DELETE" });
  loadAdminKols();
}

async function adminEditKol(id) {
  const kol = await api(`/api/kols/${id}`);
  const categories = await api("/api/categories");
  const catOptions = categories.map((c) => `<option value="${c.id}" ${kol.category_id === c.id ? "selected" : ""}>${escapeHtml(c.name)}</option>`).join("");
  const mask = document.createElement("div");
  mask.className = "modal-mask";
  mask.innerHTML = `
    <div class="modal-card">
      <h3 style="margin-bottom:12px">编辑大V：${escapeHtml(kol.name)}</h3>
      <label class="form-label">昵称
        <input id="ek-name" class="form-control" value="${escapeHtml(kol.name)}">
      </label>
      <label class="form-label">分类
        <select id="ek-category" class="form-control"><option value="">未分类</option>${catOptions}</select>
      </label>
      <label class="form-label" style="display:flex;align-items:center;gap:8px">
        <input id="ek-private" type="checkbox" ${kol.is_private ? "checked" : ""}> 私有大V（仅白名单用户可见/可订阅）
      </label>
      <label class="form-label">白名单用户（逗号分隔用户名，仅对私有大V生效）
        <input id="ek-users" class="form-control" value="${escapeHtml((kol.visible_users || []).join(", "))}" placeholder="user1, user2">
      </label>
      <div class="toolbar" style="margin-top:16px">
        <button class="btn-normal" onclick="saveKolEdit(${kol.id})">保存</button>
        <button class="btn-sm" onclick="this.closest('.modal-mask').remove()">取消</button>
      </div>
    </div>`;
  mask.addEventListener("click", (e) => {
    if (e.target === mask) mask.remove();
  });
  document.body.appendChild(mask);
}

async function saveKolEdit(id) {
  const mask = document.querySelector(".modal-mask");
  try {
    await api(`/api/kols/${id}`, {
      method: "PUT",
      body: JSON.stringify({
        name: $("#ek-name").value.trim(),
        category_id: $("#ek-category").value ? Number($("#ek-category").value) : null,
        is_private: $("#ek-private").checked,
        visible_users: $("#ek-users").value.split(",").map((s) => s.trim()).filter(Boolean),
      }),
    });
    if (mask) mask.remove();
    loadAdminKols();
  } catch (err) {
    alert("保存失败: " + err.message);
  }
}

async function loadAdminRequests() {
  const [requests, all] = await Promise.all([
    api("/api/admin/kol-requests?status=pending"),
    api("/api/admin/kol-requests"),
  ]);
  const done = all.filter((r) => r.status !== "pending");
  const pendingRows = requests.length === 0
    ? `<tr><td colspan="7" class="muted">暂无待审批申请</td></tr>`
    : requests.map((r) => `
        <tr>
          <td>${r.id}</td><td>${PLATFORM_LABELS[r.platform] || r.platform}</td>
          <td>${escapeHtml(r.name || "（未填）")}</td><td>${escapeHtml(r.external_id)}</td>
          <td>${escapeHtml(r.requester || r.user_id)}</td><td>${escapeHtml(r.created_at)}</td>
          <td>
            <button class="btn-sm" onclick="adminApproveRequest(${r.id})">通过</button>
            <button class="btn-sm danger" onclick="adminRejectRequest(${r.id})">拒绝</button>
          </td>
        </tr>`).join("");
  const historyRows = done.length === 0
    ? `<tr><td colspan="7" class="muted">暂无处理记录</td></tr>`
    : done.map((r) => `
        <tr>
          <td>${r.id}</td><td>${PLATFORM_LABELS[r.platform] || r.platform}</td>
          <td>${escapeHtml(r.name || "（未填）")}</td><td>${escapeHtml(r.external_id)}</td>
          <td>${escapeHtml(r.requester || r.user_id)}</td>
          <td class="${r.status === "approved" ? "status-ok" : "status-fail"}">${r.status === "approved" ? "已通过" : "已拒绝"}</td>
          <td>${escapeHtml(r.handled_at || "")}</td>
        </tr>`).join("");
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">Requests</p><h3 class="section-title">用户求添加</h3>
      <p class="section-meta">用户申请添加的大V，审批通过后进入订阅广场。</p></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>平台</th><th>昵称</th><th>外部ID</th><th>申请人</th><th>申请时间</th><th>操作</th></tr></thead>
          <tbody>${pendingRows}</tbody>
        </table>
      </div>
    </section>
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">History</p><h3 class="section-title">处理记录</h3></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>平台</th><th>昵称</th><th>外部ID</th><th>申请人</th><th>状态</th><th>处理时间</th></tr></thead>
          <tbody>${historyRows}</tbody>
        </table>
      </div>
    </section>`;
}

async function adminApproveRequest(id) {
  await api(`/api/admin/kol-requests/${id}/approve`, { method: "POST" });
  loadAdminRequests();
}

async function adminRejectRequest(id) {
  if (!confirm("确认拒绝该申请？")) return;
  await api(`/api/admin/kol-requests/${id}/reject`, { method: "POST" });
  loadAdminRequests();
}

async function loadAdminCategories() {
  const categories = await api("/api/categories");
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><p class="section-eyebrow">Create</p><h3 class="section-title">添加分类</h3></div>
        <div class="toolbar" style="margin-top:12px">
          <input id="cat-name" class="form-control" style="margin:0;width:280px" placeholder="分类名，如：实盘、宏观、行业研究">
          <button class="btn-normal" onclick="adminAddCategory()">添加分类</button>
        </div>
      </header>
    </section>
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">List</p><h3 class="section-title">分类列表</h3></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>分类名</th><th>大V数</th><th>操作</th></tr></thead>
          <tbody>${categories.map((c) => `
            <tr>
              <td>${c.id}</td><td>${escapeHtml(c.name)}</td><td>${c.kol_count}</td>
              <td>
                <button class="btn-sm" onclick="adminRenameCategory(${c.id})">重命名</button>
                <button class="btn-sm danger" onclick="adminDeleteCategory(${c.id})">删除</button>
              </td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
}

async function adminAddCategory() {
  try {
    await api("/api/categories", { method: "POST", body: JSON.stringify({ name: $("#cat-name").value }) });
    loadAdminCategories();
  } catch (err) {
    alert("添加失败: " + err.message);
  }
}

async function adminRenameCategory(id) {
  const name = prompt("新的分类名：");
  if (name === null || !name.trim()) return;
  try {
    await api(`/api/categories/${id}`, { method: "PUT", body: JSON.stringify({ name: name.trim() }) });
    loadAdminCategories();
  } catch (err) {
    alert("重命名失败: " + err.message);
  }
}

async function adminDeleteCategory(id) {
  if (!confirm("确认删除该分类？其下大V将变为未分类")) return;
  await api(`/api/categories/${id}`, { method: "DELETE" });
  loadAdminCategories();
}

async function loadAdminPosts() {
  const posts = await api(`/api/posts?limit=100${state.adminPostsFilter || ""}`);
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><p class="section-eyebrow">Posts</p><h3 class="section-title">帖子列表</h3></div>
        <div class="toolbar" style="margin-top:12px">
          <input id="ad-posts-q" class="form-control" style="margin:0;width:260px" placeholder="搜索标题/内容关键词" value="${escapeHtml(state.adminPostsQ || "")}">
          <select id="ad-posts-platform" class="form-control" style="margin:0;width:auto">
            <option value="">全部平台</option>
            <option value="xueqiu" ${state.adminPostsPlatform === "xueqiu" ? "selected" : ""}>雪球</option>
            <option value="weibo" ${state.adminPostsPlatform === "weibo" ? "selected" : ""}>微博</option>
            <option value="twitter" ${state.adminPostsPlatform === "twitter" ? "selected" : ""}>X</option>
          </select>
          <button class="btn-normal" onclick="adminFilterPosts()">筛选</button>
        </div>
      </header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>大V</th><th>分类</th><th>内容</th><th>时间</th><th>链接</th></tr></thead>
          <tbody>${posts.map((p) => `
            <tr>
              <td>${p.id}</td><td>${escapeHtml(p.kol_name)}</td>
              <td>${escapeHtml(p.category_name || "")}</td>
              <td><pre class="content-cell">${escapeHtml((p.title ? p.title + "\n" : "") + (p.content || "").slice(0, 120))}</pre></td>
              <td>${escapeHtml(p.published_at)}</td>
              <td><a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">原文</a></td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
}

async function adminFilterPosts() {
  state.adminPostsQ = $("#ad-posts-q").value.trim();
  state.adminPostsPlatform = $("#ad-posts-platform").value;
  const params = new URLSearchParams({ limit: "100" });
  if (state.adminPostsQ) params.set("q", state.adminPostsQ);
  if (state.adminPostsPlatform) params.set("platform", state.adminPostsPlatform);
  state.adminPostsFilter = `&${params.toString()}`;
  loadAdminPosts();
}

async function loadAdminLogs() {
  const users = await api("/api/users");
  const logs = await api(`/api/push-logs?limit=100${state.adminLogsFilter || ""}`);
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><p class="section-eyebrow">Push Logs</p><h3 class="section-title">推送记录</h3></div>
        <div class="toolbar" style="margin-top:12px">
          <select id="ad-logs-user" class="form-control" style="margin:0;width:auto">
            <option value="">全部用户</option>
            ${users.map((u) => `<option value="${u.id}" ${state.adminLogsUserId == u.id ? "selected" : ""}>${escapeHtml(u.username)}</option>`).join("")}
          </select>
          <select id="ad-logs-channel" class="form-control" style="margin:0;width:auto">
            <option value="">全部渠道</option>
            <option value="telegram" ${state.adminLogsChannel === "telegram" ? "selected" : ""}>Telegram</option>
            <option value="feishu" ${state.adminLogsChannel === "feishu" ? "selected" : ""}>飞书</option>
          </select>
          <select id="ad-logs-status" class="form-control" style="margin:0;width:auto">
            <option value="">全部状态</option>
            <option value="success" ${state.adminLogsStatus === "success" ? "selected" : ""}>成功</option>
            <option value="failed" ${state.adminLogsStatus === "failed" ? "selected" : ""}>失败</option>
          </select>
          <button class="btn-normal" onclick="adminFilterLogs()">筛选</button>
        </div>
      </header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>用户</th><th>大V</th><th>渠道</th><th>状态</th><th>错误</th></tr></thead>
          <tbody>${logs.map((l) => `
            <tr>
              <td>${escapeHtml(l.created_at)}</td>
              <td>${escapeHtml(l.user_name || "全局")}</td>
              <td>${escapeHtml(l.kol_name)}</td>
              <td>${l.channel}</td>
              <td class="${l.status === "success" ? "status-ok" : "status-fail"}">${l.status}</td>
              <td>${escapeHtml(l.error || "")}</td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
}

async function adminFilterLogs() {
  const params = new URLSearchParams({ limit: "100" });
  const userId = $("#ad-logs-user").value;
  const channel = $("#ad-logs-channel").value;
  const status = $("#ad-logs-status").value;
  if (userId) params.set("user_id", userId);
  if (channel) params.set("channel", channel);
  if (status) params.set("status", status);
  state.adminLogsFilter = `&${params.toString()}`;
  state.adminLogsUserId = userId;
  state.adminLogsChannel = channel;
  state.adminLogsStatus = status;
  loadAdminLogs();
}

async function loadAdminUsers() {
  const users = await api("/api/users");
  state.adminUsers = users;
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">Users</p><h3 class="section-title">注册用户</h3></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>Telegram</th><th>飞书</th><th>推送</th><th>注册时间</th><th>操作</th></tr></thead>
          <tbody>${users.map((u) => `
            <tr>
              <td>${u.id}</td><td>${escapeHtml(u.username)}</td>
              <td>${u.is_admin ? "管理员" : "用户"}</td>
              <td>${escapeHtml(u.telegram_chat_id || "-")}</td>
              <td>${escapeHtml(u.feishu_open_id || "-")}</td>
              <td>${u.notify_enabled ? "开启" : "关闭"}</td>
              <td>${escapeHtml(u.created_at)}</td>
              <td>
                ${u.id === state.user.id
                  ? `<span class="muted">本人</span>
                     <button class="btn-sm" onclick="adminTestPush(${u.id})">测试推送</button>`
                  : `<button class="btn-sm" onclick="adminRenameUser(${u.id})">改用户名</button>
                     <button class="btn-sm" onclick="adminToggleAdmin(${u.id}, ${!u.is_admin})">${u.is_admin ? "取消管理员" : "设为管理员"}</button>
                     <button class="btn-sm" onclick="adminResetPassword(${u.id})">重置密码</button>
                     <button class="btn-sm danger" onclick="adminDeleteUser(${u.id})">删除</button>
                     <button class="btn-sm" onclick="adminTestPush(${u.id})">测试推送</button>`}
              </td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
}

async function adminTestPush(userId) {
  const user = (state.adminUsers || []).find((u) => u.id === userId);
  const msg = prompt(
    `给「${user ? user.username : userId}」发一条测试推送：`,
    "这是一条测试推送 ✅"
  );
  if (msg === null) return;
  try {
    const data = await api("/api/admin/test-push", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, message: msg }),
    });
    const lines = data.results.map((r) => {
      const label = r.channel === "telegram" ? "Telegram" : "飞书";
      return `${label}：${r.ok ? "✅ 成功" : "❌ 失败：" + r.error}`;
    });
    alert(lines.join("\n"));
  } catch (err) {
    alert("测试失败: " + err.message);
  }
}

async function adminRenameUser(userId) {
  const user = (state.adminUsers || []).find((u) => u.id === userId);
  const name = prompt(`把「${user ? user.username : userId}」改名为：`, user ? user.username : "");
  if (name === null) return;
  const trimmed = name.trim();
  if (trimmed.length < 2 || trimmed.length > 30) {
    alert("用户名需 2-30 位");
    return;
  }
  try {
    await api(`/api/users/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ username: trimmed }),
    });
    if (userId === state.user.id) {
      state.user.username = trimmed;
      renderSidebar(state.user);
      renderTopbar(state.user);
    }
    loadAdminUsers();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function adminResetPassword(userId) {
  const user = (state.adminUsers || []).find((u) => u.id === userId);
  const pw = prompt(`为「${user ? user.username : userId}」设置新密码（至少 6 位）：`);
  if (pw === null) return;
  if (pw.length < 6) {
    alert("密码至少 6 位");
    return;
  }
  try {
    await api(`/api/users/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ password: pw }),
    });
    alert("密码已重置");
    loadAdminUsers();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function adminDeleteUser(userId) {
  const user = (state.adminUsers || []).find((u) => u.id === userId);
  if (!confirm(`确认删除用户「${user ? user.username : userId}」？其订阅关系将一并删除，不可恢复。`)) return;
  try {
    await api(`/api/users/${userId}`, { method: "DELETE" });
    loadAdminUsers();
  } catch (err) {
    alert("删除失败: " + err.message);
  }
}

async function adminToggleAdmin(userId, makeAdmin) {
  try {
    await api(`/api/users/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ is_admin: makeAdmin }),
    });
    loadAdminUsers();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

// ---------- 路由 ----------
async function router() {
  const hash = location.hash.replace(/^#\/?/, "") || "home";
  const [page, param] = hash.split("/");
  if (!state.token) {
    $("#app-view").classList.add("hidden");
    $("#auth-view").classList.remove("hidden");
    return;
  }
  $("#auth-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  try {
    state.user = await api("/api/me");
  } catch {
    return;
  }
  renderSidebar(state.user);
  renderTopbar(state.user);
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.route === page || b.dataset.route === `${page}/${param}`)
  );
  try {
    if (page === "home") await renderHome();
    else if (page === "mysubs") await renderMySubs();
    else if (page === "timeline") await renderTimeline();
    else if (page === "settings") await renderSettings();
    else if (page === "search") await renderSearch();
    else if (page === "kol") await renderKolPage(Number(param));
    else if (page === "admin") {
      if (!state.user.is_admin) { location.hash = "#/home"; return; }
      await renderAdmin(param || "kols");
    }
    else { location.hash = "#/home"; await renderHome(); }
  } catch (err) {
    $("#main").innerHTML = emptyState(err.message);
  }
}

// ---------- 认证 ----------
async function doLogin(e) {
  e.preventDefault();
  $("#auth-error").textContent = "";
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: $("#login-username").value.trim(), password: $("#login-password").value }),
    });
    state.token = data.token;
    localStorage.setItem("dav_token", data.token);
    location.hash = "#/home";
    router();
  } catch (err) {
    $("#auth-error").textContent = err.message;
  }
}

async function doRegister(e) {
  e.preventDefault();
  $("#reg-error").textContent = "";
  try {
    const data = await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({ username: $("#reg-username").value.trim(), password: $("#reg-password").value }),
    });
    state.token = data.token;
    localStorage.setItem("dav_token", data.token);
    location.hash = "#/home";
    router();
  } catch (err) {
    $("#reg-error").textContent = err.message;
  }
}

function switchAuthMode(mode) {
  const isLogin = mode === "login";
  $("#login-form").classList.toggle("hidden", !isLogin);
  $("#register-form").classList.toggle("hidden", isLogin);
  $("#auth-error").textContent = "";
  $("#reg-error").textContent = "";
  document.querySelectorAll(".switch-btn").forEach((btn) =>
    btn.classList.toggle("active", btn.dataset.mode === mode)
  );
}

// ---------- 事件 ----------
$("#login-form").addEventListener("submit", doLogin);
$("#register-form").addEventListener("submit", doRegister);
document.querySelectorAll(".switch-btn").forEach((btn) =>
  btn.addEventListener("click", () => switchAuthMode(btn.dataset.mode))
);
$("#btn-back").addEventListener("click", () => history.back());
window.addEventListener("hashchange", router);

router();
