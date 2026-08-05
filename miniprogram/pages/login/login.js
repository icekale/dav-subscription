const { loginWithWechat, accountLogin } = require("../../utils/api");
const app = getApp();

Page({
  data: {
    loading: true,
    accountMode: false,
    isRegister: false,
    username: "",
    password: "",
    code: "",
    error: "",
  },

  onLoad() {
    this.tryWechatLogin();
  },

  async tryWechatLogin() {
    this.setData({ loading: true });
    try {
      await app.autoLogin();
      wx.reLaunch({ url: "/pages/index/index" });
    } catch (err) {
      // 后端未配置微信凭据等：降级到账号登录
      this.setData({ loading: false, accountMode: false, error: "" });
    }
  },

  switchMode(e) {
    this.setData({ isRegister: e.currentTarget.dataset.register, error: "" });
  },

  showAccount() {
    this.setData({ accountMode: true, error: "" });
  },

  onUsername(e) { this.setData({ username: e.detail.value }); },
  onPassword(e) { this.setData({ password: e.detail.value }); },
  onCode(e) { this.setData({ code: e.detail.value }); },

  async submitAccount() {
    const { username, password, isRegister } = this.data;
    if (username.trim().length < 2 || password.length < 6) {
      this.setData({ error: "用户名至少2位，密码至少6位" });
      return;
    }
    this.setData({ error: "" });
    try {
      const code = isRegister ? this.data.code.trim() : "";
      if (isRegister && !code) {
        this.setData({ error: "请填写邀请码" });
        return;
      }
      await accountLogin(username.trim(), password, isRegister, code);
      wx.reLaunch({ url: "/pages/index/index" });
    } catch (err) {
      this.setData({ error: err.message });
    }
  },
});
