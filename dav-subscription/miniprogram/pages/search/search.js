const { request } = require("../../utils/api");

const PLATFORM_LABELS = { xueqiu: "雪球", weibo: "微博", twitter: "X" };

Page({
  data: {
    keyword: "",
    results: [],
    loading: false,
    searched: false,
    showAsk: false,
    askPlatform: "xueqiu",
    askPlatformIndex: 0,
    askPlatforms: [
      { value: "xueqiu", label: "雪球" },
      { value: "weibo", label: "微博" },
      { value: "twitter", label: "X" },
    ],
    askLink: "",
  },

  onInput(e) {
    this.setData({ keyword: e.detail.value });
  },

  toggleAsk() {
    this.setData({ showAsk: !this.data.showAsk });
  },

  onAskPlatform(e) {
    const index = Number(e.detail.value);
    this.setData({ askPlatformIndex: index, askPlatform: this.data.askPlatforms[index].value });
  },

  onAskLink(e) {
    this.setData({ askLink: e.detail.value });
  },

  async submitAsk() {
    const external_id = this.data.askLink.trim();
    if (!external_id) {
      wx.showToast({ title: "请填写大V主页链接或ID", icon: "none" });
      return;
    }
    try {
      await request("/api/kol-requests", {
        method: "POST",
        data: { platform: this.data.askPlatform, external_id },
      });
      wx.showToast({ title: "已提交，等待管理员审批", icon: "success" });
      this.setData({ showAsk: false, askLink: "" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
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
