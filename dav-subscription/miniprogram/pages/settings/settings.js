const { request } = require("../../utils/api");

Page({
  data: {
    tg: "",
    tgBound: false,
    fsOpen: "",
    fsBound: false,
    fsIncomplete: false,
    notify: true,
    bindCode: "",
    bindMinutes: 0,
    tgBot: "",
    fsBotName: "",
  },

  onLoad() {
    this.load();
  },

  onShow() {
    this._pollCount = 0;
    if (this._pollTimer) clearInterval(this._pollTimer);
    this._pollTimer = setInterval(() => {
      this._pollCount += 1;
      this.load();
      if (this._pollCount >= 20) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
    }, 5000);
  },

  onHide() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  },

  async load() {
    try {
      const user = await request("/api/me");
      const guide = user.push_guide || {};
      this.setData({
        tg: user.telegram_chat_id,
        tgBound: !!user.telegram_chat_id,
        fsOpen: user.feishu_open_id,
        fsBound: !!(user.feishu_open_id && user.feishu_chat_id),
        fsIncomplete: !!user.feishu_open_id && !user.feishu_chat_id,
        notify: user.notify_enabled,
        tgBot: guide.telegram_bot_username || "",
        fsBotName: guide.feishu_bot_name || "",
      });
      if (user.telegram_chat_id && user.feishu_open_id && user.feishu_chat_id && this._pollTimer) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  onNotify(e) { this.setData({ notify: e.detail.value }); },

  async save() {
    try {
      await request("/api/me", {
        method: "PUT",
        data: { notify_enabled: this.data.notify },
      });
      wx.showToast({ title: "已保存", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async unbind(e) {
    const channel = e.currentTarget.dataset.channel;
    const label = channel === "telegram" ? "Telegram" : "飞书";
    const { confirm } = await wx.showModal({
      title: "解绑确认",
      content: `确认解绑 ${label}？解绑后将不再往该渠道推送。`,
    });
    if (!confirm) return;
    try {
      const data = channel === "telegram"
        ? { telegram_chat_id: "" }
        : { feishu_open_id: "", feishu_chat_id: "" };
      await request("/api/me", { method: "PUT", data });
      this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async genBindCode() {
    try {
      const data = await request("/api/me/bind-code", { method: "POST" });
      this.setData({ bindCode: data.code, bindMinutes: Math.floor(data.expires_in_seconds / 60) });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },
});
