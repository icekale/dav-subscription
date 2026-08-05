const { request, resolveAvatar } = require("../../utils/api");
const { platformLabel } = require("../../utils/labels");

Page({
  data: {
    kols: [],
    groups: [],
    platform: "",
    loading: true,
    platforms: [
      { value: "", label: "全部" },
      { value: "xueqiu", label: "雪球" },
      { value: "combination", label: "雪球组合" },
      { value: "weibo", label: "微博" },
      { value: "twitter", label: "X" },
    ],
  },

  onShow() {
    this.load();
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  async load() {
    try {
      const q = this.data.platform ? `?platform=${this.data.platform}` : "";
      const kols = (await request(`/api/catalog${q}`)).map((k) => ({
        ...k,
        platform_label: platformLabel(k.platform),
        avatar_url: resolveAvatar(k.avatar_url),
      }));
      const byCat = {};
      for (const k of kols) {
        const key = k.category_name || "未分类";
        (byCat[key] = byCat[key] || []).push(k);
      }
      const groups = Object.entries(byCat).map(([name, items]) => ({ name, items }));
      this.setData({ kols, groups, loading: false });
    } catch (err) {
      this.setData({ loading: false });
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  switchPlatform(e) {
    this.setData({ platform: e.currentTarget.dataset.p, loading: true });
    this.load();
  },

  goSearch() {
    wx.navigateTo({ url: "/pages/search/search" });
  },

  goKol(e) {
    wx.navigateTo({ url: `/pages/kol/kol?id=${e.currentTarget.dataset.id}` });
  },

  async toggleSubscribe(e) {
    const id = e.currentTarget.dataset.id;
    const kol = this.data.kols.find((k) => k.id === id);
    if (!kol) return;
    try {
      if (kol.subscribed) {
        await request(`/api/subscriptions/${id}`, { method: "DELETE" });
      } else {
        await request("/api/subscriptions", { method: "POST", data: { kol_id: id } });
      }
      this.setData({
        kols: this.data.kols.map((k) => (k.id === id ? { ...k, subscribed: !k.subscribed } : k)),
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },
});
