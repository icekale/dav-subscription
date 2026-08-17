---
name: V Push
description: 安静的控制台：把多源大V动态送到用户自己的渠道
colors:
  primary: "#1f74ee"
  primary-strong: "#1668e0"
  primary-text: "#1668e0"
  primary-soft: "rgba(22, 119, 255, 0.12)"
  canvas: "#f5f5f7"
  surface: "#ffffff"
  ink: "#1d1d1f"
  ink-strong: "#222c3c"
  muted: "#6e6e73"
  faint: "#667080"
  line: "rgba(12, 18, 34, 0.1)"
  success: "#16a34a"
  warning: "#d97706"
  danger: "#dc2626"
  data-up: "#b05b63"
  data-down: "#23714a"
  white: "#ffffff"
typography:
  display:
    fontFamily: "SF Pro SC, SF Pro Display, PingFang SC, Helvetica Neue, Arial, sans-serif"
    fontSize: "30px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.2px"
  title:
    fontFamily: "SF Pro SC, SF Pro Display, PingFang SC, Helvetica Neue, Arial, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.3
    letterSpacing: "normal"
  body:
    fontFamily: "SF Pro SC, SF Pro Text, PingFang SC, Helvetica Neue, Arial, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.65
    letterSpacing: "normal"
  label:
    fontFamily: "SF Pro SC, SF Pro Text, PingFang SC, Helvetica Neue, Arial, sans-serif"
    fontSize: "13px"
    fontWeight: 500
    lineHeight: 1.3
    letterSpacing: "normal"
  caption:
    fontFamily: "SF Pro SC, SF Pro Text, PingFang SC, Helvetica Neue, Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "normal"
    fontFeature: "tabular-nums"
rounded:
  "2xs": "6px"
  xs: "10px"
  control: "12px"
  sm: "14px"
  md: "18px"
  card: "20px"
  pill: "999px"
spacing:
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "20px"
  page: "24px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.white}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 20px"
    height: "42px"
  button-primary-hover:
    backgroundColor: "{colors.primary-strong}"
    textColor: "{colors.white}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 20px"
    height: "42px"
  button-ghost:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink-strong}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "34px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.control}"
    padding: "0 14px"
    height: "42px"
  chip:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 14px"
    height: "38px"
  chip-selected:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.white}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 14px"
    height: "38px"
  nav-item-active:
    backgroundColor: "{colors.primary-soft}"
    textColor: "{colors.primary-text}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "10px 12px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.card}"
    padding: "16px"
---

# Design System: V Push

## Overview

**Creative North Star: "安静的控制台"**

V Push 是一台安静的控制台：用户在桌面或手机上打开它，快速确认「谁发了新动态、有没有推出去、数据源是否健康」，然后合上。它不是内容社区，而是通知管线——界面的任务是把状态讲清楚，然后退到后台。

默认界面保持低饱和的克制。只有状态真的变化时，才用克制蓝和告警色把信息顶到眼前。密度遵循「信息优先」：订阅广场是卡片网格，管理端是数据表格，时间线是紧凑的时间分组列表。手感是克制精致：少装饰，边和字都收着，按下去才有反馈。

审美上明确拒绝营销式落地页、插画装饰、霓虹暗色和玻璃拟态。克制蓝是唯一的强调色，每一次出现都对应「可以操作 / 已经选中 / 需要关注」。深色是同一套系统的夜间版：色相不变，只换画布和字。动效只回应状态，不让人等动画。

**Key Characteristics:**

- 单一强调色（克制蓝）只服务状态与操作，不装饰
- 信息密度优先：卡片网格 + 数据表格 + 紧凑时间线
- 壳层用不透明画布色，不用半透明模糊
- 深/浅是同一套 token 的夜间换底，不是另一套皮肤
- 手机浏览器与桌面同为一等场景：触控目标 ≥44px

## Colors

克制的中性画布，加上一枚只在有事时出现的蓝。

### Primary

- **克制蓝** (`{colors.primary}`): 实底填充——主按钮、选中的筛选胶囊、新帖胶囊。白字走这条，对比约 4.4:1。
- **克制蓝（字与描边）** (`{colors.primary-text}`): 浅底上的链接、描边、激活字。比填充深一档，保证约 5.1:1。悬停实底用 `{colors.primary-strong}`。
- **克制蓝软底** (`{colors.primary-soft}`): 导航选中、星标开、淡提示。有色，但不是实心块。

