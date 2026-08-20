const $ = (sel) => document.querySelector(sel);

const PLATFORM_LABELS = { xueqiu: "雪球", combination: "雪球组合", weibo: "微博", twitter: "X" };
const PLATFORM_SHORT_LABELS = { xueqiu: "雪球", combination: "组合", weibo: "微博", twitter: "X" };
function platformShortLabel(p) {
  return p ? (PLATFORM_SHORT_LABELS[p] || PLATFORM_LABELS[p]) : "全部";
}
const PLATFORM_ICONS = {
  "": `<svg class="pt-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z"/></svg>`,
  xueqiu: `<svg class="pt-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true"><circle cx="9.3" cy="13.7" r="7.2"/><circle cx="14.7" cy="10.3" r="7.2"/></svg>`,
  combination: `<svg class="pt-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round" stroke-linecap="round" aria-hidden="true"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="m3.3 7 8.7 5 8.7-5"/><path d="M12 22V12"/></svg>`,
  weibo: `<svg class="pt-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M10.098 20.323c-3.977.391-7.414-1.406-7.672-4.02-.259-2.609 2.759-5.047 6.74-5.441 3.979-.394 7.413 1.404 7.671 4.018.259 2.6-2.759 5.049-6.737 5.439l-.002.004zM9.05 17.219c-.384.616-1.208.884-1.829.602-.612-.279-.793-.991-.406-1.593.379-.595 1.176-.861 1.793-.601.622.263.82.972.442 1.592zm1.27-1.627c-.141.237-.449.353-.689.253-.236-.09-.313-.361-.177-.586.138-.227.436-.346.672-.24.239.09.315.36.18.601l.014-.028zm.176-2.719c-1.893-.493-4.033.45-4.857 2.118-.836 1.704-.026 3.591 1.886 4.21 1.983.64 4.318-.341 5.132-2.179.8-1.793-.201-3.642-2.161-4.149zm7.563-1.224c-.346-.105-.57-.18-.405-.615.375-.977.42-1.804 0-2.404-.781-1.112-2.915-1.053-5.364-.03 0 0-.766.331-.571-.271.376-1.217.315-2.224-.27-2.809-1.338-1.337-4.869.045-7.888 3.08C1.309 10.87 0 13.273 0 15.348c0 3.981 5.099 6.395 10.086 6.395 6.536 0 10.888-3.801 10.888-6.82 0-1.822-1.547-2.854-2.915-3.284v.01zm1.908-5.092c-.766-.856-1.908-1.187-2.96-.962-.436.09-.706.511-.616.932.09.42.511.691.932.602.511-.105 1.067.044 1.442.465.376.421.466.977.316 1.473-.136.406.089.856.51.992.405.119.857-.105.992-.512.33-1.021.12-2.178-.646-3.035l.03.045zm2.418-2.195c-1.576-1.757-3.905-2.419-6.054-1.968-.496.104-.812.587-.706 1.081.104.496.586.813 1.082.707 1.532-.331 3.185.15 4.296 1.383 1.112 1.246 1.429 2.943.947 4.416-.165.48.106 1.007.586 1.157.479.165.991-.104 1.157-.586.675-2.088.241-4.478-1.338-6.235l.03.045z"/></svg>`,
  twitter: `<svg class="pt-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z"/></svg>`,
};
const CHANNEL_ICONS = {
  telegram: `<svg class="ch-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M11.944 0A12 12 0 0 0 0 12a12 12 0 0 0 12 12 12 12 0 0 0 12-12A12 12 0 0 0 12 0a12 12 0 0 0-.056 0zm4.962 7.224c.1-.002.321.023.465.14a.506.506 0 0 1 .171.325c.016.093.036.306.02.472-.18 1.898-.962 6.502-1.36 8.627-.168.9-.499 1.201-.82 1.23-.696.065-1.225-.46-1.9-.902-1.056-.693-1.653-1.124-2.678-1.8-1.185-.78-.417-1.21.258-1.91.177-.184 3.247-2.977 3.307-3.23.007-.032.014-.15-.056-.212s-.174-.041-.249-.024c-.106.024-1.793 1.14-5.061 3.345-.48.33-.913.49-1.302.48-.428-.008-1.252-.241-1.865-.44-.752-.245-1.349-.374-1.297-.789.027-.216.325-.437.893-.663 3.498-1.524 5.83-2.529 6.998-3.014 3.332-1.386 4.025-1.627 4.476-1.635z"/></svg>`,
  feishu: `<svg class="ch-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 2.5c-2 3.4-4.6 5.4-8.8 6.2 4.2.8 6.8 2.8 8.8 6.2 2-3.4 4.6-5.4 8.8-6.2-4.2-.8-6.8-2.8-8.8-6.2z"/></svg>`,
  wecom: `<svg class="ch-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 4c-4.42 0-8 3.02-8 6.75 0 2.13 1.22 4.02 3.12 5.26L6.2 19.5l3.66-1.83c.68.15 1.4.24 2.14.24 4.42 0 8-3.02 8-6.75S16.42 4 12 4z"/></svg>`,
  bark: `<svg class="ch-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>`,
};
const CHANNEL_LABELS = { telegram: "Telegram", feishu: "飞书", wecom: "企业微信", bark: "Bark" };
const USER_CHANNEL_KEYS = ["telegram", "feishu", "wecom", "bark"];
const APP_VERSION = "1.12.23";
const PLATFORM_TABS = ["", "xueqiu", "combination", "weibo", "twitter"];
const STATS_TABS = ["overview", "health", "config", "cookies", "proxies"];
const TL_PLATFORMS = PLATFORM_TABS.map((p) => [p, p ? PLATFORM_LABELS[p] : "全部"]);
const STAR_SVG = `<svg class="star-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.5l2.95 5.98 6.6.96-4.78 4.66 1.13 6.58L12 17.6l-5.9 3.1 1.13-6.58L2.45 9.44l6.6-.96L12 2.5z"/></svg>`;
// 次要（降频）铃铛图标：线性风格，与 TRASH_ICON 一致（stroke=currentColor）
const BELL_ICON = `<svg class="bell-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>`;
const BELL_OFF_ICON = `<svg class="bell-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8.7 3A6 6 0 0 1 18 8a21.3 21.3 0 0 0 .6 5"/><path d="M17 17H3s3-2 3-9a4.67 4.67 0 0 1 .3-1.7"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/><path d="m2 2 20 20"/></svg>`;
// 显示/隐藏（筛选器语义）眼睛图标：线性风格，与 BELL_ICON 一致（stroke=currentColor）
const EYE_ICON = `<svg class="eye-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><circle cx="12" cy="12" r="3"/></svg>`;
const EYE_OFF_ICON = `<svg class="eye-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z"/><path d="m3 3 18 18"/></svg>`;
const TRASH_ICON = `<svg class="trash-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>`;
// 筛选漏斗图标：线性风格，与 EYE/BELL 一致（stroke=currentColor），补齐三键图标的视觉平衡
const FILTER_ICON = `<svg class="funnel-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>`;
const V_ICON = `<svg class="nav-v-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 4.5L12 19.5L19.5 4.5"/></svg>`;
const BOOK_ICON = `<svg class="nav-book-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>`;
// 导航线性图标集（lucide 风格，stroke=currentColor，与 STAR/BELL/EYE 同一词汇）
const LIST_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/></svg>`;
const GRID_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/></svg>`;
const TRENDING_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 7l-8.5 8.5-5-5L2 17"/><path d="M16 7h6v6"/></svg>`;
const BOOKMARK_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z"/></svg>`;
const GEAR_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`;
const DASHBOARD_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>`;
const FOLDER_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>`;
const USER_PLUS_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M19 8v6M22 11h-6"/></svg>`;
const FILE_TEXT_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6"/><path d="M16 13H8M16 17H8"/></svg>`;
const SEND_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 2L11 13"/><path d="M22 2l-7 20-4-9-9-4z"/></svg>`;
const HISTORY_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/></svg>`;
const DATABASE_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/><path d="M3 12c0 1.66 4 3 9 3s9-1.34 9-3"/></svg>`;
const USERS_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`;
const KEY_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>`;
const PLUS_ICON = `<svg class="nav-svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`;
const X_ICON = `<svg class="x-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>`;
const ARROW_UP_ICON = `<svg class="tl-badge-arrow" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg>`;
const SEARCH_ICON = `<svg class="search-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>`;
const GITHUB_ICON = `<svg class="sidebar-gh-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.55 0-.27-.01-1.17-.02-2.12-3.2.7-3.87-1.36-3.87-1.36-.52-1.33-1.28-1.68-1.28-1.68-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.03 1.75 2.69 1.25 3.35.95.1-.74.4-1.25.72-1.54-2.55-.29-5.23-1.28-5.23-5.68 0-1.26.45-2.28 1.18-3.09-.12-.29-.51-1.46.11-3.05 0 0 .96-.31 3.15 1.18a10.9 10.9 0 0 1 5.74 0c2.19-1.49 3.15-1.18 3.15-1.18.62 1.59.23 2.76.11 3.05.73.81 1.18 1.83 1.18 3.09 0 4.41-2.69 5.38-5.25 5.67.41.35.77 1.05.77 2.12 0 1.53-.01 2.76-.01 3.14 0 .3.2.66.8.55A11.51 11.51 0 0 0 23.5 12C23.5 5.65 18.35.5 12 .5z"/></svg>`;
// 主题切换图标：线性风格，与 TRASH_ICON 一致（stroke=currentColor）
const THEME_SUN_ICON = `<svg class="theme-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/></svg>`;
const THEME_MOON_ICON = `<svg class="theme-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`;
const THEME_AUTO_ICON = `<svg class="theme-ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/></svg>`;
const state = {
  token: localStorage.getItem("dav_token") || "",
  user: null,
  catalog: [],
  platform: "",
  mysubsPlatform: "",
  mysubsFavorite: false,
  adminKolsPlatform: "",
  adminKols: [],
  adminKolsQ: "",
  adminKolsCategory: "",
  adminKolsStatus: "",
  adminKolsPage: 0,
  adminKolsTotal: 0,
  adminUsers: [],
  adminUsersQ: "",
  adminUsersFilter: "all",
  inactivePolicy: { inactive_after_days: 90, inactive_purge_after_days: 30 },
  homeQ: "",
  homeCategory: "",
  timelineFavorite: false,
  timelineSecondary: false,
  timelinePlatform: "",
  timelineCategory: "",
  timelineTag: "",
  timelineQ: "",
};

function escapeHtml(text) {
  return String(text ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function imgProxyUrl(url) {
  return `/api/img-proxy?url=${encodeURIComponent(url)}`;
}

function imgOnError(img) {
  // 第三方图床直连失败（大陆访问 X 图床被墙等）→ 经服务端代理转发
  if (!img || img.dataset.proxied) return;
  const src = img.getAttribute("src") || "";
  if (src.startsWith("/api/img-proxy")) return;
  img.dataset.proxied = "1";
  img.src = imgProxyUrl(src);
  img.onerror = null;
}

// ---------- 图片灯箱（点击放大原图，背景变暗，多图可左右切换） ----------
let _lightboxImages = [];
let _lightboxIndex = 0;

function openLightbox(img) {
  if (!img) return;
  // 收集当前帖子（同一 .post-images 容器）里的全部图片，支持左右切换
  const container = img.closest(".post-images");
  if (container) {
    _lightboxImages = [...container.querySelectorAll("img")]
      .map((im) => im.currentSrc || im.src || "")
      .filter(Boolean);
  } else {
    _lightboxImages = [(img.currentSrc || img.src || "")].filter(Boolean);
  }
  if (!_lightboxImages.length) return;
  _lightboxIndex = Math.max(0, _lightboxImages.indexOf(img.currentSrc || img.src || ""));
  closeLightbox(); // 防重复打开
  const overlay = document.createElement("div");
  overlay.className = "lightbox";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "查看大图");
  overlay.innerHTML = `
    <button class="lightbox-close" aria-label="关闭" onclick="event.stopPropagation();closeLightbox()">✕</button>
    <img class="lightbox-img" src="${escapeHtml(_lightboxImages[_lightboxIndex])}" alt="" onerror="imgOnError(this)">
    ${_lightboxImages.length > 1 ? `
      <button class="lightbox-nav lightbox-prev" aria-label="上一张" onclick="event.stopPropagation();lightboxStep(-1)">‹</button>
      <button class="lightbox-nav lightbox-next" aria-label="下一张" onclick="event.stopPropagation();lightboxStep(1)">›</button>
      <span class="lightbox-count">${_lightboxIndex + 1} / ${_lightboxImages.length}</span>` : ""}`;
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeLightbox();
  });
  // 移动端滑动手势：左右滑动切换图片（与「点击遮罩关闭」的 tap 区分）
  overlay.addEventListener("touchstart", lightboxTouchStart, { passive: true });
  overlay.addEventListener("touchmove", lightboxTouchMove, { passive: false });
  overlay.addEventListener("touchend", lightboxTouchEnd, { passive: true });
  document.body.appendChild(overlay);
  document.body.classList.add("lightbox-open");
  document.addEventListener("keydown", lightboxKeyHandler);
}

let _lbTouchStart = null;

function lightboxTouchStart(e) {
  // 从箭头/关闭按钮上开始的滑动不拦截（按钮有自己的事件）
  if (e.target.closest(".lightbox-nav, .lightbox-close")) return;
  _lbTouchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY };
}

function lightboxTouchMove(e) {
  if (!_lbTouchStart) return;
  const dx = e.touches[0].clientX - _lbTouchStart.x;
  const dy = e.touches[0].clientY - _lbTouchStart.y;
  // 水平滑动占优时拦截：阻止页面滚动，也阻止松手后合成 click（避免误关灯箱）
  if (Math.abs(dx) > 10 && Math.abs(dx) > Math.abs(dy)) e.preventDefault();
}

function lightboxTouchEnd(e) {
  if (!_lbTouchStart) return;
  const dx = e.changedTouches[0].clientX - _lbTouchStart.x;
  const dy = e.changedTouches[0].clientY - _lbTouchStart.y;
  _lbTouchStart = null;
  if (Math.abs(dx) < 40 || Math.abs(dx) < Math.abs(dy) * 1.5) return; // 阈值：水平 40px 且明显占优
  lightboxStep(dx < 0 ? 1 : -1);
}

function lightboxStep(dir) {
  if (_lightboxImages.length < 2) return;
  _lightboxIndex = (_lightboxIndex + dir + _lightboxImages.length) % _lightboxImages.length;
  const img = document.querySelector(".lightbox-img");
  if (!img) return;
  img.style.opacity = "0";
  setTimeout(() => {
    img.src = _lightboxImages[_lightboxIndex];
    img.style.opacity = "";
    img.onerror = imgOnError;
    const count = document.querySelector(".lightbox-count");
    if (count) count.textContent = `${_lightboxIndex + 1} / ${_lightboxImages.length}`;
  }, 120); // 与淡出过渡衔接
}

function lightboxKeyHandler(e) {
  if (e.key === "Escape") closeLightbox();
  else if (e.key === "ArrowLeft") lightboxStep(-1);
  else if (e.key === "ArrowRight") lightboxStep(1);
}

function closeLightbox() {
  const overlay = document.querySelector(".lightbox");
  if (!overlay) return;
  overlay.classList.add("closing"); // 触发淡出+轻微缩小动画
  // 动画结束后移除 DOM；reduced-motion 下 animation 被禁用（animationend 不触发），用超时兜底
  const remove = () => overlay.remove();
  overlay.addEventListener("animationend", remove, { once: true });
  setTimeout(remove, 240); // 略大于关闭动画 200ms；reduced-motion 下 animationend 不触发时兜底
  document.body.classList.remove("lightbox-open");
  document.removeEventListener("keydown", lightboxKeyHandler);
}

let _toastTimer = null;
// 操作反馈统一走 toast：成功 flash(msg)，失败 flash(msg, "error")。绑定码等需停留的内容仍写在页面上。
function flash(message, type = "success") {
  let el = $("#toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.setAttribute("aria-live", "polite"); // 操作反馈对读屏可感知
    document.body.appendChild(el);
  }
  el.className = `toast ${type}`;
  el.textContent = message;
  el.classList.remove("hide");
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => {
    el.classList.add("hide");
    setTimeout(() => el.remove(), 320);
  }, 2600);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  const resp = await fetch(path, { ...options, headers });
  if (resp.status === 401) {
    logout();
    throw new Error("登录已过期，请重新登录");
  }
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) {
    // FastAPI 422 等校验错误的 detail 是数组/对象，直接拼接会显示 [object Object]
    const detail = data.detail;
    const msg = typeof detail === "string" ? detail : (detail ? JSON.stringify(detail) : resp.statusText);
    throw new Error(msg);
  }
  return data;
}

function clearSessionCaches() {
  if (typeof stopTimelinePoll === "function") stopTimelinePoll();
  _tlPosts.length = 0;
  _tlOffset = 0;
  _tlHasMore = true;
  _tlExpanded.clear();
  _tlLatestId = 0;
  _tlLoadedFilter = null;
  _tlSavedScrollY = 0;
  _tlPendingNew.length = 0;
  _tlPendingLatestId = 0;
  pendingBind = null;
  state.timelineQ = "";
  state.timelineCategory = "";
  state.timelineTag = "";
  state.timelinePlatform = "";
  state.timelineFavorite = false;
  state.timelineSecondary = false;
}

function logout() {
  state.token = "";
  state.user = null;
  localStorage.removeItem("dav_token");
  clearSessionCaches();
  location.hash = "#/timeline";
  $("#app-view").classList.add("hidden");
  $("#auth-view").classList.remove("hidden");
  resetAuthButtons();
}

function resetAuthButtons() {
  // 登录/注册提交中按钮会 disabled；登出或切换模式后恢复默认态
  const loginBtn = $("#login-form")?.querySelector('button[type="submit"]');
  const regBtn = $("#register-form")?.querySelector('button[type="submit"]');
  if (loginBtn) { loginBtn.disabled = false; loginBtn.textContent = "登 录"; }
  if (regBtn) { regBtn.disabled = false; regBtn.textContent = "创建账号"; }
}

function avatarText(name) {
  return (name || "?").trim().slice(0, 1).toUpperCase();
}

function avatarHtml(name, url) {
  if (url) return `<img class="kol-avatar" src="${escapeHtml(url)}" alt="" loading="lazy">`;
  return `<div class="kol-avatar">${escapeHtml(avatarText(name))}</div>`;
}

// ---------- 壳 ----------
const NAV = [
  { group: "订阅", items: [
    { route: "timeline", icon: LIST_ICON, label: "最新动态" },
    { route: "home", icon: GRID_ICON, label: "订阅广场" },
    { route: "combinations", icon: TRENDING_ICON, label: "组合订阅" },
    { route: "mysubs", icon: BOOKMARK_ICON, label: "我的订阅" },
    { route: "settings", icon: GEAR_ICON, label: "推送设置" },
  ]},
  { group: "", admin: true, subs: [
    { label: "内容管理", items: [
      { route: "admin/dashboard", icon: DASHBOARD_ICON, label: "全景概览" },
      { route: "admin/kols", icon: V_ICON, label: "大V管理" },
      { route: "admin/vocab", icon: FOLDER_ICON, label: "标签分类" },
      { route: "admin/requests", icon: USER_PLUS_ICON, label: "添加审批" },
    ]},
    { label: "数据与日志", items: [
      { route: "admin/stats", icon: BOOK_ICON, label: "数据源" },
      { route: "admin/posts", icon: FILE_TEXT_ICON, label: "帖子" },
      { route: "admin/logs", icon: SEND_ICON, label: "推送记录" },
      { route: "admin/audit", icon: HISTORY_ICON, label: "操作日志" },
      { route: "admin/backup", icon: DATABASE_ICON, label: "备份" },
    ]},
    { label: "用户与注册", items: [
      { route: "admin/users", icon: USERS_ICON, label: "用户" },
      { route: "admin/codes", icon: KEY_ICON, label: "注册码" },
    ]},
  ]},
];

function renderSidebar(user) {
  const navItemHtml = (item) => `
        <button class="nav-item" data-route="${item.route}" onclick="location.hash='#/${item.route}'">
          <span class="nav-icon">${item.icon}</span>
          <span class="nav-label">${item.label}</span>
        </button>`;
  const html = NAV.filter((g) => !g.admin || user.is_admin)
    .map((group) => `
      ${group.group ? `<div class="nav-group-label">${group.group}</div>` : ""}
      ${(group.items || []).map(navItemHtml).join("")}
      ${(group.subs || []).map((sub) => `
        <details class="nav-sub" open>
          <summary class="nav-sub-label">${sub.label}</summary>
          ${sub.items.map(navItemHtml).join("")}
        </details>`).join("")}
    `).join("");
  $("#sidebar-nav").innerHTML = html;
  $("#sidebar-user").innerHTML = `
    <div class="theme-switcher" id="theme-switcher"></div>
    <div class="sidebar-foot-links">
      <a id="sidebar-gh-link" class="sidebar-gh-link" href="https://github.com/icekale/vpush" target="_blank" rel="noopener" title="GitHub 项目">${GITHUB_ICON}</a>
      <span class="sidebar-user-meta" id="sidebar-version">v${APP_VERSION}</span>
    </div>
  `;
  renderThemeSwitcher();
  checkUpdate();
}

const MOBILE_NAV = [
  { route: "timeline", icon: LIST_ICON, label: "动态" },
  { route: "home", icon: GRID_ICON, label: "广场" },
  { route: "combinations", icon: TRENDING_ICON, label: "组合" },
  { route: "mysubs", icon: BOOKMARK_ICON, label: "订阅" },
  { route: "settings", icon: GEAR_ICON, label: "设置" },
];

function renderBottomNav(user) {
  const tabs = [...MOBILE_NAV];
  if (user.is_admin) tabs.push({ route: "more", icon: PLUS_ICON, label: "更多" });
  $("#bottom-nav").innerHTML = tabs.map((t) => `
    <button class="bnav-item" data-route="${t.route}" onclick="location.hash='#/${t.route}'">
      <span class="bnav-icon">${t.icon}</span>
      <span class="bnav-label">${t.label}</span>
    </button>`).join("");
}

async function renderMore(seq) {
  if (!state.user.is_admin) { location.hash = "#/timeline"; return; }
  setPageTitle("更多");
  const adminGroup = NAV.find((g) => g.admin) || { items: [], subs: [] };
  const adminItems = [
    ...(adminGroup.items || []),
    ...(adminGroup.subs || []).flatMap((s) => s.items || []),
  ];
  $("#main").innerHTML = `
    <section class="section-panel">
      <div class="more-grid">
        ${adminItems.map((item) => `
          <button class="more-item" onclick="location.hash='#/${item.route}'">
            <span class="more-icon">${item.icon}</span>
            <span class="more-label">${escapeHtml(item.label)}</span>
          </button>`).join("")}
      </div>
    </section>`;
}

async function checkUpdate() {
  try {
    const v = await api("/api/version");
    const link = $("#sidebar-gh-link");
    const meta = $("#sidebar-version");
    if (!link || !meta) return;
    // 始终显示服务端返回的当前版本，避免本地硬编码版本过期
    meta.innerHTML = `v${escapeHtml(v.current)}`;
    if (v.update_available && v.latest) {
      link.classList.add("has-update");
      meta.innerHTML += ` <a class="sidebar-update" href="${escapeHtml(v.url)}" target="_blank" rel="noopener" title="有新版本">↑ ${escapeHtml(v.latest)}</a>`;
    }
  } catch {
    /* 更新检查失败不打扰，保留本地硬编码版本兜底 */
  }
}

function renderTopbar(user) {
  $("#topbar-user").innerHTML = `
    <button class="theme-toggle-btn" id="theme-toggle-btn" onclick="cycleTheme()" aria-label="切换主题" title="切换主题"></button>
    <div class="user-chip">
      <div class="user-avatar">${escapeHtml(avatarText(user.username))}</div>
      <div class="user-meta">
        <span class="user-name">${escapeHtml(user.username)}</span>
        <span class="user-role">${user.is_admin ? "管理员" : "订阅用户"}</span>
      </div>
    </div>
    <button class="topbar-logout" onclick="logout()">退出</button>`;
  updateThemeToggleIcon();
}

function setPageTitle(title, back = false) {
  $("#page-title").textContent = title;
  $("#btn-back").classList.toggle("hidden", !back);
}

function emptyState(text, actionHtml = "") {
  return `<div class="empty">${escapeHtml(text)}${actionHtml}</div>`;
}

function homeHasFilters() {
  return !!(state.homeQ || state.homeCategory);
}

function homeToggleFilter() {
  const panel = $("#home-filter-panel");
  const btn = $("#home-filter-toggle");
  if (!panel || !btn) return;
  const open = panel.hasAttribute("hidden");
  panel.toggleAttribute("hidden", !open);
  btn.setAttribute("aria-expanded", String(open));
}

function homeMobilePlatformsHtml() {
  return TL_PLATFORMS.map(([p, label]) => {
    const short = platformShortLabel(p);
    return `
    <button class="tl-pill ${state.platform === p ? "selected" : ""}"
      data-platform="${p}" aria-label="${label}" title="${label}"
      role="radio" aria-checked="${state.platform === p}"
      onclick="homePickMobilePlatform('${p}')">
      ${PLATFORM_ICONS[p || ""]}<span>${short}</span>
    </button>`;
  }).join("");
}

async function homePickMobilePlatform(platform) {
  state.platform = platform;
  const platforms = $("#home-mobile-platforms");
  if (platforms) platforms.innerHTML = homeMobilePlatformsHtml();
  await loadHomeKols(routeRenderSeq);
}

async function homeResetFilters() {
  state.homeQ = state.homeCategory = state.platform = "";
  await renderHome(routeRenderSeq);
}

// ---------- 订阅广场 ----------
async function renderHome(seq) {
  setPageTitle("订阅广场");
  state.platform = "";
  const mobileHome = isMobileTimelineFilter();
  let onboardingHtml = "";
  if (state.user && !state.user.subscription_count) {
    try {
      const recs = await api("/api/recommendations");
      if (routeStillActive(seq) && recs.length) {
        onboardingHtml = `
          <section class="section-panel">
            <header class="section-head"><div>
              <h3 class="section-title">欢迎！先订阅几位大V</h3>
              <p class="section-meta">以下是最热门的大V；订阅后新帖会自动推送到你绑定的渠道。</p>
            </div></header>
            <div class="row" style="gap:12px;flex-wrap:wrap">${recs.map((rec) => `
              <div class="kol-item" style="flex:1;min-width:230px">
                ${avatarHtml(rec.name, rec.avatar_url)}
                <a class="kol-info" href="#/kol/${rec.id}">
                  <div class="base">
                    <span class="name">${escapeHtml(rec.name)}</span>
                    <span class="tag">${PLATFORM_LABELS[rec.platform] || escapeHtml(rec.platform)}</span>
                    ${rec.category_name ? `<span class="tag">${escapeHtml(rec.category_name)}</span>` : ""}
                  </div>
                  <div class="desc">${rec.subscriber_count} 人订阅</div>
                </a>
                <button class="btn-sub ${rec.subscribed ? "subscribed" : ""}" onclick="quickSubscribe(${rec.id}, this)">
                  ${rec.subscribed ? "✓ 已订阅" : "订阅"}
                </button>
              </div>`).join("")}
            </div>
            <p class="muted" style="margin-top:12px">也可以先去<a href="#/settings">绑定推送渠道</a>，再回来订阅。</p>
          </section>`;
      }
    } catch {
      /* 推荐加载失败不阻塞页面 */
    }
  }
  if (!routeStillActive(seq)) return; // 已切走：不写旧首页的 DOM
  $("#main").innerHTML = `
    ${onboardingHtml}
    <section class="section-panel home-panel">
      <header class="section-head home-head">
        <div>
          <h3 class="section-title">全部大V</h3>
          <p class="section-meta" id="catalog-meta">加载中…</p>
        </div>
        ${mobileHome ? `
          <div class="icon-badge-bar" id="home-mobile-bar">
            <div class="tl-pills" id="home-mobile-platforms" role="radiogroup" aria-label="平台">
              ${homeMobilePlatformsHtml()}
            </div>
            <button type="button" id="home-filter-toggle" class="fav-toggle ${homeHasFilters() ? "has-filter" : ""}" aria-label="筛选" aria-expanded="false" aria-controls="home-filter-panel" onclick="homeToggleFilter()">${FILTER_ICON}筛选</button>
          </div>
          <div class="home-filter-content" id="home-filter-panel" hidden>
            <div class="search-bar home-search-bar">
              ${SEARCH_ICON}
              <input id="home-search" placeholder="搜索昵称或 ID" value="${escapeHtml(state.homeQ || "")}" oninput="homeSearch(this.value)">
            </div>
            <div class="home-cats" id="home-cats"></div>
            <div class="home-filter-actions">
              <button class="btn-ghost" onclick="homeResetFilters()">清除筛选</button>
            </div>
          </div>` : `
          <div class="toolbar" style="margin-top:12px">
            <div class="search-bar" style="flex:1;min-width:220px">
              ${SEARCH_ICON}
              <input id="home-search" placeholder="搜索昵称或 ID，即时过滤" oninput="homeSearch(this.value)">
            </div>
            <div class="platform-tabs" id="platform-tabs"></div>
          </div>
          <div class="home-cats" id="home-cats"></div>`}
      </header>
      ${state.user?.is_admin ? "" : `
        <div class="request-banner">
          <div class="request-banner-icon">${PLUS_ICON}</div>
          <div class="request-banner-copy">
            <div class="title">想关注的大V不在列表里？</div>
            <div class="desc">提交申请，管理员审批通过后自动上架并通知你</div>
          </div>
          <button class="btn-normal" onclick="location.hash='#/search'">申请添加</button>
        </div>`}
      <div id="kol-list" class="kol-grid"></div>
    </section>`;
  renderPlatformTabs();
  await loadHomeKols(seq);
}

function renderPlatformTabs() {
  const tabs = $("#platform-tabs");
  if (tabs) tabs.innerHTML = PLATFORM_TABS.map((p) => platformTabHTML(p, state.platform, "switchPlatform")).join("");
}

function categoryChipsHtml() {
  const cats = [...new Set(state.catalog.map((k) => k.category_name || ""))].filter(Boolean).sort();
  const chip = (c, label) => `<button class="cat-chip ${state.homeCategory === c ? "selected" : ""}" data-cat="${escapeHtml(c)}" onclick="pickHomeCategory(this.dataset.cat)">${escapeHtml(label)}</button>`;
  return chip("", "全部分类") + cats.map((c) => chip(c, c)).join("");
}

function pickHomeCategory(cat) {
  state.homeCategory = cat;
  renderHomeList();
}

function homeSearch(v) {
  state.homeQ = v.trim();
  renderHomeList();
}

function homeFilteredKols() {
  const q = state.homeQ.toLowerCase();
  return state.catalog.filter((k) => {
    if (state.homeCategory && k.category_name !== state.homeCategory) return false;
    if (!q) return true;
    return (k.name || "").toLowerCase().includes(q) || (k.external_id || "").toLowerCase().includes(q);
  });
}

function renderHomeList() {
  $("#home-filter-toggle")?.classList.toggle("has-filter", homeHasFilters());
  const cats = $("#home-cats");
  if (cats) cats.innerHTML = categoryChipsHtml();
  const meta = $("#catalog-meta");
  if (meta) meta.textContent = `共 ${state.catalog.length} 位大V · 已订阅 ${state.catalog.filter((k) => k.subscribed).length} 位`;
  const list = homeFilteredKols();
  const target = $("#kol-list");
  if (!target) return; // 已离开首页（如正在加载时切走），不写不存在的 DOM
  target.innerHTML = list.length
    ? groupedKolCards(list)
    : emptyState(state.catalog.length ? "没有匹配的大V" : "暂无大V，管理员可在管理后台添加");
}

function platformTabHTML(p, current, handler) {
  const label = p ? PLATFORM_LABELS[p] : "全部";
  const short = platformShortLabel(p);
  return `<button class="platform-tab ${p === current ? "selected" : ""}" data-platform="${p || "all"}"
    title="${label}" aria-label="${label}"
    onclick="${handler}('${p}')">${PLATFORM_ICONS[p || ""]}<span class="pt-label">${short}</span></button>`;
}

let _homeKolsSeq = 0;
async function loadHomeKols(routeSeq) {
  const seq = ++_homeKolsSeq;
  let kols;
  try {
    const params = state.platform ? `?platform=${state.platform}` : "";
    kols = await api(`/api/catalog${params}`);
  } catch (err) {
    if (seq !== _homeKolsSeq || !routeStillActive(routeSeq)) return;
    const list = $("#kol-list");
    if (list) list.innerHTML = emptyState("加载失败: " + err.message);
    return;
  }
  // 平台已切换或已离开首页：不写全局状态也不写 DOM，避免旧目录覆盖当前页面
  if (seq !== _homeKolsSeq || !routeStillActive(routeSeq)) return;
  state.catalog = kols;
  renderHomeList();
}

function groupedKolCards(kols) {
  const groups = {};
  for (const kol of kols) {
    const key = kol.category_name || "";
    (groups[key] = groups[key] || []).push(kol);
  }
  return Object.entries(groups)
    .map(([name, items]) => `
      <div class="group-head">
        <span style="font-weight:600;color:var(--color-text-strong)">${escapeHtml(name || "未分类")}</span>
        <span class="g-count">${items.length} 位</span>
      </div>
      ${items.map(kolCard).join("")}`)
    .join("");
}

async function switchPlatform(platform) {
  state.platform = platform;
  renderPlatformTabs();
  await loadHomeKols(routeRenderSeq);
}

function kolCard(kol) {
  return `
    <div class="kol-card">
      <div class="kol-card-head">
        ${avatarHtml(kol.name, kol.avatar_url)}
        <div class="kol-card-info">
          <div class="base">
            <span class="name" title="${escapeHtml(kol.name)}">${escapeHtml(kol.name)}</span>
            <span class="tag">${PLATFORM_LABELS[kol.platform] || escapeHtml(kol.platform)}</span>
            ${kol.category_name ? `<span class="tag">${escapeHtml(kol.category_name)}</span>` : ""}
            ${kol.platform === "combination" && kol.quote && kol.quote.day_percent_gain != null ? `<span class="tag cube-day ${kol.quote.day_percent_gain >= 0 ? "up" : "down"}">${kol.quote.day_percent_gain >= 0 ? "+" : ""}${kol.quote.day_percent_gain.toFixed(2)}%</span>` : ""}
          </div>
          <div class="desc">外部 ID：${escapeHtml(kol.external_id)}${kol.enabled ? "" : " · 已停用"}</div>
        </div>
      </div>
      ${kol.subscribed && kol.platform === "xueqiu" ? `<div class="kol-card-subtype">${subTypeSwitchesHtml(kol.id, kol.subscribe_type || "post")}</div>` : ""}
      <div class="kol-card-actions">
        <button class="btn-sub ${kol.subscribed ? "subscribed" : ""}" onclick="toggleSubscribe(${kol.id}, this)">
          ${kol.subscribed ? "✓ 已订阅" : "订阅"}
        </button>
        ${kol.subscribed ? `<button class="fav-btn ${kol.favorite ? "fav-on" : ""}" onclick="toggleFavorite(${kol.id}, this)" title="特别关注：优先推送" aria-label="${kol.favorite ? "取消特别关注" : "设为特别关注"}">${STAR_SVG}</button>` : ""}
        ${kol.subscribed ? `<button class="fav-btn ${kol.secondary ? "sec-on" : "sec-off"}" onclick="toggleSecondary(${kol.id}, this)" title="次要：新帖合并进摘要推送（降频）" aria-label="${kol.secondary ? "取消次要" : "设为次要"}">${kol.secondary ? BELL_OFF_ICON : BELL_ICON}</button>` : ""}
        ${state.user?.is_admin ? `<button class="btn-sm danger kol-del" onclick="adminDeleteKolFromHome(${kol.id})" title="删除该大V" aria-label="删除该大V">${TRASH_ICON}</button>` : ""}
      </div>
    </div>`;
}

async function adminDeleteKolFromHome(kolId) {
  const kol = state.catalog.find((k) => k.id === kolId);
  if (!confirm(`确认删除该大V${kol ? `「${kol.name}」` : ""}？其订阅关系会一并移除。`)) return;
  try {
    await api(`/api/kols/${kolId}`, { method: "DELETE" });
    flash(`已删除「${kol ? kol.name : "该大V"}」`);
    await refreshKolsView(); // 按当前路由刷新，删除期间切走不会污染新页面
  } catch (err) {
    alert("删除失败: " + err.message);
  }
}

