const { request } = require("../../utils/api");

const PLATFORM_LABELS = { xueqiu: "雪球", weibo: "微博", twitter: "X" };

Page({
  data: { keyword: "", results: [], loading: false, searched: false },

  onInput(e) {
    this.setData({ keyword: e.detail.value });
  },

  async doSearch() {
    const keyword = this.data.keyword.trim().toLowerCase();
    if (!keyword) return;
    this.setData({ loading: true, searched: false });
    try {
      const kols = await request("/api/catalog");
      const results = kols.filter(
        (k) => k.name.toLowerCase().includes(keyword) || k.external_id.toLowerCase().includes(keyword)
      );
      this.setData({ results, loading: false, searched: true });
    } catch (err) {
      this.setData({ loading: false, searched: true });
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  platformLabel(platform) {
    return PLATFORM_LABELS[platform] || platform;
  },

  goKol(e) {
    wx.navigateTo({ url: `/pages/kol/kol?id=${e.currentTarget.dataset.id}` });
  },

  async toggleSubscribe(e) {
    const id = e.currentTarget.dataset.id;
    const kol = this.data.results.find((k) => k.id === id);
    if (!kol) return;
    try {
      if (kol.subscribed) {
        await request(`/api/subscriptions/${id}`, { method: "DELETE" });
      } else {
        await request("/api/subscriptions", { method: "POST", data: { kol_id: id } });
      }
      this.setData({
        results: this.data.results.map((k) => (k.id === id ? { ...k, subscribed: !k.subscribed } : k)),
      });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },
});
