const $ = (sel) => document.querySelector(sel);

const PLATFORM_LABELS = { xueqiu: "雪球", combination: "雪球组合", weibo: "微博", twitter: "X" };
const PLATFORM_ICONS = {
  "": `<svg class="pt-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/></svg>`,
  xueqiu: `<svg class="pt-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><circle cx="9.3" cy="13.7" r="7.2"/><circle cx="14.7" cy="10.3" r="7.2"/></svg>`,
  combination: `<svg class="pt-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" aria-hidden="true"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>`,
  weibo: `<svg class="pt-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M10.098 20.323c-3.977.391-7.414-1.406-7.672-4.02-.259-2.609 2.759-5.047 6.74-5.441 3.979-.394 7.413 1.404 7.671 4.018.259 2.6-2.759 5.049-6.737 5.439l-.002.004zM9.05 17.219c-.384.616-1.208.884-1.829.602-.612-.279-.793-.991-.406-1.593.379-.595 1.176-.861 1.793-.601.622.263.82.972.442 1.592zm1.27-1.627c-.141.237-.449.353-.689.253-.236-.09-.313-.361-.177-.586.138-.227.436-.346.672-.24.239.09.315.36.18.601l.014-.028zm.176-2.719c-1.893-.493-4.033.45-4.857 2.118-.836 1.704-.026 3.591 1.886 4.21 1.983.64 4.318-.341 5.132-2.179.8-1.793-.201-3.642-2.161-4.149zm7.563-1.224c-.346-.105-.57-.18-.405-.615.375-.977.42-1.804 0-2.404-.781-1.112-2.915-1.053-5.364-.03 0 0-.766.331-.571-.271.376-1.217.315-2.224-.27-2.809-1.338-1.337-4.869.045-7.888 3.08C1.309 10.87 0 13.273 0 15.348c0 3.981 5.099 6.395 10.086 6.395 6.536 0 10.888-3.801 10.888-6.82 0-1.822-1.547-2.854-2.915-3.284v.01zm1.908-5.092c-.766-.856-1.908-1.187-2.96-.962-.436.09-.706.511-.616.932.09.42.511.691.932.602.511-.105 1.067.044 1.442.465.376.421.466.977.316 1.473-.136.406.089.856.51.992.405.119.857-.105.992-.512.33-1.021.12-2.178-.646-3.035l.03.045zm2.418-2.195c-1.576-1.757-3.905-2.419-6.054-1.968-.496.104-.812.587-.706 1.081.104.496.586.813 1.082.707 1.532-.331 3.185.15 4.296 1.383 1.112 1.246 1.429 2.943.947 4.416-.165.48.106 1.007.586 1.157.479.165.991-.104 1.157-.586.675-2.088.241-4.478-1.338-6.235l.03.045z"/></svg>`,
  twitter: `<svg class="pt-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z"/></svg>`,
};
const APP_VERSION = "1.4.0";
const PLATFORM_TABS = ["", "xueqiu", "combination", "weibo", "twitter"];
const state = {
  token: localStorage.getItem("dav_token") || "",
  user: null,
  catalog: [],
  platform: "",
  mysubsPlatform: "",
  adminKolsPlatform: "",
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

function avatarHtml(name, url) {
  if (url) return `<img class="kol-avatar" src="${escapeHtml(url)}" alt="" loading="lazy">`;
  return `<div class="kol-avatar">${escapeHtml(avatarText(name))}</div>`;
}

// ---------- 壳 ----------
const NAV = [
  { group: "订阅", items: [
    { route: "home", icon: "◎", label: "订阅广场" },
    { route: "combinations", icon: "◈", label: "组合订阅" },
    { route: "mysubs", icon: "▤", label: "我的订阅" },
    { route: "timeline", icon: "☰", label: "动态" },
    { route: "settings", icon: "⚙", label: "推送设置" },
  ]},
  { group: "管理", admin: true, items: [
    { route: "admin/stats", icon: "◎", label: "数据源" },
    { route: "admin/kols", icon: "◇", label: "大V管理" },
    { route: "admin/requests", icon: "✚", label: "求添加" },
    { route: "admin/codes", icon: "✉", label: "注册码" },
    { route: "admin/categories", icon: "▣", label: "分类管理" },
    { route: "admin/posts", icon: "▤", label: "帖子" },
    { route: "admin/logs", icon: "☰", label: "推送记录" },
    { route: "admin/audit", icon: "◈", label: "操作日志" },
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
  $("#sidebar-user").innerHTML = `
    <div class="sidebar-user-row">
      <span class="sidebar-user-name">${escapeHtml(user.username)}</span>
      ${user.is_admin ? '<span class="sidebar-user-badge">管理员</span>' : ""}
    </div>
    <div class="sidebar-user-meta">大V订阅 v${APP_VERSION}</div>`;
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
  let onboardingHtml = "";
  if (state.user && !state.user.subscription_count) {
    try {
      const recs = await api("/api/recommendations");
      if (recs.length) {
        onboardingHtml = `
          <section class="section-panel" style="border-color:var(--color-primary)">
            <header class="section-head"><div>
              <p class="section-eyebrow">Welcome</p>
              <h3 class="section-title">👋 欢迎！先订阅几位大V</h3>
              <p class="section-meta">以下是最热门的大V；订阅后新帖会自动推送到你绑定的渠道。</p>
            </div></header>
            <div class="row" style="gap:12px;flex-wrap:wrap">${recs.map((rec) => `
              <div class="kol-item" style="flex:1;min-width:230px">
                ${avatarHtml(rec.name, rec.avatar_url)}
                <div class="kol-info" onclick="location.hash='#/kol/${rec.id}'">
                  <div class="base">
                    <span class="name">${escapeHtml(rec.name)}</span>
                    <span class="tag">${PLATFORM_LABELS[rec.platform] || rec.platform}</span>
                    ${rec.category_name ? `<span class="tag">${escapeHtml(rec.category_name)}</span>` : ""}
                  </div>
                  <div class="desc">${rec.subscriber_count} 人订阅</div>
                </div>
                <button class="btn-sub ${rec.subscribed ? "subscribed" : ""}" onclick="quickSubscribe(${rec.id}, this)">
                  ${rec.subscribed ? "✓ 已订阅" : "订阅"}
                </button>
              </div>`).join("")}
            </div>
            <p class="muted" style="margin-top:12px">💡 也可以先去<a href="#/settings">绑定推送渠道</a>，再回来订阅。</p>
          </section>`;
      }
    } catch {
      /* 推荐加载失败不阻塞页面 */
    }
  }
  $("#main").innerHTML = `
    ${heroPanel("DaV Catalog", "订阅广场", "浏览大V目录，点击卡片查看动态，一键订阅你关注的人。",
      [])}
    ${onboardingHtml}
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
      ${state.user?.is_admin ? "" : `
        <div class="request-banner">
          <div class="request-banner-icon">✚</div>
          <div class="request-banner-copy">
            <div class="title">想关注的大V不在列表里？</div>
            <div class="desc">提交申请，管理员审批通过后自动上架并通知你</div>
          </div>
          <button class="btn-normal" onclick="location.hash='#/search'">申请添加</button>
        </div>`}
      <div id="kol-list"></div>
    </section>`;
  state.platform = "";
  renderPlatformTabs();
  await loadHomeKols();
}

function renderPlatformTabs() {
  $("#platform-tabs").innerHTML = PLATFORM_TABS.map((p) => platformTabHTML(p, state.platform, "switchPlatform")).join("");
}

function platformTabHTML(p, current, handler) {
  const label = p ? PLATFORM_LABELS[p] : "全部";
  return `<button class="platform-tab ${p === current ? "selected" : ""}" data-platform="${p || "all"}"
    title="${label}" aria-label="${label}"
    onclick="${handler}('${p}')">${PLATFORM_ICONS[p || ""]}</button>`;
}

async function loadHomeKols() {
  try {
    const params = state.platform ? `?platform=${state.platform}` : "";
    state.catalog = await api(`/api/catalog${params}`);
    $("#catalog-meta").textContent = `共 ${state.catalog.length} 个大V`;
    $("#kol-list").innerHTML = state.catalog.length
      ? groupedKolCards(state.catalog)
      : emptyState("暂无大V，管理员可在管理后台添加");
  } catch (err) {
    $("#kol-list").innerHTML = emptyState("加载失败: " + err.message);
  }
}

function groupedKolCards(kols) {
  const groups = {};
  for (const kol of kols) {
    const key = kol.category_name || "未分类";
    (groups[key] = groups[key] || []).push(kol);
  }
  return Object.entries(groups)
    .map(([name, items]) => `
      <div class="group-head" style="display:flex;justify-content:space-between;align-items:baseline;margin:18px 2px 8px">
        <span style="font-weight:600;color:var(--color-text-strong)">${escapeHtml(name)}</span>
        <span class="muted">${items.length} 位</span>
      </div>
      ${items.map(kolCard).join("")}`)
    .join("");
}

async function switchPlatform(platform) {
  state.platform = platform;
  renderPlatformTabs();
  await loadHomeKols();
}

function kolCard(kol) {
  return `
    <div class="kol-item">
      ${avatarHtml(kol.name, kol.avatar_url)}
      <div class="kol-info" onclick="location.hash='#/kol/${kol.id}'">
        <div class="base">
          <span class="name">${escapeHtml(kol.name)}</span>
          <span class="tag">${PLATFORM_LABELS[kol.platform] || kol.platform}</span>
          ${kol.category_name ? `<span class="tag">${escapeHtml(kol.category_name)}</span>` : ""}
        </div>
        <div class="desc">外部 ID：${escapeHtml(kol.external_id)}${kol.enabled ? "" : " · 已停用"}</div>
      </div>
      <button class="btn-sub ${kol.subscribed ? "subscribed" : ""}" onclick="toggleSubscribe(${kol.id}, this)">
        ${kol.subscribed ? "✓ 已订阅" : "订阅"}
      </button>
      ${kol.subscribed && kol.platform === "xueqiu" ? subTypeSwitchesHtml(kol.id, kol.subscribe_type || "post") : ""}
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
    const wasSubscribed = kol ? kol.subscribed : btn.classList.contains("subscribed");
    if (wasSubscribed) {
      await api(`/api/subscriptions/${kolId}`, { method: "DELETE" });
    } else {
      await api("/api/subscriptions", { method: "POST", body: JSON.stringify({ kol_id: kolId, type: "post" }) });
    }
    refreshKolsView();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function quickSubscribe(kolId, btn) {
  try {
    await api("/api/subscriptions", { method: "POST", body: JSON.stringify({ kol_id: kolId, type: "post" }) });
    btn.classList.add("subscribed");
    btn.textContent = "✓ 已订阅";
    btn.disabled = true;
    state.user.subscription_count = (state.user.subscription_count || 0) + 1;
  } catch (err) {
    alert("订阅失败: " + err.message);
  }
}

function refreshKolsView() {
  const hash = location.hash;
  if (hash.startsWith("#/combinations")) renderCombinations();
  else if (hash.startsWith("#/mysubs")) renderMySubs();
  else if (hash.startsWith("#/kol/")) renderKolPage(Number(hash.split("/")[2] || 0));
  else loadHomeKols();
}

function subTypeSwitchesHtml(kolId, current) {
  const cur = current || "post";
  const postOn = cur !== "reply";
  const replyOn = cur !== "post";
  return `
    <div class="sub-type-switches" data-kol="${kolId}">
      <label class="sub-type-switch">
        <input type="checkbox" ${postOn ? "checked" : ""} onchange="setSubscribeType(${kolId}, 'post', this)">
        <span>帖子</span>
      </label>
      <label class="sub-type-switch">
        <input type="checkbox" ${replyOn ? "checked" : ""} onchange="setSubscribeType(${kolId}, 'reply', this)">
        <span>回复</span>
      </label>
    </div>`;
}

async function setSubscribeType(kolId, which, input) {
  const box = input.closest(".sub-type-switches");
  const boxes = box.querySelectorAll('input[type="checkbox"]');
  const postOn = boxes[0].checked;
  const replyOn = boxes[1].checked;
  if (!postOn && !replyOn) {
    input.checked = true; // 至少保留一种类型；取消订阅请点「已订阅」主按钮
    alert("请至少保留一种订阅类型；取消订阅请点「已订阅」按钮");
    return;
  }
  const type = postOn && replyOn ? "both" : postOn ? "post" : "reply";
  try {
    await api(`/api/subscriptions/${kolId}`, { method: "PUT", body: JSON.stringify({ type }) });
    const kol = state.catalog.find((k) => k.id === kolId);
    if (kol) {
      kol.subscribed = true;
      kol.subscribe_type = type;
    }
  } catch (err) {
    alert("切换订阅类型失败: " + err.message);
    refreshKolsView();
  }
}

// ---------- 我的订阅 / 动态 ----------
async function renderMySubs() {
  setPageTitle("我的订阅");
  $("#main").innerHTML = `
    ${heroPanel("My Subscriptions", "我的订阅", "管理你关注的大V与组合，随时取消订阅。", ["大V", "组合"])}
    <section class="section-panel">
      <header class="section-head">
        <div>
          <p class="section-eyebrow">Subscriptions</p>
          <h3 class="section-title">已订阅</h3>
        </div>
      </header>
      <div class="platform-tabs" id="mysubs-tabs" style="margin-top:12px"></div>
      <div id="mysubs-list"></div>
    </section>`;
  try {
    const subs = await api("/api/my/subscriptions");
    state.catalog = subs.map((k) => ({ ...k, subscribed: true }));
    renderMySubsTabs();
    renderMySubsList();
  } catch (err) {
    $("#mysubs-list").innerHTML = emptyState(err.message);
  }
}

function renderMySubsTabs() {
  $("#mysubs-tabs").innerHTML = PLATFORM_TABS.map((p) => platformTabHTML(p, state.mysubsPlatform, "switchMySubsPlatform")).join("");
}

function switchMySubsPlatform(platform) {
  state.mysubsPlatform = platform;
  renderMySubsTabs();
  renderMySubsList();
}

function renderMySubsList() {
  const kols = state.catalog.filter(
    (k) => !state.mysubsPlatform || k.platform === state.mysubsPlatform
  );
  $("#mysubs-list").innerHTML = kols.length
    ? kols.map(kolCard).join("")
    : emptyState("这里还没有订阅", `<div><button class="btn-normal btn-add" onclick="location.hash='#/home'">去订阅广场看看</button></div>`);
}

async function renderCombinations() {
  setPageTitle("组合订阅");
  $("#main").innerHTML = `
    ${heroPanel("Combination Subscriptions", "组合订阅", "订阅雪球组合，每次调仓（持仓变化）都会实时推送。", ["调仓提醒", "模拟仓"])}
    <section class="section-panel">
      <header class="section-head">
        <div>
          <p class="section-eyebrow">Cubes</p>
          <h3 class="section-title">雪球组合</h3>
          <p class="section-meta" id="combo-meta">加载中…</p>
        </div>
      </header>
      <div id="combo-list"></div>
    </section>`;
  try {
    const kols = await api("/api/catalog?platform=combination");
    state.catalog = kols;
    $("#combo-meta").textContent = `共 ${kols.length} 个组合`;
    $("#combo-list").innerHTML = kols.length
      ? kols.map(kolCard).join("")
      : emptyState(
          "还没有添加雪球组合",
          state.user?.is_admin
            ? `<div><button class="btn-normal btn-add" onclick="location.hash='#/admin/kols'">去管理后台添加</button></div>`
            : `<div><button class="btn-normal btn-add" onclick="location.hash='#/search'">申请添加 →</button></div>`
        );
  } catch (err) {
    $("#combo-list").innerHTML = emptyState(err.message);
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
  const safeUrl = /^https?:\/\//i.test(post.url || "") ? post.url : "#";
  return `
    <div class="post-item">
      <div class="p-header">
        ${avatarHtml(post.kol_name, post.avatar_url)}
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
        ${post.post_type === "reply" ? `<span class="cat">回复</span>` : ""}
        <a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener">查看原文 →</a>
      </div>
    </div>`;
}

// ---------- 搜索 ----------
async function renderSearch() {
  setPageTitle("搜索", true);
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const query = params.get("q") || "";
  $("#main").innerHTML = `
    ${heroPanel("Search", "搜索大V", "按昵称或外部 ID（雪球 UID / 微博 UID / X 用户名）查找。")}
    <section class="section-panel">
      <div class="search-bar" style="margin-bottom:16px">
        <span>🔍</span>
        <input id="search-input" placeholder="输入昵称或 ID，回车搜索" value="${escapeHtml(query)}" onkeydown="if(event.key==='Enter')doSearch()">
        <button class="btn-ghost" onclick="doSearch()">搜索</button>
      </div>
      <div id="search-result"></div>
    </section>`;
  if (!state.user?.is_admin) {
    const askSection = document.createElement("div");
    askSection.innerHTML = `
      <section class="section-panel">
        <header class="section-head">
          <div><p class="section-eyebrow">Request</p><h3 class="section-title">申请添加大V</h3>
          <p class="section-meta">目录里没有的大V？提交申请，管理员审批通过后即可订阅。</p></div>
        </header>
        <div class="toolbar" style="margin-top:12px">
          <select id="ask-platform" class="form-control" style="margin:0;width:auto">
            <option value="xueqiu">雪球</option>
            <option value="combination">雪球组合</option>
            <option value="weibo">微博</option>
            <option value="twitter">X</option>
          </select>
          <input id="ask-link" class="form-control" style="margin:0;flex:1;min-width:220px" placeholder="大V主页链接或 ID">
          <button class="btn-normal" onclick="submitAsk()">提交申请</button>
        </div>
        <div id="ask-result" class="muted" style="margin-top:12px"></div>
      </section>
      <section class="section-panel">
        <header class="section-head"><div><p class="section-eyebrow">My Requests</p><h3 class="section-title">我的申请</h3></div></header>
        <div id="my-asks"></div>
      </section>`;
    $("#main").appendChild(askSection.firstElementChild);
    $("#main").appendChild(askSection.children[1]);
    loadMyAsks();
  }
  if (query) doSearch();
  else $("#search-input").focus();
}

async function submitAsk() {
  const external_id = $("#ask-link").value.trim();
  if (!external_id) {
    alert("请填写大V主页链接或 ID");
    return;
  }
  try {
    await api("/api/kol-requests", {
      method: "POST",
      body: JSON.stringify({ platform: $("#ask-platform").value, external_id }),
    });
    $("#ask-link").value = "";
    $("#ask-result").textContent = "已提交 ✅ 管理员审批通过后会自动出现在订阅广场";
    loadMyAsks();
  } catch (err) {
    $("#ask-result").textContent = "提交失败: " + err.message;
  }
}

async function loadMyAsks() {
  try {
    const asks = await api("/api/my/kol-requests");
    const statusMap = { pending: "待审批", approved: "已通过 ✅", rejected: "已拒绝" };
    $("#my-asks").innerHTML = asks.length
      ? `<div class="table-wrap"><table>
          <thead><tr><th>平台</th><th>外部 ID</th><th>状态</th><th>提交时间</th></tr></thead>
          <tbody>${asks.map((a) => `
            <tr>
              <td>${PLATFORM_LABELS[a.platform] || a.platform}</td>
              <td>${escapeHtml(a.external_id)}</td>
              <td class="${a.status === "approved" ? "status-ok" : a.status === "rejected" ? "status-fail" : ""}">${statusMap[a.status] || escapeHtml(a.status)}</td>
              <td>${escapeHtml(a.created_at)}</td>
            </tr>`).join("")}</tbody>
        </table></div>`
      : emptyState("还没有提交过申请");
  } catch {
    /* 忽略加载失败 */
  }
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
            ${kol.subscribed && kol.platform === "xueqiu" ? subTypeSwitchesHtml(kol.id, kol.subscribe_type || "post") : ""}
            <button class="btn-sub ${kol.subscribed ? "subscribed" : ""}" id="kol-sub-btn" onclick="toggleKolPageSubscribe(${kol.id})">
              ${kol.subscribed ? "✓ 已订阅" : "订阅"}
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
  await toggleSubscribe(kolId, $("#kol-sub-btn"));
}

// ---------- 推送设置 ----------
let settingsPollTimer = null;
let settingsPollCount = 0;

function stopSettingsPoll() {
  if (settingsPollTimer) {
    clearInterval(settingsPollTimer);
    settingsPollTimer = null;
  }
}

function channelStatusHtml(user) {
  const tg = user.telegram_chat_id;
  const tgCustom = user.custom_telegram_bot;
  const fsOpen = user.feishu_open_id;
  const fsChat = user.feishu_chat_id;
  const wc = user.wecom_webhook;
  const fsOk = !!(fsOpen && fsChat);
  return `
    <div class="row" style="gap:16px;flex-wrap:wrap">
      <div class="channel-card">
        <div class="channel-head">
          <b>Telegram${tgCustom ? ' <span class="tag">自建</span>' : ""}</b>
          <span class="${tg ? "status-ok" : "status-fail"}">${tg ? "已绑定 ✅" : "未绑定"}</span>
        </div>
        <p class="muted" style="margin:8px 0 0">${tg ? (tgCustom ? "使用你自己的机器人推送" : "官方机器人推送已启用") : "按下方步骤操作"}</p>
        ${tg
          ? `<button class="btn-sm" style="margin-top:10px" onclick="unbindChannel('${tgCustom ? "telegram_bot_token" : "telegram_chat_id"}')">解绑</button>`
          : `<button class="btn-sm" style="margin-top:10px" onclick="bindChannel('telegram')">一键绑定官方机器人</button>
             <div id="bind-result-telegram"></div>
             <details style="margin-top:10px">
               <summary class="muted" style="cursor:pointer">或使用自己的机器人（推荐）</summary>
               <ol style="padding-left:18px;line-height:1.8;margin-top:8px">
                 <li>打开 Telegram 搜索 <b>@BotFather</b>，发 <code>/newbot</code> 创建机器人，拿到 token</li>
                 <li>给你的新机器人发任意消息（如 <code>/start</code>）</li>
                 <li>把 token 粘贴到下方点「保存」，系统自动识别你的会话，无需手动填 ID</li>
               </ol>
               <div class="row" style="gap:8px;margin-top:10px">
                 <input id="set-custom-tg" class="form-control" style="flex:1;min-width:220px" type="password" placeholder="123456:ABC-DEF...">
                 <button class="btn-normal" onclick="saveCustomTgBot()">保存</button>
               </div>
               <p id="custom-tg-result" class="muted"></p>
             </details>`}
      </div>
      <div class="channel-card">
        <div class="channel-head">
          <b>飞书</b>
          <span class="${fsOk ? "status-ok" : (fsOpen ? "status-warn" : "status-fail")}">${fsOk ? "已绑定 ✅" : (fsOpen ? "未完成" : "未绑定")}</span>
        </div>
        <p class="muted" style="margin:8px 0 0">
          ${fsOk ? "私聊会话已建立，推送正常"
            : (fsOpen ? "已关联账号，请先在飞书私聊机器人发一条消息"
            : "按下方步骤操作，本页会自动刷新状态")}
        </p>
        ${fsOpen
          ? `<button class="btn-sm" style="margin-top:10px" onclick="unbindChannel('feishu')">解绑</button>`
          : `<button class="btn-sm" style="margin-top:10px" onclick="bindChannel('feishu')">绑定</button>
             <div id="bind-result-feishu"></div>`}
      </div>
      <div class="channel-card">
        <div class="channel-head">
          <b>企业微信</b>
          <span class="${wc ? "status-ok" : "status-fail"}">${wc ? "已绑定 ✅" : "未绑定"}</span>
        </div>
        <p class="muted" style="margin:8px 0 0">${wc ? "群机器人推送已启用" : "在企业微信群添加群机器人，把 webhook 粘贴到下方输入框即可"}</p>
        ${wc ? `<button class="btn-sm" style="margin-top:10px" onclick="unbindChannel('wecom')">解绑</button>` : ""}
      </div>
    </div>`;
}

async function refreshSettingsStatus() {
  settingsPollCount += 1;
  try {
    const user = await api("/api/me");
    state.user = user;
    const el = $("#push-status");
    if (!el) {
      stopSettingsPoll();
      return;
    }
    el.innerHTML = channelStatusHtml(user);
    if (user.telegram_chat_id && user.feishu_open_id && user.feishu_chat_id && user.wecom_webhook) stopSettingsPoll();
  } catch {
    /* 轮询失败忽略 */
  }
  if (settingsPollCount >= 25) stopSettingsPoll();
}

async function renderSettings() {
  setPageTitle("推送设置");
  try {
    state.user = await api("/api/me");
    const guide = state.user.push_guide || {};
    const tgBot = guide.telegram_bot_username || "";
    const fsBot = guide.feishu_bot_name || "";
    const tgTarget = tgBot
      ? `<a href="https://t.me/${encodeURIComponent(tgBot)}" target="_blank" rel="noopener">@${escapeHtml(tgBot)}</a>`
      : "你的机器人";
    const fsTarget = fsBot ? `<b>${escapeHtml(fsBot)}</b>` : "你的机器人应用名";
    $("#main").innerHTML = `
      ${heroPanel("Push Settings", "推送设置", "跟着步骤走，2 分钟完成：绑定 Telegram / 飞书 / 企业微信，新帖就会自动推给你。", ["Telegram", "飞书", "企业微信"])}
      <section class="section-panel">
        <header class="section-head">
          <div>
            <p class="section-eyebrow">Channels</p>
            <h3 class="section-title">推送渠道状态</h3>
            <p class="section-meta">新帖会推送到你绑定的渠道；状态每 4 秒自动刷新。</p>
          </div>
        </header>
        <div id="push-status">${channelStatusHtml(state.user)}</div>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <p class="section-eyebrow">Delivery</p>
            <h3 class="section-title">推送通道选择</h3>
            <p class="section-meta">绑定多个渠道时，可只给选中的渠道推送；不选则全部推送。</p>
          </div>
        </header>
        <div class="channel-picks" id="push-channels-box">${pushChannelsHtml(state.user)}</div>
        ${(state.user.telegram_chat_id || state.user.feishu_open_id || state.user.feishu_chat_id || state.user.wecom_webhook)
          ? `<div class="toolbar" style="margin-top:14px">
               <button class="btn-normal" onclick="savePushChannels()">保存推送通道</button>
               <span id="push-channels-result" class="muted"></span>
             </div>` : ""}
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <p class="section-eyebrow">Telegram</p>
            <h3 class="section-title">① 打开 Telegram 机器人</h3>
          </div>
        </header>
        <ol style="padding-left:20px;line-height:2">
          <li>打开 Telegram，搜索并进入 ${tgTarget}（找不到就点上方链接）。</li>
          <li>点击「开始」或发送任意消息（如 <code>/start</code>），系统自动记录你的会话。</li>
          <li>回到本页，状态几秒内自动变成「已绑定 ✅」。</li>
          <li>发 <code>/list</code> 可查看大V目录，<code>/sub 大VID</code> 直接订阅。</li>
        </ol>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <p class="section-eyebrow">WeCom</p>
            <h3 class="section-title">② 绑定企业微信群机器人</h3>
            <p class="section-meta">无需申请应用；在企业微信任意群里添加「群机器人」即可，推送会发到这个群。</p>
          </div>
        </header>
        <ol style="padding-left:20px;line-height:2">
          <li>打开企业微信，进入一个群（没有就新建一个，例如「大V推送」）。</li>
          <li>点右上角 <code>...</code> → 「群机器人」→「添加机器人」，按提示创建并起名。</li>
          <li>创建完成后复制 webhook 地址（<code>https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...</code>）。</li>
          <li>粘贴到下方输入框，点「保存绑定」，状态即变为「已绑定 ✅」。</li>
        </ol>
        <div class="form-row" style="margin-top:14px">
          <label for="set-wecom-webhook">群机器人 webhook 地址</label>
          <div class="row" style="gap:10px;flex-wrap:wrap">
            <input id="set-wecom-webhook" class="form-control" style="flex:1;min-width:280px"
              type="text" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
              value="${escapeHtml(state.user.wecom_webhook || "")}">
            <button class="btn-normal" onclick="saveWecomWebhook()">保存绑定</button>
          </div>
        </div>
        <p class="muted">⚠️ webhook 等同群管理权限，请勿泄露给他人；不同用户应使用各自的群机器人。</p>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <p class="section-eyebrow">Feishu</p>
            <h3 class="section-title">③ 打开飞书机器人（重要：请用私聊）</h3>
          </div>
        </header>
        <ol style="padding-left:20px;line-height:2">
          <li>打开飞书 App，点顶部「搜索」，搜索 ${fsTarget} 并进入。</li>
          <li>关键：请在该机器人的<b>「私聊」会话</b>里发任意消息（如 <code>/start</code>）——群聊不会推送新帖，这一步只是建立会话。</li>
          <li>回到本页，在下方「与网页/小程序账号同步」里点「生成绑定码」，把 <code>/bind 6位码</code> 发给机器人。</li>
          <li>发送后本页状态会变成「已绑定 ✅」，网页订阅与飞书推送自动同步。</li>
          <li>发 <code>/list</code> 可查看大V目录，点卡片上的按钮即可订阅。</li>
        </ol>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <p class="section-eyebrow">Sync</p>
            <h3 class="section-title">④ 与网页/小程序账号同步（可选）</h3>
            <p class="section-meta">机器人是独立账号；想让机器人订阅与网页账号合并，用绑定码。</p>
          </div>
        </header>
        <ol style="padding-left:20px;line-height:2">
          <li>点下方「生成绑定码」。</li>
          <li>把 <code>/bind 6位码</code> 发给 Telegram / 飞书机器人（企业微信群机器人是单向 webhook，不支持指令）。</li>
          <li>绑定后机器人账号合并到当前账号，订阅与推送同步，一处订阅处处同步。</li>
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
        <div class="form-row" style="margin-top:16px">
          <label for="set-daily">每日精选摘要</label>
          <select id="set-daily" class="form-control" onchange="saveDailyReport()">
            <option value="1" ${state.user.daily_report_enabled ? "selected" : ""}>开启（每天 20:00 推送一次今日订阅总览）</option>
            <option value="0" ${!state.user.daily_report_enabled ? "selected" : ""}>关闭</option>
          </select>
        </div>
        <p class="muted">开启后，每天 20:00 把你订阅大V当天的新动态汇总成一条推送。</p>
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
    settingsPollCount = 0;
    stopSettingsPoll();
    settingsPollTimer = setInterval(refreshSettingsStatus, 4000);
  } catch (err) {
    $("#main").innerHTML = emptyState(err.message);
  }
}

function pushChannelsHtml(user) {
  const opts = [];
  if (user.telegram_chat_id) opts.push(["telegram", "Telegram"]);
  if (user.feishu_open_id || user.feishu_chat_id) opts.push(["feishu", "飞书"]);
  if (user.wecom_webhook) opts.push(["wecom", "企业微信"]);
  if (!opts.length) return `<p class="muted">还没有绑定推送渠道，先完成上方任一渠道绑定后即可选择。</p>`;
  const selected = (user.push_channels || "").split(",").map((s) => s.trim()).filter(Boolean);
  return opts.map(([ch, label]) => `
    <label class="channel-pick">
      <input type="checkbox" value="${ch}" ${selected.length === 0 || selected.includes(ch) ? "checked" : ""}> ${label}
    </label>`).join("");
}

async function savePushChannels() {
  const boxes = [...document.querySelectorAll("#push-channels-box input[type=checkbox]")];
  if (!boxes.length) return;
  const channels = boxes.filter((b) => b.checked).map((b) => b.value);
  if (!channels.length) {
    alert("请至少保留一个推送通道；全部不想要可以关闭「新帖推送开关」");
    return;
  }
  try {
    await api("/api/me", { method: "PUT", body: JSON.stringify({ push_channels: channels.join(",") }) });
    state.user.push_channels = channels.join(",");
    $("#push-channels-result").textContent = "已保存 ✅";
  } catch (err) {
    alert("保存失败: " + err.message);
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

async function saveDailyReport() {
  try {
    await api("/api/me", {
      method: "PUT",
      body: JSON.stringify({ daily_report_enabled: $("#set-daily").value === "1" }),
    });
  } catch (err) {
    alert("保存失败: " + err.message);
  }
}

async function bindChannel(channel) {
  try {
    const data = await api("/api/me/bind-code", { method: "POST" });
    const code = data.code;
    const guide = state.user.push_guide || {};
    const el = channel === "telegram" ? $("#bind-result-telegram") : $("#bind-result-feishu");
    if (channel === "telegram" && guide.telegram_bot_username) {
      const link = `https://t.me/${encodeURIComponent(guide.telegram_bot_username)}?start=bind_${code}`;
      el.innerHTML = `
        <p style="margin:10px 0 6px">点击下方按钮，Telegram 会自动打开机器人并完成绑定：</p>
        <a class="btn-normal" href="${link}" target="_blank" rel="noopener">一键绑定 Telegram</a>
        <p class="muted" style="margin-top:8px">按钮没反应？复制 <b>${escapeHtml(code)}</b> 粘贴给机器人也可以。</p>`;
    } else {
      const label = channel === "telegram" ? "Telegram" : "飞书";
      el.innerHTML = `
        <p style="margin:10px 0 6px">复制绑定码，粘贴发送给${label}机器人（自动识别，无需命令）：</p>
        <b style="font-size:20px;letter-spacing:3px">${escapeHtml(code)}</b>`;
    }
  } catch (err) {
    alert("生成绑定码失败: " + err.message);
  }
}

async function saveCustomTgBot() {
  const token = ($("#set-custom-tg").value || "").trim();
  if (!token) {
    alert("请先粘贴你的 bot token");
    return;
  }
  try {
    await api("/api/me", { method: "PUT", body: JSON.stringify({ telegram_bot_token: token }) });
    renderSettings();
    alert("自建机器人绑定成功 ✅ 之后推送会通过你的机器人发送");
  } catch (err) {
    $("#custom-tg-result").textContent = "绑定失败：" + err.message;
  }
}

async function unbindChannel(channel) {
  const label = channel === "telegram_chat_id" ? "Telegram"
    : channel === "telegram_bot_token" ? "Telegram（自建机器人）"
    : channel === "wecom" ? "企业微信" : "飞书";
  if (!confirm(`确认解绑 ${label}？解绑后将不再往该渠道推送。`)) return;
  try {
    const body = channel === "feishu"
      ? { feishu_open_id: "", feishu_chat_id: "" }
      : channel === "wecom"
        ? { wecom_webhook: "" }
        : channel === "telegram_bot_token"
          ? { telegram_bot_token: "", telegram_chat_id: "" }
        : { telegram_chat_id: "" };
    await api("/api/me", { method: "PUT", body: JSON.stringify(body) });
    renderSettings();
  } catch (err) {
    alert("解绑失败: " + err.message);
  }
}

async function saveWecomWebhook() {
  const webhook = ($("#set-wecom-webhook").value || "").trim();
  if (webhook && !/^https:\/\/qyapi\.weixin\.qq\.com\/cgi-bin\/webhook\/send\?key=/.test(webhook)) {
    alert("webhook 地址无效，应为 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=... 格式");
    return;
  }
  try {
    await api("/api/me", {
      method: "PUT",
      body: JSON.stringify({ wecom_webhook: webhook }),
    });
    renderSettings();
    if (webhook) alert("企业微信绑定成功 ✅");
  } catch (err) {
    alert("保存失败: " + err.message);
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

// ---------- 管理后台（导航统一走左侧边栏） ----------
async function renderAdmin(tab) {
  setPageTitle("管理后台");
  $("#main").innerHTML = `
    ${heroPanel("Admin Console", "管理后台", "维护大V目录、分类与推送记录，查看注册用户。")}
    <div id="admin-body"></div>`;
  const loaders = { stats: loadAdminStats, kols: loadAdminKols, requests: loadAdminRequests, codes: loadAdminCodes, categories: loadAdminCategories, posts: loadAdminPosts, logs: loadAdminLogs, audit: loadAdminAudit, users: loadAdminUsers };
  try {
    await loaders[tab]();
  } catch (err) {
    $("#admin-body").innerHTML = emptyState("加载失败: " + err.message);
  }
}

async function loadAdminStats() {
  const [s, xq] = await Promise.all([api("/api/stats"), api("/api/admin/xueqiu-cookie")]);
  const fmtTime = (ts) => (ts ? new Date(Number(ts) * 1000).toLocaleString() : "尚未抓取");
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">Data Sources</p><h3 class="section-title">数据源</h3>
      <p class="section-meta">各平台抓取状态与登录凭据维护。</p></div></header>
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
      <div class="table-wrap" style="margin-top:16px">
        <table>
          <thead><tr><th>平台</th><th>状态</th><th>通道</th><th>最近成功</th><th>最近失败</th><th>连续失败</th></tr></thead>
          <tbody>${(s.sources || []).map((src) => {
            const channel = src.platform === "twitter"
              ? (src.direct_mode === "direct"
                  ? '<span class="status-ok">直抓</span>'
                  : src.direct_mode === "fallback"
                    ? '<span class="status-warn" title="' + escapeHtml(src.direct_fallback_reason || "") + '">备用RSS</span>'
                    : '<span class="muted">-</span>')
              : '<span class="muted">-</span>';
            return `
              <tr>
                <td>${PLATFORM_LABELS[src.platform] || src.platform}</td>
                <td class="${src.ok ? "status-ok" : "status-fail"}">${src.ok ? "正常" : "无成功记录"}</td>
                <td>${channel}</td>
                <td>${src.last_ok_at ? fmtTime(src.last_ok_at) : "-"}</td>
                <td class="muted">${src.last_error ? escapeHtml(src.last_error.slice(0, 60)) : "-"}</td>
                <td class="${src.consecutive_fails >= 3 ? "status-fail" : ""}">${src.consecutive_fails}</td>
              </tr>`;
          }).join("")}</tbody>
        </table>
      </div>
      <div class="row" style="gap:14px;align-items:flex-end;margin-top:18px;flex-wrap:wrap">
        <label style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--color-text-muted)">轮询间隔(秒)
          <input id="pc-interval" type="number" class="form-control" style="margin:0;width:110px" min="1" max="3600" value="${s.polling_config.interval_seconds}">
        </label>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--color-text-muted)">优先大V间隔(秒)
          <input id="pc-priority" type="number" class="form-control" style="margin:0;width:110px" min="1" max="600" value="${s.polling_config.priority_interval_seconds}">
        </label>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--color-text-muted)">合并推送周期(秒)
          <input id="pc-digest" type="number" class="form-control" style="margin:0;width:110px" min="0" max="86400" value="${s.polling_config.digest_interval_seconds}">
        </label>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--color-text-muted)">雪球探测(秒)
          <input id="pc-probe" type="number" class="form-control" style="margin:0;width:110px" min="0" max="86400" value="${s.polling_config.source_probe_interval_seconds}">
        </label>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--color-text-muted)">cookie保活(秒)
          <input id="pc-keepalive" type="number" class="form-control" style="margin:0;width:110px" min="0" max="86400" value="${s.polling_config.cookie_keepalive_interval_seconds}">
        </label>
        <label style="display:flex;flex-direction:column;gap:6px;font-size:12px;color:var(--color-text-muted)">每日精选小时
          <input id="pc-daily" type="number" class="form-control" style="margin:0;width:110px" min="0" max="23" value="${s.polling_config.daily_report_hour}">
        </label>
        <label style="display:flex;align-items:center;gap:8px;font-size:12px;color:var(--color-text-muted);height:36px">
          <input id="pc-translate" type="checkbox" ${s.polling_config.translate_twitter_content ? "checked" : ""}> X 内容自动翻译成中文
          <span class="muted">（配置 TWITTER_COOKIE 后走 X 官方翻译，质量同网页版）</span>
        </label>
        <button class="btn-normal" onclick="savePollingConfig()">保存抓取设置</button>
        <span id="pc-result" class="muted"></span>
      </div>
      <div style="margin-top:16px">
        <button class="btn-normal" onclick="startWeiboQr()">微博扫码登录</button>
        <span class="muted" style="margin-left:10px">用微博 App 扫码后自动保存 Cookie，无需手动复制</span>
        <p class="muted" style="margin-top:10px">
          微博 Cookie：${s.weibo_cookie && s.weibo_cookie.set
            ? `已写入（${escapeHtml(s.weibo_cookie.updated_at || "")}）`
            : "未写入"}
          ${s.keepalive_interval_seconds > 0 ? `· 每 ${Math.round(s.keepalive_interval_seconds / 3600)} 小时自动保活` : ""}
        </p>
      </div>
      <div id="wb-qr-box" style="margin-top:16px"></div>
    </section>
    <section class="section-panel">
      <header class="section-head">
        <div><p class="section-eyebrow">Xueqiu</p><h3 class="section-title">雪球 Cookie</h3>
        <p class="section-meta">${xq.set ? `已写入（${escapeHtml(xq.updated_at || "")}），预览：${escapeHtml(xq.preview)}` : "未写入，抓取可能受限或被反爬拦截"}${s.keepalive_interval_seconds > 0 ? ` · 每 ${Math.round(s.keepalive_interval_seconds / 3600)} 小时自动保活` : ""}</p></div>
      </header>
      <textarea id="xq-cookie" class="form-control" rows="4" style="font-family:monospace" placeholder="登录 xueqiu.com 后，浏览器 F12 → Application → Cookies 复制整串（形如 xq_a_token=...; u=...）"></textarea>
      <div class="toolbar" style="margin-top:12px">
        <button class="btn-normal" onclick="saveXueqiuCookie()">保存雪球 Cookie</button>
        <span id="xq-result" class="muted"></span>
      </div>
    </section>`;
}

async function savePollingConfig() {
  const body = {
    interval_seconds: Number($("#pc-interval").value),
    priority_interval_seconds: Number($("#pc-priority").value),
    digest_interval_seconds: Number($("#pc-digest").value),
    source_probe_interval_seconds: Number($("#pc-probe").value),
    cookie_keepalive_interval_seconds: Number($("#pc-keepalive").value),
    daily_report_hour: Number($("#pc-daily").value),
    translate_twitter_content: $("#pc-translate").checked,
  };
  try {
    await api("/api/admin/polling-config", { method: "PUT", body: JSON.stringify(body) });
    $("#pc-result").textContent = "已保存 ✅ 即时生效";
    loadAdminStats();
  } catch (err) {
    alert("保存失败: " + err.message);
  }
}

async function saveXueqiuCookie() {
  const cookie = $("#xq-cookie").value.trim();
  if (!cookie) {
    alert("请先粘贴雪球 cookie");
    return;
  }
  try {
    await api("/api/admin/xueqiu-cookie", {
      method: "POST",
      body: JSON.stringify({ cookie }),
    });
    $("#xq-result").textContent = "已保存 ✅";
    loadAdminStats();
  } catch (err) {
    alert("保存失败: " + err.message);
  }
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
  let kols, categories;
  try {
    [kols, categories] = await Promise.all([
      api(`/api/kols${state.adminKolsPlatform ? `?platform=${state.adminKolsPlatform}` : ""}`),
      api("/api/categories"),
    ]);
  } catch (err) {
    $("#admin-body").innerHTML = emptyState("加载失败: " + err.message);
    return;
  }
  const catOptions = categories.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><p class="section-eyebrow">Create</p><h3 class="section-title">添加大V</h3></div>
        <div class="toolbar" style="margin-top:12px">
          <select id="ad-platform" class="form-control" style="margin:0;width:auto">
            <option value="xueqiu">雪球</option>
            <option value="combination">雪球组合</option>
            <option value="weibo">微博</option>
            <option value="twitter">X</option>
          </select>
          <select id="ad-category" class="form-control" style="margin:0;width:auto"><option value="">未分类</option>${catOptions}</select>
          <input id="ad-name" class="form-control" style="margin:0;width:200px" placeholder="昵称">
          <input id="ad-external" class="form-control" style="margin:0;width:300px" placeholder="user_id / uid / X主页链接 / 雪球主页链接">
          <button class="btn-normal" onclick="adminAddKol()">添加</button>
        </div>
      </header>
    </section>
    <section class="section-panel">
      <header class="section-head">
        <div><p class="section-eyebrow">Batch</p><h3 class="section-title">批量导入大V</h3>
        <p class="section-meta">每行一个：昵称 + 雪球主页链接/UID（昵称可省略），如：<code>段永平 https://xueqiu.com/u/12345</code></p></div>
      </header>
      <textarea id="ad-batch-lines" class="form-control" rows="8" style="font-family:monospace;min-height:180px;resize:vertical" placeholder="https://xueqiu.com/u/12345&#10;段永平 12345&#10;https://xueqiu.com/67890"></textarea>
      <div class="toolbar" style="margin-top:12px">
        <select id="ad-batch-platform" class="form-control" style="margin:0;width:auto">
          <option value="xueqiu">雪球</option>
          <option value="combination">雪球组合</option>
          <option value="weibo">微博</option>
          <option value="twitter">X</option>
        </select>
        <select id="ad-batch-category" class="form-control" style="margin:0;width:auto"><option value="">未分类</option>${catOptions}</select>
        <button class="btn-normal" onclick="adminBatchAddKols()">批量导入</button>
        <span id="ad-batch-result" class="muted"></span>
      </div>
    </section>
    <section class="section-panel">
      <header class="section-head">
        <div><p class="section-eyebrow">List</p><h3 class="section-title">大V列表</h3></div>
        <div class="platform-tabs" id="admin-kols-tabs" style="margin-top:12px"></div>
      </header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>平台</th><th>昵称</th><th>分类</th><th>外部ID</th><th>优先</th><th>原创</th><th>可见性</th><th>状态</th><th>操作</th></tr></thead>
          <tbody>${kols.map((k) => `
            <tr>
              <td>${k.id}</td><td>${PLATFORM_LABELS[k.platform] || k.platform}</td>
              <td>${escapeHtml(k.name)}</td><td>${escapeHtml(k.category_name || "")}</td>
              <td>${escapeHtml(k.external_id)}</td>
              <td>${k.priority ? '<span class="status-ok">是</span>' : "否"}</td>
              <td>${k.original_only ? '<span class="status-ok">是</span>' : "否"}</td>
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
  $("#admin-kols-tabs").innerHTML = PLATFORM_TABS.map((p) => platformTabHTML(p, state.adminKolsPlatform, "switchAdminKolsPlatform")).join("");
}

function switchAdminKolsPlatform(platform) {
  state.adminKolsPlatform = platform;
  loadAdminKols();
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
  try {
    await api(`/api/kols/${id}`, { method: "PUT", body: JSON.stringify({ enabled: !!enabled }) });
    loadAdminKols();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function adminTogglePriority(id, priority) {
  try {
    await api(`/api/kols/${id}`, { method: "PUT", body: JSON.stringify({ priority: !!priority }) });
    loadAdminKols();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function adminDeleteKol(id) {
  if (!confirm("确认删除该大V？")) return;
  try {
    await api(`/api/kols/${id}`, { method: "DELETE" });
    loadAdminKols();
  } catch (err) {
    alert("删除失败: " + err.message);
  }
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
      <label class="form-label" style="display:flex;align-items:center;gap:8px">
        <input id="ek-original" type="checkbox" ${kol.original_only ? "checked" : ""}> 只看原创（微博跳过转发，适合转发刷屏的大V）
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
        original_only: $("#ek-original").checked,
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
  let requests, all;
  try {
    [requests, all] = await Promise.all([
      api("/api/admin/kol-requests?status=pending"),
      api("/api/admin/kol-requests"),
    ]);
  } catch (err) {
    $("#admin-body").innerHTML = emptyState("加载失败: " + err.message);
    return;
  }
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
  try {
    await api(`/api/admin/kol-requests/${id}/approve`, { method: "POST" });
    loadAdminRequests();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function adminRejectRequest(id) {
  if (!confirm("确认拒绝该申请？")) return;
  try {
    await api(`/api/admin/kol-requests/${id}/reject`, { method: "POST" });
    loadAdminRequests();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function loadAdminCodes() {
  const codes = await api("/api/admin/register-codes");
  const used = codes.filter((c) => c.used_by).length;
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><p class="section-eyebrow">Invite Codes</p><h3 class="section-title">生成注册邀请码</h3>
        <p class="section-meta">一次性注册码，用户注册后自动作废；共 ${codes.length} 个，已用 ${used} 个。</p></div>
      </header>
      <div class="toolbar" style="margin-top:12px">
        <select id="rc-note" class="form-control" style="margin:0;width:auto">
          <option value="">无备注</option>
          <option value="内部">内部</option>
          <option value="朋友">朋友</option>
        </select>
        <input id="rc-count" class="form-control" style="margin:0;width:80px" type="number" min="1" max="100" value="5">
        <button class="btn-normal" onclick="adminGenerateCodes()">生成</button>
        <span id="rc-result" class="muted"></span>
      </div>
    </section>
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">List</p><h3 class="section-title">注册码列表</h3></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>邀请码</th><th>备注</th><th>状态</th><th>使用者</th><th>生成时间</th><th>使用时间</th><th>操作</th></tr></thead>
          <tbody>${codes.length === 0 ? `<tr><td colspan="7" class="muted">暂无注册码</td></tr>` : codes.map((c) => `
            <tr>
              <td><code>${escapeHtml(c.code)}</code></td>
              <td>${escapeHtml(c.note || "")}</td>
              <td class="${c.used_by ? "status-fail" : "status-ok"}">${c.used_by ? "已使用" : "可用"}</td>
              <td>${escapeHtml(c.used_by_name || "")}</td>
              <td>${escapeHtml(c.created_at)}</td>
              <td>${escapeHtml(c.used_at || "")}</td>
              <td>${c.used_by ? "" : `<button class="btn-sm danger" onclick="adminRevokeCode('${escapeHtml(c.code)}')">作废</button>`}</td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
}

async function adminRevokeCode(code) {
  if (!confirm(`确认作废注册码 ${code}？作废后无法再使用。`)) return;
  try {
    await api(`/api/admin/register-codes/${encodeURIComponent(code)}`, { method: "DELETE" });
    loadAdminCodes();
  } catch (err) {
    alert("作废失败: " + err.message);
  }
}

async function adminGenerateCodes() {
  try {
    const data = await api("/api/admin/register-codes", {
      method: "POST",
      body: JSON.stringify({
        count: Number($("#rc-count").value) || 5,
        note: $("#rc-note").value,
      }),
    });
    $("#rc-result").textContent = `已生成 ${data.count} 个：${data.codes.join("  ")}`;
    loadAdminCodes();
  } catch (err) {
    alert("生成失败: " + err.message);
  }
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
  try {
    await api(`/api/categories/${id}`, { method: "DELETE" });
    loadAdminCategories();
  } catch (err) {
    alert("删除失败: " + err.message);
  }
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
            <option value="wecom" ${state.adminLogsChannel === "wecom" ? "selected" : ""}>企业微信</option>
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

async function loadAdminAudit() {
  const logs = await api("/api/admin/logs?limit=100");
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head"><div><p class="section-eyebrow">Audit</p><h3 class="section-title">操作日志</h3>
      <p class="section-meta">管理员关键操作记录（改权限/删用户/增删大V/注册码/cookie）。</p></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th>时间</th><th>管理员</th><th>操作</th><th>目标</th><th>详情</th></tr></thead>
          <tbody>${logs.length === 0 ? `<tr><td colspan="5" class="muted">暂无记录</td></tr>` : logs.map((l) => `
            <tr>
              <td>${escapeHtml(l.created_at)}</td>
              <td>${escapeHtml(l.username || "")}</td>
              <td>${escapeHtml(l.action)}</td>
              <td>${escapeHtml(l.target)}</td>
              <td class="muted">${escapeHtml(l.detail)}</td>
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
          <thead><tr><th>ID</th><th>用户名</th><th>角色</th><th>Telegram</th><th>飞书</th><th>企业微信</th><th>推送</th><th>注册时间</th><th>操作</th></tr></thead>
          <tbody>${users.map((u) => `
            <tr>
              <td>${u.id}</td><td>${escapeHtml(u.username)}</td>
              <td>${u.is_admin ? "管理员" : "用户"}</td>
              <td>${escapeHtml(u.telegram_chat_id || "-")}</td>
              <td>${escapeHtml(u.feishu_open_id || "-")}</td>
              <td>${u.wecom_webhook ? "已绑定" : "-"}</td>
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
      const label = r.channel === "telegram" ? "Telegram" : r.channel === "wecom" ? "企业微信" : "飞书";
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
  stopSettingsPoll();
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
    else if (page === "combinations") await renderCombinations();
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
      body: JSON.stringify({
        username: $("#reg-username").value.trim(),
        password: $("#reg-password").value,
        code: $("#reg-code").value.trim(),
      }),
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
