const { request, resolveAvatar } = require("../../utils/api");
const { platformLabel, subTypeLabel } = require("../../utils/labels");

const SUB_TYPES = [
  { value: "post", label: "帖子" },
  { value: "reply", label: "回复" },
  { value: "both", label: "帖子+回复" },
];

// 组合快照时间（后端 UTC "YYYY-MM-DD HH:MM:SS"）转本地 "MM-DD HH:MM"
function formatSnapshotTime(ts) {
  if (!ts) return "";
  const d = new Date(String(ts).replace(" ", "T") + "Z");
  if (isNaN(d.getTime())) return "";
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

Page({
  data: {
    kol: null,
    posts: [],
    loading: true,
    subTypes: SUB_TYPES,
    holdings: [],
    holdingsUpdatedAt: "",
    navSeries: [],
    navBenchmark: [],
    navHint: "",
    quoteDisplay: null,
  },

  onLoad(options) {
    this.kolId = Number(options.id);
    this.load();
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  async load() {
    try {
      const [kol, posts] = await Promise.all([
        request(`/api/kols/${this.kolId}`),
        request(`/api/kols/${this.kolId}/posts?limit=50`),
      ]);
      kol.platform_label = platformLabel(kol.platform);
      kol.avatar_url = resolveAvatar(kol.avatar_url);
      posts.forEach((p) => {
        p.platform_label = platformLabel(p.platform || kol.platform);
        p.avatar_url = resolveAvatar(p.avatar_url || kol.avatar_url);
      });
      const extra = { holdings: [], holdingsUpdatedAt: "", navSeries: [], navBenchmark: [], navHint: "", quoteDisplay: null };
      if (kol.platform === "combination") {
        const [holdings, nav] = await Promise.all([
          request(`/api/kols/${this.kolId}/holdings`),
          request(`/api/kols/${this.kolId}/nav`),
        ]);
        extra.holdings = (holdings.holdings || []).map((h) => {
          const delta = h.prev != null && Math.abs(h.weight - h.prev) >= 0.01
            ? `${h.weight >= h.prev ? "+" : ""}${(h.weight - h.prev).toFixed(1)}`
            : "";
          return { ...h, delta, deltaClass: delta && Number(delta) >= 0 ? "up" : delta ? "down" : "" };
        });
        if (holdings.cash != null) extra.holdings.push({ name: "现金", symbol: "CASH", weight: holdings.cash, delta: "", deltaClass: "" });
        extra.holdingsUpdatedAt = formatSnapshotTime(holdings.updated_at);
        extra.navSeries = nav.series || [];
        extra.navBenchmark = nav.benchmark || [];
        extra.navHint = extra.navBenchmark.length >= 2 ? " · 对照沪深300" : "";
        const q = kol.quote || {};
        if (q.day_percent_gain != null || q.net_value != null) {
          const d = q.day_percent_gain;
          extra.quoteDisplay = {
            net: q.net_value != null ? q.net_value.toFixed(3) : "—",
            day: d != null ? `${d >= 0 ? "+" : ""}${d.toFixed(2)}%` : "—",
            dayClass: d != null ? (d >= 0 ? "up" : "down") : "",
            time: formatSnapshotTime(kol.quote_at),
          };
        }
      }
      this.setData({ kol, posts, loading: false, ...extra }, () => this.drawNavChart());
    } catch (err) {
      this.setData({ loading: false });
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  drawNavChart() {
    const series = this.data.navSeries;
    const benchmark = this.data.navBenchmark || [];
    if (!series || series.length < 2) return;
    wx.createSelectorQuery()
      .in(this)
      .select("#navChart")
      .fields({ node: true, size: true })
      .exec((res) => {
        if (!res || !res[0] || !res[0].node) return;
        const canvas = res[0].node;
        const ctx = canvas.getContext("2d");
        const dpr = wx.getSystemInfoSync().pixelRatio || 2;
        const w = res[0].width;
        const h = res[0].height;
        canvas.width = w * dpr;
        canvas.height = h * dpr;
        ctx.scale(dpr, dpr);

        const padL = 4;
        const padR = 4;
        const padT = 16;
        const padB = 20;
        const pw = w - padL - padR;
        const ph = h - padT - padB;
        let cube = series;
        let bench = null;
        if (benchmark.length >= 2) {
          const bm = {};
          benchmark.forEach((p) => { bm[p.date] = p.value; });
          const aligned = series.filter((p) => bm[p.date] != null);
          if (aligned.length >= 2 && aligned[0].value && bm[aligned[0].date]) {
            const c0 = aligned[0].value;
            const b0 = bm[aligned[0].date];
            cube = aligned.map((p) => ({ date: p.date, value: p.value / c0 }));
            bench = aligned.map((p) => ({ date: p.date, value: bm[p.date] / b0 }));
          }
        }
        const vals = cube.map((p) => p.value).concat(bench ? bench.map((p) => p.value) : []);
        let min = Math.min(...vals);
        let max = Math.max(...vals);
        if (max - min < 1e-9) {
          max += 0.005;
          min -= 0.005;
        }
        const span = max - min;
        min -= span * 0.05;
        max += span * 0.05;
        const X = (i) => padL + (i / (cube.length - 1)) * pw;
        const Y = (v) => padT + (1 - (v - min) / (max - min)) * ph;

        // 网格 + Y 轴刻度
        ctx.font = "10px sans-serif";
        ctx.fillStyle = "rgba(0,0,0,0.45)";
        ctx.strokeStyle = "rgba(0,0,0,0.08)";
        ctx.lineWidth = 1;
        for (let i = 0; i <= 3; i++) {
          const v = min + ((max - min) * i) / 3;
          const y = Y(v);
          ctx.beginPath();
          ctx.moveTo(padL, y);
          ctx.lineTo(w - padR, y);
          ctx.stroke();
          ctx.fillText(v.toFixed(3), 2, y + 3);
        }

        const up = series[series.length - 1].value >= series[0].value;
        const color = up ? "#e64340" : "#07c160";

        // 渐变面积
        const grad = ctx.createLinearGradient(0, padT, 0, padT + ph);
        grad.addColorStop(0, up ? "rgba(230,67,64,0.14)" : "rgba(7,193,96,0.14)");
        grad.addColorStop(1, "rgba(0,0,0,0)");
        ctx.fillStyle = grad;
        ctx.beginPath();
        ctx.moveTo(X(0), padT + ph);
        cube.forEach((p, i) => ctx.lineTo(X(i), Y(p.value)));
        ctx.lineTo(X(cube.length - 1), padT + ph);
        ctx.closePath();
        ctx.fill();

        if (bench) {
          ctx.strokeStyle = "rgba(0,0,0,0.35)";
          ctx.lineWidth = 1;
          ctx.setLineDash([4, 3]);
          ctx.beginPath();
          bench.forEach((p, i) => (i === 0 ? ctx.moveTo(X(i), Y(p.value)) : ctx.lineTo(X(i), Y(p.value))));
          ctx.stroke();
          ctx.setLineDash([]);
        }

        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        cube.forEach((p, i) => (i === 0 ? ctx.moveTo(X(i), Y(p.value)) : ctx.lineTo(X(i), Y(p.value))));
        ctx.stroke();

        const first = cube[0].date;
        const mid = cube[Math.floor(cube.length / 2)].date;
        const last = cube[cube.length - 1];
        ctx.fillStyle = "rgba(0,0,0,0.45)";
        ctx.textAlign = "left";
        ctx.fillText(first, padL, h - 6);
        ctx.textAlign = "center";
        ctx.fillText(mid, padL + pw / 2, h - 6);
        ctx.textAlign = "right";
        ctx.fillText(last.date, w - padR, h - 6);
        ctx.fillStyle = color;
        ctx.fillText(series[series.length - 1].value.toFixed(3), w - padR, Y(last.value) - 4);
      });
  },

  async toggleSubscribe() {
    const kol = this.data.kol;
    if (!kol) return;
    try {
      if (kol.subscribed) {
        await request(`/api/subscriptions/${kol.id}`, { method: "DELETE" });
      } else {
        await request("/api/subscriptions", { method: "POST", data: { kol_id: kol.id } });
      }
      this.setData({ "kol.subscribed": !kol.subscribed });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async changeSubType(e) {
    const type = e.currentTarget.dataset.type;
    const kol = this.data.kol;
    if (!kol || kol.subscribe_type === type) return;
    try {
      await request(`/api/subscriptions/${kol.id}`, {
        method: "PUT",
        data: { type },
      });
      this.setData({ "kol.subscribe_type": type });
      wx.showToast({ title: `已设为「${subTypeLabel(type)}」`, icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async toggleFavorite() {
    const kol = this.data.kol;
    if (!kol || !kol.subscribed) return;
    const next = !kol.favorite;
    try {
      await request(`/api/subscriptions/${kol.id}/favorite`, {
        method: "PUT",
        data: { favorite: next },
      });
      this.setData({ "kol.favorite": next });
      wx.showToast({ title: next ? "已加入特别关注 ⭐" : "已取消特别关注", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async toggleSecondary() {
    const kol = this.data.kol;
    if (!kol || !kol.subscribed) return;
    const next = !kol.secondary;
    try {
      await request(`/api/subscriptions/${kol.id}/secondary`, {
        method: "PUT",
        data: { secondary: next },
      });
      this.setData({ "kol.secondary": next });
      wx.showToast({ title: next ? "已设为次要（降频推送）🔕" : "已取消次要", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  copyLink(e) {
    wx.setClipboardData({ data: e.currentTarget.dataset.url });
  },
});
