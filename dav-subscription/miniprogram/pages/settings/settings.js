const { request } = require("../../utils/api");

Page({
  data: { tg: "", fs: "", notify: true },

  onLoad() {
    this.load();
  },

  async load() {
    try {
      const user = await request("/api/me");
      this.setData({ tg: user.telegram_chat_id, fs: user.feishu_open_id, notify: user.notify_enabled });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  onTg(e) { this.setData({ tg: e.detail.value }); },
  onFs(e) { this.setData({ fs: e.detail.value }); },
  onNotify(e) { this.setData({ notify: e.detail.value }); },

  async save() {
    try {
      await request("/api/me", {
        method: "PUT",
        data: { telegram_chat_id: this.data.tg.trim(), feishu_open_id: this.data.fs.trim(), notify_enabled: this.data.notify },
      });
      wx.showToast({ title: "已保存", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },
});
