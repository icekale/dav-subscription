const { request, resolveAvatar } = require("../../utils/api");
const { platformLabel, subTypeLabel } = require("../../utils/labels");

const SUB_TYPES = [
  { value: "post", label: "帖子" },
  { value: "reply", label: "回复" },
  { value: "both", label: "帖子+回复" },
];

Page({
  data: { kol: null, posts: [], loading: true, subTypes: SUB_TYPES },

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
      this.setData({ kol, posts, loading: false });
    } catch (err) {
      this.setData({ loading: false });
      wx.showToast({ title: err.message, icon: "none" });
    }
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