async function toggleSubscribe(kolId, btn) {
  const kol = state.catalog.find((k) => k.id === kolId);
  if (kol?.subscribed && !confirm(`取消订阅「${kol.name}」？将不再推送其新动态。`)) return;
  try {
    const wasSubscribed = kol ? kol.subscribed : btn.classList.contains("subscribed");
    if (wasSubscribed) {
      await api(`/api/subscriptions/${kolId}`, { method: "DELETE" });
    } else {
      await api("/api/subscriptions", { method: "POST", body: JSON.stringify({ kol_id: kolId, type: "post" }) });
    }
    flash(`已${wasSubscribed ? "退订" : "订阅"}「${kol ? kol.name : "该大V"}」`);
    if (kol) kol.subscribed = !wasSubscribed;
    await refreshKolsView();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function toggleFavorite(kolId, btn) {
  const kol = state.catalog.find((k) => k.id === kolId);
  const next = !(kol ? kol.favorite : false);
  try {
    await api(`/api/subscriptions/${kolId}/favorite`, {
      method: "PUT",
      body: JSON.stringify({ favorite: next }),
    });
    if (kol) kol.favorite = next;
    if (btn) btn.classList.toggle("fav-on", next);
    flash(next ? "已加星标" : "已取消星标");
    if (location.hash.startsWith("#/home")) renderHomeList();
    else if (location.hash.startsWith("#/mysubs")) renderMySubsList();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function toggleSecondary(kolId, btn) {
  const kol = state.catalog.find((k) => k.id === kolId);
  const next = !(kol ? kol.secondary : false);
  try {
    await api(`/api/subscriptions/${kolId}/secondary`, {
      method: "PUT",
      body: JSON.stringify({ secondary: next }),
    });
    if (kol) kol.secondary = next;
    if (btn) btn.classList.toggle("sec-on", next);
    flash(next ? "已设为次要（降频推送）" : "已取消次要");
    if (location.hash.startsWith("#/home")) renderHomeList();
    else if (location.hash.startsWith("#/mysubs")) renderMySubsList();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function quickSubscribe(kolId, btn) {
  try {
    await api("/api/subscriptions", { method: "POST", body: JSON.stringify({ kol_id: kolId, type: "post" }) });
    btn.classList.add("subscribed");
    btn.textContent = "✓ 已订阅";
    btn.disabled = true;
    state.user.subscription_count = (state.user.subscription_count || 0) + 1;
    loadHomeKols(routeRenderSeq); // 订阅后重拉 catalog，已订阅置顶即时生效
  } catch (err) {
    alert("订阅失败: " + err.message);
  }
}

async function refreshKolsView() {
  // 发起前捕获当前路由令牌；完成后再写 DOM，避免局部刷新覆盖已切走的新路由
  const seq = routeRenderSeq;
  const hash = location.hash;
  if (hash.startsWith("#/home")) await loadHomeKols(seq); // 重拉 catalog，已订阅置顶即时生效
  else if (hash.startsWith("#/combinations")) await renderCombinations(seq);
  else if (hash.startsWith("#/mysubs")) await renderMySubs(seq);
  else if (hash.startsWith("#/kol/")) await renderKolPage(Number(hash.split("/")[2] || 0), seq);
  else if (hash.startsWith("#/search")) doSearch(seq);
}

function subTypeSwitchesHtml(kolId, current) {
  const cur = current || "post";
  const postOn = cur !== "reply";
  const replyOn = cur !== "post";
  return `
    <div class="sub-type-switches" data-kol="${kolId}">
      <label class="sub-type-switch">
        <input type="checkbox" ${postOn ? "checked" : ""} onchange="setSubscribeType(${kolId}, this)">
        <span>帖子</span>
      </label>
      <label class="sub-type-switch">
        <input type="checkbox" ${replyOn ? "checked" : ""} onchange="setSubscribeType(${kolId}, this)">
        <span>回复</span>
      </label>
    </div>`;
}

async function setSubscribeType(kolId, input) {
  const box = input.closest(".sub-type-switches");
  const boxes = box.querySelectorAll('input[type="checkbox"]');
  const postOn = boxes[0].checked;
  const replyOn = boxes[1].checked;
  if (!postOn && !replyOn) {
    input.checked = true; // 至少保留一种类型；取消订阅请点「已订阅」主按钮
    alert("请至少保留一种订阅类型；取消订阅请点「已订阅」按钮");
    return;
  }
  const type = postOn && replyOn ? "both" : postOn ? "post" : "reply";
  try {
    await api(`/api/subscriptions/${kolId}`, { method: "PUT", body: JSON.stringify({ type }) });
    const kol = state.catalog.find((k) => k.id === kolId);
    if (kol) {
      kol.subscribed = true;
      kol.subscribe_type = type;
    }
  } catch (err) {
    alert("切换订阅类型失败: " + err.message);
    refreshKolsView();
  }
}

// ---------- 我的订阅 / 动态 ----------
async function renderMySubs(seq) {
  setPageTitle("我的订阅");
  const mobileFilter = isMobileTimelineFilter();
  $("#main").innerHTML = `
    <section class="section-panel${mobileFilter ? " home-panel" : ""}">
      <header class="section-head home-head">
        <div>
          <h3 class="section-title">已订阅</h3>
        </div>
      </header>
      <div class="toolbar" style="margin:12px 0 16px">
        <div class="${mobileFilter ? "icon-badge-bar mysubs-mobile-filters" : "platform-tabs"}" id="mysubs-tabs"></div>
        ${mobileFilter ? "" : `<button id="mysubs-fav-toggle" class="fav-toggle ${state.mysubsFavorite ? "fav-on" : ""}" onclick="toggleMySubsFav()">${STAR_SVG} 特别关注</button>`}
      </div>
      <div id="mysubs-list" class="kol-grid"></div>
    </section>`;
  try {
    const subs = await api("/api/my/subscriptions");
    if (!routeStillActive(seq)) return; // 已切走：不写旧页面数据
    state.catalog = subs.map((k) => ({ ...k, subscribed: true }));
    renderMySubsTabs();
    renderMySubsList();
  } catch (err) {
    if (!routeStillActive(seq)) return;
    $("#mysubs-list").innerHTML = emptyState(err.message);
  }
}

function mysubsMobileFiltersHtml() {
  const platforms = TL_PLATFORMS.map(([p, label]) => {
    const short = platformShortLabel(p);
    return `
    <button class="tl-pill ${state.mysubsPlatform === p ? "selected" : ""}"
      data-platform="${p}"
      aria-label="${label}"
      title="${label}"
      role="radio"
      aria-checked="${state.mysubsPlatform === p}"
      onclick="switchMySubsPlatform('${p}')">
      ${PLATFORM_ICONS[p || ""]}<span>${short}</span>
    </button>`;
  }).join("");
  return `<div class="tl-pills" role="radiogroup" aria-label="平台">${platforms}</div>
    <button class="fav-toggle ${state.mysubsFavorite ? "fav-on" : ""}"
      aria-label="特别关注"
      aria-pressed="${state.mysubsFavorite}"
      onclick="toggleMySubsFav()">${STAR_SVG} 特别关注</button>`;
}

function renderMySubsTabs() {
  $("#mysubs-tabs").innerHTML = isMobileTimelineFilter()
    ? mysubsMobileFiltersHtml()
    : PLATFORM_TABS.map((p) => platformTabHTML(p, state.mysubsPlatform, "switchMySubsPlatform")).join("");
}

function switchMySubsPlatform(platform) {
  state.mysubsPlatform = platform;
  renderMySubsTabs();
  renderMySubsList();
}

function renderMySubsList() {
  let kols = state.catalog.filter(
    (k) => !state.mysubsPlatform || k.platform === state.mysubsPlatform
  );
  if (state.mysubsFavorite) {
    kols = kols.filter((k) => k.favorite);
  } else {
    kols = [...kols].sort((a, b) => (b.favorite ? 1 : 0) - (a.favorite ? 1 : 0));
  }
  // 同类别排在一起（组内保持星标优先/订阅顺序），未分类排最后
  kols = [...kols].sort((a, b) => (a.category_name ? 0 : 1) - (b.category_name ? 0 : 1));
  $("#mysubs-list").innerHTML = kols.length
    ? groupedKolCards(kols)
    : emptyState("这里还没有订阅", `<div><button class="btn-normal btn-add" onclick="location.hash='#/home'">去订阅广场看看</button></div>`);
}

function toggleMySubsFav() {
  state.mysubsFavorite = !state.mysubsFavorite;
  const btn = $("#mysubs-fav-toggle");
  if (btn) btn.classList.toggle("fav-on", state.mysubsFavorite);
  renderMySubsTabs(); // 移动端星标角标在 #mysubs-tabs 内，需重绘
  renderMySubsList();
}

async function renderCombinations(seq) {
  setPageTitle("组合订阅");
  $("#main").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div>
          <h3 class="section-title">雪球组合</h3>
          <p class="section-meta" id="combo-meta">加载中…</p>
        </div>
      </header>
      <div id="combo-list" class="kol-grid"></div>
    </section>`;
  try {
    const kols = await api("/api/catalog?platform=combination");
    if (!routeStillActive(seq)) return; // 已切走：不写旧页面数据
    state.catalog = kols;
    $("#combo-meta").textContent = `共 ${kols.length} 个组合`;
    $("#combo-list").innerHTML = kols.length
      ? kols.map(kolCard).join("")
      : emptyState(
          "还没有添加雪球组合",
          state.user?.is_admin
            ? `<div><button class="btn-normal btn-add" onclick="location.hash='#/admin/kols'">去管理后台添加</button></div>`
            : `<div><button class="btn-normal btn-add" onclick="location.hash='#/search'">申请添加 →</button></div>`
        );
  } catch (err) {
    if (!routeStillActive(seq)) return;
    $("#combo-list").innerHTML = emptyState(err.message);
  }
}

// ---------- 动态 ----------
let _tlSeq = 0;
const _tlPosts = [];
let _tlOffset = 0;
let _tlHasMore = true;
let _tlLoadingMore = false;
const _tlExpanded = new Set();
let _tlTags = null;
let _tlDynamicTags = [];
let _tlLatestId = 0;        // 当前已加载的最新帖 id，用于后台检测新帖
let _tlLoadedFilter = null; // 缓存列表对应的筛选条件快照
let _tlSavedScrollY = 0;    // 离开动态页时的滚动位置，切回时恢复
let _tlPendingNew = [];     // 轮询拉到的新帖（点提示条时直接插到列表顶部）
let _tlPendingLatestId = 0; // 已拉取的新帖中最新 id，轮询去重
let _tlRefreshing = false;  // 刷新锁：防止连点/并发 poll 重复插入新帖
let _tlPollTimer = null;    // 新帖轮询定时器
let _tlWideWatchBound = false; // 1280px 断点只绑一次，避免开关留在已隐藏的栏里

function tlFilterKey() {
  return JSON.stringify([
    state.timelineQ || "", state.timelinePlatform || "",
    state.timelineCategory || "", state.timelineTag || "", state.timelineFavorite,
    state.timelineSecondary,
  ]);
}

// 生效筛选条件 → 可见 chip 列表：用户随时能看到自己被什么过滤着，逐个可移除
// label 直接存已转义文本（escapeHtml 在构造行完成，渲染处不再重复转义）
function tlPanelFilterOn() {
  return !!(state.timelineQ || state.timelineTag);
}

function tlActiveChips() {
  const chips = [];
  if (state.timelineQ) chips.push({ key: "q", label: `关键词：${escapeHtml(state.timelineQ)}` });
  if (state.timelineTag) chips.push({ key: "tag", label: `标签：${escapeHtml(state.timelineTag)}` });
  return chips;
}

function tlActiveChipsHtml() {
  const chips = tlActiveChips();
  if (!chips.length) return "";
  return `<div class="tl-active-chips">${chips.map((c) => `
    <span class="tl-active-chip">${c.label}<button class="tl-chip-x" onclick="tlRemoveFilter('${c.key}')" aria-label="移除${c.label}" title="移除该筛选">${X_ICON}</button></span>`).join("")}</div>`;
}

function tlRemoveFilter(key) {
  if (key === "q") state.timelineQ = "";
  else if (key === "tag") {
    state.timelineTag = "";
    const tagSel = $("#tl-tag");
    if (tagSel) tagSel.value = "";
  }
  loadTimeline(true, routeRenderSeq);
  renderRailTags(_tlDynamicTags.slice(0, 8));
}

const TL_SKELETON = `<div class="tl-skeleton">${Array(4).fill(`
    <div class="tl-sk-item">
      <div class="tl-sk-avatar"></div>
      <div class="tl-sk-lines">
        <div class="tl-sk-line" style="width:42%"></div>
        <div class="tl-sk-line" style="width:96%"></div>
        <div class="tl-sk-line" style="width:74%"></div>
      </div>
    </div>`).join("")}
  </div>`;


function isMobileTimelineFilter() {
  return window.matchMedia("(max-width: 768px)").matches;
}

function isWideTimeline() {
  return window.matchMedia("(min-width: 1280px)").matches;
}

function ensureWideTimelineWatch() {
  if (_tlWideWatchBound) return;
  _tlWideWatchBound = true;
  window.matchMedia("(min-width: 1280px)").addEventListener("change", () => {
    if ($("#tl-feed-panel")) renderTimeline(routeRenderSeq);
  });
}

function tlViewTogglesHtml() {
  return `
          <button id="timeline-fav-toggle" class="fav-toggle ${state.timelineFavorite ? "fav-on" : ""}" aria-pressed="${state.timelineFavorite}" onclick="toggleTimelineFav()">${STAR_SVG} 特别关注</button>
          <button id="timeline-secondary-toggle" class="fav-toggle ${state.timelineSecondary ? "fav-on" : ""}" aria-pressed="${state.timelineSecondary}" onclick="toggleTimelineSecondary()" title="显示/隐藏次要大V动态（默认隐藏）">${state.timelineSecondary ? EYE_ICON : EYE_OFF_ICON} 次要大V</button>`;
}

function tlSearchBarHtml() {
  return `<div class="search-bar tl-rail-search">
      ${SEARCH_ICON}
      <input id="tl-q" type="search" placeholder="搜索动态" value="${escapeHtml(state.timelineQ || "")}" aria-label="搜索动态" onkeydown="if(event.key==='Enter')tlApplyRailSearch()">
    </div>`;
}

function tlApplyRailSearch() {
  tlApplyFilter();
}

async function renderTimeline(seq) {
  setPageTitle("最新动态");
  ensureWideTimelineWatch();
  // 离开期间筛选条件未变且有缓存 → 直接恢复列表并检测新帖，不重新加载（保留阅读位置）
  const reuse = _tlPosts.length && _tlLoadedFilter === tlFilterKey();
  const wide = isWideTimeline();
  $("#main").innerHTML = `
    <div class="tl-layout">
    <div class="tl-main">
    <div class="tl-filterbar" id="tl-filterbar">
      <div class="tl-filterbar-top icon-badge-bar">
        <div class="tl-pills" id="tl-pills" role="radiogroup" aria-label="平台">${tlPillsHtml()}</div>
        ${wide ? "" : `<div class="tl-actions">
          <button id="tl-filter-toggle" class="fav-toggle ${tlPanelFilterOn() ? "has-filter" : ""}" aria-label="筛选" aria-expanded="false" aria-controls="tl-filter-panel" onclick="tlFilterPanel()">${FILTER_ICON}筛选</button>
        </div>`}
      </div>
      ${wide ? "" : `<div class="tl-filter-panel" id="tl-filter-panel">
        ${tlSearchBarHtml()}
        <div class="tl-filter-views">${tlViewTogglesHtml()}</div>
        <div class="tl-filter-row">
          <select id="tl-tag" class="form-control" onchange="tlApplyFilter()"><option value="">全部标签</option></select>
        </div>
        <div class="tl-filter-actions">
          <button class="btn-ghost" onclick="tlResetFilters()">清除筛选</button>
          <button class="btn-normal" onclick="tlApplyFilter()">完成</button>
        </div>
      </div>`}
      <div class="tl-new-badge" id="tl-new-badge">
        <button class="tl-new-badge-btn" onclick="refreshTimeline()" aria-label="有新动态，点击查看">
          ${ARROW_UP_ICON}
          <span class="tl-badge-avatars" id="tl-new-avatars"></span>
          已发布
        </button>
      </div>
    </div>
    <div id="tl-active-chips-wrap">${tlActiveChipsHtml()}</div>
    <section class="section-panel tl-feed-panel" id="tl-feed-panel">
      <div id="feed">${reuse ? "" : TL_SKELETON}</div>
    </section>
    </div>
    ${wide ? `<aside class="tl-rail" id="tl-rail" aria-label="发现">
      <div class="tl-rail-head">${tlSearchBarHtml()}</div>
      <div class="tl-rail-body">
        <div class="tl-rail-card tl-rail-view">${tlViewTogglesHtml()}</div>
        <div id="tl-rail-recs"></div>
        <div id="tl-rail-tags"></div>
      </div>
    </aside>` : ""}
    </div>`;
  if (reuse) {
    renderTimelineFeed();
    window.scrollTo(0, _tlSavedScrollY); // 恢复离开时的阅读位置
    startTimelinePoll();
    pollNewPosts(); // 后台检测新帖，有则浮出提示条
    if (!wide) loadTimelineTags().catch(() => { _tlTags = []; _tlDynamicTags = []; });
    if (wide) loadTimelineRail(seq);
    return;
  }
  _tlPosts.length = 0;
  _tlOffset = 0;
  _tlHasMore = true;
  _tlLatestId = 0;
  try {
    if (!wide) {
      await loadTimelineTags().catch(() => { _tlTags = []; _tlDynamicTags = []; }); // 标签下拉失败降级，不阻塞 feed
    }
    await loadTimeline(true, seq);
    if (wide) loadTimelineRail(seq);
    startTimelinePoll();
    pollNewPosts(); // 首屏就绪后立即查一次新帖
  } catch (err) {
    if (!routeStillActive(seq)) return;
    const feed = $("#feed");
    if (feed) feed.innerHTML = emptyState("加载失败: " + err.message,
      `<div><button class="btn-normal" onclick="renderTimeline()">重试</button></div>`);
  }
}

function startTimelinePoll() {
  stopTimelinePoll();
  _tlPollTimer = setInterval(pollNewPosts, 60000); // X 式：约每分钟静默查一次新帖，计数实时更新
}
function stopTimelinePoll() {
  if (_tlPollTimer) { clearInterval(_tlPollTimer); _tlPollTimer = null; }
}

async function pollNewPosts() {
  // X 式新帖检测：按 since_id 只拉新帖，缓存到 _tlPendingNew；胶囊显示「已发布」，条数写在 aria-label
  if (!_tlLatestId || !$("#feed")) return;
  const seq = routeRenderSeq;
  try {
    const params = new URLSearchParams({ limit: "50", since_id: String(_tlPendingLatestId || _tlLatestId) });
    if (state.timelineQ) params.set("q", state.timelineQ);
    if (state.timelinePlatform) params.set("platform", state.timelinePlatform);
    if (state.timelineCategory) params.set("category_id", state.timelineCategory);
    if (state.timelineTag) params.set("tag", state.timelineTag);
    if (state.timelineFavorite) params.set("favorite", "1");
    if (state.timelineSecondary) params.set("include_secondary", "1");
    const posts = await api(`/api/my/feed?${params}`);
    if (!routeStillActive(seq) || !$("#feed")) return;
    const newer = posts.filter((p) => p.id > _tlPendingLatestId);
    if (!newer.length) return;
    // 并发轮询/点击补拉可能重叠：pending 按 id 去重后再累加
    const have = new Set(_tlPendingNew.map((p) => p.id));
    for (const p of newer) {
      if (!have.has(p.id)) {
        have.add(p.id);
        _tlPendingNew.push(p);
      }
    }
    _tlPendingLatestId = Math.max(_tlPendingLatestId, ...newer.map((p) => p.id));
    const label = `${_tlPendingNew.length} 条新动态，点击查看`;
    const btn = $(".tl-new-badge-btn");
    if (btn) {
      btn.title = label;
      btn.setAttribute("aria-label", label);
    }
    const avatars = $("#tl-new-avatars");
    if (avatars) avatars.innerHTML = tlBadgeAvatarsHtml(_tlPendingNew);
    const badge = $("#tl-new-badge");
    if (badge) badge.classList.add("show");
    $("#tl-feed-panel")?.classList.add("has-new");
  } catch { /* 新帖检测失败静默 */ }
}

// 新帖胶囊头像：去重取前 3 个（无头像用首字色块）；超出的作者不另画 +N，条数只在 aria-label
function tlBadgeAvatarsHtml(posts, max = 3) {
  const seen = new Set();
  const avs = [];
  for (const p of posts) {
    const key = p.kol_id || p.kol_name;
    if (seen.has(key)) continue;
    seen.add(key);
    if (avs.length >= max) break;
    avs.push(p.avatar_url
      ? `<img src="${escapeHtml(p.avatar_url)}" alt="" onerror="this.remove()">`
      : `<span class="ph">${escapeHtml(avatarText(p.kol_name))}</span>`);
  }
  return avs.join("");
}

async function refreshTimeline() {
  if (_tlRefreshing) return; // 连点/并发：已有刷新在飞则忽略
  _tlRefreshing = true;
  try {
    if (!_tlPendingNew.length) {
      // 兜底：无缓存新帖时全量刷新
      await loadTimeline(true, routeRenderSeq);
      window.scrollTo({ top: 0, behavior: "smooth" });
      return;
    }
    // 先补拉一次最新：覆盖「提示条出现后又有新帖」的窗口，点击即刷新到真正最新状态
    await pollNewPosts();
    const badge = $("#tl-new-badge");
    // 与已渲染列表按 id 去重后插入：多批轮询累积（含并发重叠）统一按 id 倒序
    const seen = new Set(_tlPosts.map((p) => p.id));
    const incoming = _tlPendingNew.filter((p) => !seen.has(p.id)).sort((a, b) => b.id - a.id);
    if (incoming.length) {
      _tlPosts.unshift(...incoming);
      _tlOffset += incoming.length; // 新帖进了 DB 顶部，offset 分页要同步后移
      _tlLatestId = Math.max(_tlLatestId, _tlPendingLatestId);
      _tlPendingNew = [];
      _tlPendingLatestId = 0;
      renderTimelineFeed();
    }
    if (badge) badge.classList.remove("show");
    $("#tl-feed-panel")?.classList.remove("has-new");
    window.scrollTo({ top: 0, behavior: "smooth" });
  } finally {
    _tlRefreshing = false;
  }
}

function tlPillsHtml() {
  return TL_PLATFORMS.map(([p, label]) => {
    const selected = state.timelinePlatform === p;
    const short = platformShortLabel(p);
    return `
    <button class="tl-pill ${selected ? "selected" : ""}" role="radio" data-platform="${p}" aria-label="${label}" title="${label}" aria-checked="${selected}" onclick="tlPickPlatform('${p}')">
      ${PLATFORM_ICONS[p || ""]}
      <span>${short}</span>
    </button>`;
  }).join("");
}

function tlPickPlatform(p) {
  const prev = state.timelinePlatform;
  state.timelinePlatform = p;
  const pills = $("#tl-pills");
  if (pills) pills.innerHTML = tlPillsHtml();
  const btn = $("#tl-filter-toggle");
  if (btn) btn.classList.toggle("has-filter", tlPanelFilterOn());
  tlSyncActiveChips();
  loadTimeline(true, routeRenderSeq, { revertPlatform: prev });
}

function tlSyncActiveChips() {
  const wrap = $("#tl-active-chips-wrap");
  if (wrap) wrap.innerHTML = tlActiveChipsHtml();
}

function tlFilterPanel() {
  const bar = $("#tl-filterbar");
  if (!bar) return;
  const open = bar.classList.toggle("open");
  const btn = $("#tl-filter-toggle");
  if (btn) btn.setAttribute("aria-expanded", String(open));
  if (open) $("#tl-q")?.focus();
}

function tlApplyFilter() {
  const q = $("#tl-q");
  if (q) state.timelineQ = q.value.trim();
  const tag = $("#tl-tag");
  if (tag) state.timelineTag = tag.value;
  state.timelineCategory = "";
  $("#tl-filterbar")?.classList.remove("open");
  const btn = $("#tl-filter-toggle");
  if (btn) {
    btn.classList.toggle("has-filter", tlPanelFilterOn());
    btn.setAttribute("aria-expanded", "false");
  }
  tlSyncActiveChips();
  loadTimeline(true, routeRenderSeq);
}

function tlResetFilters() {
  state.timelineQ = "";
  state.timelineCategory = "";
  state.timelineTag = "";
  state.timelinePlatform = "";
  state.timelineFavorite = false;
  state.timelineSecondary = false;
  const q = $("#tl-q"); if (q) q.value = "";
  const tag = $("#tl-tag"); if (tag) tag.value = "";
  const pills = $("#tl-pills"); if (pills) pills.innerHTML = tlPillsHtml();
  const fb = $("#tl-filter-toggle"); if (fb) {
    fb.classList.remove("has-filter");
    fb.setAttribute("aria-expanded", "false");
  }
  const fav = $("#timeline-fav-toggle"); if (fav) {
    fav.classList.remove("fav-on");
    fav.setAttribute("aria-pressed", "false");
  }
  const sec = $("#timeline-secondary-toggle"); if (sec) {
    sec.classList.remove("fav-on");
    sec.setAttribute("aria-pressed", "false");
  }
  $("#tl-filterbar")?.classList.remove("open");
  loadTimeline(true, routeRenderSeq);
  renderRailTags(_tlDynamicTags.slice(0, 8));
}

// 点击帖子标签直接进入该标签筛选（复用 timelineTag 状态与筛选条）
function tlPickTag(tag) {
  state.timelineTag = tag;
  const tagSel = $("#tl-tag");
  if (tagSel) tagSel.value = tag;
  const btn = $("#tl-filter-toggle");
  if (btn) {
    btn.classList.toggle("has-filter", tlPanelFilterOn());
  }
  tlSyncActiveChips();
  loadTimeline(true, routeRenderSeq);
  renderRailTags(_tlDynamicTags.slice(0, 8));
}

async function loadTimelineTags() {
  if (!_tlTags) {
    const data = await api("/api/tags");
    // 词表是对象数组（{tag, keywords}）+ 贴文实际出现的动态标签（含股票名），下拉合并去重
    const vocabTags = (Array.isArray(data?.tags) ? data.tags : [])
      .map((r) => (typeof r === "string" ? r : r.tag)).filter(Boolean);
    const dynamicTags = Array.isArray(data?.dynamic_tags) ? data.dynamic_tags : [];
    _tlDynamicTags = dynamicTags;
    _tlTags = [...new Set([...vocabTags, ...dynamicTags])];
  }
  const sel = $("#tl-tag");
  if (!sel) return;
  sel.innerHTML = `<option value="">全部标签</option>` + _tlTags.map((t) =>
    `<option value="${escapeHtml(t)}" ${state.timelineTag === t ? "selected" : ""}>${escapeHtml(t)}</option>`).join("");
}

async function loadTimelineRail(routeSeq) {
  if (!$("#tl-rail")) return;
  try {
    const recs = await api("/api/recommendations?unsubscribed=1");
    if (!routeStillActive(routeSeq) || !$("#tl-rail")) return;
    renderRailRecs(Array.isArray(recs) ? recs : []);
  } catch (err) {
    const el = $("#tl-rail-recs");
    if (el) el.innerHTML = railFailHtml("推荐关注", "推荐加载失败", err);
  }
  try {
    let tags = _tlDynamicTags;
    if (!_tlTags) {
      const data = await api("/api/tags");
      tags = Array.isArray(data?.dynamic_tags) ? data.dynamic_tags : [];
      _tlDynamicTags = tags;
    }
    if (!routeStillActive(routeSeq) || !$("#tl-rail")) return;
    renderRailTags((tags || []).slice(0, 8));
  } catch (err) {
    const el = $("#tl-rail-tags");
    if (el) el.innerHTML = railFailHtml("热门标签", "标签加载失败", err);
  }
}

function railFailHtml(title, lead, err) {
  const detail = err?.message ? `：${escapeHtml(err.message)}` : "";
  return `<section class="tl-rail-card">
      <h3 class="tl-rail-title">${escapeHtml(title)}</h3>
      <div class="tl-rail-fail">
        <p class="muted">${escapeHtml(lead)}${detail}</p>
        <button type="button" class="btn-ghost" onclick="loadTimelineRail(routeRenderSeq)">重试</button>
      </div>
    </section>`;
}

function renderRailRecs(recs) {
  const el = $("#tl-rail-recs");
  if (!el) return;
  const list = recs.filter((r) => !r.subscribed).slice(0, 4);
  if (!list.length) { el.innerHTML = ""; return; }
  el.innerHTML = `
    <section class="tl-rail-card">
      <h3 class="tl-rail-title">推荐关注</h3>
      ${list.map((r) => `
        <div class="tl-rail-rec">
          ${avatarHtml(r.name, r.avatar_url)}
          <div class="tl-rail-rec-info">
            <a class="tl-rail-rec-name" href="#/kol/${r.id}">${escapeHtml(r.name)}</a>
            <div class="tl-rail-rec-meta">${escapeHtml(PLATFORM_LABELS[r.platform] || r.platform)}${r.category_name ? " · " + escapeHtml(r.category_name) : ""}</div>
          </div>
          <button type="button"
            class="btn-ghost tl-rail-subscribe"
            data-subscribed="0"
            aria-label="订阅${escapeHtml(r.name)}"
            onclick="railToggleSubscribe(${r.id}, this)">
            <span class="tl-rail-subscribe-state">订阅</span>
            <span class="tl-rail-subscribe-action" aria-hidden="true">退订</span>
          </button>
        </div>`).join("")}
      <a class="tl-rail-more" href="#/search">显示更多</a>
    </section>`;
}

function renderRailTags(tags) {
  const el = $("#tl-rail-tags");
  if (!el) return;
  if (!tags.length) { el.innerHTML = ""; return; }
  el.innerHTML = `
    <section class="tl-rail-card">
      <h3 class="tl-rail-title">热门标签</h3>
      <div class="tl-rail-tags">${tags.map((t) => `
        <button type="button" class="tl-rail-tag ${state.timelineTag === t ? "selected" : ""}" data-tag="${escapeHtml(t)}" onclick="tlPickTag(this.dataset.tag)">${escapeHtml(t)}</button>`).join("")}</div>
    </section>`;
}

async function railToggleSubscribe(kolId, btn) {
  if (!btn || btn.disabled) return;
  const subscribed = btn.dataset.subscribed === "1";
  const name = btn.closest(".tl-rail-rec")?.querySelector(".tl-rail-rec-name")?.textContent || "该大V";
  const restoreFocus = document.activeElement === btn && btn.matches(":focus-visible");
  btn.disabled = true;
  btn.setAttribute("aria-busy", "true");
  try {
    if (subscribed) {
      await api(`/api/subscriptions/${kolId}`, { method: "DELETE" });
    } else {
      await api("/api/subscriptions", {
        method: "POST",
        body: JSON.stringify({ kol_id: kolId, type: "post" }),
      });
    }
    const nextSubscribed = !subscribed;
    btn.dataset.subscribed = nextSubscribed ? "1" : "0";
    btn.classList.toggle("subscribed", nextSubscribed);
    btn.setAttribute("aria-label", `${nextSubscribed ? "退订" : "订阅"}${name}`);
    btn.title = nextSubscribed ? "点击退订" : "";
    const stateLabel = btn.querySelector(".tl-rail-subscribe-state");
    if (stateLabel) stateLabel.textContent = nextSubscribed ? "✓ 已订阅" : "订阅";
    if (state.user) {
      const delta = nextSubscribed ? 1 : -1;
      state.user.subscription_count = Math.max(0, (state.user.subscription_count || 0) + delta);
    }
    flash(`已${nextSubscribed ? "订阅" : "退订"}「${name}」`);
  } catch (err) {
    flash(`${subscribed ? "退订" : "订阅"}「${name}」失败: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.removeAttribute("aria-busy");
    if (restoreFocus && btn.isConnected && document.activeElement === document.body) {
      btn.focus({ preventScroll: true });
    }
  }
}

async function loadTimeline(reset = true, routeSeq, opts) {
  opts = opts || {};
  if (!reset && _tlLoadingMore) return;
  if (!reset) _tlLoadingMore = true;
  const seq = ++_tlSeq;
  const pills = $("#tl-pills");
  if (reset) {
    const feed = $("#feed");
    if (feed) feed.innerHTML = TL_SKELETON;
    pills?.setAttribute("aria-busy", "true");
  }
  try {
    const params = new URLSearchParams({ limit: "50", offset: String(reset ? 0 : _tlOffset) });
    if (state.timelineQ) params.set("q", state.timelineQ);
    if (state.timelinePlatform) params.set("platform", state.timelinePlatform);
    if (state.timelineCategory) params.set("category_id", state.timelineCategory);
    if (state.timelineTag) params.set("tag", state.timelineTag);
    if (state.timelineFavorite) params.set("favorite", "1");
    if (state.timelineSecondary) params.set("include_secondary", "1");
    const posts = await api(`/api/my/feed?${params}`);
    // 条件改变、已离开动态页或路由已切换：丢弃过期响应
    if (seq !== _tlSeq || !$("#feed") || !routeStillActive(routeSeq)) return;
    if (reset) {
      _tlPosts.length = 0;
      _tlOffset = 0;
    }
    _tlPosts.push(...posts);
    _tlOffset += posts.length;
    _tlHasMore = posts.length >= 50;
    if (reset) {
      _tlLatestId = posts[0]?.id || 0; // 记录第一页最新帖 id，供新帖检测
      _tlLoadedFilter = tlFilterKey();
      _tlPendingNew = []; // 筛选/刷新变化后，旧缓存的新帖失效
      _tlPendingLatestId = 0;
      const badge = $("#tl-new-badge");
      if (badge) badge.classList.remove("show");
      $("#tl-feed-panel")?.classList.remove("has-new");
    }
    renderTimelineFeed();
  } catch (err) {
    if (seq !== _tlSeq || !$("#feed") || !routeStillActive(routeSeq)) return;
    if (reset && Object.prototype.hasOwnProperty.call(opts, "revertPlatform")) {
      state.timelinePlatform = opts.revertPlatform;
      if (pills) pills.innerHTML = tlPillsHtml();
    }
    $("#feed").innerHTML = emptyState("加载失败: " + err.message,
      `<div><button class="btn-normal" onclick="loadTimeline(true, routeRenderSeq)">重试</button></div>`);
  } finally {
    if (reset) pills?.removeAttribute("aria-busy");
    if (!reset) _tlLoadingMore = false;
  }
}

function timelineLoadMore() {
  if (_tlLoadingMore || !_tlHasMore) return;
  loadTimeline(false, routeRenderSeq);
}

function renderTimelineFeed() {
  const feed = $("#feed");
  if (!feed) return;
  const posts = _tlPosts;
  const grouped = new Map();
  for (const p of posts) {
    const bucket = feedDateBucket(p.published_at);
    if (!grouped.has(bucket)) grouped.set(bucket, []);
    grouped.get(bucket).push(p);
  }
  const html = [...grouped.entries()].map(([bucket, list], gi) => `
    <div class="tl-group">
      <div class="tl-group-head"><span>${escapeHtml(bucket)}</span>${gi === 0 ? `<span class="tl-group-count">已加载 ${_tlPosts.length} 条动态</span>` : ""}</div>
      ${list.map(postCard).join("")}
    </div>`).join("");
  const footer = _tlHasMore
    ? `<div class="toolbar tl-feed-more"><button class="btn-normal" onclick="timelineLoadMore()">加载更多</button></div>`
    : (posts.length ? `<p class="muted tl-feed-end">已加载全部</p>` : "");
  const hasFilter = state.timelineQ || state.timelinePlatform || state.timelineCategory || state.timelineTag;
  const emptyMsg = state.timelineFavorite && !hasFilter
    ? "还没有特别关注大V的动态"
    : (hasFilter ? "没有符合条件的动态" : "还没有订阅任何大V");
  const emptyAction = hasFilter
    ? `<div><button class="btn-normal" onclick="tlResetFilters()">清除筛选</button></div>`
    : `<div><button class="btn-normal btn-add" onclick="location.hash='#/home'">去订阅</button></div>`;
  feed.innerHTML = posts.length
    ? html + footer
    : emptyState(emptyMsg, emptyAction);
  tlSyncActiveChips();
}

function toggleTimelineFav() {
  state.timelineFavorite = !state.timelineFavorite;
  const btn = $("#timeline-fav-toggle");
  if (btn) {
    btn.classList.toggle("fav-on", state.timelineFavorite);
    btn.setAttribute("aria-pressed", String(state.timelineFavorite));
  }
  loadTimeline(true, routeRenderSeq);
}

function toggleTimelineSecondary() {
  // 次要大V开关：默认关闭（动态页隐藏次要大V），开启后显示其动态。
  // 图标随状态切换：隐藏 = 划线眼睛（不看），显示 = 睁眼（看）。
  state.timelineSecondary = !state.timelineSecondary;
  const btn = $("#timeline-secondary-toggle");
  if (btn) {
    btn.classList.toggle("fav-on", state.timelineSecondary);
    btn.setAttribute("aria-pressed", String(state.timelineSecondary));
    btn.innerHTML = `${state.timelineSecondary ? EYE_ICON : EYE_OFF_ICON} 次要大V`;
  }
  loadTimeline(true, routeRenderSeq);
}

function tlTogglePost(id) {
  if (_tlExpanded.has(id)) _tlExpanded.delete(id);
  else _tlExpanded.add(id);
  renderTimelineFeed();
}

// published_at 支持 "YYYY-MM-DD HH:MM(:SS)"（雪球）与 RFC2822（微博/X 存 GMT/+0000），
// 解析成 Date 后按本地时区展示；无法解析返回 null（回退原样显示）
function parsePublished(s) {
  const raw = String(s || "").trim();
  if (!raw) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/.exec(raw);
  if (m) return new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0));
  const d = new Date(raw); // RFC2822 等 JS 可解析格式（带时区偏移，正确换算本地时间）
  return isNaN(d.getTime()) ? null : d;
}

function fmtPublished(s) {
  const d = parsePublished(s);
  if (!d) return escapeHtml(s || "");
  const now = new Date();
  const p = (n) => String(n).padStart(2, "0");
  const sameDay = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  if (sameDay(d, now)) return `今天 ${p(d.getHours())}:${p(d.getMinutes())}`;
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (sameDay(d, yesterday)) return `昨天 ${p(d.getHours())}:${p(d.getMinutes())}`;
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日`;
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`;
}

function feedDateBucket(s) {
  const d = parsePublished(s);
  if (!d) return "更早";
  const now = new Date();
  const p = (n) => String(n).padStart(2, "0");
  const dateKey = (x) => `${x.getFullYear()}-${p(x.getMonth() + 1)}-${p(x.getDate())}`;
  const today = dateKey(now);
  const yesterday = dateKey(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1));
  const key = dateKey(d);
  if (key === today) return "今天";
  if (key === yesterday) return "昨天";
  // 今年内按具体日期分组（如 8月3日），跨年才归入「更早」
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1}月${d.getDate()}日`;
  return "更早";
}

function postCard(post) {
  const safeUrl = /^https?:\/\//i.test(post.url || "") ? post.url : "#";
  const body = post.content || "（无正文）";
  const expanded = _tlExpanded.has(post.id);
  const shown = expanded ? body : body.slice(0, 200);
  // X 帖常 title==content（如纯链接帖），标题和正文都渲染会视觉重复，跳过标题；
  // 长文帖 title 常为 content 开头一段（截断），同样跳过避免重复展示
  const titleDup = !!post.title && (
    post.title.trim() === (post.content || "").trim()
    || (post.content || "").trimStart().startsWith(post.title.trim())
  );
  return `
    <div class="post-item">
      <div class="p-header">
        ${avatarHtml(post.kol_name, post.avatar_url)}
        <div class="p-name-line">
          <a class="p-name" href="#/kol/${post.kol_id}" title="${escapeHtml(post.kol_name)}">${escapeHtml(post.kol_name)}</a>
          <span class="p-platform" data-platform="${escapeHtml(post.platform)}" title="${escapeHtml(PLATFORM_LABELS[post.platform] || post.platform)}">
            ${PLATFORM_ICONS[post.platform] || ""}
          </span>
          <span class="p-time" title="${escapeHtml(post.published_at)}">${fmtPublished(post.published_at)}</span>
        </div>
      </div>
      ${!titleDup && post.title ? `<div class="p-title">${escapeHtml(post.title)}</div>` : ""}
      <div class="p-content">${escapeHtml(shown)}${body.length > 200
        ? `<button class="post-expand-btn" onclick="tlTogglePost(${post.id})" aria-expanded="${expanded}">${expanded ? "收起 ▲" : "展开全文 ▼"}</button>`
        : ""}</div>
      ${Array.isArray(post.images) && post.images.length ? `
        <div class="post-images">
          ${post.images.slice(0, 4).map((img) => `
            <a class="post-img-link" href="#" onclick="event.preventDefault();openLightbox(this.querySelector('img'))" aria-label="查看大图"><img src="${escapeHtml(img)}" loading="lazy" alt="" onerror="imgOnError(this)"></a>`).join("")}
          ${post.images.length > 4 ? `<span class="post-images-more">+${post.images.length - 4}</span>` : ""}
        </div>` : ""}
      <div class="p-meta">
        ${post.category_name ? `<span class="cat">${escapeHtml(post.category_name)}</span>` : ""}
        ${post.post_type === "reply" ? `<span class="cat">回复</span>` : ""}
        ${Array.isArray(post.tags) && post.tags.length
          ? post.tags.map((t) => `<button type="button" class="cat cat-tag post-tag-filter" data-tag="${escapeHtml(t)}" onclick="tlPickTag(this.dataset.tag)">${escapeHtml(t)}</button>`).join("")
          : ""}
        <a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener">查看原文 →</a>
      </div>
    </div>`;
}

// ---------- 搜索 ----------
async function renderSearch(seq) {
  setPageTitle("搜索", true);
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const query = params.get("q") || "";
  $("#main").innerHTML = `
    <section class="section-panel">
      <div class="search-bar" style="margin-bottom:16px">
        ${SEARCH_ICON}
        <input id="search-input" placeholder="输入昵称或 ID，回车搜索" value="${escapeHtml(query)}" onkeydown="if(event.key==='Enter')doSearch(routeRenderSeq)">
        <button class="btn-ghost" onclick="doSearch(routeRenderSeq)">搜索</button>
      </div>
      <div id="search-result" class="kol-grid">${emptyState("加载中…")}</div>
    </section>`;
  if (!state.user?.is_admin) {
    let cats = [];
    try { cats = await api("/api/categories"); } catch (err) { cats = []; }
    if (!routeStillActive(seq)) return;
    const catOptions = cats.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
    const askSection = document.createElement("div");
    askSection.innerHTML = `
      <section class="section-panel">
        <header class="section-head">
          <div><h3 class="section-title">申请添加大V</h3>
          <p class="section-meta">目录里没有的大V？提交申请，管理员审批通过后即可订阅。</p></div>
        </header>
        <div class="toolbar" style="margin-top:12px">
          <select id="ask-platform" class="form-control" style="margin:0;width:auto">
            <option value="xueqiu">雪球</option>
            <option value="combination">雪球组合</option>
            <option value="weibo">微博</option>
            <option value="twitter">X</option>
          </select>
          <select id="ask-category" class="form-control" style="margin:0;width:auto" aria-label="分类" required>
            <option value="">请选择分类</option>${catOptions}
          </select>
          <input id="ask-link" class="form-control" style="margin:0;flex:1;min-width:220px" placeholder="大V主页链接或 ID" oninput="onAskLinkInput()">
          <button class="btn-normal" onclick="submitAsk()">提交申请</button>
        </div>
        <div id="ask-result" class="muted" style="margin-top:12px"></div>
      </section>
      <section class="section-panel">
        <header class="section-head"><div><h3 class="section-title">我的申请</h3></div></header>
        <div id="my-asks"></div>
      </section>`;
    // 先取引用再 append：第一次 appendChild 会移动节点，children[1] 会随之失效
    const askPanel = askSection.firstElementChild;
    const myAskPanel = askSection.children[1];
    $("#main").appendChild(askPanel);
    $("#main").appendChild(myAskPanel);
    loadMyAsks(seq);
  }
  await doSearch(seq);
  if (!query && routeStillActive(seq)) $("#search-input")?.focus();
}



function detectAskPlatform(link) {
  // 与后端 _detect_platform_from_link 同规则：输入链接时自动甄别平台
  if (/(?:xueqiu\.com\/P\/|ZH\d)/.test(link)) return "combination";
  if (link.includes("xueqiu.com")) return "xueqiu";
  if (/weibo\.(com|cn)/.test(link)) return "weibo";
  if (/(^|[\/:.])x\.com|twitter\.com/.test(link)) return "twitter";
  return "";
}

function onAskLinkInput() {
  // 粘贴链接时自动甄别平台：识别出其他平台则自动切换下拉并提示
  const link = $("#ask-link").value.trim();
  const detected = detectAskPlatform(link);
  const sel = $("#ask-platform");
  if (!detected || !sel || sel.value === detected) return;
  sel.value = detected;
  showAskResult(`已识别为「${PLATFORM_LABELS[detected]}」主页链接，平台已自动切换`, false);
}

function showAskResult(msg, isError) {
  const el = $("#ask-result");
  if (!el) return;
  el.textContent = msg;
  el.classList.toggle("ask-error", !!isError);
  el.classList.toggle("ask-ok", !isError);
}

async function submitAsk() {
  const external_id = $("#ask-link").value.trim();
  const category_id = $("#ask-category") && $("#ask-category").value;
  if (!external_id) {
    showAskResult("请填写大V主页链接或 ID", true);
    return;
  }
  if (!category_id) {
    showAskResult("请选择分类", true);
    return;
  }
  try {
    await api("/api/kol-requests", {
      method: "POST",
      body: JSON.stringify({ platform: $("#ask-platform").value, external_id, category_id: Number(category_id) }),
    });
    $("#ask-link").value = "";
    showAskResult("已提交 ✅ 管理员审批通过后会自动出现在订阅广场", false);
    loadMyAsks();
  } catch (err) {
    showAskResult(err.message, true); // 后端返回具体的纠错提示（平台切换/链接格式）
  }
}

async function loadMyAsks(routeSeq) {
  try {
    const asks = await api("/api/my/kol-requests");
    if (!routeStillActive(routeSeq)) return; // 已切走：不写旧页面
    const statusMap = { pending: "待审批", approved: "已通过 ✅", rejected: "已拒绝" };
    $("#my-asks").innerHTML = asks.length
      ? `<div class="table-wrap"><table>
          <thead><tr><th scope="col">平台</th><th scope="col">外部 ID</th><th scope="col">分类</th><th scope="col">状态</th><th scope="col">提交时间</th></tr></thead>
          <tbody>${asks.map((a) => `
            <tr>
              <td>${PLATFORM_LABELS[a.platform] || escapeHtml(a.platform)}</td>
              <td>${escapeHtml(a.external_id)}</td>
              <td>${escapeHtml(a.category_name || "—")}</td>
              <td class="${a.status === "approved" ? "status-ok" : a.status === "rejected" ? "status-fail" : ""}">${statusMap[a.status] || escapeHtml(a.status)}</td>
              <td>${escapeHtml(fmtDbTime(a.created_at))}</td>
            </tr>`).join("")}</tbody>
        </table></div>`
      : emptyState("还没有提交过申请");
  } catch {
    /* 忽略加载失败 */
  }
}

async function doSearch(routeSeq) {
  const input = $("#search-input");
  if (!input) return;
  const keyword = input.value.trim().toLowerCase();
  try {
    const kols = await api("/api/catalog");
    if (!routeStillActive(routeSeq)) return;
    state.catalog = kols;
    const available = kols.filter((k) => !k.subscribed);
    const hits = keyword
      ? available.filter(
          (k) => (k.name || "").toLowerCase().includes(keyword)
            || (k.external_id || "").toLowerCase().includes(keyword)
        )
      : available;
    const target = $("#search-result");
    if (!target) return;
    target.innerHTML = hits.length
      ? hits.map(kolCard).join("")
      : emptyState(keyword ? "没有匹配的未订阅大V" : "所有大V都已订阅");
  } catch (err) {
    if (!routeStillActive(routeSeq)) return;
    const target = $("#search-result");
    if (target) target.innerHTML = emptyState("搜索失败: " + err.message);
  }
}

// ---------- 大V动态页 ----------
async function renderKolPage(kolId, seq) {
  setPageTitle("大V动态", true);
  $("#main").innerHTML = `<div class="empty">加载中…</div>`;
  try {
    const kol = await api(`/api/kols/${kolId}`);
    const posts = await api(`/api/kols/${kolId}/posts?limit=50`);
    if (!routeStillActive(seq)) return; // 已切走：不写旧页面
    const extra = kol.platform === "combination"
      ? await renderCombinationSnapshots(kol)
      : "";
    if (!routeStillActive(seq)) return;
    $("#main").innerHTML = `
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">${escapeHtml(kol.name)} · 最近动态</h3>
            <p class="section-meta">外部 ID：${escapeHtml(kol.external_id)} · ${PLATFORM_LABELS[kol.platform] || escapeHtml(kol.platform)}${kol.category_name ? " · " + escapeHtml(kol.category_name) : ""}</p>
          </div>
          <div class="toolbar" style="margin-top:12px">
            ${kol.subscribed && kol.platform === "xueqiu" ? subTypeSwitchesHtml(kol.id, kol.subscribe_type || "post") : ""}
            <button class="btn-sub ${kol.subscribed ? "subscribed" : ""}" id="kol-sub-btn" onclick="toggleKolPageSubscribe(${kol.id})">
              ${kol.subscribed ? "✓ 已订阅" : "订阅"}
            </button>
          </div>
        </header>
        ${extra}
        <div id="kol-posts">${posts.length ? posts.map(postCard).join("") : emptyState("暂无动态")}</div>
      </section>`;
  } catch (err) {
    if (!routeStillActive(seq)) return;
    $("#main").innerHTML = emptyState("加载失败: " + err.message);
  }
}

async function renderCombinationSnapshots(kol) {
  try {
    const [holdings, nav] = await Promise.all([
      api(`/api/kols/${kol.id}/holdings`),
      api(`/api/kols/${kol.id}/nav`),
    ]);
    const q = kol.quote || {};
    const quoteHtml = q.day_percent_gain != null || q.net_value != null ? `
      <div class="cube-quote">
        <div class="cube-quote-item"><span class="cube-quote-label">净值</span><span class="cube-quote-value">${q.net_value != null ? q.net_value.toFixed(3) : "—"}</span></div>
        <div class="cube-quote-item"><span class="cube-quote-label">今日涨跌</span><span class="cube-quote-value ${q.day_percent_gain != null ? (q.day_percent_gain >= 0 ? "up" : "down") : ""}">${q.day_percent_gain != null ? (q.day_percent_gain >= 0 ? "+" : "") + q.day_percent_gain.toFixed(2) + "%" : "—"}</span></div>
        ${kol.quote_at ? `<div class="cube-quote-item"><span class="cube-quote-label">快照</span><span class="cube-quote-value small">${escapeHtml(formatSnapshotTs(kol.quote_at))}</span></div>` : ""}
      </div>` : "";
    const rows = (holdings.holdings || []).map((h) => {
      const delta = h.prev != null && Math.abs(h.weight - h.prev) >= 0.01
        ? `${h.weight >= h.prev ? "+" : ""}${(h.weight - h.prev).toFixed(1)}`
        : "";
      return { ...h, delta };
    });
    if (holdings.cash != null) rows.push({ name: "现金", symbol: "CASH", weight: holdings.cash, delta: "" });
    const holdingsHtml = rows.length ? `
      <div class="cube-holdings">
        ${rows.map((h) => `
          <div class="cube-holding">
            <div class="cube-holding-head">
              <span class="cube-holding-name" title="${escapeHtml(h.symbol)}">${escapeHtml(h.name)}</span>
              <span class="cube-holding-weight">${h.weight}%${h.delta ? ` <em class="cube-holding-delta ${Number(h.delta) >= 0 ? "up" : "down"}">${h.delta}</em>` : ""}</span>
            </div>
            <div class="cube-weight-bar"><div class="cube-weight-fill" style="width:${Math.max(h.weight, 1)}%"></div></div>
          </div>`).join("")}
        ${holdings.updated_at ? `<p class="section-meta" style="margin-top:10px">持仓更新于 ${escapeHtml(formatSnapshotTs(holdings.updated_at))}</p>` : ""}
      </div>` : `<p class="section-meta">暂无持仓数据（订阅后自动抓取）</p>`;
    const navHtml = (nav.series || []).length >= 2 ? `
      <div class="cube-nav-head">
        <b>最新 ${nav.series[nav.series.length - 1].value}</b>
        <span class="section-meta">${escapeHtml(nav.series[nav.series.length - 1].date)}${(nav.benchmark || []).length >= 2 ? " · 对照沪深300" : ""}</span>
      </div>
      ${navChartSvg(nav.series, nav.benchmark)}` : `<p class="section-meta">暂无净值数据（订阅后自动抓取）</p>`;
    return `
      ${quoteHtml ? `<section class="section-panel"><h3 class="section-title">组合状态</h3>${quoteHtml}</section>` : ""}
      <section class="section-panel"><h3 class="section-title">当前持仓</h3>${holdingsHtml}</section>
      <section class="section-panel"><h3 class="section-title">净值走势</h3>${navHtml}</section>`;
  } catch (err) {
    return `<section class="section-panel"><p class="section-meta">组合数据加载失败：${escapeHtml(err.message)}</p></section>`;
  }
}

// 后端快照时间（UTC "YYYY-MM-DD HH:MM:SS"）转本地 "MM-DD HH:MM"
function formatSnapshotTs(ts) {
  const d = new Date(String(ts).replace(" ", "T") + "Z");
  if (isNaN(d.getTime())) return ts;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 净值曲线：手绘 SVG 折线（含渐变面积、网格、首/中/尾日期），A股红涨绿跌
function navChartSvg(series, benchmark) {
  const W = 640, H = 200, padL = 44, padR = 10, padT = 10, padB = 24;
  let cube = series;
  let bench = null;
  if (benchmark && benchmark.length >= 2) {
    const bm = Object.fromEntries(benchmark.map((p) => [p.date, p.value]));
    const aligned = series.filter((p) => bm[p.date] != null);
    if (aligned.length >= 2 && aligned[0].value && bm[aligned[0].date]) {
      const c0 = aligned[0].value;
      const b0 = bm[aligned[0].date];
      cube = aligned.map((p) => ({ date: p.date, value: p.value / c0 }));
      bench = aligned.map((p) => ({ date: p.date, value: bm[p.date] / b0 }));
    }
  }
  const vals = cube.map((p) => p.value).concat(bench ? bench.map((p) => p.value) : []);
  let min = Math.min(...vals);
  let max = Math.max(...vals);
  if (max - min < 1e-9) { max += 0.005; min -= 0.005; }
  const span = max - min;
  min -= span * 0.05;
  max += span * 0.05;
  const X = (i) => padL + (i / (cube.length - 1)) * (W - padL - padR);
  const Y = (v) => padT + (1 - (v - min) / (max - min)) * (H - padT - padB);
  const pts = cube.map((p, i) => `${X(i).toFixed(1)},${Y(p.value).toFixed(1)}`).join(" ");
  const up = series[series.length - 1].value >= series[0].value;
  const cssVar = up ? "--color-data-positive" : "--color-data-negative";
  const color = getComputedStyle(document.documentElement).getPropertyValue(cssVar).trim() || (up ? "#b05b63" : "#23714a");
  const muted = getComputedStyle(document.documentElement).getPropertyValue("--color-text-muted").trim() || "#6e6e73";
  const base = (H - padB).toFixed(1);
  const area = `M${X(0).toFixed(1)},${base} L${pts.replace(/ /g, " L")} L${X(cube.length - 1).toFixed(1)},${base} Z`;
  const grid = [0, 1, 2, 3].map((i) => {
    const v = min + ((max - min) * i) / 3;
    return `<line x1="${padL}" y1="${Y(v).toFixed(1)}" x2="${W - padR}" y2="${Y(v).toFixed(1)}" class="cube-nav-grid"/>`
      + `<text x="4" y="${(Y(v) + 3).toFixed(1)}" class="cube-nav-tick">${v.toFixed(3)}</text>`;
  }).join("");
  const first = cube[0], mid = cube[Math.floor(cube.length / 2)], last = cube[cube.length - 1];
  const benchLine = bench
    ? `<polyline points="${bench.map((p, i) => `${X(i).toFixed(1)},${Y(p.value).toFixed(1)}`).join(" ")}" fill="none" stroke="${muted}" stroke-width="1.5" stroke-dasharray="4 3" stroke-linejoin="round"/>`
    : "";
  return `<svg viewBox="0 0 ${W} ${H}" class="cube-nav-svg" role="img" aria-label="净值曲线">
    ${grid}
    <path d="${area}" fill="${up ? "var(--color-data-positive-soft)" : "var(--color-data-negative-soft)"}"/>
    ${benchLine}
    <polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <text x="${padL}" y="${H - 6}" class="cube-nav-date">${escapeHtml(first.date)}</text>
    <text x="${(padL + W - padR) / 2}" y="${H - 6}" text-anchor="middle" class="cube-nav-date">${escapeHtml(mid.date)}</text>
    <text x="${W - padR}" y="${H - 6}" text-anchor="end" class="cube-nav-date">${escapeHtml(last.date)}</text>
    <text x="${W - padR}" y="${(Y(last.value) - 5).toFixed(1)}" text-anchor="end" class="cube-nav-last" fill="${color}">${series[series.length - 1].value}</text>
  </svg>`;
}


async function toggleKolPageSubscribe(kolId) {
  await toggleSubscribe(kolId, $("#kol-sub-btn"));
}

// ---------- 推送设置 ----------
let settingsPollTimer = null;
let _kolImageSubscriptions = [];
const _kolImagePendingIds = new Set();
let _kolImageLoadGeneration = 0;
let _kolImageDataRevision = 0;
let _kolImageReloadNeeded = false;

function stopSettingsPoll() {
  if (settingsPollTimer) {
    clearInterval(settingsPollTimer);
    settingsPollTimer = null;
  }
}

async function reloadSettings() {
  stopSettingsPoll();
  await renderSettings(routeRenderSeq);
}

function feishuChannelBound(user) {
  return !!(user.feishu_open_id || user.feishu_chat_id || user.feishu_personal?.status === "active");
}

function channelStatusHtml(user) {
  const tg = user.telegram_chat_id;
  const tgCustom = user.custom_telegram_bot;
  const fsOpen = user.feishu_open_id;
  const fsChat = user.feishu_chat_id;
  const fsPersonal = user.feishu_personal || {};
  const fsPersonalActive = fsPersonal.status === "active";
  const wc = user.wecom_webhook;
  const bk = user.bark_key;
  const fsOk = !!(fsOpen && fsChat);
  const statusPill = (cls, text) => `<span class="channel-status ${cls}"><i class="dot"></i>${text}</span>`;
  return `
    <div class="channel-grid">
      <div class="channel-card" data-channel="telegram">
        <div class="channel-head">
          <span class="channel-title">${CHANNEL_ICONS.telegram}<b>Telegram${tgCustom ? ' <span class="tag">自建</span>' : ""}</b></span>
          ${statusPill(tg ? "status-ok" : "status-fail", tg ? "已绑定" : "未绑定")}
        </div>
        <p class="muted channel-desc">${tg ? (tgCustom ? "使用你自己的机器人推送" : "官方机器人推送已启用") : "按下方步骤操作"}</p>
        <div class="channel-actions">
          ${tg ? "" : `<div id="bind-result-telegram"></div>`}
          ${tg
            ? `<button class="channel-btn secondary" onclick="unbindChannel('${tgCustom ? "telegram_bot_token" : "telegram_chat_id"}')">解绑</button>`
            : `<button class="channel-btn primary" onclick="openBindGuide('custom-bots-bind')">去绑定</button>`}
        </div>
      </div>
      <div class="channel-card" data-channel="feishu">
        <div class="channel-head">
          <span class="channel-title">${CHANNEL_ICONS.feishu}<b>飞书${fsPersonalActive ? ' <span class="tag">个人</span>' : (fsOk ? ' <span class="tag">共享</span>' : "")}</b></span>
          ${fsPersonalActive ? statusPill("status-ok", "已绑定")
            : fsOk ? statusPill("status-ok", "已绑定")
            : fsPersonal?.status === "degraded" || fsPersonal?.status === "disabled"
              ? statusPill("status-warn", fsPersonal.status === "degraded" ? "已降级" : "已停用")
            : fsOpen ? statusPill("status-warn", "未完成")
            : statusPill("status-fail", "未绑定")}
        </div>
        <p class="muted channel-desc">
          ${fsPersonalActive ? `个人机器人推送已启用（免共享限频）${fsPersonal.app_id_masked ? " · " + escapeHtml(fsPersonal.app_id_masked) : ""}`
            : fsOk ? "共享机器人推送（不推荐，受限频影响）；建议升级个人机器人"
            : (fsOpen ? "已关联账号，请先在飞书私聊机器人发一条消息"
            : "推荐个人机器人：扫码自动创建，免共享限频")}
        </p>
        <div class="channel-actions">
          ${fsOpen || fsPersonalActive ? "" : `<div id="bind-result-feishu"></div>`}
          ${fsPersonalActive
            ? `<button class="channel-btn secondary" onclick="unbindChannel('feishu_personal')">解绑</button>`
            : fsOpen
              ? `<button class="channel-btn secondary" onclick="unbindChannel('feishu')">解绑</button>`
              : `<button class="channel-btn primary" onclick="openBindGuide('custom-bots-bind')">去绑定</button>`}
        </div>
      </div>
      <div class="channel-card" data-channel="wecom">
        <div class="channel-head">
          <span class="channel-title">${CHANNEL_ICONS.wecom}<b>企业微信</b></span>
          ${wc ? statusPill("status-ok", "已绑定") : statusPill("status-fail", "未绑定")}
        </div>
        <p class="muted channel-desc">${wc ? "群机器人推送已启用" : "在企业微信群添加群机器人，把 webhook 粘贴到下方输入框即可"}</p>
        <div class="channel-actions">
          ${wc
            ? `<button class="channel-btn secondary" onclick="unbindChannel('wecom')">解绑</button>`
            : `<button class="channel-btn primary" onclick="openBindGuide('wecom-bind')">去绑定</button>`}
        </div>
      </div>
      <div class="channel-card" data-channel="bark">
        <div class="channel-head">
          <span class="channel-title">${CHANNEL_ICONS.bark}<b>Bark</b></span>
          ${bk ? statusPill("status-ok", "已绑定") : statusPill("status-fail", "未绑定")}
        </div>
        <p class="muted channel-desc">${bk ? "iOS 推送已启用" : "iPhone 装 Bark App，把推送 key 粘贴到下方输入框即可"}</p>
        <div class="channel-actions">
          ${bk
            ? `<button class="channel-btn secondary" onclick="unbindChannel('bark')">解绑</button>`
            : `<button class="channel-btn primary" onclick="openBindGuide('bark-bind')">去绑定</button>`}
        </div>
      </div>
    </div>`;
}

async function refreshSettingsStatus() {
  try {
    const user = await api("/api/me");
    state.user = user;
    const el = $("#push-status");
    if (!el) {
      stopSettingsPoll();
      return;
    }
    el.innerHTML = channelStatusHtml(user);
    // 状态轮询会重绘卡片，把未过期的绑定码重新显示，避免刚生成的码被刷掉
    if (pendingBind && Date.now() < pendingBind.expiresAt) {
      renderBindResult(pendingBind.channel, pendingBind.code);
    } else if (pendingBind) {
      pendingBind = null;
    }
    if (user.telegram_chat_id && user.feishu_open_id && user.feishu_chat_id && user.wecom_webhook && user.bark_key) stopSettingsPoll();
  } catch {
    /* 轮询失败忽略 */
  }
}

async function renderSettings(seq) {
  setPageTitle("推送设置");
  try {
    state.user = await api("/api/me");
    if (!routeStillActive(seq)) return; // 已切走：不覆盖新路由的 state.user
    stopSettingsPoll();
    const guide = state.user.push_guide || {};
    const tgBot = guide.telegram_bot_username || "";
    const fsBot = guide.feishu_bot_name || "";
    const tgTarget = tgBot
      ? `<a href="https://t.me/${encodeURIComponent(tgBot)}" target="_blank" rel="noopener">@${escapeHtml(tgBot)}</a>`
      : "你的机器人";
    const fsTarget = fsBot ? `<b>${escapeHtml(fsBot)}</b>` : "你的机器人应用名";
    $("#main").innerHTML = `
      <div class="settings-tabs" role="tablist">
        <button class="settings-tab active" data-tab="push" onclick="switchSettingsTab('push')">推送设置</button>
        <button class="settings-tab" data-tab="bind" onclick="switchSettingsTab('bind')">渠道绑定</button>
        <button class="settings-tab" data-tab="llm" onclick="switchSettingsTab('llm')">AI 摘要</button>
        <button class="settings-tab" data-tab="account" onclick="switchSettingsTab('account')">账号设置</button>
      </div>
      <div id="st-push" class="settings-tab-panel">
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">推送开关</h3>
            <p class="section-meta">总开关与每日精选摘要。</p>
          </div>
        </header>
        <div class="form-row">
          <label for="set-notify">新帖推送开关</label>
          <select id="set-notify" class="form-control" onchange="saveNotify()">
            <option value="1" ${state.user.notify_enabled ? "selected" : ""}>开启</option>
            <option value="0" ${!state.user.notify_enabled ? "selected" : ""}>关闭</option>
          </select>
        </div>
        <p class="muted">关闭后不会向任何渠道推送新帖，订阅关系保留。</p>
        <div class="form-row" style="margin-top:16px">
          <label for="set-daily">每日精选摘要</label>
          <select id="set-daily" class="form-control" onchange="saveDailyReport()">
            <option value="1" ${state.user.daily_report_enabled ? "selected" : ""}>开启（每天 20:00 推一次 AI 每日精选）</option>
            <option value="0" ${!state.user.daily_report_enabled ? "selected" : ""}>关闭</option>
          </select>
        </div>
        <p class="muted">开启后，每天 20:00 把你订阅大V当天的新动态汇总成一条推送。</p>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">免打扰时段</h3>
            <p class="section-meta">时段内不推送新帖（支持跨午夜），结束后一次性补一条汇总；系统告警不受影响。特别关注可设为穿透免打扰。</p>
          </div>
        </header>
        <div class="dnd-form">
          <label class="switch">
            <input id="dnd-enabled" type="checkbox" ${state.user.dnd_start ? "checked" : ""} onchange="toggleDnd()">
            <span class="track"></span>
            <span>开启免打扰</span>
          </label>
          <div class="dnd-range-field" id="dnd-range-field">
            <span class="dnd-range-label">免打扰时段</span>
            <div class="dnd-range">
              <input id="dnd-start" type="time" class="form-control" value="${escapeHtml(state.user.dnd_start || "23:00")}">
              <span class="dnd-sep">至</span>
              <input id="dnd-end" type="time" class="form-control" value="${escapeHtml(state.user.dnd_end || "07:00")}">
            </div>
          </div>
          <label class="switch">
            <input id="dnd-fav" type="checkbox" ${state.user.dnd_allow_favorite ? "checked" : ""}>
            <span class="track"></span>
            <span>特别关注可穿透免打扰</span>
          </label>
          <div class="dnd-actions">
            <button class="btn-normal" onclick="saveDnd()">保存</button>
          </div>
        </div>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">关键词提醒</h3>
            <p class="section-meta">命中关键词的动态会加标记，并在免打扰时段实时推送（穿透免打扰）；每行一个，最多 20 个，每个不超过 50 字。</p>
          </div>
        </header>
        <div class="form-row">
          <label for="set-keywords">关键词（每行一个）</label>
          <textarea id="set-keywords" class="form-control" rows="4"
            placeholder="ETF&#10;降息&#10;中概股">${escapeHtml((state.user.keywords || []).join("\n"))}</textarea>
        </div>
        <div class="toolbar" style="margin-top:10px">
          <button class="btn-normal" onclick="saveKeywords()">保存关键词</button>
        </div>
        <p class="muted">适用场景：只关心某个大V聊的特定话题（如「只想要 ETF 相关的」）；命中即实时送达，不受免打扰影响。</p>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">动态图片</h3>
            <p class="section-meta">关闭某位大V的图片显示后，该大V的动态图片会从网页、推送和私有 RSS 中隐藏；头像仍会显示。仅影响当前账号。</p>
          </div>
        </header>
        <div id="kol-images-settings" class="muted kol-images-state" role="status">正在加载已订阅大V…</div>
      </section>
      </div>
      <div id="st-bind" class="settings-tab-panel">
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">推送渠道</h3>
            <p class="section-meta">绑定状态每 10 秒自动刷新；绑定了多个渠道时，可在下方勾选要接收推送的渠道（不选则全部推送）。</p>
          </div>
        </header>
        <div id="push-status">${channelStatusHtml(state.user)}</div>
        <div class="channel-picks" id="push-channels-box" style="margin-top:18px;padding-top:18px;border-top:var(--border-default)">${pushChannelsHtml(state.user)}</div>
        ${(state.user.telegram_chat_id || feishuChannelBound(state.user) || state.user.wecom_webhook || state.user.bark_key)
          ? `<div class="toolbar" style="margin-top:14px">
               <button class="btn-normal" onclick="savePushChannels()">保存推送通道</button>
             </div>` : ""}
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">渠道绑定</h3>
            <p class="section-meta">按序绑定想用的推送渠道，每个渠道的步骤可展开；绑定状态在「推送渠道状态」卡片查看。</p>
          </div>
        </header>
        <div class="channel-bind-block" id="custom-bots-bind">
          <h4 class="section-title">自建机器人（推荐，免共享限频）</h4>
          <p class="section-meta">共享机器人所有用户共用一个应用配额；自建/个人机器人是<b>属于你自己的机器人应用</b>，推送配额独立、不受共享应用限制。Telegram 自建约 1 分钟，飞书个人扫码自动创建。</p>
          <div class="channel-bind-block" style="padding-top:8px">
            <h4 class="section-title">Telegram 自建机器人</h4>
            <ol style="padding-left:20px;line-height:2">
              <li>打开 Telegram 搜索 <b>@BotFather</b>，发 <code>/newbot</code> 创建机器人，拿到 token</li>
              <li>给你的新机器人发任意消息（如 <code>/start</code>）</li>
              <li>把 token 粘贴到下方点「保存」，系统自动识别你的会话，无需手动填 ID</li>
            </ol>
            <div class="row" style="gap:8px;margin-top:10px">
              <input id="set-custom-tg" class="form-control" style="flex:1;min-width:220px" type="password" placeholder="123456:ABC-DEF...">
              <button class="btn-normal" onclick="saveCustomTgBot()">保存</button>
            </div>
          </div>
          <div class="channel-bind-block" style="padding-top:8px">
            <h4 class="section-title">飞书个人机器人（扫码自动创建）</h4>
            <div id="fs-personal-block">${feishuPersonalHtml(state.user.feishu_personal)}</div>
          </div>
        </div>
        <div class="channel-bind-block" id="telegram-bind">
          <h4 class="section-title">1. Telegram 机器人</h4>
          ${bindGuideHtml(!!state.user.telegram_chat_id, `
        <ol style="padding-left:20px;line-height:2">
          <li>打开 Telegram，搜索并进入 ${tgTarget}（找不到就点上方链接）。</li>
          <li>点击「开始」或发送任意消息（如 <code>/start</code>），系统自动记录你的会话。</li>
          <li>回到本页，状态几秒内自动变成「已绑定 ✅」。</li>
          <li>发 <code>/list</code> 可查看大V目录，<code>/sub 大VID</code> 直接订阅。</li>
        </ol>`)}
        </div>
        <div class="channel-bind-block" id="feishu-bind">
          <h4 class="section-title">2. 飞书机器人 · 共享备选</h4>
          <p class="section-meta">不推荐：所有用户共用一个应用，推送配额共享，人多可能被限频。仅作为没有个人机器人时的临时备选，建议优先用上方「自建机器人」里的个人机器人。</p>
          ${bindGuideHtml(!!(state.user.feishu_open_id && state.user.feishu_chat_id), `
        <ol style="padding-left:20px;line-height:2">
          <li>打开飞书 App，点顶部「搜索」，搜索 ${fsTarget} 并进入。</li>
          <li>关键：请在该机器人的<b>「私聊」会话</b>里发任意消息（如 <code>/start</code>）——群聊不会推送新帖，这一步只是建立会话。</li>
          <li>回到本页，在下方「与网页/小程序账号同步」里点「生成绑定码」，把 <code>/bind 6位码</code> 发给机器人。</li>
          <li>发送后本页状态会变成「已绑定 ✅」，网页订阅与飞书推送自动同步。</li>
          <li>发 <code>/list</code> 可查看大V目录，点卡片上的按钮即可订阅。</li>
        </ol>`)}
        </div>
        <div class="channel-bind-block" id="wecom-bind">
          <h4 class="section-title">3. 企业微信群机器人</h4>
          <p class="section-meta">无需申请应用；在企业微信任意群里添加「群机器人」即可，推送会发到这个群。</p>
          ${bindGuideHtml(!!state.user.wecom_webhook, `
        <ol style="padding-left:20px;line-height:2">
          <li>打开企业微信，进入一个群（没有就新建一个，例如「大V推送」）。</li>
          <li>点右上角 <code>...</code> → 「群机器人」→「添加机器人」，按提示创建并起名。</li>
          <li>创建完成后复制 webhook 地址（<code>https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...</code>）。</li>
          <li>粘贴到下方输入框，点「保存绑定」，状态即变为「已绑定 ✅」。</li>
        </ol>`)}
          <div class="form-row" style="margin-top:14px">
            <label for="set-wecom-webhook">群机器人 webhook 地址</label>
            <div class="row" style="gap:10px;flex-wrap:wrap">
              <input id="set-wecom-webhook" class="form-control" style="flex:1;min-width:280px"
                type="text" placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."
                value="${escapeHtml(state.user.wecom_webhook || "")}">
              <button class="btn-normal" onclick="saveWecomWebhook()">保存绑定</button>
            </div>
          </div>
          <p class="muted">⚠️ webhook 等同群管理权限，请勿泄露给他人；不同用户应使用各自的群机器人。</p>
        </div>
        <div class="channel-bind-block" id="bark-bind">
          <h4 class="section-title">4. Bark（iPhone 推送）</h4>
          <p class="section-meta">iOS 自托管用户神器：Bark App 免登录、免费、推送直达锁屏，无需申请任何开发者资质。</p>
          ${bindGuideHtml(!!state.user.bark_key, `
        <ol style="padding-left:20px;line-height:2">
          <li>iPhone 在 App Store 搜索「Bark」安装，打开后主屏会显示你的推送 key（形如 <code>AaBbCcDdEe...</code>）。</li>
          <li>把这个 key 粘贴到下方输入框，点「保存绑定」即可。</li>
          <li>想用自建 Bark 服务器？直接把服务器里的完整地址（<code>https://bark.example.com/xxx</code>）粘贴进来也行。</li>
        </ol>`)}
          <div class="form-row" style="margin-top:14px">
            <label for="set-bark-key">Bark 推送 key 或完整地址</label>
            <div class="row" style="gap:10px;flex-wrap:wrap">
              <input id="set-bark-key" class="form-control" style="flex:1;min-width:280px"
                type="text" placeholder="AaBbCcDdEeFf...（Bark App 里的 key）"
                value="${escapeHtml(state.user.bark_key || "")}">
              <button class="btn-normal" onclick="saveBarkKey()">保存绑定</button>
            </div>
          </div>
          <p class="muted">🔔 key 等同推送权限，请勿泄露；系统告警不依赖此 key（管理员另配系统级 Bark）。</p>
        </div>
      </section>
      </div>
      <div id="st-llm" class="settings-tab-panel">
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">AI 摘要（可选，用你的大模型）</h3>
            <p class="section-meta">配置后，每日精选摘要和免打扰汇总会先用大模型生成 AI 要点，再发原文列表。接口为 OpenAI 兼容格式（/chat/completions），DeepSeek / 通义 / Kimi / 本地 Ollama 均可。不填则用系统默认摘要。</p>
          </div>
        </header>
        <div class="form-row">
          <label for="set-llm-base">API 地址（Base URL）</label>
          <input id="set-llm-base" class="form-control" type="text"
            placeholder="https://api.deepseek.com"
            value="${escapeHtml(state.user.llm_api_base || "")}">
          <p class="muted" style="margin-top:4px">OpenAI 兼容的公网 http(s) 地址即可，不能指向内网。留空默认 DeepSeek：<code>https://api.deepseek.com</code></p>
        </div>
        <div class="form-row">
          <label for="set-llm-key">API Key</label>
          <input id="set-llm-key" class="form-control" type="password"
            placeholder="sk-...（清空并保存 = 关闭 AI 摘要）"
            value="${escapeHtml(state.user.llm_api_key || "")}" autocomplete="off">
        </div>
        <div class="form-row">
          <label for="set-llm-model">模型名</label>
          <input id="set-llm-model" class="form-control" type="text"
            placeholder="deepseek-chat"
            value="${escapeHtml(state.user.llm_model || "")}">
          <p class="muted" style="margin-top:4px">留空默认 <code>deepseek-chat</code></p>
        </div>
        <div class="toolbar" style="margin-top:10px">
          <button class="btn-normal" onclick="saveLlm()">保存</button>
        </div>
        <p class="muted">🔒 配置仅对当前账号生效，费用由你自己的 API 账号承担；生成失败会自动回退为普通摘要，不影响推送。</p>
      </section>
      </div>
      <div id="st-account" class="settings-tab-panel">
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">修改密码</h3>
            <p class="section-meta">定期更换密码，保护你的账号安全。</p>
          </div>
        </header>
        <div class="form-row">
          <label for="pw-old">原密码</label>
          <input id="pw-old" class="form-control" type="password" placeholder="输入当前密码" autocomplete="current-password">
        </div>
        <div class="form-row">
          <label for="pw-new">新密码</label>
          <input id="pw-new" class="form-control" type="password" placeholder="至少 6 位" autocomplete="new-password">
        </div>
        <div class="form-row">
          <label for="pw-confirm">确认新密码</label>
          <input id="pw-confirm" class="form-control" type="password" placeholder="再次输入新密码" autocomplete="new-password">
        </div>
        <button class="btn-normal" onclick="savePassword()">修改密码</button>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">与网页/小程序账号同步（可选）</h3>
            <p class="section-meta">机器人是独立账号；想让机器人订阅与网页账号合并，用绑定码。</p>
          </div>
        </header>
        <details class="bind-steps">
          <summary>展开查看同步步骤</summary>
        <ol style="padding-left:20px;line-height:2">
          <li>点下方「生成绑定码」。</li>
          <li>把 <code>/bind 6位码</code> 发给 Telegram / 飞书机器人（企业微信群机器人是单向 webhook，不支持指令）。</li>
          <li>绑定后机器人账号合并到当前账号，订阅与推送同步，一处订阅处处同步。</li>
        </ol>
        </details>
        <div class="row">
          <button class="btn-ghost" onclick="genBindCode()">生成绑定码</button>
        </div>
        <div id="bind-result" class="muted" style="margin-top:14px"></div>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div>
            <h3 class="section-title">RSS 订阅源（用任意阅读器收动态）</h3>
            <p class="section-meta">不想用聊天工具？把下面地址加进 Reeder / NetNewsWire / 其他任何 RSS 阅读器，就能直接收你订阅大V的动态，无需登录。</p>
          </div>
        </header>
        <div class="form-row">
          <label for="set-feed-url">你的私有订阅源地址</label>
          <div class="row" style="gap:10px;flex-wrap:wrap">
            <input id="set-feed-url" class="form-control" style="flex:1;min-width:280px" readonly
              value="${location.origin}/api/feed/${escapeHtml(state.user.feed_token || "")}.xml">
            <button class="btn-normal" onclick="copyFeedUrl()">复制</button>
            <button class="btn-ghost" onclick="regenerateFeedToken()">重新生成</button>
          </div>
        </div>
        <p class="muted">⚠️ 地址内含订阅凭证，泄露后别人能读到你的关注流；泄露了就点「重新生成」立即作废旧地址。</p>
      </section>
      </div>`;
    settingsPollTimer = setInterval(refreshSettingsStatus, 10000);
    switchSettingsTab(state.settingsTab || "push"); // 恢复上次所在分栏
    toggleDnd(); // 根据开关初始状态同步时段输入框的禁用/置灰
    loadKolImageSettings(seq);
  } catch (err) {
    $("#main").innerHTML = emptyState(err.message);
  }
}

function reloadKolImageSettingsIfNeeded() {
  if (!_kolImageReloadNeeded || _kolImagePendingIds.size) return;
  if (location.hash.replace(/^#\/?/, "").split("?")[0] !== "settings") return;
  _kolImageReloadNeeded = false;
  loadKolImageSettings(routeRenderSeq);
}

async function loadKolImageSettings(seq) {
  const target = $("#kol-images-settings");
  if (!target) return;
  const loadGeneration = ++_kolImageLoadGeneration;
  const loadRevision = _kolImageDataRevision;
  target.className = "muted kol-images-state";
  target.setAttribute("role", "status");
  target.textContent = "正在加载已订阅大V…";
  try {
    const subscriptions = await api("/api/my/subscriptions");
    if (loadGeneration !== _kolImageLoadGeneration || !routeStillActive(seq)) return;
    if (loadRevision !== _kolImageDataRevision || _kolImagePendingIds.size) {
      _kolImageReloadNeeded = true;
      reloadKolImageSettingsIfNeeded();
      return;
    }
    _kolImageReloadNeeded = false;
    _kolImageSubscriptions = subscriptions;
    renderKolImageSettings();
  } catch (err) {
    if (loadGeneration !== _kolImageLoadGeneration || !routeStillActive(seq)) return;
    if (loadRevision !== _kolImageDataRevision || _kolImagePendingIds.size) {
      _kolImageReloadNeeded = true;
      reloadKolImageSettingsIfNeeded();
      return;
    }
    _kolImageReloadNeeded = false;
    const current = $("#kol-images-settings");
    if (!current) return;
    current.className = "kol-images-local-state";
    current.setAttribute("role", "alert");
    current.innerHTML = `
      <p class="muted">加载失败: ${escapeHtml(err.message)}</p>
      <button type="button" class="btn-ghost" onclick="loadKolImageSettings(routeRenderSeq)">重试</button>`;
  }
}

function renderKolImageSettings() {
  const target = $("#kol-images-settings");
  if (!target) return;
  target.className = "";
  target.removeAttribute("role");
  if (!_kolImageSubscriptions.length) {
    target.innerHTML = emptyState(
      "还没有订阅大V",
      `<div><button type="button" class="btn-normal btn-add" onclick="location.hash='#/home'">去订阅广场</button></div>`
    );
    return;
  }
  const search = _kolImageSubscriptions.length >= 12
    ? `<div class="search-bar kol-images-search">
         ${SEARCH_ICON}
         <input id="kol-images-search" type="search" aria-label="搜索已订阅大V"
           placeholder="搜索已订阅大V" oninput="filterKolImageSettings()">
       </div>`
    : "";
  target.innerHTML = `${search}<div id="kol-images-list" class="kol-images-list" role="region" aria-label="已订阅大V的动态图片"></div><p id="kol-images-more" class="section-meta" hidden></p>`;
  filterKolImageSettings();
}

function filterKolImageSettings() {
  const list = $("#kol-images-list");
  if (!list) return;
  const query = ($("#kol-images-search")?.value || "").trim().toLowerCase();
  const filtered = query
    ? _kolImageSubscriptions.filter((kol) => {
        const platform = PLATFORM_LABELS[kol.platform] || kol.platform || "";
        return [kol.name, kol.external_id, platform]
          .some((value) => String(value || "").toLowerCase().includes(query));
      })
    : _kolImageSubscriptions;
  list.innerHTML = filtered.length
    ? filtered.map(kolImageSettingsRowHtml).join("")
    : emptyState("没有匹配的已订阅大V");
  const more = $("#kol-images-more");
  if (more) {
    const extra = Math.max(0, filtered.length - 5);
    more.hidden = extra === 0;
    more.textContent = extra ? `还有 ${extra} 位` : "";
  }
}

function kolImageSettingsRowHtml(kol) {
  const platform = PLATFORM_LABELS[kol.platform] || kol.platform || "";
  return `
    <div class="kol-images-row">
      ${avatarHtml(kol.name, kol.avatar_url)}
      <div class="kol-images-info">
        <span class="kol-images-name" title="${escapeHtml(kol.name)}">${escapeHtml(kol.name)}</span>
        <span class="kol-images-platform">${escapeHtml(platform)}</span>
      </div>
      <label class="switch kol-images-switch">
        <input type="checkbox" ${!kol.hide_images ? "checked" : ""}
          ${_kolImagePendingIds.has(kol.id) ? "disabled" : ""}
          data-kol-id="${kol.id}"
          aria-label="显示${escapeHtml(kol.name)}（${escapeHtml(platform)}）的动态图片"
          onchange="toggleKolImages(${kol.id}, this)">
        <span class="track"></span>
        <span>显示</span>
      </label>
    </div>`;
}

async function toggleKolImages(kolId, input) {
  if (!input || input.disabled || _kolImagePendingIds.has(kolId)) return;
  const kol = _kolImageSubscriptions.find((item) => item.id === kolId);
  if (!kol) return;
  const seq = routeRenderSeq;
  const show = input.checked;
  const previousHideImages = kol.hide_images;
  const restoreFocus = document.activeElement === input && input.matches(":focus-visible");
  _kolImageDataRevision += 1;
  _kolImagePendingIds.add(kolId);
  kol.hide_images = !show;
  input.disabled = true;
  try {
    await api(`/api/subscriptions/${kolId}/hide-images`, {
      method: "PUT",
      body: JSON.stringify({ hide_images: !show }),
    });
    if (!routeStillActive(seq)) return;
    flash(`${show ? "已显示" : "已隐藏"}「${kol ? kol.name : "该大V"}」的动态图片`);
  } catch (err) {
    kol.hide_images = previousHideImages;
    if (!routeStillActive(seq)) return;
    input.checked = !previousHideImages;
    flash("保存失败: " + err.message, "error");
  } finally {
    _kolImagePendingIds.delete(kolId);
    _kolImageDataRevision += 1;
    const isCurrentSettings = location.hash.replace(/^#\/?/, "").split("?")[0] === "settings";
    if (!routeStillActive(seq) && isCurrentSettings) _kolImageReloadNeeded = true;
    if (_kolImagePendingIds.size === 0 && _kolImageReloadNeeded) {
      reloadKolImageSettingsIfNeeded();
    } else if (routeStillActive(seq)) {
      const mountedInput = document.querySelector(`#kol-images-list input[data-kol-id="${kolId}"]`);
      if (mountedInput) {
        mountedInput.checked = !kol.hide_images;
        mountedInput.disabled = false;
        if (restoreFocus && (document.activeElement === input || document.activeElement === document.body)) {
          mountedInput.focus({ preventScroll: true });
        }
      }
    }
  }
}

