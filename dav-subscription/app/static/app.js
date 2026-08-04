const $ = (sel) => document.querySelector(sel);

const PLATFORM_LABELS = { xueqiu: "雪球", weibo: "微博", twitter: "X" };
const TAB_ROUTES = new Set(["home", "timeline", "me"]);
const state = { token: localStorage.getItem("dav_token") || "", user: null };

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

function kolCard(kol) {
  const subscribed = kol.subscribed ? "subscribed" : "";
  const label = kol.subscribed ? "已订阅" : "订阅";
  return `
    <div class="kol-item">
      <div class="avatar">${escapeHtml(avatarText(kol.name))}</div>
      <div class="kol-info" onclick="location.hash='#/kol/${kol.id}'">
        <div class="base">
          <span class="name">${escapeHtml(kol.name)}</span>
          ${kol.category_name ? `<span class="tag">${escapeHtml(kol.category_name)}</span>` : ""}
          <span class="tag">${PLATFORM_LABELS[kol.platform] || kol.platform}</span>
        </div>
        <div class="desc">ID: ${escapeHtml(kol.external_id)}${kol.enabled ? "" : " · 已停用"}</div>
      </div>
      <button class="btn-sub ${subscribed}" onclick="toggleSubscribe(${kol.id}, this)">${label}</button>
    </div>`;
}

