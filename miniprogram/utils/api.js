const { BASE_URL } = require("../config");

function getToken() {
  return wx.getStorageSync("dav_token") || "";
}

// 后端头像缓存返回 /avatars/xxx.jpg 这类站内相对路径，补全成完整地址；
// 外部 http(s) 地址原样返回，空值返回空串。
function resolveAvatar(url) {
  if (!url) return "";
  if (typeof url === "string" && url.startsWith("/")) {
    return `${BASE_URL}${url}`;
  }
  return url;
}

function request(path, options = {}) {
  const token = getToken();
  const headers = Object.assign(
    { "Content-Type": "application/json" },
    options.headers || {}
  );
  if (token) headers.Authorization = `Bearer ${token}`;

  return new Promise((resolve, reject) => {
    wx.request({
      url: `${BASE_URL}${path}`,
      method: options.method || "GET",
      data: options.data,
      header: headers,
      success(res) {
        if (res.statusCode === 401) {
          wx.removeStorageSync("dav_token");
          wx.removeStorageSync("dav_user");
          wx.reLaunch({ url: "/pages/login/login" });
          reject(new Error("登录已过期"));
          return;
        }
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
          return;
        }
        reject(new Error((res.data && res.data.detail) || `请求失败(${res.statusCode})`));
      },
      fail(err) {
        reject(new Error(err.errMsg || "网络错误"));
      },
    });
  });
}

// 微信登录：wx.login 拿 code -> 后端换 token
function loginWithWechat() {
  return new Promise((resolve, reject) => {
    wx.login({
      success: async ({ code }) => {
        try {
          const data = await request("/api/auth/wechat", {
            method: "POST",
            data: { code },
          });
          wx.setStorageSync("dav_token", data.token);
          wx.setStorageSync("dav_user", data.user);
          resolve(data);
        } catch (err) {
          reject(err);
        }
      },
      fail: (err) => reject(new Error(err.errMsg || "微信登录失败")),
    });
  });
}

function accountLogin(username, password, register, code) {
  const path = register ? "/api/auth/register" : "/api/auth/login";
  return request(path, {
    method: "POST",
    data: register ? { username, password, code } : { username, password },
  }).then((data) => {
    wx.setStorageSync("dav_token", data.token);
    wx.setStorageSync("dav_user", data.user);
    return data;
  });
}

function logout() {
  wx.removeStorageSync("dav_token");
  wx.removeStorageSync("dav_user");
  wx.reLaunch({ url: "/pages/login/login" });
}

async function loadSession() {
  const data = await request("/api/me");
  wx.setStorageSync("dav_user", data);
  return data;
}

module.exports = {
  BASE_URL,
  request,
  loginWithWechat,
  accountLogin,
  logout,
  loadSession,
  resolveAvatar,
};
