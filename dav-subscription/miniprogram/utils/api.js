// 后端地址：开发者工具勾选“不校验合法域名”后可直接用本机地址；
// 真机/上线需要改成已备案的 HTTPS 域名并配置 request 合法域名。
const BASE_URL = "http://localhost:8000";

function getToken() {
  return wx.getStorageSync("dav_token") || "";
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
};
