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
    </div>`;
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
    $("#main").innerHTML = `
      ${heroPanel("Push Settings", "推送设置", "绑定你的 Telegram / 飞书账号，新帖按订阅关系逐人推送。", ["Telegram", "飞书"])}
      <section class="section-panel">
        <div class="notice">
          <b>怎么绑定？</b><br>
          · Telegram：给机器人发任意消息后，用 @userinfobot 查询自己的 chat_id（需在 config.yaml 配置 bot_token）。<br>
          · 飞书：需要飞书自建应用的 app_id / app_secret（未配置时飞书推送会跳过）。
        </div>
        <div class="form-row">
          <label for="set-tg">Telegram chat_id</label>
          <input id="set-tg" class="form-control" value="${escapeHtml(state.user.telegram_chat_id)}" placeholder="如 123456789">
        </div>
        <div class="form-row">
          <label for="set-fs">飞书 open_id</label>
          <input id="set-fs" class="form-control" value="${escapeHtml(state.user.feishu_open_id)}" placeholder="ou_xxxxxxxx">
        </div>
        <div class="form-row">
          <label for="set-notify">新帖推送开关</label>
          <select id="set-notify" class="form-control">
            <option value="1" ${state.user.notify_enabled ? "selected" : ""}>开启</option>
            <option value="0" ${!state.user.notify_enabled ? "selected" : ""}>关闭</option>
          </select>
        </div>
        <button class="btn-normal" onclick="saveSettings()">保存设置</button>
      </section>`;
  } catch (err) {
    $("#main").innerHTML = emptyState(err.message);
  }
}

async function saveSettings() {
  try {
    await api("/api/me", {
      method: "PUT",
      body: JSON.stringify({
        telegram_chat_id: $("#set-tg").value.trim(),
        feishu_open_id: $("#set-fs").value.trim(),
        notify_enabled: $("#set-notify").value === "1",
      }),
    });
    alert("已保存");
  } catch (err) {
    alert("保存失败: " + err.message);
  }
}

// ---------- 管理后台 ----------
const ADMIN_TABS = [
  ["stats", "状态"],
  ["kols", "大V管理"],
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
  const loaders = { stats: loadAdminStats, kols: loadAdminKols, categories: loadAdminCategories, posts: loadAdminPosts, logs: loadAdminLogs, users: loadAdminUsers };
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
    </section>`;
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
      <header class="section-head"><div><p class="section-eyebrow">List</p><h3 class="section-title">大V列表</h3></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>平台</th><th>昵称</th><th>分类</th><th>外部ID</th><th>优先</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>${kols.map((k) => `
            <tr>
              <td>${k.id}</td><td>${PLATFORM_LABELS[k.platform] || k.platform}</td>
              <td>${escapeHtml(k.name)}</td><td>${escapeHtml(k.category_name || "")}</td>
              <td>${escapeHtml(k.external_id)}</td>
              <td>${k.priority ? '<span class="status-ok">是</span>' : "否"}</td>
              <td class="${k.enabled ? "status-ok" : "status-fail"}">${k.enabled ? "启用" : "停用"}</td>
              <td>
                <button class="btn-sm" onclick="adminTogglePriority(${k.id}, ${!k.priority})">${k.priority ? "取消优先" : "设为优先"}</button>
                <button class="btn-sm" onclick="adminToggleKol(${k.id}, ${k.enabled ? 0 : 1})">${k.enabled ? "停用" : "启用"}</button>
                <button class="btn-sm danger" onclick="adminDeleteKol(${k.id})">删除</button>
              </td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
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
  const posts = await api("/api/posts?limit=100");
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">Posts</p><h3 class="section-title">帖子列表</h3></div></header>
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

async function loadAdminLogs() {
  const logs = await api("/api/push-logs?limit=100");
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">Push Logs</p><h3 class="section-title">推送记录</h3></div></header>
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

async function loadAdminUsers() {
  const users = await api("/api/users");
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
                  ? '<span class="muted">本人</span>'
                  : `<button class="btn-sm" onclick="adminToggleAdmin(${u.id}, ${!u.is_admin})">${u.is_admin ? "取消管理员" : "设为管理员"}</button>`}
              </td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
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