function switchSettingsTab(name) {
  // 设置页分段导航：推送 / 渠道绑定 / AI 摘要 / 账号设置
  state.settingsTab = name;
  document.querySelectorAll(".settings-tab").forEach((b) =>
    b.classList.toggle("active", b.dataset.tab === name)
  );
  ["push", "bind", "llm", "account"].forEach((t) => {
    const el = document.getElementById("st-" + t);
    if (el) el.style.display = t === name ? "" : "none";
  });
}

function statsTabFromHash() {
  const tab = new URLSearchParams(location.hash.split("?")[1] || "").get("tab") || "overview";
  return STATS_TABS.includes(tab) ? tab : "overview";
}

function switchStatsTab(name) {
  // 数据源页分段导航：监控总览 / 大V健康 / 抓取设置 / Cookie 管理 / 代理
  if (!STATS_TABS.includes(name)) name = "overview";
  document.querySelectorAll(".settings-tab[data-tab]").forEach((b) => {
    const on = b.dataset.tab === name;
    b.classList.toggle("active", on);
    if (STATS_TABS.includes(b.dataset.tab)) b.setAttribute("aria-selected", String(on));
  });
  STATS_TABS.forEach((t) => {
    const el = document.getElementById("st-" + t);
    if (!el) return;
    const on = t === name;
    el.style.display = on ? "" : "none";
    el.hidden = !on;
  });
  const next = name === "overview" ? "#/admin/stats" : `#/admin/stats?tab=${name}`;
  if (location.hash !== next) history.replaceState(null, "", next);
  if (name === "proxies") loadProxyAdmin();
}

