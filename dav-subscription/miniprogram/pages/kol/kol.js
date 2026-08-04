const { request } = require("../../utils/api");

const PLATFORM_LABELS = { xueqiu: "雪球", weibo: "微博", twitter: "X" };

Page({
  data: { kol: null, posts: [], loading: true },

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
      this.setData({ kol, posts, loading: false });
    } catch (err) {
      this.setData({ loading: false });
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  platformLabel(platform) {
    return PLATFORM_LABELS[platform] || platform;
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

  copyLink(e) {
    wx.setClipboardData({ data: e.currentTarget.dataset.url });
  },
});
