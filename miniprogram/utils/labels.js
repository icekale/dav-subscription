// 平台 / 订阅类型文案映射，供各页面统一使用。
const PLATFORM_LABELS = {
  xueqiu: "雪球",
  combination: "雪球组合",
  weibo: "微博",
  twitter: "X",
  ima: "ima",
  zsxq: "星球",
};

const SUB_TYPE_LABELS = {
  post: "帖子",
  reply: "回复",
  both: "帖子+回复",
};

function platformLabel(platform) {
  return PLATFORM_LABELS[platform] || platform || "";
}

function subTypeLabel(type) {
  return SUB_TYPE_LABELS[type] || "帖子";
}

module.exports = {
  PLATFORM_LABELS,
  SUB_TYPE_LABELS,
  platformLabel,
  subTypeLabel,
};