function cookieRepairItems(s) {
  const items = [];
  const src = {};
  (s.sources || []).forEach((row) => { src[row.platform] = row; });
  const live = (s.kol_health || []).filter((k) => k.enabled);
  const hasXq = live.some((k) => k.platform === "xueqiu" || k.platform === "combination");
  const hasWb = live.some((k) => k.platform === "weibo");
  const hasTw = live.some((k) => k.platform === "twitter");
  const xq = s.xueqiu_cookie || {};
  const xqErr = `${src.xueqiu?.last_error || ""} ${src.combination?.last_error || ""}`;
  const xqSick = /cookie|waf|反爬|401|403|失效|登录/i.test(xqErr);
  if (hasXq && !xq.set) items.push({ key: "xq-missing", label: "雪球 Cookie 未写入" });
  else if (hasXq && src.xueqiu && !src.xueqiu.ok && xqSick) {
    items.push({ key: "xq-bad", label: "雪球 Cookie 可能失效" });
  }
  const wb = src.weibo;
  if (hasWb && wb && !wb.ok && /登录|login|cookie|会话/i.test(wb.last_error || "")) {
    items.push({ key: "wb-bad", label: "微博登录态失效，可扫码续期" });
  }
  const tw = s.twitter_cookie || {};
  const twReason = src.twitter?.direct_fallback_reason || src.twitter?.last_error || "";
  if (hasTw && src.twitter?.direct_mode === "fallback" && /cookie|401|403|89|32|未配置|twitter/i.test(twReason)) {
    items.push({ key: "x-bad", label: "X Cookie 可能失效" });
  } else if (hasTw && !tw.set) {
    items.push({ key: "x-missing", label: "X Cookie 未写入" });
  }
  return items;
}

function cookieRepairBanner(s) {
  const items = cookieRepairItems(s);
  if (!items.length) return "";
  return `<div class="notice notice-warn" role="status">
    <div class="notice-warn-body">
      <strong>Cookie 需要更新</strong>
      <p>${items.map((i) => escapeHtml(i.label)).join("；")}。保存后即时生效，不用改配置文件、不用重启。</p>
    </div>
    <button type="button" class="btn-normal" onclick="switchStatsTab('cookies')">去更新</button>
  </div>`;
}

function cookieUpdatedLabel(info) {
  if (!info || !info.set) return "未写入";
  if (info.from_env) return "已从环境变量读取";
  return info.updated_at ? `已写入（${escapeHtml(fmtTs(info.updated_at))}）` : "已写入";
}

function bindGuideHtml(bound, stepsHtml) {
  // 渠道绑定步骤折叠：未绑定时默认展开引导，已绑定时收起来（页面不再一屏放不下）
  return `<details class="bind-steps" ${bound ? "" : "open"}>
    <summary>${bound ? "已绑定 ✅ · 展开查看绑定步骤" : "展开查看绑定步骤"}</summary>
    ${stepsHtml}
  </details>`;
}

// ---------- 飞书个人机器人（扫码注册） ----------
const fsPersonalState = { sessionId: "", bindCommand: "", bindExpiresAt: 0, pollTimer: null, countdownTimer: null };

function feishuPersonalHtml(fs) {
  fs = fs || {};
  if (!fs.available) {
    return `<p class="muted">⚠️ 个人机器人功能未启用（服务端未配置 FEISHU_CREDENTIAL_KEY），请使用上方共享机器人。</p>`;
  }
  if (fs.status === "active") {
    return `<div class="row" style="gap:10px;flex-wrap:wrap;align-items:center">
      <span class="channel-status status-ok"><i class="dot"></i>个人机器人已激活${fs.app_id_masked ? " · " + escapeHtml(fs.app_id_masked) : ""}</span>
      <button class="channel-btn secondary" onclick="unbindChannel('feishu_personal')">解绑个人机器人</button>
    </div>
    <p class="muted" style="margin-top:8px">推送将使用你的个人应用发送，配额独立、不受共享应用限制；共享机器人绑定保留，个人机器人失效时自动回退。</p>`;
  }
  if (fs.status === "degraded") {
    return `<div class="row" style="gap:10px;flex-wrap:wrap;align-items:center">
      <span class="channel-status status-warn"><i class="dot"></i>个人机器人已降级（暂用共享推送）</span>
      <button class="channel-btn primary" onclick="startFeishuPersonal()">重新扫码绑定</button>
    </div>`;
  }
  if (fsPersonalState.sessionId) {
    return fsPersonalStateHtml();
  }
  return `<div class="row" style="gap:10px;flex-wrap:wrap;margin-top:8px">
    <button class="btn-normal" onclick="startFeishuPersonal()">扫码创建个人机器人</button>
    <span class="muted">需要飞书扫码；个人应用会创建在你自己的飞书租户里。</span>
  </div>`;
}

function fsPersonalStateHtml() {
  const st = fsPersonalState;
  const secs = Math.max(0, Math.ceil((st.bindExpiresAt - Date.now()) / 1000));
  const uri = st.verificationUri || "";
  return `<div id="fs-personal-flow">
    <div style="text-align:center;padding:8px 0 12px">
      ${st.qrUri ? `<img class="qr-frame" src="${st.qrUri}" alt="扫码二维码">` : ""}
      <p class="muted qr-status">用飞书「扫一扫」扫码；或点链接打开：
        <a href="${escapeHtml(uri)}" target="_blank" rel="noopener">${escapeHtml(uri)}</a>
      </p>
    </div>
    ${st.bindCommand ? `
    <p style="line-height:1.9">下一步：打开刚创建的个人机器人<b>私聊窗口</b>，发送：<br>
      <code class="bind-code">${escapeHtml(st.bindCommand)}</code>
      <span id="fs-bind-countdown" class="muted" style="margin-left:8px">${secs}s</span>
    </p>
    <div class="row" style="gap:10px;margin-top:8px;flex-wrap:wrap">
      <button class="btn-normal btn-sm" onclick="refreshFeishuBindCode()">重新生成绑定码</button>
      <button class="btn-ghost btn-sm" onclick="cancelFeishuPersonal()">取消</button>
    </div>` : `
    <p class="muted">⏳ 等待扫码…（扫完码会自动进入下一步）</p>
    <button class="btn-ghost btn-sm" onclick="cancelFeishuPersonal()">取消</button>`}
  </div>`;
}

async function startFeishuPersonal() {
  try {
    const data = await api("/api/me/feishu-personal/register", { method: "POST" });
    fsPersonalState.sessionId = data.session_id;
    fsPersonalState.bindCommand = "";
    fsPersonalState.verificationUri = data.verification_uri;
    fsPersonalState.qrUri = data.qr_uri || "";
    fsPersonalRender();
    startFeishuPersonalPoll(data.session_id);
  } catch (err) {
    flash("发起个人机器人注册失败: " + err.message, "error");
  }
}

function fsPersonalRender() {
  // 局部重绘个人机器人区块（不整页重绘：renderSettings 需要路由序号，轮询里拿不到）
  const el = $("#fs-personal-block");
  if (el) el.innerHTML = feishuPersonalHtml(state.user.feishu_personal);
}

function startFeishuPersonalPoll(sessionId) {
  stopFeishuPersonalPoll();
  fsPersonalState.pollTimer = setInterval(async () => {
    try {
      const data = await api(`/api/me/feishu-personal/register/${sessionId}`);
      fsPersonalState.verificationUri = data.verification_uri;
      fsPersonalState.qrUri = data.qr_uri || fsPersonalState.qrUri;
      // 同步个人机器人展示状态（轮询期间 /api/me 不会刷新）
      state.user.feishu_personal = state.user.feishu_personal || {};
      if (data.personal_bot_status) state.user.feishu_personal.status = data.personal_bot_status;
      if (data.status === "awaiting_bind" && data.bind_command) {
        fsPersonalState.bindCommand = data.bind_command;
        fsPersonalState.bindExpiresAt = (data.bind_code_expires_at || 0) * 1000;
        stopFeishuPersonalPoll();
        fsPersonalRender();
        startFeishuBindCountdown();
      } else if (data.status === "active") {
        stopFeishuPersonalPoll();
        fsPersonalState.sessionId = "";
        fsPersonalRender();
        flash("个人机器人已绑定");
      } else if (["expired", "cancelled", "degraded"].includes(data.status)) {
        stopFeishuPersonalPoll();
        fsPersonalState.sessionId = "";
        fsPersonalRender();
        if (data.status === "degraded") flash("个人机器人绑定失败：" + (data.last_error || "未知错误"), "error");
      } else {
        // pending / credentials_created：局部刷新等待扫码区域
        fsPersonalRender();
      }
    } catch (err) {
      // 轮询失败静默，下轮再试；会话不存在则结束
      if (String(err.message).includes("404")) {
        stopFeishuPersonalPoll();
        fsPersonalState.sessionId = "";
        fsPersonalRender();
      }
    }
  }, 1000);  // 绑定轮询：1s 一次，扫码/绑定完成及时反映（状态接口很轻量）
}

function stopFeishuPersonalPoll() {
  if (fsPersonalState.pollTimer) {
    clearInterval(fsPersonalState.pollTimer);
    fsPersonalState.pollTimer = null;
  }
  if (fsPersonalState.countdownTimer) {
    clearInterval(fsPersonalState.countdownTimer);
    fsPersonalState.countdownTimer = null;
  }
}

function startFeishuBindCountdown() {
  if (fsPersonalState.countdownTimer) clearInterval(fsPersonalState.countdownTimer);
  fsPersonalState.countdownTimer = setInterval(() => {
    const secs = Math.max(0, Math.ceil((fsPersonalState.bindExpiresAt - Date.now()) / 1000));
    const el = $("#fs-bind-countdown");
    if (el) el.textContent = `${secs}s`;
    if (secs <= 0) {
      clearInterval(fsPersonalState.countdownTimer);
      // 绑定码过期：轮询刷新（服务端 awaiting_bind 状态下重新生成即可）
      if (fsPersonalState.sessionId) startFeishuPersonalPoll(fsPersonalState.sessionId);
    }
  }, 1000);
}

