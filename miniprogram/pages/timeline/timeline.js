const { request } = require("../../utils/api");

const PLATFORM_LABELS = { xueqiu: "雪球", weibo: "微博", twitter: "X" };

Page({
  data: { posts: [], loading: true },

  onShow() {
    this.load();
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  async load() {
    try {
      const posts = await request("/api/my/feed?limit=100");
      this.setData({ posts, loading: false });
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

  copyLink(e) {
    wx.setClipboardData({ data: e.currentTarget.dataset.url });
  },
});
