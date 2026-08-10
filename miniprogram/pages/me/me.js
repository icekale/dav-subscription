const { request, logout } = require("../../utils/api");
const app = getApp();

Page({
  data: { user: null },

  onShow() {
    this.load();
  },

  async load() {
    try {
      const user = await request("/api/me");
      app.globalData.user = user;
      this.setData({ user });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  goSubs() {
    wx.navigateTo({ url: "/pages/mysubs/mysubs" });
  },

  goSettings() {
    wx.navigateTo({ url: "/pages/settings/settings" });
  },

  goAbout() {
    wx.showModal({
      title: "V Push",
      content: "聚合订阅雪球 / 微博 / X 大V公开动态，新帖推送到 Telegram / 飞书 / 企业微信。",
      showCancel: false,
    });
  },

  doLogout() {
    wx.showModal({
      title: "退出登录",
      content: "确认退出当前账号？",
      success: (res) => {
        if (res.confirm) logout();
      },
    });
  },
});