async function refreshFeishuBindCode() {
  if (!fsPersonalState.sessionId) return;
  try {
    const data = await api(`/api/me/feishu-personal/register/${fsPersonalState.sessionId}/refresh-code`, { method: "POST" });
    fsPersonalState.bindCommand = data.bind_command;
    fsPersonalState.bindExpiresAt = (data.bind_code_expires_at || 0) * 1000;
    stopFeishuPersonalPoll();
    fsPersonalRender();
    startFeishuBindCountdown();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function cancelFeishuPersonal() {
  if (!fsPersonalState.sessionId) return;
  try {
    await api(`/api/me/feishu-personal/register/${fsPersonalState.sessionId}/cancel`, { method: "POST" });
  } catch { /* 忽略 */ }
  stopFeishuPersonalPoll();
  fsPersonalState.sessionId = "";
  fsPersonalRender();
}

function openBindGuide(sectionId) {
  // 渠道绑定块在独立「渠道绑定」分栏里，先切过去再滚动并展开步骤
  if (sectionId.endsWith("-bind")) {
    switchSettingsTab("bind");
  }
  const sec = document.getElementById(sectionId);
  if (!sec) return;
  sec.scrollIntoView({ behavior: "smooth", block: "start" });
  const details = sec.querySelector("details.bind-steps");
  if (details) details.open = true;
}

function pushChannelsHtml(user) {
  const opts = [];
  if (user.telegram_chat_id) opts.push(["telegram", "Telegram"]);
  if (feishuChannelBound(user)) opts.push(["feishu", "飞书"]);
  if (user.wecom_webhook) opts.push(["wecom", "企业微信"]);
  if (user.bark_key) opts.push(["bark", "Bark"]);
  if (!opts.length) return `<p class="muted">还没有绑定推送渠道，先完成上方任一渠道绑定后即可选择。</p>`;
  const selected = (user.push_channels || "").split(",").map((s) => s.trim()).filter(Boolean);
  const isChecked = (ch) => selected.length === 0 || selected.includes(ch);
  return opts.map(([ch, label]) => `
    <label class="channel-pick ${isChecked(ch) ? "selected" : ""}" data-channel="${ch}" title="${escapeHtml(label)}">
      <input type="checkbox" value="${ch}" ${isChecked(ch) ? "checked" : ""}
        onchange="this.closest('.channel-pick').classList.toggle('selected', this.checked)">
      <span class="ch-icon-wrap">${CHANNEL_ICONS[ch]}</span>
      <span class="ch-check">✓</span>
    </label>`).join("");
}

async function savePushChannels() {
  const boxes = [...document.querySelectorAll("#push-channels-box input[type=checkbox]")];
  if (!boxes.length) return;
  const channels = boxes.filter((b) => b.checked).map((b) => b.value);
  if (!channels.length) {
    flash("请至少保留一个推送通道；全部不想要可以关闭「新帖推送开关」", "error");
    return;
  }
  try {
    await api("/api/me", { method: "PUT", body: JSON.stringify({ push_channels: channels.join(",") }) });
    state.user.push_channels = channels.join(",");
    flash("已保存");
  } catch (err) {
    flash(err.message, "error");
  }
}

async function saveNotify() {
  try {
    await api("/api/me", {
      method: "PUT",
      body: JSON.stringify({ notify_enabled: $("#set-notify").value === "1" }),
    });
    flash("已保存");
  } catch (err) {
    flash(err.message, "error");
  }
}

async function saveDailyReport() {
  try {
    await api("/api/me", {
      method: "PUT",
      body: JSON.stringify({ daily_report_enabled: $("#set-daily").value === "1" }),
    });
    flash("已保存");
  } catch (err) {
    flash(err.message, "error");
  }
}

function toggleDnd() {
  // 免打扰开关与时段输入联动：关闭时时段输入禁用并置灰
  const on = $("#dnd-enabled").checked;
  const field = $("#dnd-range-field");
  if (field) field.classList.toggle("is-off", !on);
  $("#dnd-start").disabled = !on;
  $("#dnd-end").disabled = !on;
}

async function saveDnd() {
  const enabled = $("#dnd-enabled").checked;
  const start = $("#dnd-start").value;
  const end = $("#dnd-end").value;
  const allowFav = $("#dnd-fav").checked;
  if (enabled && (!start || !end || start === end)) {
    flash("请设置不同的开始与结束时间", "error");
    return;
  }
  try {
    await api("/api/me", {
      method: "PUT",
      body: JSON.stringify({
        dnd_start: enabled ? start : "",
        dnd_end: enabled ? end : "",
        dnd_allow_favorite: allowFav,
      }),
    });
    state.user.dnd_start = enabled ? start : "";
    state.user.dnd_end = enabled ? end : "";
    state.user.dnd_allow_favorite = allowFav;
    flash("已保存");
  } catch (err) {
    flash(err.message, "error");
  }
}

let pendingBind = null; // { channel, code, expiresAt }——轮询重绘后恢复显示

function renderBindResult(channel, code) {
  const el = channel === "telegram" ? $("#bind-result-telegram") : $("#bind-result-feishu");
  if (!el) return;
  const guide = state.user.push_guide || {};
  if (channel === "telegram" && guide.telegram_bot_username) {
    const link = `https://t.me/${encodeURIComponent(guide.telegram_bot_username)}?start=bind_${code}`;
    el.innerHTML = `
      <p style="margin:10px 0 6px">点击下方按钮，Telegram 会自动打开机器人并完成绑定：</p>
      <a class="btn-normal" href="${link}" target="_blank" rel="noopener">一键绑定 Telegram</a>
      <p class="muted" style="margin-top:8px">按钮没反应？复制 <b>${escapeHtml(code)}</b> 粘贴给机器人也可以。</p>`;
  } else {
    const label = channel === "telegram" ? "Telegram" : "飞书";
    el.innerHTML = `
      <p style="margin:10px 0 6px">复制绑定码，粘贴发送给${label}机器人（自动识别，无需命令）：</p>
      <b style="font-size:var(--text-icon);letter-spacing:3px;font-family:var(--font-mono);font-variant-numeric:tabular-nums">${escapeHtml(code)}</b>`;
  }
}

async function bindChannel(channel) {
  try {
    const data = await api("/api/me/bind-code", { method: "POST" });
    pendingBind = {
      channel,
      code: data.code,
      expiresAt: Date.now() + (data.expires_in_seconds || 600) * 1000,
    };
    renderBindResult(channel, data.code);
  } catch (err) {
    flash(err.message, "error");
  }
}

async function saveCustomTgBot() {
  const token = ($("#set-custom-tg").value || "").trim();
  if (!token) {
    flash("请先粘贴你的 bot token", "error");
    return;
  }
  try {
    await api("/api/me", { method: "PUT", body: JSON.stringify({ telegram_bot_token: token }) });
    flash("自建机器人已绑定");
    await reloadSettings();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function unbindChannel(channel) {
  const label = channel === "telegram_chat_id" ? "Telegram"
    : channel === "telegram_bot_token" ? "Telegram（自建机器人）"
    : channel === "feishu_personal" ? "飞书个人机器人"
    : channel === "wecom" ? "企业微信"
    : channel === "bark" ? "Bark" : "飞书";
  if (!confirm(`确认解绑 ${label}？解绑后将不再通过该方式推送（共享机器人绑定不受影响）。`)) return;
  try {
    if (channel === "feishu_personal") {
      stopFeishuPersonalPoll();
      fsPersonalState.sessionId = "";
      await api("/api/me/feishu-personal", { method: "DELETE" });
      flash(`已解绑 ${label}`);
      await reloadSettings();
      return;
    }
    const body = channel === "feishu"
      ? { feishu_open_id: "", feishu_chat_id: "" }
      : channel === "wecom"
        ? { wecom_webhook: "" }
        : channel === "bark"
          ? { bark_key: "" }
        : channel === "telegram_bot_token"
          ? { telegram_bot_token: "", telegram_chat_id: "" }
        : { telegram_chat_id: "" };
    await api("/api/me", { method: "PUT", body: JSON.stringify(body) });
    flash(`已解绑 ${label}`);
    await reloadSettings();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function saveWecomWebhook() {
  const webhook = ($("#set-wecom-webhook").value || "").trim();
  if (webhook && !/^https:\/\/qyapi\.weixin\.qq\.com\/cgi-bin\/webhook\/send\?key=/.test(webhook)) {
    flash("webhook 地址无效，应为 https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=... 格式", "error");
    return;
  }
  try {
    await api("/api/me", {
      method: "PUT",
      body: JSON.stringify({ wecom_webhook: webhook }),
    });
    flash(webhook ? "企业微信已绑定" : "企业微信已解绑");
    await reloadSettings();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function saveBarkKey() {
  const key = ($("#set-bark-key").value || "").trim();
  try {
    await api("/api/me", {
      method: "PUT",
      body: JSON.stringify({ bark_key: key }),
    });
    flash(key ? "Bark 已绑定" : "Bark 已解绑");
    await reloadSettings();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function saveKeywords() {
  const keywords = ($("#set-keywords").value || "")
    .split(/[\n,]/)
    .map((k) => k.trim())
    .filter(Boolean);
  try {
    await api("/api/me", {
      method: "PUT",
      body: JSON.stringify({ keywords }),
    });
    flash(`已保存 ${keywords.length} 个关键词`);
  } catch (err) {
    flash(err.message, "error");
  }
}

async function saveLlm() {
  const payload = {
    llm_api_base: ($("#set-llm-base").value || "").trim(),
    llm_api_key: ($("#set-llm-key").value || "").trim(),
    llm_model: ($("#set-llm-model").value || "").trim(),
  };
  try {
    await api("/api/me", { method: "PUT", body: JSON.stringify(payload) });
    flash(payload.llm_api_key ? "已保存" : "AI 摘要已关闭");
    await reloadSettings();
  } catch (err) {
    flash(err.message, "error");
  }
}

function copyFeedUrl() {
  const input = $("#set-feed-url");
  if (!input || !input.value) return;
  copyText(input.value, "订阅源地址已复制");
}

async function regenerateFeedToken() {
  if (!confirm("重新生成后旧地址立即失效，确认？")) return;
  try {
    const res = await api("/api/me/feed-token/regenerate", { method: "POST" });
    state.user.feed_token = res.feed_token;
    flash("订阅源地址已重新生成");
    await reloadSettings();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function savePassword() {
  const oldPw = $("#pw-old").value;
  const newPw = $("#pw-new").value;
  const confirmPw = $("#pw-confirm").value;
  if (!oldPw || newPw.length < 6) {
    flash("请填写原密码，新密码至少 6 位", "error");
    return;
  }
  if (newPw !== confirmPw) {
    flash("两次输入的新密码不一致", "error");
    return;
  }
  try {
    await api("/api/me/password", {
      method: "POST",
      body: JSON.stringify({ old_password: oldPw, new_password: newPw }),
    });
    $("#pw-old").value = $("#pw-new").value = $("#pw-confirm").value = "";
    flash("密码已修改");
  } catch (err) {
    flash(err.message, "error");
  }
}

async function genBindCode() {
  try {
    const data = await api("/api/me/bind-code", { method: "POST" });
    $("#bind-result").innerHTML =
      `绑定码：<b style="font-size:var(--text-icon);letter-spacing:3px;font-family:var(--font-mono);font-variant-numeric:tabular-nums">${escapeHtml(data.code)}</b>` +
      `（${Math.floor(data.expires_in_seconds / 60)} 分钟内有效）<br>` +
      `发给机器人：<code>/bind ${escapeHtml(data.code)}</code>`;
  } catch (err) {
    flash(err.message, "error");
  }
}

// ---------- 管理后台（导航统一走左侧边栏） ----------
let _adminRenderSeq = 0; // 当前管理后台渲染令牌：loader 写 #admin-body 前凭此丢弃过期响应

async function renderAdmin(tab, seq) {
  _adminRenderSeq = seq;
  setPageTitle("管理后台");
  $("#main").innerHTML = `
    <div id="admin-body"><div class="admin-skeleton" aria-hidden="true">${Array(3).fill(`
      <div class="admin-sk-card">
        <div class="admin-sk-line admin-sk-head"></div>
        <div class="admin-sk-table-row"><div class="admin-sk-line"></div><div class="admin-sk-line"></div><div class="admin-sk-line"></div></div>
        <div class="admin-sk-table-row"><div class="admin-sk-line"></div><div class="admin-sk-line"></div></div>
        <div class="admin-sk-table-row"><div class="admin-sk-line"></div><div class="admin-sk-line"></div><div class="admin-sk-line"></div></div>
      </div>`).join("")}
    </div>`;
  const loaders = { dashboard: loadAdminDashboard, stats: loadAdminStats, kols: loadAdminKols, requests: loadAdminRequests, codes: loadAdminCodes, vocab: loadAdminVocab, posts: loadAdminPosts, logs: loadAdminLogs, audit: loadAdminAudit, backup: loadAdminBackup, users: loadAdminUsers };
  try {
    await loaders[tab]();
  } catch (err) {
    // 只有当前路由仍是本次渲染目标时才写错误状态，避免旧路由的错误覆盖新 tab
    if (routeStillActive(seq)) $("#admin-body").innerHTML = emptyState("加载失败: " + err.message);
  }
}

let statsTimer = null;

function stopStatsTimer() {
  if (statsTimer) {
    clearInterval(statsTimer);
    statsTimer = null;
  }
}

function fmtTs(ts) {
  return ts ? new Date(Number(ts) * 1000).toLocaleString() : "-";
}

// 数据库里 SQLite 生成的 created_at/fetched_at 是 UTC（datetime('now')），
// 展示时按 UTC 解析并转成浏览器本地时间（北京时间），避免慢 8 小时
function fmtDbTime(s) {
  if (!s) return "-";
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/.exec(String(s));
  if (!m) return s;
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]));
  if (Number.isNaN(d.getTime())) return s;
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function rateBar(rate) {
  if (rate === null || rate === undefined) return `<span class="muted">暂无数据</span>`;
  const tone = rate >= 95 ? "ok" : rate >= 70 ? "warn" : "fail";
  return `
    <div class="rate-row">
      <div class="rate-bar">
        <div class="rate-fill ${tone}" style="width:${Math.min(100, Math.max(0, rate))}%"></div>
      </div>
      <span class="rate-label">${rate}%</span>
    </div>`;
}

async function loadAdminStats() {
  stopStatsTimer();
  const s = await api("/api/stats");
  if (!routeStillActive(_adminRenderSeq)) return;
  const xq = s.xueqiu_cookie || {};
  const tw = s.twitter_cookie || {};
  $("#admin-body").innerHTML = `
    <div class="settings-tabs" role="tablist" aria-label="数据源管理">
      <button type="button" class="settings-tab active" role="tab" id="tab-overview" aria-selected="true" aria-controls="st-overview" data-tab="overview" onclick="switchStatsTab('overview')">监控总览</button>
      <button type="button" class="settings-tab" role="tab" id="tab-health" aria-selected="false" aria-controls="st-health" data-tab="health" onclick="switchStatsTab('health')">大V健康</button>
      <button type="button" class="settings-tab" role="tab" id="tab-config" aria-selected="false" aria-controls="st-config" data-tab="config" onclick="switchStatsTab('config')">抓取设置</button>
      <button type="button" class="settings-tab" role="tab" id="tab-cookies" aria-selected="false" aria-controls="st-cookies" data-tab="cookies" onclick="switchStatsTab('cookies')">Cookie 管理</button>
      <button type="button" class="settings-tab" role="tab" id="tab-proxies" aria-selected="false" aria-controls="st-proxies" data-tab="proxies" onclick="switchStatsTab('proxies')">代理</button>
    </div>
    <div id="st-overview" class="settings-tab-panel" role="tabpanel" aria-labelledby="tab-overview">
      <section class="section-panel">
        <header class="section-head">
          <div><h3 class="section-title">数据源稳定性</h3>
          <p class="section-meta">抓取健康、24h 成功率与事件流；页面每 30 秒自动刷新。</p></div>
          <div class="toolbar" style="margin-top:12px">
            <span id="stats-refresh-at" class="muted"></span>
            <button class="btn-ghost" onclick="loadAdminStats()">立即刷新</button>
          </div>
        </header>
        <div id="stats-cards"></div>
        <div id="stats-poll-error"></div>
        <div id="stats-ops" style="margin-top:16px"></div>
        <div class="table-wrap" style="margin-top:16px">
          <table>
            <thead><tr><th scope="col">平台</th><th scope="col">状态</th><th scope="col">通道</th><th scope="col">24h 成功率</th><th scope="col">成功 / 失败</th><th scope="col">连续失败</th><th scope="col">最近成功</th><th scope="col">下次重试</th><th scope="col">最近错误</th></tr></thead>
            <tbody id="sources-table"></tbody>
          </table>
        </div>
      </section>
      <section class="section-panel">
        <header class="section-head"><div><h3 class="section-title">数据源事件</h3>
        <p class="section-meta">最近 30 条抓取成功 / 失败 / 降级记录（保留 7 天）。</p></div></header>
        <div id="source-events"></div>
      </section>
    </div>
    <div id="st-health" class="settings-tab-panel" role="tabpanel" aria-labelledby="tab-health" style="display:none">
      <section class="section-panel">
        <header class="section-head"><div><h3 class="section-title">大V抓取健康</h3>
        <p class="section-meta">按「最近抓到新帖时间」从旧到新排列，顶部即长期无更新的候选排查对象。</p></div></header>
        <div id="kol-health"></div>
      </section>
    </div>
    <div id="st-config" class="settings-tab-panel" role="tabpanel" aria-labelledby="tab-config" style="display:none">
      <section class="section-panel">
        <header class="section-head">
          <div><h3 class="section-title">抓取设置</h3>
          <p class="section-meta">按抓取档位分组配置；保存后即时生效，无需重启。</p></div>
        </header>
        <div class="cfg-grid">
          <div class="cfg-group">
            <p class="cfg-group-title">基础轮询</p>
            <div class="cfg-fields">
              <label class="cfg-field" title="全局轮询间隔（所有大V的最低抓取频率）">
                <span>轮询间隔<span class="cfg-unit">秒</span></span>
                <input id="pc-interval" type="number" class="form-control" min="1" max="3600" value="${s.polling_config.interval_seconds}">
              </label>
              <label class="cfg-field" title="标记为「优先」的大V用更短间隔抓取，新帖更早送达">
                <span>优先大V间隔<span class="cfg-unit">秒</span></span>
                <input id="pc-priority" type="number" class="form-control" min="1" max="600" value="${s.polling_config.priority_interval_seconds}">
              </label>
              <label class="cfg-field" title="普通大V帖子按此周期合并推送摘要；0 = 实时单条推送">
                <span>合并推送周期<span class="cfg-unit">秒</span></span>
                <input id="pc-digest" type="number" class="form-control" min="0" max="86400" value="${s.polling_config.digest_interval_seconds}">
              </label>
            </div>
          </div>
          <div class="cfg-group">
            <p class="cfg-group-title">雪球组合 <span class="hint">调仓实时推送</span></p>
            <div class="cfg-fields">
              <label class="cfg-field" title="组合抓取频率；无新帖时自动拉长（2 倍步进），调仓出现即恢复">
                <span>组合基础间隔<span class="cfg-unit">秒</span></span>
                <input id="pc-cb" type="number" class="form-control" min="5" max="3600" value="${s.polling_config.combination_base_seconds}">
              </label>
              <label class="cfg-field" title="组合长期无调仓时封顶的空轮间隔，避免空转刷接口">
                <span>组合空轮封顶<span class="cfg-unit">秒</span></span>
                <input id="pc-cc" type="number" class="form-control" min="5" max="86400" value="${s.polling_config.combination_idle_cap_seconds}">
              </label>
            </div>
          </div>
          <div class="cfg-group">
            <p class="cfg-group-title">自适应降频 <span class="hint">无新帖自动拉长</span></p>
            <div class="cfg-fields">
              <label class="cfg-field" title="普通大V长期无新帖时封顶的空轮间隔，控制对平台的请求频率">
                <span>普通大V空轮封顶<span class="cfg-unit">秒</span></span>
                <input id="pc-nc" type="number" class="form-control" min="5" max="86400" value="${s.polling_config.normal_idle_cap_seconds}">
              </label>
              <label class="cfg-field" title="优先大V长期无新帖时封顶的空轮间隔">
                <span>优先大V空轮封顶<span class="cfg-unit">秒</span></span>
                <input id="pc-pc" type="number" class="form-control" min="5" max="86400" value="${s.polling_config.priority_idle_cap_seconds}">
              </label>
              <label class="cfg-field" title="X 直抓失败期间封顶的抓取间隔，失败期放慢以免空打接口">
                <span>X失败封顶<span class="cfg-unit">秒</span></span>
                <input id="pc-xc" type="number" class="form-control" min="5" max="86400" value="${s.polling_config.x_fallback_cap_seconds}">
              </label>
            </div>
          </div>
          <div class="cfg-group">
            <p class="cfg-group-title">次要大V <span class="hint">低频合并</span></p>
            <div class="cfg-fields">
              <label class="cfg-field" title="次要大V基础抓取间隔（低于普通大V频率）">
                <span>抓取间隔<span class="cfg-unit">秒</span></span>
                <input id="pc-si" type="number" class="form-control" min="60" max="86400" value="${s.polling_config.secondary_interval_seconds}">
              </label>
              <label class="cfg-field" title="次要大V长期无新帖时封顶的空轮间隔">
                <span>空轮封顶<span class="cfg-unit">秒</span></span>
                <input id="pc-sc" type="number" class="form-control" min="60" max="86400" value="${s.polling_config.secondary_idle_cap_seconds}">
              </label>
              <label class="cfg-field" title="次要大V帖子按此周期合并推送；0 = 实时推送">
                <span>推送周期<span class="cfg-unit">秒</span></span>
                <input id="pc-sd" type="number" class="form-control" min="0" max="86400" value="${s.polling_config.secondary_digest_interval_seconds}">
              </label>
              <label class="cfg-field" title="合并推送最低条数：周期内积压不足此数则不推送、继续攒，够数才推">
                <span>最低条数<span class="cfg-unit">条</span></span>
                <input id="pc-sd-min" type="number" class="form-control" min="1" max="100" value="${s.polling_config.secondary_min_digest_count ?? 1}">
              </label>
            </div>
          </div>
          <div class="cfg-group">
            <p class="cfg-group-title">X 通道</p>
            <div class="cfg-fields">
              <label class="cfg-field cfg-check" title="X 内容自动翻译成中文（配置 TWITTER_COOKIE 后走 X 官方翻译，质量同网页版）">
                <input id="pc-translate" type="checkbox" ${s.polling_config.translate_twitter_content ? "checked" : ""}>
                <span>X 内容自动翻译成中文</span>
                <span class="cfg-check-desc">配置 TWITTER_COOKIE 后走 X 官方翻译，质量同网页版</span>
              </label>
            </div>
          </div>
          <div class="cfg-group">
            <p class="cfg-group-title">保活与定时</p>
            <div class="cfg-fields">
              <label class="cfg-field" title="雪球保活探测间隔；0 = 关闭自动保活">
                <span>雪球探测<span class="cfg-unit">秒</span></span>
                <input id="pc-probe" type="number" class="form-control" min="0" max="86400" value="${s.polling_config.source_probe_interval_seconds}">
              </label>
              <label class="cfg-field" title="登录态自动保活间隔；0 = 关闭">
                <span>cookie保活<span class="cfg-unit">秒</span></span>
                <input id="pc-keepalive" type="number" class="form-control" min="0" max="86400" value="${s.polling_config.cookie_keepalive_interval_seconds}">
              </label>
              <label class="cfg-field" title="每日精选推送的小时（0-23，北京时间）">
                <span>每日精选<span class="cfg-unit">时</span></span>
                <input id="pc-daily" type="number" class="form-control" min="0" max="23" value="${s.polling_config.daily_report_hour}">
              </label>
            </div>
          </div>
        </div>
        <div class="cfg-save-row">
          <button class="btn-normal" onclick="savePollingConfig()">保存抓取设置</button>
        </div>
      </section>
    </div>
    <div id="st-cookies" class="settings-tab-panel" role="tabpanel" aria-labelledby="tab-cookies" style="display:none">
      <div id="cookie-repair-inline"></div>
      <section class="section-panel">
        <header class="section-head">
          <div><h3 class="section-title">雪球 Cookie</h3>
          <p class="section-meta">${cookieUpdatedLabel(xq)}${xq.preview ? ` · 预览 ${escapeHtml(xq.preview)}` : ""}${s.keepalive_interval_seconds > 0 ? ` · 每 ${Math.round(s.keepalive_interval_seconds / 3600)} 小时探测` : ""}。登录 xueqiu.com → F12 → Application → Cookies，复制整串后保存，即时生效。</p></div>
        </header>
        <textarea id="xq-cookie" class="form-control cookie-paste" rows="4" placeholder="xq_a_token=...; u=..."></textarea>
        <div class="toolbar" style="margin-top:12px">
          <button type="button" class="btn-normal" onclick="saveXueqiuCookie()">保存雪球 Cookie</button>
          <button type="button" class="btn-ghost" onclick="pasteCookieField('xq-cookie')">从剪贴板填入</button>
        </div>
      </section>
      <section class="section-panel">
        <header class="section-head"><div><h3 class="section-title">微博 Cookie</h3>
        <p class="section-meta">${cookieUpdatedLabel(s.weibo_cookie)}。用微博 App 扫码后自动保存，无需复制。</p></div></header>
        <div>
          <button type="button" class="btn-normal" onclick="startWeiboQr()">微博扫码登录</button>
        </div>
        <div id="wb-qr-box" class="qr-box"></div>
      </section>
      <section class="section-panel">
        <header class="section-head">
          <div><h3 class="section-title">X Cookie</h3>
          <p class="section-meta">${cookieUpdatedLabel(tw)}${tw.preview ? ` · 预览 ${escapeHtml(tw.preview)}` : ""}。登录 x.com → F12 → Application → Cookies，复制整串（需含 auth_token 与 ct0），保存即时生效。</p></div>
        </header>
        <textarea id="tw-cookie" class="form-control cookie-paste" rows="4" placeholder="auth_token=...; ct0=..."></textarea>
        <div class="toolbar" style="margin-top:12px">
          <button type="button" class="btn-normal" onclick="saveTwitterCookie()">保存 X Cookie</button>
          <button type="button" class="btn-ghost" onclick="pasteCookieField('tw-cookie')">从剪贴板填入</button>
        </div>
      </section>
    </div>
    <div id="st-proxies" class="settings-tab-panel" role="tabpanel" aria-labelledby="tab-proxies" style="display:none"></div>`;
  renderStatsData(s);
  switchStatsTab(statsTabFromHash());
  statsTimer = setInterval(async () => {
    try {
      const fresh = await api("/api/stats");
      renderStatsData(fresh);
    } catch {
      /* 后台刷新失败不打扰，等下一轮 */
    }
  }, 30000);
}

function renderStatsData(s) {
  const banner = cookieRepairBanner(s);
  const cards = $("#stats-cards");
  if (cards) {
    const existing = cards.previousElementSibling;
    if (existing && existing.classList.contains("notice-warn")) existing.remove();
    if (banner) cards.insertAdjacentHTML("beforebegin", banner);
  }
  const cookieInline = $("#cookie-repair-inline");
  if (cookieInline) cookieInline.innerHTML = banner;
  if (cards) {
    cards.innerHTML = `
      <div class="dash-stats">
        ${statCard("轮询间隔", `${s.polling_interval_seconds} 秒`)}
        ${statCard("最近抓取", fmtTs(s.last_poll_at))}
        ${statCard("抓取耗时", s.last_poll_duration_ms ? `${(Number(s.last_poll_duration_ms) / 1000).toFixed(1)} 秒` : "-")}
        ${statCard("大V / 启用", `${s.kols} / ${s.enabled_kols}`)}
        ${statCard("活跃抓取", s.active_kols ?? "-")}
        ${statCard("优先大V", s.priority_kols)}
        ${statCard("次要大V", s.secondary_kols)}
        ${statCard("用户 / 帖子", `${s.users} / ${s.posts}`)}
      </div>`;
  }
  const pollErr = $("#stats-poll-error");
  if (pollErr) {
    pollErr.innerHTML = s.last_poll_error
      ? `<div class="notice" style="margin-top:16px">最近轮询异常：${escapeHtml(s.last_poll_error)}</div>`
      : "";
  }
  const ops = $("#stats-ops");
  if (ops) {
    const alerts = s.alerts || {};
    const chips = [
      s.retry_pending
        ? `<span class="channel-status status-warn"><i class="dot"></i>待重试推送 ${s.retry_pending} 条</span>`
        : `<span class="channel-status status-ok"><i class="dot"></i>重试队列空闲</span>`,
    ];
    if (alerts.push_alert_last_at) chips.push(`<span class="channel-status status-warn"><i class="dot"></i>推送告警 ${fmtTs(alerts.push_alert_last_at)}</span>`);
    if (alerts.x_direct_alert_at) chips.push(`<span class="channel-status status-warn"><i class="dot"></i>X失败告警 ${fmtTs(alerts.x_direct_alert_at)}</span>`);
    if (alerts.cookie_keepalive_alert_at) chips.push(`<span class="channel-status status-warn"><i class="dot"></i>cookie保活告警 ${fmtTs(alerts.cookie_keepalive_alert_at)}</span>`);
    if (alerts.xueqiu_probe_alert_at) chips.push(`<span class="channel-status status-warn"><i class="dot"></i>雪球探测告警 ${fmtTs(alerts.xueqiu_probe_alert_at)}</span>`);
    ops.innerHTML = `<div class="row" style="gap:10px;flex-wrap:wrap">${chips.join("")}</div>`;
  }
  const tbody = $("#sources-table");
  if (tbody) {
    tbody.innerHTML = (s.sources || []).map((src) => {
      const channel = src.platform === "twitter"
        ? (src.direct_mode === "direct"
            ? '<span class="status-ok">直抓</span>'
            : src.direct_mode === "fallback"
              ? '<span class="status-warn" title="' + escapeHtml(src.direct_fallback_reason || "") + '">直抓失败</span>'
              : '<span class="muted">-</span>')
        : '<span class="muted">-</span>';
      return `
        <tr>
          <td>${PLATFORM_LABELS[src.platform] || escapeHtml(src.platform)}</td>
          <td class="${src.ok ? "status-ok" : "status-fail"}">${src.ok ? "正常" : "无成功记录"}</td>
          <td>${channel}</td>
          <td>${rateBar(src.success_rate_24h)}</td>
          <td>${src.ok_24h} / ${src.fail_24h}${src.warn_24h ? ` <span class="status-warn">⚠${src.warn_24h}</span>` : ""}</td>
          <td class="${src.consecutive_fails >= 3 ? "status-fail" : ""}">${src.consecutive_fails}</td>
          <td>${fmtTs(src.last_ok_at)}</td>
          <td>${src.next_retry_at ? fmtTs(src.next_retry_at) : "-"}</td>
          <td class="muted" title="${escapeHtml(src.last_error || "")}">${src.last_error ? escapeHtml(src.last_error.slice(0, 40)) : "-"}</td>
        </tr>`;
    }).join("");
  }
  const events = $("#source-events");
  if (events) {
    const rows = s.recent_source_events || [];
    events.innerHTML = rows.length
      ? `<div class="table-wrap"><table>
          <thead><tr><th scope="col">时间</th><th scope="col">平台</th><th scope="col">状态</th><th scope="col">详情</th></tr></thead>
          <tbody>${rows.map((e) => `
            <tr>
              <td class="muted">${escapeHtml(fmtDbTime(e.created_at))}</td>
              <td>${PLATFORM_LABELS[e.platform] || escapeHtml(e.platform)}</td>
              <td>${e.status === "ok"
                ? '<span class="status-ok">正常</span>'
                : e.status === "warn"
                  ? '<span class="status-warn">警告</span>'
                  : '<span class="status-fail">失败</span>'}</td>
              <td class="muted">${escapeHtml(e.detail)}</td>
            </tr>`).join("")}</tbody>
        </table></div>`
      : emptyState("暂无事件，抓取正常运行中");
  }
  const kh = $("#kol-health");
  if (kh) {
    const rows = s.kol_health || [];
    kh.innerHTML = rows.length
      ? `<div class="table-wrap"><table>
          <thead><tr><th scope="col">大V</th><th scope="col">平台</th><th scope="col">状态</th><th scope="col">最近抓到新帖</th></tr></thead>
          <tbody>${rows.map((h) => `
            <tr>
              <td>${escapeHtml(h.name)}</td>
              <td>${PLATFORM_LABELS[h.platform] || escapeHtml(h.platform)}</td>
              <td>${h.enabled
                ? (h.last_post_at
                    ? '<span class="status-ok">正常</span>'
                    : '<span class="status-warn">从未抓到</span>')
                : '<span class="status-fail">已停用</span>'}</td>
              <td class="muted">${h.last_post_at ? escapeHtml(fmtDbTime(h.last_post_at)) : "-"}</td>
            </tr>`).join("")}</tbody>
        </table></div>`
      : emptyState("还没有添加大V");
  }
  const refreshAt = $("#stats-refresh-at");
  if (refreshAt) refreshAt.textContent = `更新于 ${new Date().toLocaleTimeString()}`;
}

async function savePollingConfig() {
  const body = {
    interval_seconds: Number($("#pc-interval").value),
    priority_interval_seconds: Number($("#pc-priority").value),
    digest_interval_seconds: Number($("#pc-digest").value),
    source_probe_interval_seconds: Number($("#pc-probe").value),
    cookie_keepalive_interval_seconds: Number($("#pc-keepalive").value),
    daily_report_hour: Number($("#pc-daily").value),
    translate_twitter_content: $("#pc-translate").checked,
    combination_base_seconds: Number($("#pc-cb").value),
    combination_idle_cap_seconds: Number($("#pc-cc").value),
    normal_idle_cap_seconds: Number($("#pc-nc").value),
    priority_idle_cap_seconds: Number($("#pc-pc").value),
    x_fallback_cap_seconds: Number($("#pc-xc").value),
    secondary_interval_seconds: Number($("#pc-si").value),
    secondary_idle_cap_seconds: Number($("#pc-sc").value),
    secondary_digest_interval_seconds: Number($("#pc-sd").value),
    secondary_min_digest_count: Number($("#pc-sd-min").value),
  };
  try {
    await api("/api/admin/polling-config", { method: "PUT", body: JSON.stringify(body) });
    // 标准操作反馈 toast；不重建页面（loadAdminStats 会整页重建并跳回监控总览）
    flash("抓取设置已保存，即时生效");
  } catch (err) {
    flash(err.message, "error");
  }
}

async function pasteCookieField(inputId) {
  const el = $("#" + inputId);
  if (!el) return;
  try {
    const text = (await navigator.clipboard.readText()).trim();
    if (!text) {
      flash("剪贴板是空的", "error");
      return;
    }
    el.value = text;
    el.focus();
    flash("已填入，确认后点保存");
  } catch {
    flash("无法读剪贴板，请直接粘贴到输入框", "error");
  }
}

function proxyStatusLabel(status) {
  return { unknown: "未测", ok: "可用", dead: "失效" }[status] || "未知";
}

function proxyStatusClass(status) {
  return { ok: "status-ok", dead: "status-fail" }[status] || "";
}

function proxyOptionLabel(row) {
  const auth = row.username ? `${escapeHtml(row.username)}@` : "";
  return `#${row.id} ${row.protocol} ${auth}${escapeHtml(row.host)}:${row.port}`;
}

function proxyBusy(btn, on) {
  if (!btn) return false;
  if (on && btn.disabled) return true;
  btn.disabled = on;
  return false;
}

async function loadProxyAdmin() {
  const box = $("#st-proxies");
  if (!box) return;
  const drafts = {};
  document.querySelectorAll("textarea[id^='pp-import-']").forEach((el) => {
    if (el.value) drafts[el.id] = el.value;
  });
  try {
    const [routes, pools, proxies] = await Promise.all([
      api("/api/admin/proxy-routes"),
      api("/api/admin/proxy-pools"),
      api("/api/admin/proxies"),
    ]);
    box.innerHTML = renderProxyAdmin(routes, pools.items || [], proxies.items || []);
    Object.entries(drafts).forEach(([id, text]) => {
      const el = document.getElementById(id);
      if (el) el.value = text;
    });
    ["xueqiu", "combination", "weibo", "twitter"].forEach((p) => {
      const r = routes[p] || {};
      if (r.pool_id && $(`#pr-${p}-pool`)) $(`#pr-${p}-pool`).value = String(r.pool_id);
      if (r.proxy_id && $(`#pr-${p}-proxy`)) $(`#pr-${p}-proxy`).value = String(r.proxy_id);
      syncProxyRouteInputs(p);
    });
  } catch (err) {
    box.innerHTML = `<p class="muted">${escapeHtml(err.message || "加载代理失败")}</p>
      <div class="toolbar"><button type="button" class="btn-ghost" onclick="loadProxyAdmin()">重试</button></div>`;
  }
}

function renderProxyAdmin(routes, pools, proxies) {
  const platforms = ["xueqiu", "combination", "weibo", "twitter"];
  const poolOpts = pools.length
    ? pools.map((p) => `<option value="${p.id}">${escapeHtml(p.name)}（${p.proxy_count}）</option>`).join("")
    : `<option value="">先创建代理池</option>`;
  const proxyOpts = proxies.length
    ? proxies.map((p) => `<option value="${p.id}">${proxyOptionLabel(p)}</option>`).join("")
    : `<option value="">先导入或提取代理</option>`;
  const routeRows = platforms.map((p) => {
    const r = routes[p] || { mode: "direct" };
    const label = PLATFORM_LABELS[p];
    return `<div class="proxy-route">
      <label class="cfg-field">
        <span>${label}</span>
        <select id="pr-${p}-mode" class="form-control" onchange="syncProxyRouteInputs('${p}')">
          <option value="direct"${r.mode === "direct" ? " selected" : ""}>直连</option>
          <option value="pool"${r.mode === "pool" ? " selected" : ""}>指定池</option>
          <option value="proxy"${r.mode === "proxy" ? " selected" : ""}>指定代理</option>
        </select>
      </label>
      <label class="cfg-field" id="pr-${p}-pool-wrap"${r.mode === "pool" ? "" : " hidden"}>
        <span>代理池</span>
        <select id="pr-${p}-pool" class="form-control" aria-label="${label} 代理池">${poolOpts}</select>
      </label>
      <label class="cfg-field" id="pr-${p}-proxy-wrap"${r.mode === "proxy" ? "" : " hidden"}>
        <span>指定代理</span>
        <select id="pr-${p}-proxy" class="form-control" aria-label="${label} 指定代理">${proxyOpts}</select>
      </label>
    </div>`;
  }).join("");
  const poolCards = pools.map((p) => {
    const rows = proxies.filter((x) => x.pool_id === p.id);
    const lines = rows.map((x) => {
      const statusClass = proxyStatusClass(x.status);
      return `<tr>
      <td class="ak-hide-mobile" data-label="协议">${escapeHtml(x.protocol)}</td>
      <td data-label="地址">${escapeHtml(x.host)}:${x.port}</td>
      <td class="ak-hide-mobile" data-label="账号">${escapeHtml(x.username || "—")}</td>
      <td data-label="状态"${statusClass ? ` class="${statusClass}"` : ""}>${escapeHtml(proxyStatusLabel(x.status))}</td>
      <td class="ak-hide-mobile" data-label="来源">${x.source === "extract" ? "提取" : "手动"}</td>
      <td data-label="过期">${x.expires_at ? fmtTs(x.expires_at) : "—"}</td>
      <td class="ak-actions" data-label="操作">
        <button type="button" class="btn-sm" data-proxy-test="${x.id}" onclick="testProxyNode(${x.id})">测试</button>
        <button type="button" class="btn-sm danger" onclick="deleteProxyNode(${x.id})">删除</button>
      </td>
    </tr>`;
    }).join("");
    const extract = p.kind === "extract"
      ? `<p class="section-meta proxy-extract-url">提取 ${escapeHtml(p.extract_url || "未填")}${p.last_error ? ` · 上次错误 ${escapeHtml(p.last_error)}` : ""}</p>
         <div class="toolbar"><button type="button" class="btn-ghost" data-proxy-extract="${p.id}" onclick="extractProxyPool(${p.id})">立即提取</button></div>`
      : "";
    return `<section class="section-panel">
      <header class="section-head rc-list-head"><div>
        <h3 class="section-title">${escapeHtml(p.name)} <span class="hint">${p.kind === "extract" ? "提取池" : "静态池"} · ${escapeHtml(p.protocol)}</span></h3>
        ${extract}
      </div>
      <button type="button" class="btn-ghost danger" onclick="deleteProxyPool(${p.id})">删除池</button></header>
      <label class="form-label" for="pp-import-${p.id}"><span>导入节点</span>
        <textarea id="pp-import-${p.id}" class="form-control cookie-paste proxy-import" rows="3" placeholder="host:port 或 socks5://user:pass@host:port，一行一条"></textarea>
      </label>
      <div class="toolbar">
        <button type="button" class="btn-normal" data-proxy-import="${p.id}" onclick="importProxyPool(${p.id})">导入</button>
      </div>
      <div class="table-wrap proxy-nodes-wrap">
        <table class="ak-table proxy-nodes">
          <thead><tr><th>协议</th><th>地址</th><th>账号</th><th>状态</th><th>来源</th><th>过期</th><th>操作</th></tr></thead>
          <tbody>${lines || `<tr class="ak-empty"><td colspan="7" class="muted">还没有节点，先导入或提取。</td></tr>`}</tbody>
        </table>
      </div>
    </section>`;
  }).join("");
  return `
    <section class="section-panel">
      <header class="section-head"><div>
        <h3 class="section-title">抓取出口</h3>
        <p class="section-meta">按平台选择直连、指定池或指定代理。组合与雪球常同出口，但不强制绑定。池空时本轮抓取失败，不会偷偷直连。</p>
      </div></header>
      <div class="cfg-fields">${routeRows}</div>
      <div class="cfg-save-row"><button type="button" class="btn-normal" id="pr-save" onclick="saveProxyRoutes()">保存出口</button></div>
    </section>
    <section class="section-panel">
      <header class="section-head"><div>
        <h3 class="section-title">新建代理池</h3>
        <p class="section-meta">静态池粘贴导入；提取池填商家提取 URL（一行一个 IP），按过期秒数刷新。</p>
      </div></header>
      <div class="cfg-fields">
        <label class="cfg-field"><span>名称</span><input id="pp-name" class="form-control" maxlength="40" placeholder="海外S5"></label>
        <label class="cfg-field"><span>类型</span>
          <select id="pp-kind" class="form-control" onchange="syncProxyPoolForm()">
            <option value="static">静态</option>
            <option value="extract">提取 URL</option>
          </select>
        </label>
        <label class="cfg-field"><span>协议</span>
          <select id="pp-protocol" class="form-control">
            <option value="http">HTTP</option>
            <option value="socks5">SOCKS5</option>
          </select>
        </label>
        <label class="cfg-field" id="pp-extract-wrap" hidden><span>提取 URL</span><input id="pp-extract-url" class="form-control" placeholder="https://api.example.com/get?key="></label>
        <label class="cfg-field" id="pp-expire-wrap" hidden><span>过期<span class="cfg-unit">秒</span></span><input id="pp-expire" type="number" class="form-control" min="0" value="300"></label>
        <label class="cfg-field" id="pp-refresh-wrap" hidden><span>刷新<span class="cfg-unit">秒</span></span><input id="pp-refresh" type="number" class="form-control" min="0" value="180"></label>
      </div>
      <div class="cfg-save-row"><button type="button" class="btn-normal" id="pp-create" onclick="createProxyPool()">创建</button></div>
    </section>
    ${poolCards || `<p class="muted">还没有代理池。先创建一个，再导入或提取。</p>`}`;
}

function syncProxyRouteInputs(platform) {
  const mode = $(`#pr-${platform}-mode`)?.value;
  const poolWrap = $(`#pr-${platform}-pool-wrap`);
  const proxyWrap = $(`#pr-${platform}-proxy-wrap`);
  if (poolWrap) poolWrap.hidden = mode !== "pool";
  if (proxyWrap) proxyWrap.hidden = mode !== "proxy";
}

function syncProxyPoolForm() {
  const extract = $("#pp-kind")?.value === "extract";
  ["pp-extract-wrap", "pp-expire-wrap", "pp-refresh-wrap"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.hidden = !extract;
  });
}

async function saveProxyRoutes() {
  const body = {};
  for (const p of ["xueqiu", "combination", "weibo", "twitter"]) {
    const mode = $(`#pr-${p}-mode`).value;
    body[p] = { mode };
    if (mode === "pool") {
      const poolId = $(`#pr-${p}-pool`).value;
      if (!poolId) {
        flash("请先创建代理池", "error");
        return;
      }
      body[p].pool_id = Number(poolId);
    }
    if (mode === "proxy") {
      const proxyId = $(`#pr-${p}-proxy`).value;
      if (!proxyId) {
        flash("请先导入或提取代理", "error");
        return;
      }
      body[p].proxy_id = Number(proxyId);
    }
  }
  const btn = $("#pr-save");
  if (proxyBusy(btn, true)) return;
  try {
    await api("/api/admin/proxy-routes", { method: "PUT", body: JSON.stringify(body) });
    flash("抓取出口已保存");
    loadProxyAdmin();
  } catch (err) {
    flash(err.message || "保存失败", "error");
  } finally {
    if (btn && document.body.contains(btn)) btn.disabled = false;
  }
}

async function createProxyPool() {
  const name = $("#pp-name").value.trim();
  if (!name) {
    flash("请填写代理池名称", "error");
    return;
  }
  const kind = $("#pp-kind").value;
  if (kind === "extract" && !$("#pp-extract-url").value.trim()) {
    flash("提取池需要填写提取 URL", "error");
    return;
  }
  const btn = $("#pp-create");
  if (proxyBusy(btn, true)) return;
  try {
    await api("/api/admin/proxy-pools", {
      method: "POST",
      body: JSON.stringify({
        name,
        kind,
        protocol: $("#pp-protocol").value,
        extract_url: $("#pp-extract-url").value,
        expire_seconds: Number($("#pp-expire").value || 0),
        refresh_interval_seconds: Number($("#pp-refresh").value || 0),
      }),
    });
    flash("代理池已创建");
    loadProxyAdmin();
  } catch (err) {
    flash(err.message || "创建失败", "error");
  } finally {
    if (btn && document.body.contains(btn)) btn.disabled = false;
  }
}

async function importProxyPool(poolId) {
  const text = $(`#pp-import-${poolId}`)?.value || "";
  if (!text.trim()) {
    flash("请先粘贴要导入的代理", "error");
    return;
  }
  const btn = document.querySelector(`[data-proxy-import="${poolId}"]`);
  if (proxyBusy(btn, true)) return;
  try {
    const result = await api(`/api/admin/proxy-pools/${poolId}/import`, {
      method: "POST",
      body: JSON.stringify({ text }),
    });
    const ta = $(`#pp-import-${poolId}`);
    if (ta) ta.value = "";
    flash(`导入 ${result.imported} 条`);
    loadProxyAdmin();
  } catch (err) {
    flash(err.message || "导入失败", "error");
  } finally {
    if (btn && document.body.contains(btn)) btn.disabled = false;
  }
}

async function extractProxyPool(poolId) {
  const btn = document.querySelector(`[data-proxy-extract="${poolId}"]`);
  if (proxyBusy(btn, true)) return;
  try {
    const result = await api(`/api/admin/proxy-pools/${poolId}/extract`, { method: "POST" });
    flash(`提取 ${result.imported} 条`);
    loadProxyAdmin();
  } catch (err) {
    flash(err.message || "提取失败", "error");
  } finally {
    if (btn && document.body.contains(btn)) btn.disabled = false;
  }
}

async function deleteProxyPool(poolId) {
  if (!confirm("删除这个代理池及其节点？")) return;
  try {
    await api(`/api/admin/proxy-pools/${poolId}`, { method: "DELETE" });
    flash("已删除");
    loadProxyAdmin();
  } catch (err) {
    flash(err.message || "删除失败", "error");
  }
}

async function deleteProxyNode(proxyId) {
  if (!confirm("删除后需要重新导入。确定删除这个节点？")) return;
  try {
    await api(`/api/admin/proxies/${proxyId}`, { method: "DELETE" });
    flash("已删除");
    loadProxyAdmin();
  } catch (err) {
    flash(err.message || "删除失败", "error");
  }
}

async function testProxyNode(proxyId) {
  const btn = document.querySelector(`[data-proxy-test="${proxyId}"]`);
  if (proxyBusy(btn, true)) return;
  try {
    const result = await api(`/api/admin/proxies/${proxyId}/test`, { method: "POST" });
    flash(result.ok ? "测试成功" : (result.error || `测试失败 ${result.status_code || ""}`), result.ok ? "success" : "error");
    await loadProxyAdmin();
  } catch (err) {
    flash(err.message || "测试失败", "error");
    if (btn && document.body.contains(btn)) btn.disabled = false;
  }
}

async function saveXueqiuCookie() {
  const cookie = $("#xq-cookie").value.trim();
  if (!cookie) {
    flash("请先粘贴雪球 Cookie", "error");
    return;
  }
  try {
    await api("/api/admin/xueqiu-cookie", {
      method: "POST",
      body: JSON.stringify({ cookie }),
    });
    flash("雪球 Cookie 已保存，即时生效");
    history.replaceState(null, "", "#/admin/stats?tab=cookies");
    await loadAdminStats();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function saveTwitterCookie() {
  const cookie = $("#tw-cookie").value.trim();
  if (!cookie) {
    flash("请先粘贴 X Cookie", "error");
    return;
  }
  try {
    await api("/api/admin/twitter-cookie", {
      method: "POST",
      body: JSON.stringify({ cookie }),
    });
    flash("X Cookie 已保存，即时生效");
    history.replaceState(null, "", "#/admin/stats?tab=cookies");
    await loadAdminStats();
  } catch (err) {
    flash(err.message, "error");
  }
}

let wbQrTimer = null;
let wbQrSeq = 0;

async function startWeiboQr() {
  try {
    const data = await api("/api/admin/weibo-qr/start", { method: "POST" });
    $("#wb-qr-box").innerHTML = `
      <div class="qr-card">
        <img src="${escapeHtml(data.qrurl)}" alt="微博登录二维码" width="220" height="220">
      </div>
      <p class="muted qr-status" id="wb-qr-status">等待扫码…</p>`;
    if (wbQrTimer) clearTimeout(wbQrTimer);
    const seq = ++wbQrSeq;
    const tick = async () => {
      if (seq !== wbQrSeq) return;
      const cont = await pollWeiboQr(data.qrid);
      if (seq !== wbQrSeq || !cont) return;
      wbQrTimer = setTimeout(tick, 2000);
    };
    wbQrTimer = setTimeout(tick, 2000);
  } catch (err) {
    flash(err.message, "error");
  }
}

async function pollWeiboQr(qrid) {
  try {
    const data = await api(`/api/admin/weibo-qr/status?qrid=${encodeURIComponent(qrid)}`);
    const statusEl = $("#wb-qr-status");
    if (!statusEl) return false;
    if (data.status === "pending") {
      statusEl.textContent = "等待扫码…";
      return true;
    }
    if (data.status === "scanned") {
      statusEl.textContent = "已扫描，请在手机上确认登录";
      return true;
    }
    if (data.status === "ok") {
      statusEl.textContent = "登录成功，微博 Cookie 已自动保存";
      flash("微博 Cookie 已保存");
    }
    return false;
  } catch (err) {
    const statusEl = $("#wb-qr-status");
    if (statusEl) statusEl.textContent = "登录失败：" + err.message;
    return false;
  }
}

function statCard(label, value) {
  return `
    <div class="dash-stat">
      <div class="dash-stat-label">${escapeHtml(label)}</div>
      <div class="dash-stat-value">${escapeHtml(String(value))}</div>
    </div>`;
}

async function loadAdminDashboard() {
  try {
    const [d, st] = await Promise.all([api("/api/admin/dashboard"), api("/api/stats")]);
    const u = d.users || {};
    const s = d.subscriptions || {};
    const p = d.posts || {};
    const pu = d.pushes || {};
    const CHANNEL_LABELS_LOOKUP = { telegram: "Telegram", feishu: "飞书", wecom: "企业微信" };
    const rate = pu.success_rate != null ? `${pu.success_rate}%` : "—";

    // 14 天推送趋势柱状图（纯 CSS，零依赖）
    const trend = pu.trend_14d || [];
    const maxPushed = Math.max(1, ...trend.map((t) => t.pushed));
    const trendHtml = trend.length
      ? `<div class="dash-trend" role="list" aria-label="近 14 天推送趋势">${trend.map((t) => {
          const fail = Math.max(0, t.pushed - t.ok);
          // 红/绿分别按失败数/成功数相对最大值定高，二者之和 = 总推送量高度，不会溢出
          const failPct = Math.floor((fail / maxPushed) * 100);
          const okPct = Math.floor((t.ok / maxPushed) * 100);
          const tip = `${t.date}：推送 ${t.pushed} 条，成功 ${t.ok}，失败 ${fail}`;
          return `<div class="dash-trend-col" role="listitem" title="${escapeHtml(tip)}" aria-label="${escapeHtml(tip)}">
            <div class="dash-trend-bar">
              <div class="dash-trend-fail" style="height:${failPct}%"></div>
              <div class="dash-trend-ok" style="height:${okPct}%"></div>
            </div>
            <div class="dash-trend-date">${escapeHtml(t.date.slice(5))}</div>
          </div>`;
        }).join("")}</div>`
      : `<p class="muted">近 14 天暂无推送记录</p>`;

    // 平台来源分布
    const platformRows = Object.entries(p.by_platform || {}).map(([k, v]) => {
      const total = p.total || 1;
      const w = Math.round((v / total) * 100);
      return `<div class="dash-bar-row">
        <span class="dash-bar-label">${PLATFORM_LABELS[k] || escapeHtml(k)}</span>
        <div class="dash-bar-track"><div class="dash-bar-fill" style="width:${w}%"></div></div>
        <span class="dash-bar-value">${v}</span>
      </div>`;
    }).join("");

    // 渠道推送成功率
    const channelRows = Object.entries(pu.by_channel || {}).map(([k, v]) => {
      const r = v.total ? Math.round((v.ok / v.total) * 100) : 0;
      return `<div class="dash-bar-row">
        <span class="dash-bar-label">${CHANNEL_LABELS_LOOKUP[k] || escapeHtml(k)}</span>
        <div class="dash-bar-track"><div class="dash-bar-fill ${r < 90 ? "warn" : ""}" style="width:${r}%"></div></div>
        <span class="dash-bar-value">${v.ok}/${v.total}（${r}%）</span>
      </div>`;
    }).join("");

    // 数据源健康：各平台状态表 + 24h 事件流（复用 /api/stats 的实时指标）
    const sources = st.sources || [];
    const srcRows = sources.length
      ? sources.map((src) => {
          const statusCls = src.ok ? "status-ok" : "status-fail";
          const statusText = src.ok ? "正常" : src.consecutive_fails >= 3 ? "持续失败" : "无成功记录";
          const channel =
            src.platform === "twitter"
              ? src.direct_mode === "direct"
                ? '<span class="status-ok">直抓</span>'
                : src.direct_mode === "fallback"
                  ? `<span class="status-warn" title="${escapeHtml(src.direct_fallback_reason || "")}">直抓失败</span>`
                  : '<span class="muted">-</span>'
              : '<span class="muted">-</span>';
          return `<tr>
            <td>${PLATFORM_LABELS[src.platform] || escapeHtml(src.platform)}</td>
            <td class="${statusCls}">${statusText}</td>
            <td>${channel}</td>
            <td>${rateBar(src.success_rate_24h)}</td>
            <td class="${src.consecutive_fails >= 3 ? "status-fail" : ""}">${src.consecutive_fails}</td>
            <td class="muted" title="${escapeHtml(src.last_error || "")}">${src.last_error ? escapeHtml(src.last_error.slice(0, 34)) : "-"}</td>
          </tr>`;
        }).join("")
      : '<tr><td colspan="6" class="muted">暂无数据源</td></tr>';
    const events = (st.recent_source_events || []).slice(0, 6);
    const eventRows = events.length
      ? events.map((e) => `<div class="dash-event">
          <span class="dash-event-dot ${escapeHtml(e.status)}"></span>
          <span class="muted dash-event-time">${escapeHtml(fmtDbTime(e.created_at))}</span>
          <span class="dash-event-platform">${PLATFORM_LABELS[e.platform] || escapeHtml(e.platform)}</span>
          <span class="${e.status === "ok" ? "status-ok" : e.status === "warn" ? "status-warn" : "status-fail"}">${e.status === "ok" ? "正常" : e.status === "warn" ? "警告" : "失败"}</span>
          <span class="muted dash-event-detail" title="${escapeHtml(e.detail || "")}">${escapeHtml(e.detail || "")}</span>
        </div>`).join("")
      : `<p class="muted">近 24 小时无异常事件</p>`;

    if (!routeStillActive(_adminRenderSeq)) return;
    $("#admin-body").innerHTML = `
      <section class="section-panel">
        <header class="section-head"><div><h3 class="section-title">核心指标</h3>
        <p class="section-meta">用户、订阅与推送的业务总览（推送统计为近 7 天）。</p></div></header>
        <div class="dash-stats">
          ${statCard("注册用户", u.total || 0)}
          ${statCard("绑定渠道用户", u.bound || 0)}
          ${statCard("订阅数", s.total || 0)}
          ${statCard("近 7 天推送", pu.total_7d || 0)}
          ${statCard("推送成功率", rate)}
          ${statCard("帖子总量", p.total || 0)}
        </div>
      </section>
      <section class="section-panel">
        <header class="section-head"><div><h3 class="section-title">近 14 天推送趋势</h3>
        <p class="section-meta">每日推送条数（绿色=成功，红色=失败）。</p></div></header>
        ${trendHtml}
      </section>
      <div class="dash-split">
        <section class="section-panel">
          <header class="section-head"><div><h3 class="section-title">帖子来源分布</h3>
          <p class="section-meta">累计抓取帖子按平台。</p></div></header>
          ${platformRows || `<p class="muted">暂无帖子</p>`}
        </section>
        <section class="section-panel">
          <header class="section-head"><div><h3 class="section-title">渠道推送成功率（7 天）</h3>
          <p class="section-meta">各渠道成功/总数与成功率。</p></div></header>
          ${channelRows || `<p class="muted">近 7 天暂无推送</p>`}
        </section>
      </div>
      <section class="section-panel">
        <header class="section-head"><div><h3 class="section-title">数据源健康</h3>
        <p class="section-meta">各平台抓取状态与 24h 成功率，以及最近事件流。</p></div></header>
        <div class="table-wrap">
          <table>
            <thead><tr><th scope="col">平台</th><th scope="col">状态</th><th scope="col">通道</th><th scope="col">24h 成功率</th><th scope="col">连续失败</th><th scope="col">最近错误</th></tr></thead>
            <tbody>${srcRows}</tbody>
          </table>
        </div>
        ${eventRows ? `<div class="dash-events">${eventRows}</div>` : ""}
      </section>`;
  } catch (err) {
    if (!routeStillActive(_adminRenderSeq)) return;
    $("#admin-body").innerHTML = emptyState("加载失败: " + err.message,
      `<div><button class="btn-normal" onclick="loadAdminDashboard()">重试</button></div>`);
  }
}

let _adminKolsSeq = 0;
const _adminKolsPageSize = 50;
let _adminKolsSelected = new Set(); // 批量操作选中的大V id（跨页保留）

async function loadAdminKols(opts) {
  opts = opts || {};
  const seq = ++_adminKolsSeq;
  let data, categories;
  try {
    const params = new URLSearchParams({
      limit: String(_adminKolsPageSize),
      offset: String((state.adminKolsPage || 0) * _adminKolsPageSize),
    });
    if (state.adminKolsPlatform) params.set("platform", state.adminKolsPlatform);
    if (state.adminKolsCategory) params.set("category_id", state.adminKolsCategory);
    if (state.adminKolsStatus !== "") params.set("status", state.adminKolsStatus);
    if (state.adminKolsQ) params.set("q", state.adminKolsQ);
    [data, categories] = await Promise.all([api(`/api/admin/kols?${params}`), api("/api/categories")]);
  } catch (err) {
    if (!routeStillActive(_adminRenderSeq)) return;
    if (seq === _adminKolsSeq) $("#admin-body").innerHTML = emptyState("加载失败: " + err.message);
    return;
  }
  if (seq !== _adminKolsSeq) return; // 已切换筛选/翻页，丢弃过期响应
  const matchIds = new Set(data.ids || []);
  const focusIds = opts.focusIds || [];
  const visibleFocus = focusIds.filter((id) => matchIds.has(id));
  if (visibleFocus.length) {
    const idx = (data.ids || []).indexOf(visibleFocus[0]);
    const wantPage = Math.max(0, Math.floor(idx / _adminKolsPageSize));
    if (wantPage !== (state.adminKolsPage || 0)) {
      state.adminKolsPage = wantPage;
      return loadAdminKols({ focusIds: visibleFocus });
    }
  }
  const highlightIds = new Set(visibleFocus);
  const kols = data.items || [];
  state.adminKols = kols;
  state.adminKolsTotal = data.total || 0;
  for (const id of [..._adminKolsSelected]) {
    if (!matchIds.has(id)) _adminKolsSelected.delete(id);
  }
  const catOptions = categories.map((c) => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join("");
  const page = state.adminKolsPage || 0;
  const pages = Math.max(1, Math.ceil((data.total || 0) / _adminKolsPageSize));
  if (!routeStillActive(_adminRenderSeq)) return;
  const selCount = _adminKolsSelected.size;
  const rows = kols.map((k) => {
    const tier = k.priority ? "优先" : k.secondary ? "次要" : "普通";
    const orig = k.platform === "weibo"
      ? (k.original_only ? '<span class="status-ok">是</span>' : "否")
      : "—";
    const tierBtns = k.priority
      ? `<button class="btn-sm" onclick="adminTogglePriority(${k.id}, false)">改普通</button>
                <button class="btn-sm" onclick="adminToggleSecondary(${k.id}, true)">设次要</button>`
      : k.secondary
        ? `<button class="btn-sm" onclick="adminToggleSecondary(${k.id}, false)">改普通</button>
                <button class="btn-sm" onclick="adminTogglePriority(${k.id}, true)">设优先</button>`
        : `<button class="btn-sm" onclick="adminTogglePriority(${k.id}, true)">设优先</button>
                <button class="btn-sm" onclick="adminToggleSecondary(${k.id}, true)">设次要</button>`;
    return `
            <tr class="${highlightIds.has(k.id) ? "ak-row-flash" : ""}">
              <td class="ak-check"><input type="checkbox" class="kol-check" data-id="${k.id}" ${_adminKolsSelected.has(k.id) ? "checked" : ""} onchange="adminKolToggleSelect(this)" aria-label="选择 ${escapeHtml(k.name)}"></td>
              <td class="ak-hide-mobile" data-label="ID">${k.id}</td>
              <td data-label="平台">${PLATFORM_LABELS[k.platform] || k.platform}</td>
              <td data-label="昵称">${escapeHtml(k.name)}</td>
              <td data-label="分类">${escapeHtml(k.category_name || "")}</td>
              <td class="ak-hide-mobile" data-label="外部ID">${escapeHtml(k.external_id)}</td>
              <td data-label="档位">${tier}</td>
              <td class="ak-hide-mobile" data-label="原创">${orig}</td>
              <td data-label="可见性">${k.is_private ? '<span class="status-warn">私有</span>' : "公开"}</td>
              <td data-label="状态" class="${k.enabled ? "status-ok" : "status-fail"}">${k.enabled ? "启用" : "停用"}</td>
              <td class="ak-actions" data-label="操作">
                ${tierBtns}
                <button class="btn-sm" onclick="adminToggleKol(${k.id}, ${k.enabled ? 0 : 1})">${k.enabled ? "停用" : "启用"}</button>
                <button class="btn-sm" onclick="adminEditKol(${k.id})">编辑</button>
                <button class="btn-sm danger" onclick="adminDeleteKol(${k.id})">删除</button>
              </td>
            </tr>`;
  }).join("");
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">添加大V</h3></div>
        <div class="toolbar" style="margin-top:12px">
          <select id="ad-platform" class="form-control" style="margin:0;width:auto" aria-label="平台" onchange="adminPlatformDefaultCat(this)">
            <option value="xueqiu">雪球</option>
            <option value="combination">雪球组合</option>
            <option value="weibo">微博</option>
            <option value="twitter">X</option>
          </select>
          <select id="ad-category" class="form-control" style="margin:0;width:auto" aria-label="分类"><option value="">未分类</option>${catOptions}</select>
          <input id="ad-name" class="form-control" style="margin:0;width:200px" placeholder="昵称" aria-label="昵称">
          <input id="ad-external" class="form-control" style="margin:0;width:300px" placeholder="user_id / uid / X主页链接 / 雪球主页链接" aria-label="外部ID或主页链接">
          <button class="btn-normal" id="ad-add-btn" onclick="adminAddKol()">添加</button>
        </div>
      </header>
    </section>
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">批量导入大V</h3>
        <p class="section-meta">每行一个：昵称 + 主页链接/UID（昵称可省略）。自动识别平台：雪球主页→雪球、雪球组合页→雪球组合、微博主页→微博、X 主页→X；纯 UID 等无法识别的行使用下方默认平台。如：<code>段永平 https://xueqiu.com/u/12345</code></p></div>
      </header>
      <textarea id="ad-batch-lines" class="form-control" rows="8" style="font-family:monospace;min-height:180px;resize:vertical" placeholder="https://xueqiu.com/u/12345&#10;段永平 12345&#10;https://weibo.com/u/1642591402&#10;https://x.com/elonmusk&#10;https://xueqiu.com/P/ZH123456"></textarea>
      <div class="toolbar" style="margin-top:12px">
        <label class="muted" for="ad-batch-platform">默认平台（未识别的行）</label>
        <select id="ad-batch-platform" class="form-control" style="margin:0;width:auto" aria-label="默认平台（未识别的行）" onchange="adminPlatformDefaultCat(this, '#ad-batch-category')">
          <option value="xueqiu">雪球</option>
          <option value="combination">雪球组合</option>
          <option value="weibo">微博</option>
          <option value="twitter">X</option>
        </select>
        <select id="ad-batch-category" class="form-control" style="margin:0;width:auto" aria-label="导入分类"><option value="">未分类</option>${catOptions}</select>
        <button class="btn-normal" id="ad-batch-btn" onclick="adminBatchAddKols()">批量导入</button>
        <div id="ad-batch-result" class="muted" style="white-space:pre-line"></div>
      </div>
    </section>
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">大V列表</h3>
        <p class="section-meta" id="admin-kols-meta">共 ${state.adminKolsTotal} 个大V · 优先约 60 秒抓一次，次要走低频摘要</p></div>
        <div class="toolbar ak-filters">
          <input id="ak-q" class="form-control" style="width:200px" placeholder="昵称 / 外部ID" value="${escapeHtml(state.adminKolsQ || "")}" onkeydown="if(event.key==='Enter')adminKolsApplyFilter()">
          <select id="ak-category" class="form-control" style="width:auto" onchange="adminKolsApplyFilter()"><option value="">全部分类</option>${catOptions}</select>
          <select id="ak-status" class="form-control" style="width:auto" onchange="adminKolsApplyFilter()">
            <option value="">全部状态</option>
            <option value="1" ${state.adminKolsStatus === "1" ? "selected" : ""}>启用</option>
            <option value="0" ${state.adminKolsStatus === "0" ? "selected" : ""}>停用</option>
          </select>
          <button type="button" class="btn-ghost ak-search-btn" onclick="adminKolsApplyFilter()">搜索</button>
          <button type="button" class="btn-ghost ak-clear-btn" onclick="adminKolsClearFilter()">清除</button>
        </div>
        <div class="platform-tabs ak-platform-tabs" id="admin-kols-tabs"></div>
      </header>
      <div class="toolbar admin-batch-bar" id="ak-batch-bar" style="margin-top:10px;display:${selCount ? "flex" : "none"};align-items:center;gap:8px;flex-wrap:wrap">
        <strong>已选 ${selCount} 个</strong>
        <button class="btn-sm" onclick="adminKolBatch('enable')">批量启用</button>
        <button class="btn-sm" onclick="adminKolBatch('disable')">批量停用</button>
        <button class="btn-sm" onclick="adminKolBatch('priority', true)">批量设优先</button>
        <button class="btn-sm" onclick="adminKolBatch('secondary', true)">批量设次要</button>
        <button class="btn-sm" onclick="adminKolBatch('normal')">批量设普通</button>
        <select id="ak-batch-category" class="form-control" style="width:auto"><option value="">批量改分类…</option>${catOptions}<option value="0">（清除分类）</option></select>
        <button class="btn-sm" onclick="adminKolBatchCategory()">应用分类</button>
        <button class="btn-sm danger" onclick="adminKolBatch('delete')">批量删除</button>
        <button class="btn-sm" onclick="adminKolClearSelect()">取消选择</button>
      </div>
      <div class="table-wrap">
        <table class="ak-table">
          <thead><tr><th scope="col" style="width:32px"><input type="checkbox" id="ak-checkall" onchange="adminKolTogglePage(this)" aria-label="全选当前页"></th><th scope="col">ID</th><th scope="col">平台</th><th scope="col">昵称</th><th scope="col">分类</th><th scope="col">外部ID</th><th scope="col">档位</th><th scope="col">原创</th><th scope="col">可见性</th><th scope="col">状态</th><th scope="col">操作</th></tr></thead>
          <tbody>${rows || `<tr class="ak-empty"><td colspan="11" class="muted">${state.adminKolsQ || state.adminKolsCategory || state.adminKolsStatus !== "" || state.adminKolsPlatform ? "没有匹配的大V" : "还没有大V，先用上方表单添加"}</td></tr>`}</tbody>
        </table>
      </div>
      <div class="toolbar" style="margin-top:12px;justify-content:center;gap:12px;align-items:center">
        <button class="btn-sm" ${page <= 0 ? "disabled" : ""} onclick="adminKolsPage(${page - 1})">← 上一页</button>
        <span class="muted">第 ${page + 1}/${pages} 页 · 共 ${state.adminKolsTotal} 个</span>
        <button class="btn-sm" ${page + 1 >= pages ? "disabled" : ""} onclick="adminKolsPage(${page + 1})">下一页 →</button>
      </div>
    </section>`;
  // 回填筛选控件当前值（页面重建后）
  const qEl = $("#ak-q"); if (qEl) qEl.value = state.adminKolsQ || "";
  const catEl = $("#ak-category"); if (catEl) catEl.value = state.adminKolsCategory || "";
  const statusEl = $("#ak-status"); if (statusEl) statusEl.value = state.adminKolsStatus ?? "";
  adminKolSyncCheckall(kols);
  $("#admin-kols-tabs").innerHTML = PLATFORM_TABS.map((p) => platformTabHTML(p, state.adminKolsPlatform, "switchAdminKolsPlatform")).join("");
  return { hiddenFocus: focusIds.length > 0 && visibleFocus.length === 0 };
}

function switchAdminKolsPlatform(platform) {
  const qEl = $("#ak-q");
  if (qEl) state.adminKolsQ = qEl.value.trim();
  state.adminKolsPlatform = platform;
  state.adminKolsPage = 0;
  loadAdminKols();
}

function adminKolsApplyFilter() {
  state.adminKolsQ = $("#ak-q").value.trim();
  state.adminKolsCategory = $("#ak-category").value;
  state.adminKolsStatus = $("#ak-status").value;
  state.adminKolsPage = 0;
  loadAdminKols();
}

function adminKolsClearFilter() {
  state.adminKolsQ = "";
  state.adminKolsCategory = "";
  state.adminKolsStatus = "";
  state.adminKolsPlatform = "";
  state.adminKolsPage = 0;
  loadAdminKols();
}

function adminKolSyncCheckall(kols) {
  const list = kols || state.adminKols || [];
  const checkall = $("#ak-checkall");
  if (!checkall) return;
  const pageSelected = list.filter((k) => _adminKolsSelected.has(k.id)).length;
  checkall.checked = !!list.length && pageSelected === list.length;
  checkall.indeterminate = pageSelected > 0 && pageSelected < list.length;
}

function adminKolsPage(page) {
  state.adminKolsPage = page;
  loadAdminKols();
}

function adminKolToggleSelect(el) {
  const id = Number(el.dataset.id);
  if (el.checked) _adminKolsSelected.add(id);
  else _adminKolsSelected.delete(id);
  const bar = $("#ak-batch-bar");
  if (bar) {
    bar.style.display = _adminKolsSelected.size ? "flex" : "none";
    const strong = bar.querySelector("strong");
    if (strong) strong.textContent = `已选 ${_adminKolsSelected.size} 个`;
  }
  adminKolSyncCheckall();
}

function adminKolTogglePage(el) {
  document.querySelectorAll(".kol-check").forEach((c) => {
    c.checked = el.checked;
    const id = Number(c.dataset.id);
    if (el.checked) _adminKolsSelected.add(id);
    else _adminKolsSelected.delete(id);
  });
  const bar = $("#ak-batch-bar");
  if (bar) {
    bar.style.display = _adminKolsSelected.size ? "flex" : "none";
    const strong = bar.querySelector("strong");
    if (strong) strong.textContent = `已选 ${_adminKolsSelected.size} 个`;
  }
  adminKolSyncCheckall();
}

function adminKolClearSelect() {
  _adminKolsSelected.clear();
  document.querySelectorAll(".kol-check").forEach((c) => { c.checked = false; });
  const bar = $("#ak-batch-bar");
  if (bar) bar.style.display = "none";
  const checkall = $("#ak-checkall");
  if (checkall) {
    checkall.checked = false;
    checkall.indeterminate = false;
  }
}

async function adminKolBatch(action, value) {
  const ids = [..._adminKolsSelected];
  if (!ids.length) return;
  if (action === "delete" && !confirm(`确认删除选中的 ${ids.length} 个大V？（将同时清理其订阅/帖子/推送记录）`)) return;
  const bar = $("#ak-batch-bar");
  const buttons = bar ? [...bar.querySelectorAll("button")] : [];
  buttons.forEach((b) => { b.disabled = true; });
  try {
    await api("/api/admin/kols/batch", {
      method: "POST",
      body: JSON.stringify({ ids, action, value: value ?? null }),
    });
    flash(action === "normal" ? `已将 ${ids.length} 个大V设为普通档` : `已对 ${ids.length} 个大V执行批量操作`);
    _adminKolsSelected.clear();
    loadAdminKols();
  } catch (err) {
    flash("批量操作失败: " + err.message, "error");
    buttons.forEach((b) => { b.disabled = false; });
  }
}

async function adminKolBatchCategory() {
  const value = $("#ak-batch-category").value;
  if (value === "") { flash("请选择要应用到的分类", "error"); return; }
  await adminKolBatch("category", value === "0" ? null : Number(value));
}

async function adminBatchAddKols() {
  const lines = $("#ad-batch-lines").value;
  if (!lines.trim()) {
    flash("请先粘贴要导入的大V链接/ID", "error");
    return;
  }
  const platform = $("#ad-batch-platform").value;
  const category = $("#ad-batch-category").value;
  const btn = $("#ad-batch-btn");
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/kols/batch", {
      method: "POST",
      body: JSON.stringify({
        platform,
        lines,
        category_id: category ? Number(category) : null,
      }),
    });
    const failLines = data.failed.map((f) => `${f.line} — ${f.error}`).join("\n");
    const view = await loadAdminKols({ focusIds: data.ids || [] });
    const resultEl = $("#ad-batch-result");
    if (resultEl) {
      resultEl.textContent = data.failed.length
        ? `成功 ${data.ok}/${data.total}，失败 ${data.failed.length} 条${failLines ? `\n${failLines}` : ""}`
        : `成功 ${data.ok}/${data.total}`;
      resultEl.style.color = data.failed.length ? "var(--color-danger)" : "var(--color-success)";
      resultEl.style.fontWeight = "600";
    }
    const hidden = view && view.hiddenFocus && data.ok;
    flash(data.failed.length
      ? `导入完成：成功 ${data.ok}/${data.total}，失败 ${data.failed.length} 条${hidden ? "，不在当前筛选里" : ""}`
      : hidden
        ? `导入成功：${data.ok} 个，不在当前筛选里`
        : `导入成功：${data.ok} 个`);
  } catch (err) {
    flash("批量导入失败: " + err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

// 雪球组合默认分类：实盘（选平台后自动填写）
function adminPlatformDefaultCat(sel, catSel) {
  if (sel.value !== "combination") return;
  const cat = $(catSel || "#ad-category");
  if (!cat) return;
  for (const opt of cat.options) {
    if (opt.textContent.trim() === "实盘") { cat.value = opt.value; break; }
  }
}

async function adminAddKol() {
  const name = $("#ad-name").value.trim();
  const platform = $("#ad-platform").value;
  const category = $("#ad-category").value;
  const external = $("#ad-external").value.trim();
  if (!external) {
    flash("请填写外部ID或主页链接", "error");
    return;
  }
  const btn = $("#ad-add-btn");
  if (btn) btn.disabled = true;
  try {
    const created = await api("/api/kols", {
      method: "POST",
      body: JSON.stringify({
        platform,
        name,
        external_id: external,
        category_id: category ? Number(category) : null,
      }),
    });
    const view = await loadAdminKols({ focusIds: created.id ? [created.id] : [] });
    const label = created.name || name || "未命名";
    flash(view && view.hiddenFocus ? `已添加「${label}」，不在当前筛选里` : `已添加「${label}」`);
  } catch (err) {
    flash("添加失败: " + err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function adminToggleKol(id, enabled) {
  const kol = state.adminKols.find((k) => k.id === id);
  try {
    await api(`/api/kols/${id}`, { method: "PUT", body: JSON.stringify({ enabled: !!enabled }) });
    flash(`已${enabled ? "启用" : "停用"}「${kol ? kol.name : "该大V"}」`);
    loadAdminKols();
  } catch (err) {
    flash("操作失败: " + err.message, "error");
  }
}

async function adminTogglePriority(id, priority) {
  const kol = state.adminKols.find((k) => k.id === id);
  try {
    await api(`/api/kols/${id}`, { method: "PUT", body: JSON.stringify({ priority: !!priority }) });
    flash(`已${priority ? "设为优先" : "改为普通档"}「${kol ? kol.name : "该大V"}」`);
    loadAdminKols();
  } catch (err) {
    flash("操作失败: " + err.message, "error");
  }
}

async function adminToggleSecondary(id, secondary) {
  const kol = state.adminKols.find((k) => k.id === id);
  try {
    await api(`/api/kols/${id}`, { method: "PUT", body: JSON.stringify({ secondary: !!secondary }) });
    flash(`已${secondary ? "设为次要" : "改为普通档"}「${kol ? kol.name : "该大V"}」`);
    loadAdminKols();
  } catch (err) {
    flash("操作失败: " + err.message, "error");
  }
}

async function adminDeleteKol(id) {
  const kol = state.adminKols.find((k) => k.id === id);
  const subs = Number(kol && kol.subscriber_count) || 0;
  if (!confirm(`确认删除该大V${kol ? `「${kol.name}」` : ""}？将同时清理 ${subs} 个订阅及其帖子/推送记录。`)) return;
  try {
    await api(`/api/kols/${id}`, { method: "DELETE" });
    flash(`已删除「${kol ? kol.name : "该大V"}」`);
    loadAdminKols();
  } catch (err) {
    flash("删除失败: " + err.message, "error");
  }
}

function adminKolEditSnapshot() {
  return JSON.stringify({
    name: $("#ek-name").value.trim(),
    category: $("#ek-category").value,
    priv: $("#ek-private").checked,
    orig: $("#ek-original") ? $("#ek-original").checked : false,
    users: $("#ek-users").value.trim(),
  });
}

async function adminEditKol(id) {
  let kol, categories;
  try {
    [kol, categories] = await Promise.all([api(`/api/kols/${id}`), api("/api/categories")]);
  } catch (err) {
    flash("加载失败: " + err.message, "error");
    return;
  }
  const catOptions = categories.map((c) => `<option value="${c.id}" ${kol.category_id === c.id ? "selected" : ""}>${escapeHtml(c.name)}</option>`).join("");
  const mask = document.createElement("div");
  mask.className = "modal-mask";
  mask.innerHTML = `
    <div class="modal-card" role="dialog" aria-modal="true" aria-labelledby="ek-title">
      <h3 id="ek-title" style="margin-bottom:12px">编辑大V：${escapeHtml(kol.name)}</h3>
      <label class="form-label">昵称
        <input id="ek-name" class="form-control" value="${escapeHtml(kol.name)}">
      </label>
      <label class="form-label">分类
        <select id="ek-category" class="form-control"><option value="">未分类</option>${catOptions}</select>
      </label>
      <label class="form-label" style="display:flex;align-items:center;gap:8px">
        <input id="ek-private" type="checkbox" ${kol.is_private ? "checked" : ""} onchange="document.getElementById('ek-users-wrap').hidden=!this.checked"> 私有大V（仅白名单用户可见/可订阅）
      </label>
      ${kol.platform === "weibo" ? `<label class="form-label" style="display:flex;align-items:center;gap:8px">
        <input id="ek-original" type="checkbox" ${kol.original_only ? "checked" : ""}> 只看原创（微博跳过转发，适合转发刷屏的大V）
      </label>` : ""}
      <label class="form-label" id="ek-users-wrap" ${kol.is_private ? "" : "hidden"}>白名单用户（逗号分隔用户名）
        <input id="ek-users" class="form-control" value="${escapeHtml((kol.visible_users || []).join(", "))}" placeholder="user1, user2">
      </label>
      <div class="toolbar" style="margin-top:16px">
        <button class="btn-normal" id="ek-save" onclick="saveKolEdit(${kol.id})">保存</button>
        <button type="button" class="btn-sm" data-close>取消</button>
      </div>
    </div>`;
  const initial = (() => {
    document.body.appendChild(mask);
    return adminKolEditSnapshot();
  })();
  const tryClose = () => {
    if (adminKolEditSnapshot() !== initial && !confirm("有未保存的修改，确定关闭？")) return;
    mask.remove();
  };
  mask.addEventListener("click", (e) => {
    if (e.target === mask) tryClose();
  });
  mask.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      e.preventDefault();
      tryClose();
      return;
    }
    if (e.key === "Tab") {
      const nodes = [...mask.querySelectorAll("button, input, select, textarea")].filter((el) => !el.disabled && !el.hidden && el.offsetParent);
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
  });
  mask.querySelector("[data-close]").addEventListener("click", tryClose);
  // 焦点管理：打开聚焦首个输入框；无论以哪种方式关闭，焦点都还原到触发按钮
  const trigger = document.activeElement;
  const firstInput = mask.querySelector("input, select, textarea, button");
  if (firstInput) firstInput.focus();
  const observer = new MutationObserver(() => {
    if (!document.body.contains(mask)) {
      observer.disconnect();
      if (trigger && trigger.isConnected) trigger.focus();
    }
  });
  observer.observe(document.body, { childList: true });
}

async function saveKolEdit(id) {
  const mask = document.querySelector(".modal-mask");
  const name = $("#ek-name").value.trim();
  const isPrivate = $("#ek-private").checked;
  const visibleUsers = $("#ek-users").value.split(",").map((s) => s.trim()).filter(Boolean);
  if (isPrivate && !visibleUsers.length) {
    if (!confirm("白名单为空，该大V将对所有人隐藏。仍要保存？")) return;
  }
  const body = {
    name,
    category_id: $("#ek-category").value ? Number($("#ek-category").value) : null,
    is_private: isPrivate,
    visible_users: visibleUsers,
  };
  if ($("#ek-original")) body.original_only = $("#ek-original").checked;
  const btn = $("#ek-save");
  if (btn) btn.disabled = true;
  try {
    await api(`/api/kols/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    if (mask) mask.remove();
    flash(`已保存「${name}」`);
    loadAdminKols();
  } catch (err) {
    flash("保存失败: " + err.message, "error");
    if (btn) btn.disabled = false;
  }
}

async function loadAdminRequests() {
  let requests, all;
  try {
    [requests, all] = await Promise.all([
      api("/api/admin/kol-requests?status=pending"),
      api("/api/admin/kol-requests"),
    ]);
  } catch (err) {
    if (!routeStillActive(_adminRenderSeq)) return;
    $("#admin-body").innerHTML = emptyState("加载失败: " + err.message);
    return;
  }
  const done = all.filter((r) => r.status !== "pending");
  const pendingRows = requests.length === 0
    ? `<tr><td colspan="8" class="muted">暂无待审批申请</td></tr>`
    : requests.map((r) => `
        <tr>
          <td>${r.id}</td><td>${PLATFORM_LABELS[r.platform] || r.platform}</td>
          <td>${escapeHtml(r.name || "（未填）")}</td><td>${escapeHtml(r.external_id)}</td>
          <td>${escapeHtml(r.category_name || "—")}</td>
          <td>${escapeHtml(r.requester || r.user_id)}</td><td>${escapeHtml(fmtDbTime(r.created_at))}</td>
          <td>
            <button class="btn-sm" onclick="adminApproveRequest(${r.id})">通过</button>
            <button class="btn-sm danger" onclick="adminRejectRequest(${r.id})">拒绝</button>
          </td>
        </tr>`).join("");
  const historyRows = done.length === 0
    ? `<tr><td colspan="8" class="muted">暂无处理记录</td></tr>`
    : done.map((r) => `
        <tr>
          <td>${r.id}</td><td>${PLATFORM_LABELS[r.platform] || r.platform}</td>
          <td>${escapeHtml(r.name || "（未填）")}</td><td>${escapeHtml(r.external_id)}</td>
          <td>${escapeHtml(r.category_name || "—")}</td>
          <td>${escapeHtml(r.requester || r.user_id)}</td>
          <td class="${r.status === "approved" ? "status-ok" : "status-fail"}">${r.status === "approved" ? "已通过" : "已拒绝"}</td>
          <td>${escapeHtml(fmtDbTime(r.handled_at))}</td>
        </tr>`).join("");
  if (!routeStillActive(_adminRenderSeq)) return;
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head"><div><h3 class="section-title">添加审批</h3>
      <p class="section-meta">用户申请添加的大V，审批通过后进入订阅广场。</p></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">ID</th><th scope="col">平台</th><th scope="col">昵称</th><th scope="col">外部ID</th><th scope="col">分类</th><th scope="col">申请人</th><th scope="col">申请时间</th><th scope="col">操作</th></tr></thead>
          <tbody>${pendingRows}</tbody>
        </table>
      </div>
    </section>
    <section class="section-panel">
      <header class="section-head"><div><h3 class="section-title">处理记录</h3></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">ID</th><th scope="col">平台</th><th scope="col">昵称</th><th scope="col">外部ID</th><th scope="col">分类</th><th scope="col">申请人</th><th scope="col">状态</th><th scope="col">处理时间</th></tr></thead>
          <tbody>${historyRows}</tbody>
        </table>
      </div>
    </section>`;
}

async function adminApproveRequest(id) {
  try {
    await api(`/api/admin/kol-requests/${id}/approve`, { method: "POST" });
    flash("已通过申请，大V已进入订阅广场");
    loadAdminRequests();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

async function adminRejectRequest(id) {
  if (!confirm("确认拒绝该申请？")) return;
  try {
    await api(`/api/admin/kol-requests/${id}/reject`, { method: "POST" });
    flash("已拒绝该申请");
    loadAdminRequests();
  } catch (err) {
    alert("操作失败: " + err.message);
  }
}

const _codesUi = {
  note: "",
  count: 5,
  expires: 7,
  filter: "available",
  q: "",
  result: null,
};

function parseDbUtcMs(s) {
  if (!s) return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2}):(\d{2})$/.exec(String(s));
  if (!m) return null;
  return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
}

function codeStatus(c) {
  if (c.used_by) return "used";
  if (c.revoked_at) return "revoked";
  const exp = parseDbUtcMs(c.expires_at);
  if (exp != null && exp <= Date.now()) return "expired";
  return "available";
}

function codeStatusLabel(status) {
  return { available: "可用", used: "已用", revoked: "已作废", expired: "已过期" }[status] || status;
}

function codeStatusClass(status) {
  return { available: "status-ok", used: "status-fail", revoked: "status-fail", expired: "status-warn" }[status] || "";
}

function formatInviteCopy(codeList, expiresDays, note) {
  const head = expiresDays
    ? `V Push 邀请码（一次性，${expiresDays}天内有效）`
    : "V Push 邀请码（一次性）";
  const lines = [head, ...codeList];
  if (note) lines.push(`备注：${note}`);
  return lines.join("\n");
}

function formatInviteCopyUntil(codeList, expiresAt, note) {
  const head = expiresAt
    ? `V Push 邀请码（一次性，有效期至 ${fmtDbTime(expiresAt)})`
    : "V Push 邀请码（一次性）";
  const lines = [head, ...codeList];
  if (note) lines.push(`备注：${note}`);
  return lines.join("\n");
}

function copyDataAttr(text) {
  return encodeURIComponent(String(text ?? "")).replace(/'/g, "%27");
}

function copyText(text, okMsg) {
  if (!text) return;
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(
      () => flash(okMsg || "已复制"),
      () => alert("请手动复制：\n" + text),
    );
  } else {
    alert("请手动复制：\n" + text);
  }
}

let _adminCodesSelected = new Set();

function codeCanRevoke(c) {
  return c && !c.used_by && !c.revoked_at;
}

function codeCanPurge(c) {
  const st = codeStatus(c);
  return st === "used" || st === "revoked" || st === "expired";
}

function adminCodesSelectedRows() {
  const all = state.adminCodes || [];
  return all.filter((c) => _adminCodesSelected.has(c.code));
}

function adminCodesSyncBar() {
  const bar = $("#rc-batch-bar");
  if (!bar) return;
  const selected = adminCodesSelectedRows();
  bar.style.display = _adminCodesSelected.size ? "flex" : "none";
  const strong = bar.querySelector("strong");
  if (strong) {
    const visibleSelected = document.querySelectorAll(".rc-check:checked").length;
    strong.textContent = visibleSelected < _adminCodesSelected.size
      ? `已选 ${_adminCodesSelected.size} 个（当前显示 ${visibleSelected}）`
      : `已选 ${_adminCodesSelected.size} 个`;
  }
  const revokeBtn = $("#rc-batch-revoke");
  const purgeBtn = $("#rc-batch-purge");
  if (revokeBtn) revokeBtn.disabled = !selected.some(codeCanRevoke);
  if (purgeBtn) purgeBtn.disabled = !selected.some(codeCanPurge);
}

function adminCodesToggle(el) {
  const code = el.dataset.code;
  if (!code) return;
  if (el.checked) _adminCodesSelected.add(code);
  else _adminCodesSelected.delete(code);
  adminCodesSyncBar();
  adminCodesSyncBatchChecks();
  adminCodesSyncPageCheck();
}

function adminCodesTogglePage(el) {
  document.querySelectorAll(".rc-check").forEach((c) => {
    c.checked = el.checked;
    if (el.checked) _adminCodesSelected.add(c.dataset.code);
    else _adminCodesSelected.delete(c.dataset.code);
  });
  adminCodesSyncBatchChecks();
  adminCodesSyncPageCheck();
  adminCodesSyncBar();
}

function adminCodesSyncPageCheck() {
  const el = $("#rc-checkall");
  if (!el) return;
  const boxes = [...document.querySelectorAll(".rc-check")];
  el.checked = boxes.length > 0 && boxes.every((c) => c.checked);
  el.indeterminate = boxes.some((c) => c.checked) && !el.checked;
}

function adminCodesToggleBatch(el) {
  const batchId = el.dataset.batch;
  document.querySelectorAll(`.rc-check[data-batch="${batchId}"]`).forEach((c) => {
    c.checked = el.checked;
    if (el.checked) _adminCodesSelected.add(c.dataset.code);
    else _adminCodesSelected.delete(c.dataset.code);
  });
  el.indeterminate = false;
  adminCodesSyncBatchChecks();
  adminCodesSyncPageCheck();
  adminCodesSyncBar();
}

function adminCodesSyncBatchChecks() {
  document.querySelectorAll(".rc-batch-check").forEach((el) => {
    const boxes = [...document.querySelectorAll(`.rc-check[data-batch="${el.dataset.batch}"]`)];
    el.checked = boxes.length > 0 && boxes.every((c) => c.checked);
    el.indeterminate = boxes.some((c) => c.checked) && !el.checked;
  });
}

function adminCodesClearSelect() {
  _adminCodesSelected.clear();
  document.querySelectorAll(".rc-check").forEach((c) => { c.checked = false; });
  document.querySelectorAll(".rc-batch-check").forEach((c) => {
    c.checked = false;
    c.indeterminate = false;
  });
  adminCodesSyncPageCheck();
  adminCodesSyncBar();
}

function adminCodesCopySelected() {
  const codes = [..._adminCodesSelected];
  if (!codes.length) return;
  copyText(codes.join("\n"), `已复制 ${codes.length} 个邀请码`);
}

async function adminCodesBatch(action) {
  const selected = adminCodesSelectedRows();
  const codes = action === "revoke"
    ? selected.filter(codeCanRevoke).map((c) => c.code)
    : selected.filter(codeCanPurge).map((c) => c.code);
  if (!codes.length) return;
  const skipped = selected.length - codes.length;
  const skipTip = skipped ? `（另有 ${skipped} 个${action === "revoke" ? "不可作废" : "不可删除"}，已跳过）` : "";
  const ok = action === "revoke"
    ? confirm(`将作废选中的 ${codes.length} 个未使用邀请码${skipTip}，确认？`)
    : confirm(`将从列表删除选中的 ${codes.length} 个已用/已作废/已过期邀请码${skipTip}，不可恢复。确认？`);
  if (!ok) return;
  try {
    const data = await api("/api/admin/register-codes/batch", {
      method: "POST",
      body: JSON.stringify({ codes, action }),
    });
    const serverSkipped = data.skipped || 0;
    const msg = action === "revoke"
      ? (serverSkipped ? `已作废 ${data.count} 个，跳过 ${serverSkipped} 个` : `已作废 ${data.count} 个邀请码`)
      : (serverSkipped ? `已删除 ${data.count} 个，跳过 ${serverSkipped} 个` : `已删除 ${data.count} 个邀请码`);
    flash(msg);
    _adminCodesSelected.clear();
    loadAdminCodes();
  } catch (err) {
    flash(err.message, "error");
  }
}

function saveCodesForm() {
  const note = $("#rc-note");
  const count = $("#rc-count");
  const exp = $("#rc-expires");
  const q = $("#rc-q");
  if (note) _codesUi.note = note.value;
  if (count) _codesUi.count = Number(count.value) || 5;
  if (exp) _codesUi.expires = exp.value === "" ? null : Number(exp.value);
  if (q) _codesUi.q = q.value.trim();
}

function adminCodesPreset(note) {
  const el = $("#rc-note");
  if (el) el.value = note;
  _codesUi.note = note;
  adminCodesSyncPresets();
}

function adminCodesNoteInput() {
  const el = $("#rc-note");
  _codesUi.note = el ? el.value : "";
  adminCodesSyncPresets();
}

function adminCodesSyncPresets() {
  document.querySelectorAll(".rc-preset").forEach((b) => {
    b.classList.toggle("selected", b.dataset.note === _codesUi.note);
  });
}

async function loadAdminCodes(refetch = true) {
  if (refetch || !state.adminCodes) {
    state.adminCodes = await api("/api/admin/register-codes");
  }
  const known = new Set((state.adminCodes || []).map((c) => c.code));
  for (const code of [..._adminCodesSelected]) {
    if (!known.has(code)) _adminCodesSelected.delete(code);
  }
  if (!routeStillActive(_adminRenderSeq)) return;
  const filter = _codesUi.filter;
  const expVal = _codesUi.expires == null ? "" : String(_codesUi.expires);
  const result = _codesUi.result;
  const allCodes = state.adminCodes || [];
  const tabCounts = { available: 0, used: 0, revoked: 0, expired: 0, all: allCodes.length };
  for (const c of allCodes) tabCounts[codeStatus(c)] += 1;
  const filterBtn = (key, label) =>
    `<button type="button" class="settings-tab ${filter === key ? "active" : ""}" role="tab" aria-selected="${filter === key}" data-filter="${key}" onclick="saveCodesForm();_codesUi.filter='${key}';loadAdminCodes(false)">${label} ${tabCounts[key]}</button>`;

  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">生成注册邀请码</h3>
        <p class="section-meta">一次性邀请码，按批生成；用过即废，可设有效期。</p></div>
      </header>
      <div class="rc-generate">
        <label class="rc-field rc-field-note">
          <span>备注</span>
          <input id="rc-note" class="form-control" maxlength="40" placeholder="给谁、什么场合" value="${escapeHtml(_codesUi.note)}" oninput="adminCodesNoteInput()">
        </label>
        <div class="rc-field">
          <span>常用</span>
          <div class="rc-presets" role="group" aria-label="常用备注">
            <button type="button" class="rc-preset${_codesUi.note === "内部" ? " selected" : ""}" data-note="内部" onclick="adminCodesPreset('内部')">内部</button>
            <button type="button" class="rc-preset${_codesUi.note === "朋友" ? " selected" : ""}" data-note="朋友" onclick="adminCodesPreset('朋友')">朋友</button>
          </div>
        </div>
        <label class="rc-field rc-field-count">
          <span>数量</span>
          <input id="rc-count" class="form-control" type="number" min="1" max="100" value="${escapeHtml(String(_codesUi.count))}">
        </label>
        <label class="rc-field rc-field-expires">
          <span>有效期</span>
          <select id="rc-expires" class="form-control">
            <option value="1" ${expVal === "1" ? "selected" : ""}>1天</option>
            <option value="7" ${expVal === "7" ? "selected" : ""}>7天</option>
            <option value="30" ${expVal === "30" ? "selected" : ""}>30天</option>
            <option value="" ${expVal === "" ? "selected" : ""}>永不过期</option>
          </select>
        </label>
        <div class="rc-field-submit">
          <button class="btn-normal" onclick="adminGenerateCodes()">生成</button>
        </div>
      </div>
      ${result ? renderCodesResult(result) : ""}
    </section>
    <section class="section-panel">
      <header class="section-head rc-list-head">
        <div>
          <h3 class="section-title">注册码列表</h3>
          <p class="section-meta">${tabCounts.all} 个 · ${tabCounts.available} 可用</p>
        </div>
        <div class="search-bar rc-search">
          ${SEARCH_ICON}
          <input id="rc-q" type="search" placeholder="搜索码或备注" value="${escapeHtml(_codesUi.q)}" oninput="_codesUi.q=this.value;renderCodesList()">
        </div>
      </header>
      <div class="settings-tabs rc-tabs" role="tablist" aria-label="注册码状态">
        ${filterBtn("available", "可用")}
        ${filterBtn("used", "已用")}
        ${filterBtn("revoked", "已作废")}
        ${filterBtn("expired", "已过期")}
        ${filterBtn("all", "全部")}
      </div>
      <div class="toolbar admin-batch-bar" id="rc-batch-bar" style="margin-top:10px;display:${_adminCodesSelected.size ? "flex" : "none"};align-items:center;gap:8px;flex-wrap:wrap">
        <strong>已选 ${_adminCodesSelected.size} 个</strong>
        <button type="button" class="btn-sm" onclick="adminCodesCopySelected()">复制</button>
        <button type="button" class="btn-sm" id="rc-batch-revoke" onclick="adminCodesBatch('revoke')">作废未用</button>
        <button type="button" class="btn-sm danger" id="rc-batch-purge" onclick="adminCodesBatch('delete')">清掉废码</button>
        <button type="button" class="btn-sm" onclick="adminCodesClearSelect()">取消选择</button>
      </div>
      <div class="rc-list-toolbar">
        <label class="rc-checkall">
          <input type="checkbox" id="rc-checkall" onchange="adminCodesTogglePage(this)" aria-label="全选当前筛选">
          <span>全选当前筛选</span>
        </label>
      </div>
      <div id="rc-list"></div>
    </section>`;
  renderCodesList();
  adminCodesSyncBar();
}

function renderCodesList() {
  const codes = state.adminCodes || [];
  const filter = _codesUi.filter;
  const q = (_codesUi.q || "").trim().toLowerCase();
  const filtered = codes.filter((c) => {
    if (filter !== "all" && codeStatus(c) !== filter) return false;
    if (!q) return true;
    return String(c.code).toLowerCase().includes(q) || String(c.note || "").toLowerCase().includes(q);
  });
  const groups = [];
  const byBatch = new Map();
  for (const c of codes) {
    const id = c.batch_id || c.code;
    if (!byBatch.has(id)) byBatch.set(id, []);
    byBatch.get(id).push(c);
  }
  const visibleIds = new Set(filtered.map((c) => c.batch_id || c.code));
  for (const [id, rows] of byBatch) {
    if (!visibleIds.has(id)) continue;
    groups.push({ id, rows, visible: rows.filter((c) => filtered.includes(c)) });
  }
  groups.sort((a, b) => String(b.rows[0].created_at).localeCompare(String(a.rows[0].created_at)));
  const el = $("#rc-list");
  if (el) el.innerHTML = renderCodeGroups(groups, filter);
  adminCodesSyncBatchChecks();
  adminCodesSyncPageCheck();
  adminCodesSyncBar();
}

function renderCodesResult(result) {
  const days = result.expires_in_days;
  const copy = formatInviteCopy(result.codes, days, result.note);
  return `<div class="rc-result">
    <div class="rc-result-head">
      <strong>已生成 ${result.codes.length} 个</strong>
      <div class="rc-result-actions">
        <button class="btn-sm" data-copy="${copyDataAttr(copy)}" onclick="copyText(decodeURIComponent(this.getAttribute('data-copy')), '已复制本批邀请码')">复制全部</button>
        <button class="btn-sm danger" onclick="adminRevokeBatch('${escapeHtml(result.batch_id)}', true)">作废本批未用</button>
        <button class="btn-sm" onclick="_codesUi.result=null;loadAdminCodes()">关闭</button>
      </div>
    </div>
    <div class="rc-result-codes">${result.codes.map((code) =>
      `<div class="rc-result-row"><code>${escapeHtml(code)}</code><button class="btn-sm" data-code="${escapeHtml(code)}" onclick="copyText(this.dataset.code, '已复制')">复制</button></div>`
    ).join("")}</div>
  </div>`;
}

function renderCodeGroups(groups, filter) {
  if (groups.length === 0) {
    const empty =
      filter === "available"
        ? "没有可用注册码。在上方生成一批，复制后发给对方。"
        : filter === "used"
          ? "还没有人用过邀请码。"
          : "没有符合条件的注册码。";
    return `<p class="rc-empty muted">${empty}</p>`;
  }
  return groups.map((g) => {
    const all = g.rows;
    const notes = [...new Set(all.map((c) => c.note || ""))];
    const noteLabel = notes.length === 1 ? (notes[0] || "无备注") : "备注不一";
    const available = all.filter((c) => codeStatus(c) === "available");
    const usedN = all.filter((c) => codeStatus(c) === "used").length;
    const unusedOpen = all.filter((c) => !c.used_by && !c.revoked_at);
    const expLabel = all[0].expires_at ? `过期 ${escapeHtml(fmtDbTime(all[0].expires_at))}` : "永不过期";
    const creator = all[0].created_by_name ? ` · ${escapeHtml(all[0].created_by_name)}` : "";
    const copyCodes = available.map((c) => c.code);
    const copyNote = notes.length === 1 ? notes[0] : "";
    const copy = formatInviteCopyUntil(copyCodes, all[0].expires_at, copyNote);
    return `<div class="rc-batch">
      <div class="rc-batch-head">
        <div class="rc-batch-info">
          <div class="rc-batch-title">
            <input type="checkbox" class="rc-batch-check" data-batch="${escapeHtml(g.id)}" onchange="adminCodesToggleBatch(this)" aria-label="全选本批可见" title="全选本批当前可见的注册码">
            <strong>${escapeHtml(noteLabel)}</strong>
            <span class="rc-counts">${available.length} 可用 / ${usedN} 已用</span>
          </div>
          <p class="muted rc-batch-meta">${escapeHtml(fmtDbTime(all[0].created_at))} · ${expLabel}${creator}</p>
        </div>
        <div class="rc-batch-actions">
          <button class="btn-sm" ${copyCodes.length ? "" : "disabled"} data-copy="${copyDataAttr(copy)}" onclick="copyText(decodeURIComponent(this.getAttribute('data-copy')), '已复制未用码')">复制未用</button>
          <button class="btn-sm danger" ${unusedOpen.length ? "" : "disabled"} onclick="adminRevokeBatch('${escapeHtml(g.id)}')">作废未用</button>
        </div>
      </div>
      <div class="table-wrap">
        <table class="rc-table">
          <thead><tr><th scope="col">邀请码</th><th scope="col">备注</th><th scope="col">状态</th><th scope="col">使用者</th><th scope="col">时间</th><th scope="col">操作</th></tr></thead>
          <tbody>${g.visible.map((c) => renderCodeRow(c)).join("")}</tbody>
        </table>
      </div>
    </div>`;
  }).join("");
}

function renderCodeRow(c) {
  const st = codeStatus(c);
  const when = c.used_at ? fmtDbTime(c.used_at) : c.revoked_at ? fmtDbTime(c.revoked_at) : c.expires_at ? fmtDbTime(c.expires_at) : fmtDbTime(c.created_at);
  const canRevoke = st === "available" || st === "expired";
  const checked = _adminCodesSelected.has(c.code) ? "checked" : "";
  return `<tr>
    <td data-label="邀请码"><span class="rc-code"><input type="checkbox" class="rc-check" data-code="${escapeHtml(c.code)}" data-batch="${escapeHtml(c.batch_id || c.code)}" ${checked} onchange="adminCodesToggle(this)" aria-label="选择邀请码"><code>${escapeHtml(c.code)}</code><button class="btn-sm" data-code="${escapeHtml(c.code)}" onclick="copyText(this.dataset.code, '已复制')">复制</button></span></td>
    <td data-label="备注" class="rc-note-cell">${escapeHtml(c.note || "")}</td>
    <td data-label="状态" class="${codeStatusClass(st)}">${codeStatusLabel(st)}</td>
    <td data-label="使用者">${escapeHtml(c.used_by_name || "")}</td>
    <td data-label="时间">${escapeHtml(when)}</td>
    <td data-label="操作">${canRevoke ? `<button class="btn-sm danger" data-code="${escapeHtml(c.code)}" onclick="adminRevokeCode(this.dataset.code)">作废</button>` : ""}</td>
  </tr>`;
}

async function adminRevokeCode(code) {
  if (!confirm(`确认作废注册码 ${code}？作废后无法再使用。`)) return;
  try {
    await api(`/api/admin/register-codes/${encodeURIComponent(code)}/revoke`, { method: "POST" });
    flash(`已作废邀请码 ${code}`);
    loadAdminCodes();
  } catch (err) {
    alert("作废失败: " + err.message);
  }
}

async function adminRevokeBatch(batchId, fromResult) {
  if (!confirm("将作废本批所有未使用的邀请码，确认？")) return;
  try {
    await api(`/api/admin/register-code-batches/${encodeURIComponent(batchId)}/revoke-unused`, { method: "POST" });
    flash("已作废本批未用码");
    if (fromResult) _codesUi.result = null;
    loadAdminCodes();
  } catch (err) {
    alert("作废失败: " + err.message);
  }
}

async function adminGenerateCodes() {
  saveCodesForm();
  try {
    const expiresRaw = $("#rc-expires").value;
    const expires_in_days = expiresRaw === "" ? null : Number(expiresRaw);
    const data = await api("/api/admin/register-codes", {
      method: "POST",
      body: JSON.stringify({
        count: Number($("#rc-count").value) || 5,
        note: $("#rc-note").value.trim(),
        expires_in_days,
      }),
    });
    _codesUi.result = { ...data, expires_in_days };
    _codesUi.filter = "available";
    flash(`已生成 ${data.count} 个邀请码`);
    loadAdminCodes();
  } catch (err) {
    alert("生成失败: " + err.message);
  }
}

async function loadAdminVocab() {
  // 深链：#/admin/vocab?tab=tags 进标签 Tab，其余值（含无参数）进分类 Tab
  const params = new URLSearchParams(location.hash.split("?")[1] || "");
  const tab = params.get("tab") === "tags" ? "tags" : "categories";
  if (!routeStillActive(_adminRenderSeq)) return;
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">标签分类</h3>
        <p class="section-meta">分类按大V分组（订阅广场/动态页/管理列表筛选）；标签按关键词规则给贴文内容自动打标。</p></div>
        <div class="settings-tabs" role="tablist" aria-label="标签分类">
          <button class="settings-tab ${tab === "categories" ? "active" : ""}" data-tab="categories" onclick="location.hash='#/admin/vocab'">分类</button>
          <button class="settings-tab ${tab === "tags" ? "active" : ""}" data-tab="tags" onclick="location.hash='#/admin/vocab?tab=tags'">标签</button>
        </div>
      </header>
      <div id="vocab-tab-body" class="settings-tab-panel"></div>
    </section>`;
  await loadAdminVocabTab(tab);
}

async function loadAdminVocabTab(tab) {
  if (tab === "tags") return loadAdminTagsTab();
  return loadAdminCategoriesTab();
}

async function loadAdminCategoriesTab() {
  const categories = await api("/api/categories");
  if (!routeStillActive(_adminRenderSeq)) return;
  $("#vocab-tab-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">添加分类</h3></div>
        <div class="toolbar" style="margin-top:12px">
          <input id="cat-name" class="form-control" style="margin:0;width:280px" placeholder="分类名，如：实盘、宏观、行业研究">
          <button class="btn-normal" onclick="adminAddCategory()">添加分类</button>
        </div>
      </header>
    </section>
    <section class="section-panel">
      <header class="section-head"><div><h3 class="section-title">分类列表</h3></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">ID</th><th scope="col">分类名</th><th scope="col">大V数</th><th scope="col">操作</th></tr></thead>
          <tbody>${categories.map((c) => `
            <tr>
              <td>${c.id}</td><td>${escapeHtml(c.name)}</td><td>${c.kol_count}</td>
              <td>
                <button class="btn-sm" onclick="adminRenameCategory(${c.id})">重命名</button>
                <button class="btn-sm danger" onclick="adminDeleteCategory(${c.id})">删除</button>
              </td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
}

async function adminAddCategory() {
  const name = $("#cat-name").value.trim();
  if (!name) {
    alert("请输入分类名");
    return;
  }
  try {
    await api("/api/categories", { method: "POST", body: JSON.stringify({ name }) });
    flash(`已添加分类「${name}」`);
    loadAdminVocabTab("categories");
  } catch (err) {
    alert("添加失败: " + err.message);
  }
}

async function adminRenameCategory(id) {
  const name = prompt("新的分类名：");
  if (name === null || !name.trim()) return;
  try {
    await api(`/api/categories/${id}`, { method: "PUT", body: JSON.stringify({ name: name.trim() }) });
    flash("已重命名分类");
    loadAdminVocabTab("categories");
  } catch (err) {
    alert("重命名失败: " + err.message);
  }
}

async function adminDeleteCategory(id) {
  if (!confirm("确认删除该分类？其下大V将变为未分类")) return;
  try {
    await api(`/api/categories/${id}`, { method: "DELETE" });
    flash("已删除分类");
    loadAdminVocabTab("categories");
  } catch (err) {
    alert("删除失败: " + err.message);
  }
}

async function loadAdminTagsTab() {
  const data = await api("/api/tags");
  const tags = Array.isArray(data?.tags) ? data.tags : [];
  const stockNames = Array.isArray(data?.stock_names) ? data.stock_names : [];
  const stockAliases = Array.isArray(data?.stock_aliases) ? data.stock_aliases : [];
  const stats = data?.stats || { total: 0, processed: 0, tagged: 0, pending: 0 };
  if (!routeStillActive(_adminRenderSeq)) return;
  // 词表编辑：每行一个标签，格式「标签名 | 关键词,关键词」；关键词为空则该标签不命中
  const vocabText = tags.map((r) => `${r.tag} | ${(r.keywords || []).join(", ")}`).join("\n");
  // 别名表编辑：每行「别名=正式名」
  const aliasText = stockAliases.map((a) => `${a.alias}=${a.stock}`).join("\n");
  $("#vocab-tab-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">贴文标签词表</h3>
        <p class="section-meta">新帖抓取入库时按关键词规则自动打标（零成本、不依赖 LLM）。每行一个标签：<b>标签名 | 关键词1,关键词2</b>，正文/标题命中任一关键词即打该标签，每条最多 3 个。</p></div>
      </header>
      <textarea id="tag-vocab-input" class="form-control" rows="10" style="margin-top:12px;font-family:monospace;line-height:1.6" placeholder="宏观 | 央行,降息,GDP&#10;大盘 | A股,沪指,指数">${escapeHtml(vocabText)}</textarea>
      <div class="toolbar" style="margin-top:12px">
        <button class="btn-normal" onclick="adminSaveTags()">保存词表</button>
      </div>
      <p class="section-meta" style="margin-top:8px">已处理 ${stats.processed} / ${stats.total} 条，其中有标签 ${stats.tagged} 条，待处理 ${stats.pending} 条</p>
    </section>
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">常用股票名</h3>
        <p class="section-meta">帖子纯文字提及这些股票名时会打上股票标签（每行一个；$股票名(代码)$ 标记自动识别、无需在此登记）。</p></div>
      </header>
      <textarea id="stock-names-input" class="form-control" rows="6" style="margin-top:12px;font-family:monospace;line-height:1.6" placeholder="贵州茅台&#10;宁德时代">${escapeHtml(stockNames.join("\n"))}</textarea>
    </section>
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">黑话别名（LLM 每日自动识别）</h3>
        <p class="section-meta">LLM 每日扫描帖子自动识别股票昵称并写入（如 宁王→宁德时代）；此处可手动修正。每行「别名=正式名」，正式名需在常用股票名表中。</p></div>
      </header>
      <textarea id="stock-aliases-input" class="form-control" rows="5" style="margin-top:12px;font-family:monospace;line-height:1.6" placeholder="宁王=宁德时代">${escapeHtml(aliasText)}</textarea>
    </section>
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">回填历史贴文</h3>
        <p class="section-meta">给未打标贴文按当前词表 + 股票名单补标签；「按当前规则重算全部」会覆盖全部历史贴文标签（危险操作，需确认）。</p></div>
      </header>
      <div class="toolbar" style="margin-top:12px">
        <button class="btn-normal" onclick="adminBackfillTags('pending')">处理待打标</button>
        <button class="btn-ghost" onclick="adminBackfillTags('all')">按当前规则重算全部</button>
        <span id="tag-backfill-result" class="muted"></span>
      </div>
    </section>
    <section class="section-panel">
      <header class="section-head"><div><h3 class="section-title">当前词表（${tags.length} 个）</h3></div></header>
      <div class="tag-vocab-preview">
        ${tags.length ? tags.map((r) => `<span class="cat cat-tag">${escapeHtml(r.tag)}</span>`).join("") : "（空）"}
      </div>
    </section>`;
}

async function adminSaveTags() {
  const raw = $("#tag-vocab-input").value;
  const tags = raw.split(/\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
    // 每行「标签名 | 关键词,关键词」；无 | 时整行视为标签名（无关键词）
    const [tag, kw] = line.split("|").map((s) => s.trim());
    const keywords = kw ? kw.split(/[,，]/).map((k) => k.trim()).filter(Boolean) : [];
    return { tag, keywords };
  }).filter((r) => r.tag);
  const stockNames = $("#stock-names-input").value.split(/\n/).map((s) => s.trim()).filter(Boolean);
  const stockAliases = $("#stock-aliases-input").value.split(/\n/).map((line) => line.trim()).filter(Boolean).map((line) => {
    const [alias, stock] = line.split(/[=＝]/).map((s) => s.trim());
    return { alias, stock };
  }).filter((r) => r.alias && r.stock);
  try {
    const data = await api("/api/tags", { method: "PUT", body: JSON.stringify({ tags, stock_names: stockNames, stock_aliases: stockAliases }) });
    flash(`已保存词表（${data.tags.length} 个标签，${data.stock_names.length} 只股票，${data.stock_aliases.length} 个别名）`);
    loadAdminVocabTab("tags");
  } catch (err) {
    alert("保存失败: " + err.message);
  }
}

async function adminBackfillTags(mode = "pending") {
  if (mode === "all" && !confirm("将覆盖全部历史贴文标签，确定继续？")) return;
  const buttons = document.querySelectorAll("[onclick^='adminBackfillTags']");
  buttons.forEach((button) => { button.disabled = true; });
  const result = $("#tag-backfill-result");
  if (result) result.textContent = mode === "all" ? "全量重算中…" : "处理中…";
  try {
    const data = await api("/api/tags/backfill", {
      method: "POST",
      body: JSON.stringify({ mode }),
    });
    if (result) result.textContent = `已处理 ${data.processed} 条，其中 ${data.tagged} 条有标签`;
    flash(mode === "all" ? "全量重算完成" : "待打标处理完成");
    loadAdminVocabTab("tags");
  } catch (err) {
    if (result) result.textContent = "";
    alert("处理失败: " + err.message);
  } finally {
    buttons.forEach((button) => { button.disabled = false; });
  }
}

let _adminPostsSeq = 0;
const _adminPosts = [];
let _adminPostsOffset = 0;
let _adminPostsHasMore = true;
const _adminPostsExpanded = new Set();
let _adminKolsOptions = null;

async function _adminKolsSelect() {
  // 大V下拉选项（按平台分组），只拉一次缓存
  if (_adminKolsOptions) return _adminKolsOptions;
  const kols = await api("/api/kols");
  const groups = {};
  for (const k of kols) {
    const g = PLATFORM_LABELS[k.platform] || k.platform || "其他";
    (groups[g] = groups[g] || []).push(k);
  }
  _adminKolsOptions = Object.entries(groups)
    .map(([g, list]) => `<optgroup label="${escapeHtml(g)}">${list.map((k) =>
      `<option value="${k.id}" ${state.adminPostsKolId == k.id ? "selected" : ""}>${escapeHtml(k.name)}</option>`).join("")}</optgroup>`)
    .join("");
  return _adminKolsOptions;
}

function renderAdminPosts() {
  const kolsHtml = _adminKolsOptions || `<option value="">全部大V</option>`;
  if (!routeStillActive(_adminRenderSeq)) return;
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">帖子列表</h3><p class="section-meta">已加载 ${_adminPosts.length} 条 · 点击内容展开全文 · 按大V/平台/关键词筛选</p></div>
        <div class="toolbar" style="margin-top:12px">
          <input id="ad-posts-q" class="form-control" style="margin:0;width:240px" placeholder="搜索标题/内容关键词" value="${escapeHtml(state.adminPostsQ || "")}" onkeydown="if(event.key==='Enter')adminFilterPosts()">
          <select id="ad-posts-platform" class="form-control" style="margin:0;width:auto" onchange="adminFilterPosts()">
            <option value="">全部平台</option>
            <option value="xueqiu" ${state.adminPostsPlatform === "xueqiu" ? "selected" : ""}>雪球</option>
            <option value="weibo" ${state.adminPostsPlatform === "weibo" ? "selected" : ""}>微博</option>
            <option value="twitter" ${state.adminPostsPlatform === "twitter" ? "selected" : ""}>X</option>
          </select>
          <select id="ad-posts-kol" class="form-control" style="margin:0;width:auto" onchange="adminFilterPosts()">${kolsHtml}</select>
          <button class="btn-normal" onclick="adminFilterPosts()">筛选</button>
        </div>
      </header>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">ID</th><th scope="col">大V</th><th scope="col">分类</th><th scope="col">内容</th><th scope="col">时间</th><th scope="col">链接</th></tr></thead>
          <tbody>${_adminPosts.map(postRowHtml).join("")}</tbody>
        </table>
      </div>
      ${_adminPostsHasMore
        ? `<div class="toolbar" style="margin-top:14px;justify-content:center"><button class="btn-normal" onclick="adminPostsLoadMore()">加载更多</button></div>`
        : `<p class="muted" style="text-align:center;margin-top:14px">已加载全部</p>`}
    </section>`;
}

function postRowHtml(p) {
  const expanded = _adminPostsExpanded.has(p.id);
  const body = (p.title ? p.title + "\n" : "") + (p.content || "");
  const safeUrl = /^https?:\/\//i.test(p.url || "") ? p.url : "";
  return `
    <tr${expanded ? ' style="background:var(--color-surface-accent-soft)"' : ""}>
      <td>${p.id}</td><td>${escapeHtml(p.kol_name)}</td>
      <td>${escapeHtml(p.category_name || "")}</td>
      <td class="post-cell" onclick="adminTogglePost(${p.id})" title="点击展开/收起全文" role="button" tabindex="0" aria-expanded="${expanded}" onkeydown="if(event.key==='Enter'||event.key===' '){event.preventDefault();adminTogglePost(${p.id})}">
        <pre class="content-cell">${escapeHtml(body.slice(0, expanded ? 100000 : 120))}</pre>
        <span class="muted">${expanded ? "▲ 收起" : (body.length > 120 ? "▼ 展开全文" : "")}</span>
      </td>
      <td>${escapeHtml(p.published_at)}</td>
      <td>${safeUrl ? `<a href="${escapeHtml(safeUrl)}" target="_blank" rel="noopener">原文</a>` : ""}</td>
    </tr>
    ${expanded ? `<tr><td colspan="6"><div class="post-detail">
        <p class="muted" style="margin-bottom:8px">类型：${p.post_type === "reply" ? "回复" : "原帖"} · 平台：${escapeHtml(p.platform)} · 外部ID：${escapeHtml(p.external_id)} · 图片：${(p.images || []).length} 张</p>
        <pre class="content-cell">${escapeHtml(body)}</pre>
      </div></td></tr>` : ""}`;
}

async function loadAdminPosts(reset = true) {
  const seq = ++_adminPostsSeq;
  const params = new URLSearchParams({ limit: "100", offset: String(reset ? 0 : _adminPostsOffset) });
  if (state.adminPostsQ) params.set("q", state.adminPostsQ);
  if (state.adminPostsPlatform) params.set("platform", state.adminPostsPlatform);
  if (state.adminPostsKolId) params.set("kol_id", state.adminPostsKolId);
  const [posts, kolsHtml] = await Promise.all([api(`/api/posts?${params}`), _adminKolsSelect()]);
  if (seq !== _adminPostsSeq) return; // 筛选条件已变，丢弃过期响应
  if (reset) {
    _adminPosts.length = 0;
    _adminPostsOffset = 0;
    _adminPostsHasMore = true;
  }
  _adminPosts.push(...posts);
  _adminPostsOffset += posts.length;
  _adminPostsHasMore = posts.length >= 100;
  _adminKolsOptions = kolsHtml;
  renderAdminPosts();
}

function adminPostsLoadMore() {
  loadAdminPosts(false);
}

function adminTogglePost(id) {
  if (_adminPostsExpanded.has(id)) _adminPostsExpanded.delete(id);
  else _adminPostsExpanded.add(id);
  renderAdminPosts();
}

async function adminFilterPosts() {
  state.adminPostsQ = $("#ad-posts-q").value.trim();
  state.adminPostsPlatform = $("#ad-posts-platform").value;
  state.adminPostsKolId = $("#ad-posts-kol").value;
  loadAdminPosts(true);
}

let _adminLogsSeq = 0;
async function loadAdminLogs() {
  const seq = ++_adminLogsSeq;
  const users = await api("/api/users");
  const logs = await api(`/api/push-logs?limit=100${state.adminLogsFilter || ""}`);
  if (seq !== _adminLogsSeq) return; // 筛选条件已变，丢弃过期响应
  if (!routeStillActive(_adminRenderSeq)) return;
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div><h3 class="section-title">推送记录</h3></div>
        <div class="toolbar" style="margin-top:12px">
          <select id="ad-logs-user" class="form-control" style="margin:0;width:auto">
            <option value="">全部用户</option>
            ${users.map((u) => `<option value="${u.id}" ${state.adminLogsUserId == u.id ? "selected" : ""}>${escapeHtml(u.username)}</option>`).join("")}
          </select>
          <select id="ad-logs-channel" class="form-control" style="margin:0;width:auto">
            <option value="">全部渠道</option>
            <option value="telegram" ${state.adminLogsChannel === "telegram" ? "selected" : ""}>Telegram</option>
            <option value="feishu" ${state.adminLogsChannel === "feishu" ? "selected" : ""}>飞书</option>
            <option value="wecom" ${state.adminLogsChannel === "wecom" ? "selected" : ""}>企业微信</option>
          </select>
          <select id="ad-logs-status" class="form-control" style="margin:0;width:auto">
            <option value="">全部状态</option>
            <option value="success" ${state.adminLogsStatus === "success" ? "selected" : ""}>成功</option>
            <option value="failed" ${state.adminLogsStatus === "failed" ? "selected" : ""}>失败</option>
          </select>
          <button class="btn-normal" onclick="adminFilterLogs()">筛选</button>
        </div>
      </header>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">时间</th><th scope="col">用户</th><th scope="col">大V</th><th scope="col">渠道</th><th scope="col">状态</th><th scope="col">错误</th></tr></thead>
          <tbody>${logs.map((l) => `
            <tr>
              <td>${escapeHtml(fmtDbTime(l.created_at))}</td>
              <td>${escapeHtml(l.user_name || "全局")}</td>
              <td>${escapeHtml(l.kol_name)}</td>
              <td>${l.channel}</td>
              <td class="${l.status === "success" ? "status-ok" : "status-fail"}">${escapeHtml(l.status)}</td>
              <td>${escapeHtml(l.error || "")}</td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
}

async function loadAdminAudit() {
  const logs = await api("/api/admin/logs?limit=100");
  if (!routeStillActive(_adminRenderSeq)) return;
  $("#admin-body").innerHTML = `
    <section class="section-panel">
      <header class="section-head">
        <div>
          <h3 class="section-title">系统日志</h3>
          <p class="section-meta">内存环形缓冲的最近 500 条日志，每 5 秒自动刷新；更完整历史见 docker logs（LOG_LEVEL=DEBUG 可开启更详细日志）。</p>
        </div>
        <div class="toolbar" style="margin-top:12px">
          <select id="syslog-level" class="form-control" style="width:auto" onchange="loadAdminSysLogsPanel()">
            <option value="">全部级别</option>
            <option value="ERROR">ERROR+</option>
            <option value="WARNING">WARNING+</option>
            <option value="INFO">INFO+</option>
            <option value="DEBUG">DEBUG（仅LOG_LEVEL=DEBUG时产生）</option>
          </select>
          <input id="syslog-q" class="form-control" style="width:220px" placeholder="关键词过滤（如 推送失败 / 大V名）" onkeydown="if(event.key==='Enter')loadAdminSysLogsPanel()">
          <button class="btn-normal" onclick="loadAdminSysLogsPanel()">刷新</button>
        </div>
      </header>
      <pre class="syslog" id="syslog-pre">加载中…</pre>
    </section>
    <section class="section-panel">
      <header class="section-head">
        <div>
          <h3 class="section-title">错误记录</h3>
          <p class="section-meta">WARNING 及以上日志持久化存储（跨重启保留最近 5000 条），即使环形缓冲滚动或重启后仍可查。</p>
        </div>
        <div class="toolbar" style="margin-top:12px">
          <select id="errlog-level" class="form-control" style="width:auto" onchange="loadAdminErrorLogs()">
            <option value="">全部级别</option>
            <option value="ERROR">ERROR+</option>
            <option value="WARNING">WARNING+</option>
          </select>
          <button class="btn-normal" onclick="loadAdminErrorLogs()">刷新</button>
        </div>
      </header>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">时间</th><th scope="col">级别</th><th scope="col">来源</th><th scope="col">内容</th></tr></thead>
          <tbody id="errlog-body"><tr><td colspan="4" class="muted">加载中…</td></tr></tbody>
        </table>
      </div>
    </section>
    <section class="section-panel">
      <header class="section-head"><div><h3 class="section-title">操作日志</h3>
      <p class="section-meta">管理员关键操作记录（改权限/删用户/增删大V/注册码/cookie）。</p></div></header>
      <div class="table-wrap">
        <table>
          <thead><tr><th scope="col">时间</th><th scope="col">管理员</th><th scope="col">操作</th><th scope="col">目标</th><th scope="col">详情</th></tr></thead>
          <tbody>${logs.length === 0 ? `<tr><td colspan="5" class="muted">暂无记录</td></tr>` : logs.map((l) => `
            <tr>
              <td>${escapeHtml(fmtDbTime(l.created_at))}</td>
              <td>${escapeHtml(l.username || "")}</td>
              <td>${escapeHtml(l.action)}</td>
              <td>${escapeHtml(l.target)}</td>
              <td class="muted">${escapeHtml(l.detail)}</td>
            </tr>`).join("")}</tbody>
        </table>
      </div>
    </section>`;
  stopSysLogsTimer();
  sysLogsTimer = setInterval(loadAdminSysLogsPanel, 5000);
  loadAdminSysLogsPanel();
  loadAdminErrorLogs();
}

async function loadAdminErrorLogs() {
  try {
    const params = new URLSearchParams({ limit: "200" });
    const levelEl = $("#errlog-level");
    const level = levelEl ? levelEl.value : "";
    if (level) params.set("level", level);
    const data = await api(`/api/admin/error-logs?${params.toString()}`);
    const rows = data.logs || [];
    const body = $("#errlog-body");
    if (!body) return;
    body.innerHTML = rows.length
      ? rows.map((r) => `
          <tr>
            <td>${escapeHtml(fmtDbTime(r.created_at))}</td>
            <td class="${r.level === "ERROR" || r.level === "CRITICAL" ? "status-fail" : ""}">${escapeHtml(r.level)}</td>
            <td class="muted">${escapeHtml(r.logger)}</td>
            <td class="muted">${escapeHtml(r.message)}</td>
          </tr>`).join("")
      : `<tr><td colspan="4" class="muted">暂无错误记录 🎉</td></tr>`;
  } catch (err) {
    const body = $("#errlog-body");
    if (body) body.innerHTML = `<tr><td colspan="4" class="muted">加载失败: ${escapeHtml(err.message)}</td></tr>`;
  }
}

let sysLogsTimer = null;

function stopSysLogsTimer() {
  if (sysLogsTimer) {
    clearInterval(sysLogsTimer);
    sysLogsTimer = null;
  }
}

async function loadAdminSysLogsPanel() {
  try {
    const params = new URLSearchParams({ limit: "500" });
    const levelEl = $("#syslog-level");
    const qEl = $("#syslog-q");
    const level = levelEl ? levelEl.value : "";
    const q = qEl ? qEl.value.trim() : "";
    if (level) params.set("level", level);
    if (q) params.set("q", q);
    const data = await api(`/api/admin/system-logs?${params.toString()}`);
    const lines = data.lines || [];
    const el = $("#syslog-pre");
    if (el) el.textContent = lines.join("\n") || "（没有匹配的日志）";
  } catch (err) {
    const el = $("#syslog-pre");
    if (el) el.textContent = "加载失败: " + err.message;
  }
}

async function adminFilterLogs() {
  const params = new URLSearchParams({ limit: "100" });
  const userId = $("#ad-logs-user").value;
  const channel = $("#ad-logs-channel").value;
  const status = $("#ad-logs-status").value;
  if (userId) params.set("user_id", userId);
  if (channel) params.set("channel", channel);
  if (status) params.set("status", status);
  state.adminLogsFilter = `&${params.toString()}`;
  state.adminLogsUserId = userId;
  state.adminLogsChannel = channel;
  state.adminLogsStatus = status;
  loadAdminLogs();
}

function backupStatusHtml(s) {
  const parts = [];
  if (s.last_ok_at) {
    parts.push(`上次<span class="status-ok">成功</span> ${escapeHtml(s.last_ok_at)}`);
  }
  if (s.last_error) {
    parts.push(`上次<span class="status-fail">失败</span> ${escapeHtml(s.last_error)}`);
  }
  if (s.last_remote_name) parts.push(`远端 ${escapeHtml(s.last_remote_name)}`);
  if (s.next_run_at) parts.push(`下次 ${escapeHtml(s.next_run_at)}`);
  if (!parts.length) {
    return `<p class="section-meta backup-status" id="backup-status">尚未执行过定时备份</p>`;
  }
  return `<p class="section-meta backup-status" id="backup-status">${parts.join(" · ")}</p>`;
}

function backupWebDAVBody() {
  const body = {
    url: $("#bk-url").value.trim(),
    username: $("#bk-user").value.trim(),
    path: $("#bk-path").value.trim() || "/vpush-backups",
    hour: Number($("#bk-hour").value),
    keep: Number($("#bk-keep").value),
  };
  const password = $("#bk-pass").value;
  if (password) body.password = password;
  return body;
}

async function loadAdminBackup() {
  const s = await api("/api/admin/backup");
  if (!routeStillActive(_adminRenderSeq)) return;
  $("#admin-body").innerHTML = `
    <section class="section-panel backup-page">
      <header class="section-head">
        <div>
          <h3 class="section-title">本机备份</h3>
          <p class="section-meta">下载当前数据库，不经过 WebDAV。</p>
        </div>
      </header>
      <div class="toolbar backup-actions">
        <button class="btn-ghost" onclick="backupDownload()">下载当前数据库</button>
      </div>
    </section>
    <section class="section-panel backup-page">
      <header class="section-head">
        <div>
          <h3 class="section-title">WebDAV 定时</h3>
          <p class="section-meta">填好后由调度每天自动上传；密码只写不回显。</p>
        </div>
      </header>
      <label class="form-label">地址
        <input id="bk-url" class="form-control" type="url" autocomplete="off" placeholder="https://example.com/webdav" value="${escapeHtml(s.url || "")}">
      </label>
      <label class="form-label">用户名
        <input id="bk-user" class="form-control" autocomplete="off" value="${escapeHtml(s.username || "")}">
      </label>
      <label class="form-label">密码
        <input id="bk-pass" class="form-control" type="password" autocomplete="new-password" placeholder="${s.password_set ? "已设置" : "WebDAV 密码"}">
      </label>
      <div class="backup-grid">
        <label class="form-label backup-path">远端目录
          <input id="bk-path" class="form-control" autocomplete="off" placeholder="/vpush-backups" value="${escapeHtml(s.path || "/vpush-backups")}">
        </label>
        <label class="form-label backup-num">每天几点
          <input id="bk-hour" class="form-control" type="number" min="0" max="23" value="${s.hour ?? 3}">
        </label>
        <label class="form-label backup-num">保留份数
          <input id="bk-keep" class="form-control" type="number" min="1" max="90" value="${s.keep ?? 14}">
        </label>
      </div>
      ${backupStatusHtml(s)}
      <div class="cfg-save-row backup-actions">
        <button class="btn-normal" onclick="saveBackupWebDAV()">保存</button>
        <button class="btn-ghost" onclick="testBackupWebDAV()">测试连接</button>
      </div>
    </section>
    <section class="section-panel backup-page">
      <header class="section-head">
        <div>
          <h3 class="section-title">恢复</h3>
          <p class="section-meta">会覆盖当前账号、订阅和帖子。恢复失败时现库不变。</p>
        </div>
      </header>
      <div class="backup-stack">
        <div class="toolbar backup-actions">
          <button id="bk-restore-webdav" class="btn-ghost danger" onclick="backupRestoreWebDAV()">从 WebDAV 恢复最新一份</button>
        </div>
        <label class="form-label">本地 .db 文件
          <input id="bk-file" class="backup-file-input" type="file" accept=".db">
        </label>
        <div class="toolbar backup-actions">
          <button id="bk-restore-upload" class="btn-ghost danger" onclick="backupRestoreUpload()">用本地备份恢复</button>
        </div>
      </div>
    </section>`;
}

async function saveBackupWebDAV() {
  try {
    await api("/api/admin/backup/webdav", {
      method: "PUT",
      body: JSON.stringify(backupWebDAVBody()),
    });
    flash("WebDAV 配置已保存");
    $("#bk-pass").value = "";
    await loadAdminBackup();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function testBackupWebDAV() {
  try {
    await api("/api/admin/backup/webdav/test", {
      method: "POST",
      body: JSON.stringify(backupWebDAVBody()),
    });
    flash("WebDAV 连接正常");
  } catch (err) {
    flash(err.message, "error");
  }
}

async function backupDownload() {
  const resp = await fetch("/api/admin/backup/download", {
    headers: { Authorization: `Bearer ${state.token}` },
  });
  if (resp.status === 401) {
    logout();
    return;
  }
  if (!resp.ok) {
    const data = await resp.json().catch(() => ({}));
    flash(typeof data.detail === "string" ? data.detail : "下载失败", "error");
    return;
  }
  const blob = await resp.blob();
  const match = /filename="?([^";]+)"?/.exec(resp.headers.get("content-disposition") || "");
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = match ? match[1] : "dav-backup.db";
  a.click();
  URL.revokeObjectURL(a.href);
}

async function backupRestoreWebDAV() {
  if (!confirm("确认用备份覆盖当前数据库？当前账号、订阅和帖子都会被替换。")) return;
  const btn = $("#bk-restore-webdav");
  if (btn) btn.disabled = true;
  try {
    await api("/api/admin/backup/restore/webdav", { method: "POST" });
    flash("已从 WebDAV 恢复");
    await loadAdminBackup();
  } catch (err) {
    flash(err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function backupRestoreUpload() {
  if (!confirm("确认用备份覆盖当前数据库？当前账号、订阅和帖子都会被替换。")) return;
  const input = $("#bk-file");
  if (!input?.files?.[0]) {
    flash("请选择 .db 备份文件", "error");
    return;
  }
  const btn = $("#bk-restore-upload");
  if (btn) btn.disabled = true;
  try {
    const fd = new FormData();
    fd.append("file", input.files[0]);
    const resp = await fetch("/api/admin/backup/restore/upload", {
      method: "POST",
      headers: { Authorization: `Bearer ${state.token}` },
      body: fd,
    });
    if (resp.status === 401) {
      logout();
      return;
    }
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      flash(typeof data.detail === "string" ? data.detail : "恢复失败", "error");
      return;
    }
    flash("已从本地备份恢复");
    await loadAdminBackup();
  } catch (err) {
    flash(err.message, "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

function userHasBoundChannel(u) {
  return !!(u.telegram_bound || u.feishu_bound || u.wecom_bound || u.bark_bound);
}

function userChannelIconsHtml(u) {
  const bound = {
    telegram: !!u.telegram_bound,
    feishu: !!u.feishu_bound,
    wecom: !!u.wecom_bound,
    bark: !!u.bark_bound,
  };
  const names = USER_CHANNEL_KEYS.filter((ch) => bound[ch]).map((ch) => CHANNEL_LABELS[ch]);
  const aria = names.length ? `已绑定 ${names.join("、")}` : "未绑定推送渠道";
  return `<span class="user-channels" title="${escapeHtml(aria)}" aria-label="${escapeHtml(aria)}">${
    USER_CHANNEL_KEYS.map((ch) =>
      `<span class="user-ch ${bound[ch] ? "on" : "off"}" data-channel="${ch}">${CHANNEL_ICONS[ch]}</span>`
    ).join("")
  }</span>`;
}

function adminUsersFiltered() {
  const q = (state.adminUsersQ || "").trim().toLowerCase();
  const filter = state.adminUsersFilter || "all";
  return (state.adminUsers || []).filter((u) => {
    if (filter === "admin" && !u.is_admin) return false;
    if (filter === "unbound" && userHasBoundChannel(u)) return false;
    if (filter === "push-off" && u.notify_enabled) return false;
    if (filter === "inactive" && !u.inactive) return false;
    if (!q) return true;
    return [u.username, u.register_code, u.register_note].some(
      (s) => String(s || "").toLowerCase().includes(q)
    );
  });
}

let _adminUsersSelected = new Set();
let _inactivePolicyDraft = null;
let _inactivePolicySaving = false;

function inactivePolicySaved() {
  return state.inactivePolicy || { inactive_after_days: 90, inactive_purge_after_days: 30 };
}

function inactivePolicyDraft() {
  return _inactivePolicyDraft || inactivePolicySaved();
}

function inactivePolicyHint(n, m) {
  n = Number(n);
  m = Number(m);
  if (!Number.isFinite(n) || n <= 0) return "已关闭标记与删除";
  if (!Number.isFinite(m) || m <= 0) return "只标记，不自动删除";
  return `每天扫一次 · 满 ${n + m} 天删除`;
}

function adminInactivePolicySyncSave() {
  const nEl = $("#au-inactive-n");
  const mEl = $("#au-inactive-m");
  const btn = $("#au-inactive-save");
  const hint = $("#au-inactive-hint");
  if (!nEl || !mEl) return;
  _inactivePolicyDraft = {
    inactive_after_days: nEl.value,
    inactive_purge_after_days: mEl.value,
  };
  if (hint) hint.textContent = inactivePolicyHint(nEl.value, mEl.value);
  const saved = inactivePolicySaved();
  const dirty =
    Number(nEl.value) !== Number(saved.inactive_after_days) ||
    Number(mEl.value) !== Number(saved.inactive_purge_after_days);
  if (btn) btn.disabled = !dirty || _inactivePolicySaving;
}

function adminInactivePolicyKeydown(event) {
  if (event.key !== "Enter") return;
  event.preventDefault();
  adminSaveInactivePolicy();
}

function adminUsersSyncBar() {
  const bar = $("#au-batch-bar");
  if (!bar) return;
  bar.style.display = _adminUsersSelected.size ? "flex" : "none";
  const strong = bar.querySelector("strong");
  if (strong) strong.textContent = `已选 ${_adminUsersSelected.size} 人`;
}

function adminUserToggleSelect(el) {
  const id = Number(el.dataset.id);
  if (el.checked) _adminUsersSelected.add(id);
  else _adminUsersSelected.delete(id);
  adminUsersSyncBar();
  const checkall = $("#au-checkall");
  const boxes = [...document.querySelectorAll(".au-check")];
  if (checkall) {
    checkall.checked = boxes.length > 0 && boxes.every((c) => c.checked);
    checkall.indeterminate = boxes.some((c) => c.checked) && !checkall.checked;
  }
}

function adminUserTogglePage(el) {
  document.querySelectorAll(".au-check").forEach((c) => {
    c.checked = el.checked;
    const id = Number(c.dataset.id);
    if (el.checked) _adminUsersSelected.add(id);
    else _adminUsersSelected.delete(id);
  });
  el.indeterminate = false;
  adminUsersSyncBar();
}

function adminUserClearSelect() {
  _adminUsersSelected.clear();
  document.querySelectorAll(".au-check").forEach((c) => { c.checked = false; });
  const checkall = $("#au-checkall");
  if (checkall) {
    checkall.checked = false;
    checkall.indeterminate = false;
  }
  adminUsersSyncBar();
}

async function adminUsersBatch(action) {
  const ids = [..._adminUsersSelected];
  if (!ids.length) return;
  if (action === "delete" && !confirm(`确认删除选中的 ${ids.length} 个用户？其订阅关系将一并删除，不可恢复。`)) return;
  try {
    const data = await api("/api/admin/users/batch", {
      method: "POST",
      body: JSON.stringify({ ids, action }),
    });
    const n = data.count || 0;
    const skipped = data.skipped || 0;
    if (action === "delete") {
      flash(skipped ? `已删除 ${n} 人，跳过本人` : `已删除 ${n} 人`);
    } else if (action === "enable_notify") {
      flash(`已开启 ${n} 人推送`);
    } else if (action === "disable_notify") {
      flash(`已关闭 ${n} 人推送`);
    }
    _adminUsersSelected.clear();
    loadAdminUsers();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function loadAdminUsers() {
  let users;
  let policy;
  try {
    [users, policy] = await Promise.all([
      api("/api/users"),
      api("/api/admin/inactive-users-policy"),
    ]);
  } catch (err) {
    if (!routeStillActive(_adminRenderSeq)) return;
    $("#admin-body").innerHTML = emptyState("加载失败: " + err.message);
    return;
  }
  state.adminUsers = users;
  if (policy) state.inactivePolicy = policy;
  const known = new Set(users.map((u) => u.id));
  for (const id of [..._adminUsersSelected]) {
    if (!known.has(id)) _adminUsersSelected.delete(id);
  }
  renderAdminUsers();
}

function adminUsersApplyFilter(filter) {
  const q = $("#au-q");
  if (q) state.adminUsersQ = q.value.trim();
  if (filter) state.adminUsersFilter = filter;
  renderAdminUsers();
}

async function adminSaveInactivePolicy() {
  const nEl = $("#au-inactive-n");
  const mEl = $("#au-inactive-m");
  const btn = $("#au-inactive-save");
  if (!nEl || !mEl || _inactivePolicySaving) return;
  const n = Number(nEl.value);
  const m = Number(mEl.value);
  if (!Number.isInteger(n) || !Number.isInteger(m) || n < 0 || n > 3650 || m < 0 || m > 3650) {
    flash("天数须在 0–3650", "error");
    return;
  }
  const saved = inactivePolicySaved();
  if (n === Number(saved.inactive_after_days) && m === Number(saved.inactive_purge_after_days)) return;
  _inactivePolicySaving = true;
  if (btn) btn.disabled = true;
  try {
    state.inactivePolicy = await api("/api/admin/inactive-users-policy", {
      method: "PUT",
      body: JSON.stringify({ inactive_after_days: n, inactive_purge_after_days: m }),
    });
    _inactivePolicyDraft = null;
    flash("已保存非活跃规则");
    await loadAdminUsers();
  } catch (err) {
    flash(err.message, "error");
  } finally {
    _inactivePolicySaving = false;
    adminInactivePolicySyncSave();
  }
}

function renderAdminUsers() {
  if (!routeStillActive(_adminRenderSeq)) return;
  const body = $("#admin-body");
  if (!body) return;
  const users = state.adminUsers || [];
  const filter = state.adminUsersFilter || "all";
  const filtered = adminUsersFiltered();
  const boundN = users.filter(userHasBoundChannel).length;
  const adminN = users.filter((u) => u.is_admin).length;
  const counts = {
    all: users.length,
    admin: adminN,
    unbound: users.filter((u) => !userHasBoundChannel(u)).length,
    "push-off": users.filter((u) => !u.notify_enabled).length,
    inactive: users.filter((u) => u.inactive).length,
  };
  const tab = (key, label) =>
    `<button class="settings-tab ${filter === key ? "active" : ""}" role="tab" aria-selected="${filter === key}" onclick="adminUsersApplyFilter('${key}')">${label} ${counts[key]}</button>`;
  const emptyMsg = users.length
    ? "没有匹配的用户"
    : "还没有注册用户";
  const rows = filtered.map((u) => {
    const self = state.user && u.id === state.user.id;
    const pills = `${u.is_admin ? `<span class="user-pill">管理员</span>` : ""}${self ? `<span class="user-pill muted">本人</span>` : ""}`;
    const push = u.inactive
      ? (u.days_until_purge == null
        ? `<span class="status-warn">非活跃</span>`
        : `<span class="status-warn">非活跃</span><span class="muted"> · ${Number(u.days_until_purge)} 天后删除</span>`)
      : u.notify_enabled
      ? `<span class="status-ok">开启</span>${u.dnd_enabled ? `<span class="muted"> · 免打扰</span>` : ""}`
      : `<span class="status-fail">关闭</span>`;
    return `<tr>
      <td><input type="checkbox" class="au-check" data-id="${u.id}" ${_adminUsersSelected.has(u.id) ? "checked" : ""} onchange="adminUserToggleSelect(this)" aria-label="选择用户"></td>
      <td>
        <div class="user-name">
          <strong>${escapeHtml(u.username)}</strong>
          ${pills}
        </div>
      </td>
      <td>${escapeHtml(u.register_note || u.register_code || "—")}</td>
      <td>${userChannelIconsHtml(u)}</td>
      <td>${Number(u.subscription_count) || 0}</td>
      <td>${push}</td>
      <td>${escapeHtml(fmtDbTime(u.created_at))}</td>
      <td>
        <button class="btn-sm" onclick="adminOpenUser(${u.id})">管理</button>
        <button class="btn-sm" onclick="adminOpenUser(${u.id}, 'push')">测试推送</button>
      </td>
    </tr>`;
  }).join("");
  body.innerHTML = `
    <section class="section-panel">
      <header class="section-head au-head">
        <div>
          <h3 class="section-title">用户管理</h3>
          <p class="section-meta">${users.length} 人 · ${adminN} 管理员 · ${boundN} 已绑定渠道</p>
        </div>
        <div class="search-bar au-search">
          ${SEARCH_ICON}
          <input id="au-q" type="search" placeholder="搜索用户名 / 邀请码 / 备注，回车" value="${escapeHtml(state.adminUsersQ || "")}" onkeydown="if(event.key==='Enter')adminUsersApplyFilter()">
        </div>
      </header>
      <div class="rc-generate au-inactive-policy">
        <label class="rc-field rc-field-num">
          <span>列为非活跃 <span class="cfg-unit">天</span></span>
          <input id="au-inactive-n" class="form-control" type="number" min="0" max="3650" inputmode="numeric" value="${escapeHtml(String(inactivePolicyDraft().inactive_after_days ?? 90))}" oninput="adminInactivePolicySyncSave()" onkeydown="adminInactivePolicyKeydown(event)" aria-describedby="au-inactive-hint">
        </label>
        <label class="rc-field rc-field-num">
          <span>之后删除 <span class="cfg-unit">天</span></span>
          <input id="au-inactive-m" class="form-control" type="number" min="0" max="3650" inputmode="numeric" value="${escapeHtml(String(inactivePolicyDraft().inactive_purge_after_days ?? 30))}" oninput="adminInactivePolicySyncSave()" onkeydown="adminInactivePolicyKeydown(event)" aria-describedby="au-inactive-hint">
        </label>
        <div class="rc-field-submit">
          <button type="button" class="btn-normal" id="au-inactive-save" onclick="adminSaveInactivePolicy()">保存</button>
        </div>
        <span class="muted rc-generate-hint" id="au-inactive-hint">${escapeHtml(inactivePolicyHint(inactivePolicyDraft().inactive_after_days, inactivePolicyDraft().inactive_purge_after_days))}</span>
      </div>
      <div class="settings-tabs" role="tablist" aria-label="用户筛选">
        ${tab("all", "全部")}
        ${tab("admin", "管理员")}
        ${tab("unbound", "未绑定")}
        ${tab("push-off", "推送关闭")}
        ${tab("inactive", "非活跃")}
      </div>
      <div class="toolbar admin-batch-bar" id="au-batch-bar" style="margin-top:10px;display:${_adminUsersSelected.size ? "flex" : "none"};align-items:center;gap:8px;flex-wrap:wrap">
        <strong>已选 ${_adminUsersSelected.size} 人</strong>
        <button type="button" class="btn-sm" onclick="adminUsersBatch('enable_notify')">开启推送</button>
        <button type="button" class="btn-sm" onclick="adminUsersBatch('disable_notify')">关闭推送</button>
        <button type="button" class="btn-sm danger" onclick="adminUsersBatch('delete')">删除</button>
        <button type="button" class="btn-sm" onclick="adminUserClearSelect()">取消选择</button>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th scope="col" style="width:32px"><input type="checkbox" id="au-checkall" onchange="adminUserTogglePage(this)" aria-label="全选当前筛选"></th>
            <th scope="col">用户</th>
            <th scope="col">来源</th>
            <th scope="col">渠道</th>
            <th scope="col">订阅</th>
            <th scope="col">推送</th>
            <th scope="col">注册</th>
            <th scope="col">操作</th>
          </tr></thead>
          <tbody>${rows || `<tr><td colspan="8" class="muted">${emptyMsg}</td></tr>`}</tbody>
        </table>
      </div>
    </section>`;
  const qEl = $("#au-q");
  if (qEl) qEl.value = state.adminUsersQ || "";
  const checkall = $("#au-checkall");
  const boxes = [...document.querySelectorAll(".au-check")];
  if (checkall) {
    checkall.checked = boxes.length > 0 && boxes.every((c) => _adminUsersSelected.has(Number(c.dataset.id)));
    checkall.indeterminate = boxes.some((c) => c.checked) && !checkall.checked;
  }
  adminInactivePolicySyncSave();
}

function closeAdminModal() {
  document.querySelectorAll(".modal-mask").forEach((el) => el.remove());
}

function adminOpenUser(userId, focus) {
  const u = (state.adminUsers || []).find((row) => row.id === userId);
  if (!u) {
    flash("用户不存在或列表已过期", "error");
    return;
  }
  const self = state.user && u.id === state.user.id;
  closeAdminModal();
  const mask = document.createElement("div");
  mask.className = "modal-mask";
  mask.innerHTML = `
    <div class="modal-card user-modal" role="dialog" aria-modal="true" aria-labelledby="um-title">
      <h3 id="um-title">管理用户 · ${escapeHtml(u.username)}</h3>
      <p class="muted um-meta">ID ${u.id} · 订阅 ${Number(u.subscription_count) || 0} · 注册 ${escapeHtml(fmtDbTime(u.created_at))}</p>
      <label class="form-label">用户名
        <div class="row">
          <input id="um-name" class="form-control" maxlength="30" value="${escapeHtml(u.username)}" autocomplete="username">
          <button class="btn-sm" onclick="adminSaveUsername(${u.id})">保存</button>
        </div>
      </label>
      <label class="form-label">新密码
        <div class="row">
          <input id="um-pass" class="form-control" type="password" minlength="6" placeholder="至少 6 位" autocomplete="new-password">
          <button class="btn-sm" onclick="adminSavePassword(${u.id})">重置</button>
        </div>
      </label>
      ${self ? "" : `<div class="form-label">管理员
        <div class="toolbar">
          <button class="btn-sm" onclick="adminToggleAdmin(${u.id}, ${!u.is_admin})">${u.is_admin ? "取消管理员" : "设为管理员"}</button>
        </div>
      </div>`}
      <label class="form-label">测试推送
        <textarea id="um-push-msg" class="form-control" rows="2">这是一条测试推送</textarea>
      </label>
      <div class="toolbar">
        <button class="btn-sm" id="um-push-send" onclick="adminSendTestPush(${u.id})">发送测试</button>
      </div>
      <p id="um-push-result" class="muted um-push-result" hidden></p>
      ${self ? "" : `<div class="user-modal-danger">
        <p class="muted">删除后订阅一并清除，不可恢复。</p>
        <button class="btn-sm danger" onclick="adminDeleteUser(${u.id})">删除用户</button>
      </div>`}
      <div class="toolbar" style="margin-top:16px">
        <button class="btn-sm" onclick="closeAdminModal()">关闭</button>
      </div>
    </div>`;
  mask.addEventListener("click", (e) => {
    if (e.target === mask) mask.remove();
  });
  mask.addEventListener("keydown", (e) => {
    if (e.key === "Escape") mask.remove();
  });
  document.body.appendChild(mask);
  const trigger = document.activeElement;
  const first = focus === "push" ? $("#um-push-msg") : $("#um-name");
  if (first) first.focus();
  const observer = new MutationObserver(() => {
    if (!document.body.contains(mask)) {
      observer.disconnect();
      if (trigger && trigger.isConnected) trigger.focus();
    }
  });
  observer.observe(document.body, { childList: true });
}

async function adminSaveUsername(userId) {
  const input = $("#um-name");
  const trimmed = (input ? input.value : "").trim();
  if (trimmed.length < 6 || trimmed.length > 30) {
    flash("用户名需 6-30 位", "error");
    return;
  }
  try {
    await api(`/api/users/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ username: trimmed }),
    });
    if (state.user && userId === state.user.id) {
      state.user.username = trimmed;
      renderSidebar(state.user);
      renderTopbar(state.user);
    }
    closeAdminModal();
    flash(`已重命名用户「${trimmed}」`);
    loadAdminUsers();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function adminSavePassword(userId) {
  const input = $("#um-pass");
  const pw = input ? input.value : "";
  if (pw.length < 6) {
    flash("密码至少 6 位", "error");
    return;
  }
  try {
    await api(`/api/users/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ password: pw }),
    });
    closeAdminModal();
    flash("密码已重置");
    loadAdminUsers();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function adminSendTestPush(userId) {
  const btn = $("#um-push-send");
  const msgEl = $("#um-push-msg");
  const resultEl = $("#um-push-result");
  const msg = ((msgEl && msgEl.value) || "").trim() || "这是一条测试推送";
  if (btn) btn.disabled = true;
  try {
    const data = await api("/api/admin/test-push", {
      method: "POST",
      body: JSON.stringify({ user_id: userId, message: msg }),
    });
    const lines = (data.results || []).map((r) => {
      const label = CHANNEL_LABELS[r.channel] || r.channel;
      return r.ok ? `${label}：成功` : `${label}：失败：${r.error || ""}`;
    });
    if (resultEl) {
      resultEl.hidden = false;
      resultEl.textContent = lines.join("\n") || "没有返回渠道结果";
    }
    const failed = (data.results || []).some((r) => !r.ok);
    flash(failed ? "测试推送部分失败" : "测试推送已发送", failed ? "error" : "success");
  } catch (err) {
    flash(err.message, "error");
    if (resultEl) {
      resultEl.hidden = false;
      resultEl.textContent = err.message;
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function adminDeleteUser(userId) {
  const user = (state.adminUsers || []).find((u) => u.id === userId);
  if (!confirm(`确认删除用户「${user ? user.username : userId}」？其订阅关系将一并删除，不可恢复。`)) return;
  try {
    await api(`/api/users/${userId}`, { method: "DELETE" });
    closeAdminModal();
    flash(`已删除用户「${user ? user.username : userId}」`);
    loadAdminUsers();
  } catch (err) {
    flash(err.message, "error");
  }
}

async function adminToggleAdmin(userId, makeAdmin) {
  const user = (state.adminUsers || []).find((u) => u.id === userId);
  const name = user ? user.username : String(userId);
  if (!confirm(makeAdmin ? `确认把「${name}」设为管理员？` : `确认取消「${name}」的管理员权限？`)) return;
  try {
    await api(`/api/users/${userId}`, {
      method: "PUT",
      body: JSON.stringify({ is_admin: makeAdmin }),
    });
    closeAdminModal();
    flash(makeAdmin ? `已将「${name}」设为管理员` : `已取消「${name}」的管理员权限`);
    loadAdminUsers();
  } catch (err) {
    flash(err.message, "error");
  }
}

// ---------- 主题（深色模式）----------
const THEME_KEY = "theme"; // 值：light | dark | auto

function themeMode() {
  try {
    return localStorage.getItem(THEME_KEY) || "auto";
  } catch {
    return "auto";
  }
}

function systemPrefersDark() {
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function applyTheme() {
  const mode = themeMode();
  const dark = mode === "dark" || (mode === "auto" && systemPrefersDark());
  document.documentElement.classList.toggle("theme-dark", dark);
  // 同步顶部浏览器 UI（桌面无意义，PWA/移动端状态栏）。
  // 用页面顶部背景色而非品牌强调色：iOS 用 theme-color 填充状态栏/安全区，
  // 若填强调蓝会出现一条与页面不符的蓝色条（详见 PWA 顶部蓝条问题）。
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", dark ? "#11141a" : "#f8f8fb");
  // 品牌符号（登录页 + topbar + 侧边栏）用融合版，深浅各一
  const logo = document.querySelector(".topbar-logo");
  if (logo) logo.src = dark ? "/logo-mark-dark.svg" : "/logo-mark.svg";
  const sidebarLogo = document.querySelector("#sidebar-logo");
  if (sidebarLogo) sidebarLogo.src = dark ? "/logo-mark-dark.svg" : "/logo-mark.svg";
  const loginLogo = document.querySelector("#login-logo");
  if (loginLogo) loginLogo.src = dark ? "/logo-mark-dark.svg" : "/logo-mark.svg";
  const favicon = document.getElementById("favicon");
  if (favicon) favicon.setAttribute("href", dark ? "/logo-mark-dark.svg" : "/logo-mark.svg");
  return dark;
}

function setTheme(mode) {
  if (!["light", "dark", "auto"].includes(mode)) mode = "auto";
  try {
    localStorage.setItem(THEME_KEY, mode);
  } catch { /* localStorage 不可用则只影响当前页 */ }
  applyTheme();
  renderThemeSwitcher();
}

function themeIconFor(mode) {
  return { light: THEME_SUN_ICON, dark: THEME_MOON_ICON, auto: THEME_AUTO_ICON }[mode] || THEME_AUTO_ICON;
}

function themeLabelFor(mode) {
  return { light: "浅色", dark: "深色", auto: "跟随系统" }[mode] || "跟随系统";
}

function renderThemeSwitcher() {
  const el = $("#theme-switcher");
  if (!el) return;
  const mode = themeMode();
  el.innerHTML = ["light", "dark", "auto"].map((m) => `
    <button class="theme-mode ${mode === m ? "selected" : ""}" data-mode="${m}" title="${themeLabelFor(m)}" aria-label="${themeLabelFor(m)}" aria-pressed="${mode === m}" onclick="setTheme('${m}')">${themeIconFor(m)}</button>`).join("");
}

function updateThemeToggleIcon() {
  const btn = $("#theme-toggle-btn");
  if (btn) btn.innerHTML = themeIconFor(themeMode());
}

function cycleTheme() {
  // 移动端顶部按钮：light → dark → auto 循环切换
  const order = ["light", "dark", "auto"];
  const next = order[(order.indexOf(themeMode()) + 1) % order.length];
  setTheme(next);
  updateThemeToggleIcon();
}

// 系统主题变化时，auto 模式跟随；手动模式不打扰
if (window.matchMedia) {
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    if (themeMode() === "auto") {
      applyTheme();
      renderThemeSwitcher();
      updateThemeToggleIcon();
    }
  });
}

// ---------- 路由 ----------
let routeRenderSeq = 0; // 每次路由切换递增；异步渲染完成后凭此丢弃过期响应

function routeStillActive(seq) {
  // 令牌必须是整数且等于当前路由序号；局部刷新必须在发起请求前捕获 routeRenderSeq 并回传
  return Number.isInteger(seq) && seq === routeRenderSeq;
}

async function router() {
  const renderSeq = ++routeRenderSeq;
  stopSettingsPoll();
  stopSysLogsTimer();
  stopStatsTimer();
  stopTimelinePoll();
  // 离开动态页前记录滚动位置，切回时恢复阅读位置
  if (document.querySelector("#feed")) _tlSavedScrollY = window.scrollY;
  const hash = location.hash.replace(/^#\/?/, "") || "timeline";
  // 先去掉 query（#/search?q=xxx），再按路径分段
  const path = hash.split("?")[0];
  const [page, rawParam] = path.split("/");
  // 管理后台默认全景概览：/admin 与 /admin/dashboard 等价，侧边栏高亮才能对上
  const param = page === "admin" && !rawParam ? "dashboard" : rawParam;
  if (!state.token) {
    $("#app-view").classList.add("hidden");
    $("#auth-view").classList.remove("hidden");
    return;
  }
  $("#auth-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  try {
    state.user = await api("/api/me");
    // /api/me 挂起期间若已切走路由，旧响应不能覆盖新路由的 state.user
    if (!routeStillActive(renderSeq)) return;
  } catch {
    return;
  }
  renderSidebar(state.user);
  renderTopbar(state.user);
  renderBottomNav(state.user);
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.route === page || b.dataset.route === `${page}/${param}`)
  );
  // 底部栏高亮：管理员进后台页时高亮「更多」
  const activeBottom = page === "admin" ? "more" : page;
  document.querySelectorAll(".bnav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.route === activeBottom)
  );
  try {
    if (page === "home") await renderHome(renderSeq);
    else if (page === "combinations") await renderCombinations(renderSeq);
    else if (page === "mysubs") await renderMySubs(renderSeq);
    else if (page === "timeline") await renderTimeline(renderSeq);
    else if (page === "settings") await renderSettings(renderSeq);
    else if (page === "more") await renderMore(renderSeq);
    else if (page === "search") await renderSearch(renderSeq);
    else if (page === "kol") await renderKolPage(Number(param), renderSeq);
    else if (page === "admin") {
      if (!state.user.is_admin) { location.hash = "#/timeline"; return; }
      // 分类管理/标签管理已合并为 admin/vocab：旧书签自动跳转
      if (param === "categories" || param === "tags") {
        location.hash = "#/admin/vocab";
        return;
      }
      await renderAdmin(param || "dashboard", renderSeq);
    }
    else { location.hash = "#/timeline"; await renderTimeline(renderSeq); }
  } catch (err) {
    // 只在当前路由仍是本次渲染目标时才写错误状态，避免旧路由的错误覆盖新页面
    if (routeStillActive(renderSeq)) $("#main").innerHTML = emptyState(err.message);
  }
}

// ---------- 认证 ----------
function togglePassword(inputId, btn) {
  const input = document.getElementById(inputId);
  if (!input) return;
  const show = input.type === "password";
  input.type = show ? "text" : "password";
  btn.classList.toggle("visible", show);
  btn.setAttribute("aria-label", show ? "隐藏密码" : "显示密码");
  btn.setAttribute("aria-pressed", String(show));
}

async function doLogin(e) {
  e.preventDefault();
  $("#auth-error").textContent = "";
  const btn = $("#login-form").querySelector('button[type="submit"]');
  btn.disabled = true;
  btn.textContent = "登录中…";
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username: $("#login-username").value.trim(), password: $("#login-password").value }),
    });
    state.token = data.token;
    localStorage.setItem("dav_token", data.token);
    location.hash = "#/timeline";
    router();
  } catch (err) {
    $("#auth-error").textContent = err.message;
    btn.disabled = false;
    btn.textContent = "登 录";
  }
}

async function doRegister(e) {
  e.preventDefault();
  $("#reg-error").textContent = "";
  const btn = $("#register-form").querySelector('button[type="submit"]');
  btn.disabled = true;
  btn.textContent = "创建中…";
  try {
    const data = await api("/api/auth/register", {
      method: "POST",
      body: JSON.stringify({
        username: $("#reg-username").value.trim(),
        password: $("#reg-password").value,
        code: $("#reg-code").value.trim(),
      }),
    });
    state.token = data.token;
    localStorage.setItem("dav_token", data.token);
    location.hash = "#/timeline";
    router();
  } catch (err) {
    $("#reg-error").textContent = err.message;
    btn.disabled = false;
    btn.textContent = "创建账号";
  }
}

function switchAuthMode(mode) {
  const isLogin = mode === "login";
  $("#login-form").classList.toggle("hidden", !isLogin);
  $("#register-form").classList.toggle("hidden", isLogin);
  $("#auth-error").textContent = "";
  $("#reg-error").textContent = "";
  resetAuthButtons();
  document.querySelectorAll(".switch-btn").forEach((btn) =>
    btn.classList.toggle("active", btn.dataset.mode === mode)
  );
  // 登录/注册 tab 的选中态同步给读屏（aria-selected）
  document.querySelectorAll(".switch-btn").forEach((btn) =>
    btn.setAttribute("aria-selected", String(btn.dataset.mode === mode))
  );
}

// ---------- 事件 ----------
$("#login-form").addEventListener("submit", doLogin);
$("#register-form").addEventListener("submit", doRegister);
document.querySelectorAll(".switch-btn").forEach((btn) =>
  btn.addEventListener("click", () => switchAuthMode(btn.dataset.mode))
);
$("#btn-back").addEventListener("click", () => history.back());
window.addEventListener("hashchange", router);

// PWA：注册 Service Worker（HTTP 或私有模式下失败静默，不影响功能）
if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

applyTheme(); // 与 index.html 防闪脚本同一逻辑，兜底 + 同步 meta theme-color
router();