function postCard(post) {
  return `
    <div class="post-item">
      <div class="p-header">
        <div class="avatar">${escapeHtml(avatarText(post.kol_name))}</div>
        <div>
          <div class="p-name">${escapeHtml(post.kol_name)}</div>
          <div class="p-time">${escapeHtml(post.published_at)}</div>
        </div>
      </div>
      ${post.title ? `<div class="p-title">${escapeHtml(post.title)}</div>` : ""}
      <div class="p-content">${escapeHtml(post.content || "（无正文）")}</div>
      <div class="p-meta">
        ${post.category_name ? `<span class="cat">🗂 ${escapeHtml(post.category_name)}</span>` : ""}
        <span>${PLATFORM_LABELS[post.platform] || post.platform}</span>
        <a href="${escapeHtml(post.url)}" target="_blank" rel="noopener">查看原文 →</a>
      </div>
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
    if (btn) {
      btn.textContent = kol && kol.subscribed ? "订阅" : "已订阅";
      btn.classList.toggle("subscribed", !(kol && kol.subscribed));
    }
    if (state.catalog) {
      state.catalog = state.catalog.map((k) =>
        k.id === kolId ? { ...k, subscribed: !(k.subscribed) } : k
      );
    }
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

function renderTop(title, back = false, rightHtml = "") {
  $("#page-title").textContent = title;
  $("#btn-back").classList.toggle("hidden", !back);
  $("#top-right").innerHTML = rightHtml;
}

function showTabBar(show) {
  $("#tab-bar").classList.toggle("hidden", !show);
}

function renderEmpty(text, actionHtml = "") {
  return `<div class="empty">${escapeHtml(text)}${actionHtml}</div>`;
}

// ---------- 首页 ----------
async function renderHome() {
  renderTop("首页");
  showTabBar(true);
  const html = `
    <div class="search-bar" onclick="location.hash='#/search'">
      <span>🔍</span>&nbsp;搜索大V / 雪球UID
    </div>
    <div class="platform-tabs" id="platform-tabs"></div>
    <div class="sub-title">推荐大V<span class="tip">点击卡片查看动态</span></div>
    <div id="kol-list"></div>`;
  $("#main").innerHTML = html;
  state.platform = "";
  await loadHomeKols();
  $("#platform-tabs").innerHTML = ["", "xueqiu", "weibo", "twitter"].map((p) => `
    <button class="platform-tab ${p === state.platform ? "selected" : ""}"
      onclick="switchPlatform('${p}')">${p ? PLATFORM_LABELS[p] : "全部"}</button>`).join("");
}

async function loadHomeKols() {
  try {
    const params = state.platform ? `?platform=${state.platform}` : "";
    state.catalog = await api(`/api/catalog${params}`);
    $("#kol-list").innerHTML = state.catalog.length
      ? state.catalog.map(kolCard).join("")
      : renderEmpty("暂无大V，管理员可在后台添加");
  } catch (err) {
    $("#kol-list").innerHTML = renderEmpty("加载失败: " + err.message);
  }
}

async function switchPlatform(platform) {
  state.platform = platform;
  await loadHomeKols();
  document.querySelectorAll(".platform-tab").forEach((btn, i) => {
    const values = ["", "xueqiu", "weibo", "twitter"];
    btn.classList.toggle("selected", values[i] === platform);
  });
}

// ---------- 动态 ----------
async function renderTimeline() {
  renderTop("动态");
  showTabBar(true);
  $("#main").innerHTML = `<div class="sub-title">我的动态<span class="tip">订阅大V的最新帖</span></div><div id="feed"></div>`;
  try {
    const posts = await api("/api/my/feed?limit=100");
    $("#feed").innerHTML = posts.length
      ? posts.map(postCard).join("")
      : renderEmpty("还没有订阅任何大V", `<div><button class="btn-dark btn-add" onclick="location.hash='#/home'">去订阅</button></div>`);
  } catch (err) {
    $("#feed").innerHTML = renderEmpty("加载失败: " + err.message);
  }
}

// ---------- 搜索 ----------
async function renderSearch() {
  renderTop("查询", true);
  showTabBar(false);
  $("#main").innerHTML = `
    <div class="search-bar">
      <span>🔍</span>
      <input id="search-input" placeholder="昵称或雪球UID" onkeydown="if(event.key==='Enter')doSearch()">
    </div>
    <div id="search-result"></div>`;
  $("#search-input").focus();
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
      : renderEmpty("没有找到匹配的大V，可联系管理员添加", `<div><button class="btn-dark btn-add" onclick="location.hash='#/home'">返回首页</button></div>`);
  } catch (err) {
    $("#search-result").innerHTML = renderEmpty("搜索失败: " + err.message);
  }
}

// ---------- 大V动态页 ----------
async function renderKolPage(kolId) {
  renderTop("大V动态", true);
  showTabBar(false);
  $("#main").innerHTML = `<div class="empty">加载中…</div>`;
  try {
    const kol = await api(`/api/kols/${kolId}`);
    const posts = await api(`/api/kols/${kolId}/posts?limit=50`);
    const subscribed = kol.subscribed ? "subscribed" : "";
    $("#main").innerHTML = `
      <div class="card">
        <div class="row" style="justify-content:space-between">
          <div class="row">
            <div class="avatar">${escapeHtml(avatarText(kol.name))}</div>
            <div>
              <div class="p-name">${escapeHtml(kol.name)}</div>
              <div class="p-time">${PLATFORM_LABELS[kol.platform] || kol.platform} · ID ${escapeHtml(kol.external_id)}</div>
            </div>
          </div>
          <button class="btn-sub ${subscribed}" onclick="toggleKolPageSubscribe(${kol.id}, this)">${kol.subscribed ? "已订阅" : "订阅"}</button>
        </div>
      </div>
      <div id="kol-posts">${posts.length ? posts.map(postCard).join("") : renderEmpty("暂无动态")}</div>`;
  } catch (err) {
    $("#main").innerHTML = renderEmpty("加载失败: " + err.message);
  }
}

async function toggleKolPageSubscribe(kolId, btn) {
  await toggleSubscribe(kolId, btn);
}

// ---------- 我的 ----------
async function renderMe() {
  renderTop("我的");
  showTabBar(true);
  try {
    state.user = await api("/api/me");
    const adminMenu = state.user.is_admin
      ? `<button class="menu-item" onclick="location.hash='#/admin/kols'"><span>⚙ 管理后台</span><span class="arrow">›</span></button>`
      : "";
    $("#main").innerHTML = `
      <div class="card user-card">
        <div class="avatar">${escapeHtml(avatarText(state.user.username))}</div>
        <div>
          <div class="row">
            <span class="u-name">${escapeHtml(state.user.username)}</span>
            ${state.user.is_admin ? '<span class="u-badge">管理员</span>' : ""}
          </div>
          <div class="u-desc">订阅了 ${state.user.subscription_count} 个大V · ${state.user.notify_enabled ? "推送已开启" : "推送已关闭"}</div>
        </div>
      </div>
      <div class="menu-list">
        <button class="menu-item" onclick="location.hash='#/mysubs'"><span>我的订阅</span><span class="arrow">›</span></button>
        <button class="menu-item" onclick="location.hash='#/settings'"><span>推送设置</span><span class="arrow">›</span></button>
        ${adminMenu}
        <button class="menu-item danger" onclick="logout()"><span>退出登录</span></button>
      </div>`;
  } catch (err) {
    $("#main").innerHTML = renderEmpty(err.message);
  }
}

// ---------- 我的订阅 ----------
async function renderMySubs() {
  renderTop("我的订阅", true);
  showTabBar(false);
  $("#main").innerHTML = `<div class="empty">加载中…</div>`;
  try {
    const subs = await api("/api/my/subscriptions");
    $("#main").innerHTML = subs.length
      ? subs.map((k) => kolCard({ ...k, subscribed: true })).join("")
      : renderEmpty("还没有订阅任何大V", `<div><button class="btn-dark btn-add" onclick="location.hash='#/home'">去发现大V</button></div>`);
  } catch (err) {
    $("#main").innerHTML = renderEmpty("加载失败: " + err.message);
  }
}

// ---------- 推送设置 ----------
async function renderSettings() {
  renderTop("推送设置", true);
  showTabBar(false);
  try {
    state.user = await api("/api/me");
    $("#main").innerHTML = `
      <div class="notice">
        <b>怎么绑定推送？</b><br>
        · Telegram：给机器人发任意消息后，用 @userinfobot 查自己的 chat_id 填到下面（机器人的 bot_token 需在 config.yaml 配置）。<br>
        · 飞书：需要飞书自建应用的 app_id / app_secret（暂未配置时飞书推送会跳过）。
      </div>
      <div class="card">
        <div class="form-row">
          <label>Telegram chat_id</label>
          <input id="set-tg" value="${escapeHtml(state.user.telegram_chat_id)}" placeholder="如 123456789">
        </div>
        <div class="form-row">
          <label>飞书 open_id</label>
          <input id="set-fs" value="${escapeHtml(state.user.feishu_open_id)}" placeholder="ou_xxxxxxxx">
        </div>
        <div class="form-row">
          <label>新帖推送开关</label>
          <select id="set-notify">
            <option value="1" ${state.user.notify_enabled ? "selected" : ""}>开启</option>
            <option value="0" ${!state.user.notify_enabled ? "selected" : ""}>关闭</option>
          </select>
        </div>
        <button class="btn-primary" style="width:100%" onclick="saveSettings()">保存</button>
      </div>`;
  } catch (err) {
    $("#main").innerHTML = renderEmpty(err.message);
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
  ["kols", "订阅管理"],
  ["categories", "分类"],
  ["posts", "帖子"],
  ["logs", "推送记录"],
  ["users", "用户"],
];

async function renderAdmin(tab) {
  renderTop("管理后台", true);
  showTabBar(false);
  $("#app-view").classList.add("admin-mode");
  $("#main").innerHTML = `
    <div class="admin-tabs">
      ${ADMIN_TABS.map(([key, label]) => `
        <button class="${key === tab ? "active" : ""}" onclick="location.hash='#/admin/${key}'">${label}</button>`).join("")}
    </div>
    <div id="admin-body"></div>`;
  const body = { kols: loadAdminKols, categories: loadAdminCategories, posts: loadAdminPosts, logs: loadAdminLogs, users: loadAdminUsers };
  await body[tab]();
}

async function loadAdminKols() {
  const [kols, categories] = await Promise.all([api("/api/kols"), api("/api/categories")]);
  const catOptions = categories.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
  $("#admin-body").innerHTML = `
    <div class="card">
      <div class="card-title sub-title" style="margin:0 0 10px">添加大V</div>
      <div class="row">
        <select id="ad-platform">
          <option value="xueqiu">雪球</option>
          <option value="weibo">微博</option>
          <option value="twitter">X (RSS)</option>
        </select>
        <select id="ad-category"><option value="">未分类</option>${catOptions}</select>
        <input id="ad-name" placeholder="昵称">
        <input id="ad-external" placeholder="user_id / uid / RSS链接">
        <button class="btn-primary" onclick="adminAddKol()">添加</button>
      </div>
    </div>
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>平台</th><th>昵称</th><th>分类</th><th>外部ID</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>${kols.map((k) => `
            <tr>
              <td>${k.id}</td><td>${PLATFORM_LABELS[k.platform] || k.platform}</td>
              <td>${escapeHtml(k.name)}</td><td>${escapeHtml(k.category_name || "")}</td>
              <td>${escapeHtml(k.external_id)}</td>
              <td class="${k.enabled ? "status-ok" : "status-fail"}">${k.enabled ? "启用" : "停用"}</td>
              <td>
                <button class="btn-sm" onclick="adminToggleKol(${k.id}, ${k.enabled ? 0 : 1})">${k.enabled ? "停用" : "启用"}</button>
                <button class="btn-sm danger" onclick="adminDeleteKol(${k.id})">删除</button>
              </td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </div>`;
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

async function adminDeleteKol(id) {
  if (!confirm("确认删除该大V？")) return;
  await api(`/api/kols/${id}`, { method: "DELETE" });
  loadAdminKols();
}

async function loadAdminCategories() {
  const categories = await api("/api/categories");
  $("#admin-body").innerHTML = `
    <div class="card">
      <div class="row">
        <input id="cat-name" placeholder="分类名，如：实盘、宏观、行业研究">
        <button class="btn-primary" onclick="adminAddCategory()">添加分类</button>
      </div>
    </div>
    <div class="card">
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
    </div>`;
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
    <div class="card">
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
    </div>`;
}

async function loadAdminLogs() {
  const logs = await api("/api/push-logs?limit=100");
  $("#admin-body").innerHTML = `
    <div class="card">
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
    </div>`;
}

async function loadAdminUsers() {
  const users = await api("/api/users");
  $("#admin-body").innerHTML = `
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>Telegram</th><th>飞书</th><th>推送</th><th>注册时间</th></tr></thead>
          <tbody>${users.map((u) => `
            <tr>
              <td>${u.id}</td><td>${escapeHtml(u.username)}</td>
              <td>${u.is_admin ? "管理员" : "用户"}</td>
              <td>${escapeHtml(u.telegram_chat_id || "-")}</td>
              <td>${escapeHtml(u.feishu_open_id || "-")}</td>
              <td>${u.notify_enabled ? "开启" : "关闭"}</td>
              <td>${escapeHtml(u.created_at)}</td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </div>`;
}

// ---------- 路由 ----------
async function router() {
  const hash = location.hash.replace(/^#\/?/, "") || "home";
  const [page, param] = hash.split("/");
  $("#app-view").classList.remove("admin-mode");
  if (!state.token) {
    $("#app-view").classList.add("hidden");
    $("#auth-view").classList.remove("hidden");
    return;
  }
  $("#auth-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  document.querySelectorAll(".tab-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === page)
  );
  try {
    if (page === "home") await renderHome();
    else if (page === "timeline") await renderTimeline();
    else if (page === "me") await renderMe();
    else if (page === "search") await renderSearch();
    else if (page === "kol") await renderKolPage(Number(param));
    else if (page === "mysubs") await renderMySubs();
    else if (page === "settings") await renderSettings();
    else if (page === "admin") await renderAdmin(param || "kols");
    else { location.hash = "#/home"; await renderHome(); }
  } catch (err) {
    $("#main").innerHTML = renderEmpty(err.message);
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
  $("#auth-error").textContent = "";
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
    $("#auth-error").textContent = err.message;
  }
}

// ---------- 事件绑定 ----------
$("#login-form").addEventListener("submit", doLogin);
$("#register-form").addEventListener("submit", doRegister);
$("#toggle-auth").addEventListener("click", () => {
  const register = !$("#register-form").classList.contains("hidden");
  $("#login-form").classList.toggle("hidden", register);
  $("#register-form").classList.toggle("hidden", !register);
  $("#toggle-auth").textContent = register ? "还没有账号？去注册" : "已有账号？去登录";
});
$("#btn-back").addEventListener("click", () => history.back());
document.querySelectorAll(".tab-item").forEach((btn) =>
  btn.addEventListener("click", () => { location.hash = `#/${btn.dataset.tab}`; })
);
window.addEventListener("hashchange", router);

router();
