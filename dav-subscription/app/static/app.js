const $ = (sel) => document.querySelector(sel);

async function api(path, options = {}) {
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(text || resp.statusText);
  }
  return resp.json();
}

const PLATFORM_LABELS = { xueqiu: "雪球", weibo: "微博", twitter: "X" };
const PAGE_TITLES = { kols: "订阅管理", categories: "分类", posts: "帖子", logs: "推送记录" };

let categories = [];

async function loadCategories() {
  categories = await api("/api/categories");
  const options = categories.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
  $("#kol-category").innerHTML = `<option value="">未分类</option>${options}`;
  $("#post-category").innerHTML = `<option value="">全部分类</option>${options}`;
  $("#category-body").innerHTML = categories.map((c) => `
    <tr>
      <td>${c.id}</td>
      <td>${escapeHtml(c.name)}</td>
      <td>${c.kol_count}</td>
      <td class="row">
        <button onclick="renameCategory(${c.id})">重命名</button>
        <button onclick="deleteCategory(${c.id})">删除</button>
      </td>
    </tr>`).join("");
}

async function loadKols() {
  const kols = await api("/api/kols");
  $("#kol-body").innerHTML = kols.map((k) => `
    <tr>
      <td>${k.id}</td>
      <td>${PLATFORM_LABELS[k.platform] || k.platform}</td>
      <td>${escapeHtml(k.name)}</td>
      <td>${escapeHtml(k.category_name || "")}</td>
      <td>${escapeHtml(k.external_id)}</td>
      <td class="${k.enabled ? "ok" : ""}">${k.enabled ? "启用" : "停用"}</td>
      <td class="row">
        <button onclick="toggleKol(${k.id}, ${k.enabled ? 0 : 1})">${k.enabled ? "停用" : "启用"}</button>
        <button onclick="deleteKol(${k.id})">删除</button>
      </td>
    </tr>`).join("");
}

async function loadPosts() {
  const platform = $("#post-platform").value;
  const url = "/api/posts?limit=100" + (platform ? `&platform=${platform}` : "");
  const posts = await api(url);
  const categoryFilter = $("#post-category").value;
  const filtered = categoryFilter
    ? posts.filter((p) => String(p.category_id) === categoryFilter)
    : posts;
  $("#post-list").innerHTML = filtered.map((p) => `
    <li>
      <a href="${escapeHtml(p.url)}" target="_blank" rel="noopener">
        <strong>${escapeHtml(p.title || "（无标题）")}</strong>
      </a>
      <span>${PLATFORM_LABELS[p.platform] || p.platform} · ${escapeHtml(p.kol_name)}${p.category_name ? " · " + escapeHtml(p.category_name) : ""} · ${escapeHtml(p.published_at)}</span>
      <p>${escapeHtml(p.content || "")}</p>
    </li>`).join("");
}

async function loadLogs() {
  const logs = await api("/api/push-logs?limit=100");
  $("#log-body").innerHTML = logs.map((l) => `
    <tr>
      <td>${escapeHtml(l.created_at)}</td>
      <td>${escapeHtml(l.kol_name)}</td>
      <td>${escapeHtml(l.title || "")}</td>
      <td>${l.channel}</td>
      <td class="${l.status === "success" ? "ok" : "fail"}">${l.status}</td>
      <td>${escapeHtml(l.error || "")}</td>
    </tr>`).join("");
}

async function toggleKol(id, enabled) {
  await api(`/api/kols/${id}`, { method: "PUT", body: JSON.stringify({ enabled: !!enabled }) });
  loadKols();
}

async function deleteKol(id) {
  if (!confirm("确认删除该大V？")) return;
  await api(`/api/kols/${id}`, { method: "DELETE" });
  loadKols();
}

async function renameCategory(id) {
  const category = categories.find((c) => c.id === id);
  const name = prompt("新的分类名：", category?.name || "");
  if (name === null || !name.trim()) return;
  try {
    await api(`/api/categories/${id}`, {
      method: "PUT",
      body: JSON.stringify({ name: name.trim() }),
    });
    loadCategories();
  } catch (err) {
    alert("重命名失败: " + err.message);
  }
}

async function deleteCategory(id) {
  const category = categories.find((c) => c.id === id);
  if (!confirm(`确认删除分类「${category?.name || id}」？其下大V将变为未分类`)) return;
  try {
    await api(`/api/categories/${id}`, { method: "DELETE" });
    loadCategories();
    loadKols();
  } catch (err) {
    alert("删除失败: " + err.message);
  }
}

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

document.querySelectorAll(".menu-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".menu-item").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#page-${btn.dataset.page}`).classList.add("active");
    $("#page-title").textContent = PAGE_TITLES[btn.dataset.page] || btn.dataset.page;
  });
});

$("#kol-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/kols", {
      method: "POST",
      body: JSON.stringify({
        platform: $("#platform").value,
        name: $("#name").value,
        external_id: $("#external-id").value,
        category_id: $("#kol-category").value ? Number($("#kol-category").value) : null,
      }),
    });
    $("#name").value = "";
    $("#external-id").value = "";
    loadKols();
  } catch (err) {
    alert("添加失败: " + err.message);
  }
});

$("#category-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/categories", {
      method: "POST",
      body: JSON.stringify({ name: $("#category-name").value }),
    });
    $("#category-name").value = "";
    loadCategories();
  } catch (err) {
    alert("添加失败: " + err.message);
  }
});

$("#refresh-posts").addEventListener("click", loadPosts);
$("#refresh-logs").addEventListener("click", loadLogs);

loadKols();
loadCategories();
loadPosts();
loadLogs();
