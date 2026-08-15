const { request } = require("../../utils/api");
const { BASE_URL } = require("../../config");

function pushChannelOptions(user) {
  const selected = (user.push_channels || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const isChecked = (ch) => selected.length === 0 || selected.includes(ch);
  const opts = [];
  if (user.telegram_chat_id) {
    opts.push({ value: "telegram", label: "Telegram", checked: isChecked("telegram") });
  }
  if (user.feishu_open_id || user.feishu_chat_id || (user.feishu_personal && user.feishu_personal.status === "active")) {
    opts.push({ value: "feishu", label: "飞书", checked: isChecked("feishu") });
  }
  if (user.wecom_webhook) {
    opts.push({ value: "wecom", label: "企业微信", checked: isChecked("wecom") });
  }
  if (user.bark_key) {
    opts.push({ value: "bark", label: "Bark", checked: isChecked("bark") });
  }
  return opts;
}

Page({
  data: {
    tg: "",
    tgBound: false,
    tgCustom: false,
    fsOpen: "",
    fsBound: false,
    fsIncomplete: false,
    wecom: "",
    wecomBound: false,
    barkKey: "",
    barkBound: false,
    keywords: [],
    keywordsInput: "",
    feedToken: "",
    notify: true,
    dailyReport: false,
    bindCode: "",
    bindMinutes: 0,
    tgBot: "",
    fsBotName: "",
    channelOptions: [],
    customTgToken: "",
    wecomInput: "",
    dndEnabled: false,
    dndStart: "23:00",
    dndEnd: "07:00",
    dndAllowFavorite: false,
  },

  onLoad() {
    this.load();
  },

  onShow() {
    this.wecomDirty = false;
    this.load();
  },

  onHide() {
    this._stopPolling();
  },

  _stopPolling() {
    if (this._pollTimer) {
      clearInterval(this._pollTimer);
      this._pollTimer = null;
    }
  },

  // 生成绑定码后开启轮询，等待用户在机器人里 /bind 完成；轮询到绑定码到期或完成时自动停止
  _startPolling(expiresInSeconds) {
    this._stopPolling();
    this._pollCount = 0;
    // 每 5 秒一次，最长到绑定码到期（上限 20 分钟），避免 100 秒就停导致状态不再刷新
    const maxTicks = Math.min(Math.max(Math.ceil(expiresInSeconds / 5000), 1), 240);
    this._pollTimer = setInterval(() => {
      this._pollCount += 1;
      this.load(false);
      if (this._pollCount >= maxTicks) {
        this._stopPolling();
      }
    }, 5000);
  },

  // full=false 时只刷新绑定状态，不覆盖用户正在编辑的表单项（免打扰/新帖设置/通道勾选）
  async load(full = true) {
    try {
      const user = await request("/api/me");
      const guide = user.push_guide || {};
      const patch = {
        tg: user.telegram_chat_id,
        tgBound: !!user.telegram_chat_id,
        tgCustom: !!user.custom_telegram_bot,
        fsOpen: user.feishu_open_id,
        fsBound: !!(user.feishu_open_id && user.feishu_chat_id) || !!(user.feishu_personal && user.feishu_personal.status === "active"),
        fsIncomplete: !!user.feishu_open_id && !user.feishu_chat_id && !(user.feishu_personal && user.feishu_personal.status === "active"),
        wecom: user.wecom_webhook,
        wecomBound: !!user.wecom_webhook,
        barkKey: user.bark_key || "",
        barkBound: !!user.bark_key,
        feedToken: user.feed_token || "",
        tgBot: guide.telegram_bot_username || "",
        fsBotName: guide.feishu_bot_name || "",
        // 通道勾选列表随绑定状态变化（新绑定渠道要能立即出现）
        channelOptions: pushChannelOptions(user),
      };
      if (full) {
        Object.assign(patch, {
          notify: user.notify_enabled,
          dailyReport: !!user.daily_report_enabled,
          dndEnabled: !!user.dnd_start,
          dndStart: user.dnd_start || "23:00",
          dndEnd: user.dnd_end || "07:00",
          dndAllowFavorite: !!user.dnd_allow_favorite,
          keywords: user.keywords || [],
          keywordsInput: (user.keywords || []).join("\n"),
        });
      }
      this.setData(patch);
      if (!this.wecomDirty) {
        this.setData({ wecomInput: user.wecom_webhook || "" });
      }
      if (
        user.telegram_chat_id &&
        user.feishu_open_id &&
        user.feishu_chat_id &&
        user.wecom_webhook &&
        this._pollTimer
      ) {
        clearInterval(this._pollTimer);
        this._pollTimer = null;
      }
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  onNotify(e) { this.setData({ notify: e.detail.value }); },
  onDaily(e) { this.setData({ dailyReport: e.detail.value }); },
  onChannelToggle(e) {
    const channel = e.currentTarget.dataset.channel;
    const checked = e.detail.value;
    this.setData({
      channelOptions: this.data.channelOptions.map((c) =>
        c.value === channel ? { ...c, checked } : c
      ),
    });
  },
  onDndEnabled(e) { this.setData({ dndEnabled: e.detail.value }); },
  onDndStart(e) { this.setData({ dndStart: e.detail.value }); },
  onDndEnd(e) { this.setData({ dndEnd: e.detail.value }); },
  onDndFav(e) { this.setData({ dndAllowFavorite: e.detail.value }); },
  onCustomTgInput(e) { this.setData({ customTgToken: e.detail.value }); },
  onWecomInput(e) {
    this.wecomDirty = true;
    this.setData({ wecomInput: e.detail.value });
  },
  onBarkInput(e) { this.setData({ barkKey: e.detail.value }); },
  onKeywordsInput(e) {
    this.setData({ keywordsInput: e.detail.value });
  },

  async save() {
    const channels = this.data.channelOptions.filter((c) => c.checked).map((c) => c.value);
    if (this.data.channelOptions.length && !channels.length) {
      wx.showToast({ title: "请至少保留一个推送通道", icon: "none" });
      return;
    }
    try {
      await request("/api/me", {
        method: "PUT",
        data: {
          notify_enabled: this.data.notify,
          daily_report_enabled: this.data.dailyReport,
          push_channels: channels.join(","),
        },
      });
      wx.showToast({ title: "已保存", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async saveDnd() {
    const enabled = this.data.dndEnabled;
    const start = this.data.dndStart;
    const end = this.data.dndEnd;
    if (enabled && (!start || !end || start === end)) {
      wx.showToast({ title: "请设置不同的开始与结束时间", icon: "none" });
      return;
    }
    try {
      await request("/api/me", {
        method: "PUT",
        data: {
          dnd_start: enabled ? start : "",
          dnd_end: enabled ? end : "",
          dnd_allow_favorite: this.data.dndAllowFavorite,
        },
      });
      wx.showToast({ title: enabled ? "免打扰已开启" : "免打扰已关闭", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async saveCustomTg() {
    const token = this.data.customTgToken.trim();
    if (!token) {
      wx.showToast({ title: "请粘贴自建机器人 token", icon: "none" });
      return;
    }
    try {
      await request("/api/me", {
        method: "PUT",
        data: { telegram_bot_token: token },
      });
      wx.showToast({ title: "自建机器人绑定成功", icon: "success" });
      this.setData({ customTgToken: "" });
      this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async saveWecom() {
    const webhook = this.data.wecomInput.trim();
    if (webhook && !/^https:\/\/qyapi\.weixin\.qq\.com\/cgi-bin\/webhook\/send\?key=/.test(webhook)) {
      wx.showToast({ title: "企业微信 webhook 地址格式不正确", icon: "none" });
      return;
    }
    try {
      await request("/api/me", {
        method: "PUT",
        data: { wecom_webhook: webhook },
      });
      wx.showToast({ title: webhook ? "企业微信绑定成功" : "已解绑企业微信", icon: "success" });
      this.wecomDirty = false;
      this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async saveBark() {
    const key = this.data.barkKey.trim();
    try {
      await request("/api/me", {
        method: "PUT",
        data: { bark_key: key },
      });
      wx.showToast({ title: key ? "Bark 绑定成功" : "已解绑 Bark", icon: "success" });
      this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async saveKeywords() {
    const keywords = (this.data.keywordsInput || "")
      .split(/[\n,]/)
      .map((k) => k.trim())
      .filter(Boolean);
    try {
      await request("/api/me", {
        method: "PUT",
        data: { keywords },
      });
      wx.showToast({ title: `已保存 ${keywords.length} 个关键词`, icon: "success" });
      this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  copyFeed() {
    const token = this.data.feedToken;
    if (!token) return;
    const url = `${BASE_URL}/api/feed/${token}.xml`;
    wx.setClipboardData({
      data: url,
      success: () => wx.showToast({ title: "订阅源地址已复制", icon: "success" }),
    });
  },

  async regenerateFeed() {
    const { confirm } = await wx.showModal({
      title: "重新生成订阅源",
      content: "旧地址立即失效，确认？",
    });
    if (!confirm) return;
    try {
      const res = await request("/api/me/feed-token/regenerate", { method: "POST" });
      this.setData({ feedToken: res.feed_token });
      wx.showToast({ title: "已重新生成", icon: "success" });
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async unbind(e) {
    const channel = e.currentTarget.dataset.channel;
    const labels = {
      telegram: "Telegram",
      telegram_bot_token: "自建 Telegram 机器人",
      feishu: "飞书",
      wecom: "企业微信",
      bark: "Bark",
    };
    const label = labels[channel] || channel;
    const payloads = {
      telegram: { telegram_chat_id: "" },
      telegram_bot_token: { telegram_bot_token: "" },
      feishu: { feishu_open_id: "", feishu_chat_id: "" },
      wecom: { wecom_webhook: "" },
      bark: { bark_key: "" },
    };
    const { confirm } = await wx.showModal({
      title: "解绑确认",
      content: `确认解绑 ${label}？解绑后将不再往该渠道推送。`,
    });
    if (!confirm) return;
    try {
      await request("/api/me", { method: "PUT", data: payloads[channel] });
      if (channel === "wecom") this.wecomDirty = false;
      this.load();
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },

  async genBindCode() {
    try {
      const data = await request("/api/me/bind-code", { method: "POST" });
      this.setData({ bindCode: data.code, bindMinutes: Math.floor(data.expires_in_seconds / 60) });
      this._startPolling(data.expires_in_seconds);
    } catch (err) {
      wx.showToast({ title: err.message, icon: "none" });
    }
  },
});
