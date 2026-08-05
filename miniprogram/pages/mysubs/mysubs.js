const { request, resolveAvatar } = require("../../utils/api");
const { platformLabel, subTypeLabel } = require("../../utils/labels");

const SUB_TYPES = [
  { value: "post", label: "帖子" },
  { value: "reply", label: "回复" },
  { value: "both", label: "帖子+回复" },
];

Page({
  data: { kols: [], shown: [], view: "all", subTypes: SUB_TYPES, loading: true },

  onShow() {
    this.load();
  },

  onPullDownRefresh() {
    this.load().finally(() => wx.stopPullDownRefresh());
  },

  async load() {
    try {
      const kols = (await request("/api/my/subscriptions")).map((k) => ({
        ...k,
        platform_label: platformLabel(k.platform),
        avatar_url: resolveAvatar(k.avatar_url),
      }));
      this.setData({ kols, shown: this._filter(kols, this.data.view), loading: false });
    } catch (err) {
      this.setData({ loading: false });
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  _filter(kols, view) {
    if (view === "combo") return kols.filter((k) => k.platform === "combination");
    if (view === "kol") return kols.filter((k) => k.platform !== "combination");
    return kols;
  },

  switchView(e) {
    const view = e.currentTarget.dataset.view;
    this.setData({ view, shown: this._filter(this.data.kols, view) });
  },

  goHome() {
    wx.switchTab({ url: "/pages/index/index" });
  },

  goKol(e) {
    wx.navigateTo({ url: `/pages/kol/kol?id=${e.currentTarget.dataset.id}` });
  },

  async changeSubType(e) {
    const id = e.currentTarget.dataset.id;
    const type = e.currentTarget.dataset.type;
    const kol = this.data.kols.find((k) => k.id === id);
    if (!kol || kol.subscribe_type === type) return;
    try {
      await request(`/api/subscriptions/${id}`, { method: "PUT", data: { type } });
      const kols = this.data.kols.map((k) => (k.id === id ? { ...k, subscribe_type: type } : k));
      this.setData({ kols, shown: this._filter(kols, this.data.view) });
      wx.showToast({ title: `已设为「${subTypeLabel(type)}」`, icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async toggleFavorite(e) {
    const id = e.currentTarget.dataset.id;
    const kol = this.data.kols.find((k) => k.id === id);
    if (!kol) return;
    const next = !kol.favorite;
    try {
      await request(`/api/subscriptions/${id}/favorite`, {
        method: "PUT",
        data: { favorite: next },
      });
      const kols = this.data.kols.map((k) => (k.id === id ? { ...k, favorite: next } : k));
      this.setData({ kols, shown: this._filter(kols, this.data.view) });
      wx.showToast({ title: next ? "已加入特别关注 ⭐" : "已取消特别关注", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async unsubscribe(e) {
    const id = e.currentTarget.dataset.id;
    try {
      await request(`/api/subscriptions/${id}`, { method: "DELETE" });
      const kols = this.data.kols.filter((k) => k.id !== id);
      this.setData({ kols, shown: this._filter(kols, this.data.view) });
      wx.showToast({ title: "已取消订阅", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },
});
