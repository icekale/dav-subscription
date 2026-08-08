const { request, resolveAvatar } = require("../../utils/api");
const { platformLabel } = require("../../utils/labels");

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
      const posts = (await request("/api/my/feed?limit=100")).map((p) => ({
        ...p,
        platform_label: platformLabel(p.platform),
        avatar_url: resolveAvatar(p.avatar_url),
        tags: Array.isArray(p.tags) ? p.tags : [],
      }));
      this.setData({ posts, loading: false });
    } catch (err) {
      this.setData({ loading: false });
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  goHome() {
    wx.switchTab({ url: "/pages/index/index" });
  },

  copyLink(e) {
    wx.setClipboardData({ data: e.currentTarget.dataset.url });
  },
});
