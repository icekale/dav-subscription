const { request, resolveAvatar } = require("../../utils/api");
const { platformLabel } = require("../../utils/labels");

Page({
  data: { posts: [], loading: true, currentTag: "" },

  onShow() {
    this.load();
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  async load() {
    try {
      const tagQuery = this.data.currentTag
        ? `&tag=${encodeURIComponent(this.data.currentTag)}`
        : "";
      const posts = (await request(`/api/my/feed?limit=100${tagQuery}`)).map((p) => ({
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

  // 点击贴文标签：设置当前标签筛选并重新加载（下拉刷新保持 currentTag）
  selectTag(e) {
    const tag = e.currentTarget.dataset.tag;
    if (!tag || tag === this.data.currentTag) return;
    this.setData({ currentTag: tag, loading: true }, () => this.load());
  },

  clearTag() {
    this.setData({ currentTag: "", loading: true }, () => this.load());
  },

  goHome() {
    wx.switchTab({ url: "/pages/index/index" });
  },

  copyLink(e) {
    wx.setClipboardData({ data: e.currentTarget.dataset.url });
  },
});