**The Rarity Rule.** 克制蓝在任意一屏占比应 ≤10%。拿它做无状态描边、大面积底或装饰渐变，这一屏就偏了。稀有就是信息量。

### Neutral

- **画布** (`{colors.canvas}`): 页底、顶栏、侧栏、底栏。壳层与页面同色，不另做玻璃层。
- **纸面** (`{colors.surface}`): 卡片、输入、未选中胶囊。
- **墨** (`{colors.ink}` / `{colors.ink-strong}`): 正文与标题。
- **雾灰** (`{colors.muted}`): 时间、辅助说明。
- **淡灰** (`{colors.faint}`): 分组标签、更弱的元信息。
- **线** (`{colors.line}`): 默认 1px 分隔。更强/更弱用同一色相加减透明度，不另开灰。

### Semantic

- **成功绿 / 警告橙 / 危险红**: 只表示订阅成功、降级、失败。不拿来做品牌装饰。
- **数据红 / 数据绿** (`{colors.data-up}` / `{colors.data-down}`): 仅组合净值。A 股惯例红涨绿跌，与成功/危险语义色分开。
- **平台色**（雪球、微博、X、Telegram、飞书、企微）: 只给图标上色。不进按钮、不进大面积底。

深色主题换画布为 `#0f1115`、纸面 `#171a20`、正文 `#e4e6eb`；浅底蓝字提到 `#5a9bf5`。实底主色保持浅色值，因为按钮上的白字对比是按浅色算的。

## Typography

**Display Font:** SF Pro SC / SF Pro Display（回退 PingFang SC, Helvetica Neue, Arial）
**Body Font:** 同一套无衬线栈，不另配展示体
**Mono Font:** ui-monospace / SFMono-Regular / Menlo / Consolas（绑定码、系统日志）

**Character:** 系统中文无衬线。不加载网字体。字重上限 600。层级靠四档字号，不靠 14 与 15 挤在一起。

### Hierarchy

- **Display** (600, 30px): 仅登录字标。
- **Title** (600, 17px): 页标题、侧栏品牌、区块标题。
- **Body** (400, 15px, 行高 1.65，深色 1.7): 动态正文、表单、大V名。正文行宽上限 75ch。按词断行，不用 `break-all`。
- **Label** (500–600, 13px): 按钮、导航、筛选控件。
- **Caption** (400, 12px, tabular-nums): 时间、表头、底栏标签、条数。图表刻度可到 10/11px。

**The Four-Role Rule.** 阅读字号只准这四档：12 / 13 / 15 / 17。14 和 16 不进产品字号。字重不超过 600。时间、条数、净值用等宽数字。

例外（不是阅读角色）：头像字母与按钮字形 20px；移动端输入 16px，避免 iOS 聚焦整页缩放。

## Layout

桌面是 220px 侧栏 + 铺满的主列。内容区左右 24px，不在宽屏居中留白；可读性靠正文 75ch，不靠缩小外壳。

订阅广场：`auto-fill` 网格，卡片最小约 300px，间隙 14px。时间线：按日分组的列表，帖子之间一条软线。管理端：表格，表头用画布灰。

断点：900px 收侧栏信息；768px 藏侧栏、出底栏，触控目标提到 ≥44px，页边收到 14px，主区底部给底栏 + 安全区留空。640px 再收一层登录与部分表格。

间距用 8 / 12 / 16 / 20 / 24。组内紧、组间松；标题上方空隙大于下方。

## Elevation & Depth

默认平面。层级靠画布/纸面的色差和 1px 线。阴影只回应状态：卡片 hover、下拉、焦点。

壳层（顶栏、筛选条、侧栏、底栏）与画布同色、不透明，禁止半透明 + `backdrop-filter`。

### Shadow Vocabulary

- **静息抬起** (`0 2px 10px rgba(15, 23, 42, 0.04)`): 卡片 hover。深色把 alpha 提到约 0.4。
- **面板** (`0 8px 24px rgba(15, 23, 42, 0.06)`): 下拉、弹出。
- **登录抬起** (`0 12px 30px rgba(15, 23, 42, 0.05)`): 登录卡片。
- **焦点圈** (`0 0 0 3px rgba(0, 113, 227, 0.08)`): 输入与可聚焦控件。深色用 `rgba(64, 145, 255, 0.25)`。

