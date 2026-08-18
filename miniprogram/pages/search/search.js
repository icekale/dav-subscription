const { request, resolveAvatar } = require("../../utils/api");
const { platformLabel } = require("../../utils/labels");

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
      { value: "combination", label: "雪球组合" },
      { value: "weibo", label: "微博" },
      { value: "twitter", label: "X" },
    ],
    askLink: "",
    askCategories: [{ id: 0, name: "请选择分类" }],
    askCategoryIndex: 0,
    askCategoryId: 0,
  },

  onShow() {
    this.loadCategories();
  },

  async loadCategories() {
    try {
      const cats = await request("/api/categories");
      this.setData({
        askCategories: [{ id: 0, name: "请选择分类" }, ...cats],
        askCategoryIndex: 0,
        askCategoryId: 0,
      });
    } catch (err) {
      this.setData({ askCategories: [{ id: 0, name: "请选择分类" }] });
    }
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

  onAskCategory(e) {
    const index = Number(e.detail.value);
    const cat = this.data.askCategories[index];
    this.setData({ askCategoryIndex: index, askCategoryId: cat ? cat.id : 0 });
  },

  async submitAsk() {
    const external_id = this.data.askLink.trim();
    if (!external_id) {
      wx.showToast({ title: "请填写大V主页链接或ID", icon: "none" });
      return;
    }
    if (!this.data.askCategoryId) {
      wx.showToast({ title: "请选择分类", icon: "none" });
      return;
    }
    try {
      await request("/api/kol-requests", {
        method: "POST",
        data: { platform: this.data.askPlatform, external_id, category_id: this.data.askCategoryId },
      });
      wx.showToast({ title: "已提交，等待管理员审批", icon: "success" });
      this.setData({ showAsk: false, askLink: "", askCategoryIndex: 0, askCategoryId: 0 });
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
      const results = kols
        .filter(
          (k) =>
            k.name.toLowerCase().includes(keyword) ||
            (k.external_id || "").toLowerCase().includes(keyword)
        )
        .map((k) => ({
          ...k,
          platform_label: platformLabel(k.platform),
          avatar_url: resolveAvatar(k.avatar_url),
        }));
      this.setData({ results, loading: false, searched: true });
    } catch (err) {
      this.setData({ loading: false, searched: true });
      wx.showToast({ title: err.message, icon: "none" });
    }
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
