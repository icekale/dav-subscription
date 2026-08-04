const { request } = require("../../utils/api");

const PLATFORM_LABELS = { xueqiu: "雪球", weibo: "微博", twitter: "X" };

Page({
  data: { kols: [], loading: true },

  onShow() {
    this.load();
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  async load() {
    try {
      const kols = await request("/api/my/subscriptions");
      this.setData({ kols, loading: false });
    } catch (err) {
      this.setData({ loading: false });
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  platformLabel(platform) {
    return PLATFORM_LABELS[platform] || platform;
  },

  goHome() {
    wx.switchTab({ url: "/pages/index/index" });
  },

  goKol(e) {
    wx.navigateTo({ url: `/pages/kol/kol?id=${e.currentTarget.dataset.id}` });
  },

  async unsubscribe(e) {
    const id = e.currentTarget.dataset.id;
    try {
      await request(`/api/subscriptions/${id}`, { method: "DELETE" });
      this.setData({ kols: this.data.kols.filter((k) => k.id !== id) });
      wx.showToast({ title: "已取消订阅", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },
});