**The Shadow-Is-State Rule.** 平面是默认。阴影只作为 hover、浮层、焦点的响应。禁止给静止卡片同时上 1px 边框 + 宽软阴影。二选一：线，或 ≤10px blur 的轻影。

## Shapes

控件 12px 圆角，卡片 20px 封顶，筛选与开关走胶囊。更小的图标按钮 6–10px。头像正圆。

边框是 1px 中性线。选中时线色跟克制蓝走，或改实心底。不要彩色左边条，不要超过 20px 的卡片圆角。

## Components

手感：克制精致。边和字收着，状态靠色和字重，不靠阴影堆。

### Buttons

- **Shape:** 控件圆角 (12px)
- **Primary:** 克制蓝实底、白字、15px/600、高 42px、左右 20px。悬停/按下用更深一档；按下微移 1px。
- **Ghost:** 纸面 + 1px 线、13px/500、高 34px。危险变体改字和线为红，不改成实心红底。
- **Focus:** 2px 克制蓝描边，offset 2px。
- **Mobile:** 主操作最小高度 44px。

### Chips

- **Style:** 胶囊、纸面、1px 线。分类芯片 12px 高 32px；时间线平台胶囊 13px 高 38px。
- **State:** 未选中墨/线；悬停线与字转克制蓝；选中实底白字。星标/次要开关选中用软底 + 蓝字，不走实心，避免一排蓝块。

### Cards / Containers

- **Corner Style:** 卡片圆角 (20px)
- **Background:** 纸面
- **Shadow Strategy:** 静息无影；hover 改线色为克制蓝并加 xs 影
- **Border:** 1px 默认线
- **Internal Padding:** 16px

### Inputs / Fields

- **Style:** 纸面、1px 强线、12px 圆角、15px 字、高 42px
- **Focus:** 线转克制蓝字色 + 焦点圈
- **Error:** 字用危险红，不另做红底大块
- **Mobile:** 字号 16px，防 iOS 缩放

### Navigation

- **Desktop:** 220px 侧栏，画布底。项 13px，12px 圆角。悬停淡蓝底；当前项淡蓝底 + 克制蓝字 + 600。
- **Topbar:** 高 56px，与画布同色，底部分割线。
- **Mobile:** 侧栏隐藏；底栏画布色 + 顶线；项 12px；当前项克制蓝字。

### Timeline post (signature)

头像 38px，名字 15px/600，时间 12px 等宽数字，正文 15px / 1.65 / 最大 75ch。平台点是 20px 圆底上的线性图标，用平台色，不用大色块。新帖胶囊是少有的实心蓝中断：叠头像 +「已发布」，点一下即消失。

### KOL card (signature)

纸面卡片、20px 圆角。头像可用品牌渐变（上 `#2a86ff` 到主色）或缓存图。主操作与星标/删除在同一 44px 行。

## Do's and Don'ts

### Do:

- **Do** 让克制蓝只出现在可操作 / 已选中 / 需关注（主按钮、选中胶囊、焦点、新帖胶囊）。
- **Do** 用四档字号 12 / 13 / 15 / 17，时间与数字用 `tabular-nums`。
- **Do** 壳层与画布同色、不透明；深度用线，阴影留给状态。
- **Do** 图标用线性描边 SVG（`stroke="currentColor"`），与星标/铃铛同一套。
- **Do** 移动端触控 ≥44px；空状态写出下一步（「去订阅」「清除筛选」）。
- **Do** 动效限制在约 160ms；尊重 `prefers-reduced-motion`。

### Don't:

- **Don't** 用 emoji 或 Unicode 符号（☰◎◈）当导航/按钮图标。
- **Don't** 用渐变字、彩色左边条、霓虹暗色、玻璃拟态。
- **Don't** 做营销落地页排版（大留白、hero 大数字、逐屏进场）。
- **Don't** 给静止卡片同时加 1px 边框 + 宽软阴影。
- **Don't** 卡片圆角超过 20px。
- **Don't** 换第二套正文字体，或把 Inter / 思源黑体当中文界面的「高级感」。
- **Don't** 把平台品牌色铺进按钮或大面积底。
- **Don't** 编造用户评价或社会证明。
