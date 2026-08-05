const { loginWithWechat, loadSession } = require("./utils/api");

App({
  globalData: {
    user: null,
    loginPromise: null,
  },

  onLaunch() {
    const token = wx.getStorageSync("dav_token");
    if (token) {
      this.ensureSession();
    }
  },

  // 小程序启动时自动微信登录；失败（未配置）时由登录页兜底
  ensureSession() {
    if (this.globalData.loginPromise) return this.globalData.loginPromise;
    this.globalData.loginPromise = loadSession()
      .then((user) => {
        this.globalData.user = user;
        return user;
      })
      .catch(() => null)
      .finally(() => {
        this.globalData.loginPromise = null;
      });
    return this.globalData.loginPromise;
  },

  async autoLogin() {
    try {
      const res = await loginWithWechat();
      this.globalData.user = res.user;
      return res.user;
    } catch (err) {
      throw err;
    }
  },
});
