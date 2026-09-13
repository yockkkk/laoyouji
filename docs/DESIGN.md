# 康乐 · 设计基线（DESIGN.md）

> blueprint 五步流程第 2 步的产物。前端一切返工以本文件为准：**页面不得自行发明颜色、字号、间距和导航方式。**

## 0. 这份文档为什么存在

改造前 `docs/` 里没有它，后果是可指的 —— 每个页面各自发挥：

- `uni.scss` 定义了 9 个颜色变量，但页面 `<style scoped>` 里另有一套私货。`components/PlanCard.vue` 一个文件就用了 6 种棕色（`#fff8ee` `#f0dcc0` `#e8d5b5` `#7a4a10` `#a08050` `#b06a2a`），`StepTimeline.vue` 的标题色是 `#8a5a2a` —— 这 7 个值在 token 表里**一个都没有**。
- 更机械的一层原因：这些文件写的是 `<style scoped>` 而不是 `<style lang="scss" scoped>`，所以它们**根本引用不到** `uni.scss` 里的变量。硬编码不是偷懒，是当时唯一能写出来的形式。
- 13 处导航调用里有 11 处是 `uni.redirectTo`，只有 2 处 `navigateTo`。`redirectTo` 销毁当前页，返回键因此失效。
- `pages.json` 里**没有 `tabBar` 字段**，底栏是 `components/LyjTabBar.vue` 手画的，点击走 `redirectTo`（`LyjTabBar.vue:45`）—— 于是"切 tab"这个动作把页面栈清空一次。

所以本文件先把 token、信息架构、导航模型、组件契约四件事定死，再谈改页面。

## 1. 不动的东西

本次是**结构修复 + 设计系统统一**，不是视觉重做。以下明确保留：

| 保留项 | 值 | 理由 |
|---|---|---|
| 品牌主色 | `#FF6B35` 暖橙 | 已是全局识别色，醒目且不冷（re-skin 后由 `#e8541e` 调整，现值见 `uni.scss:16`） |
| 页面底色 | `#FDFBF7` 米白暖底 | 老人端长时间阅读不刺眼（re-skin 后由 `#faf6f0` 调整，现值见 `uni.scss:21`） |
| 页面数量 | **14 页**（登录 2 + 老人端 6 + 子女端 6） | 大改后又陆续新增（老人端 健康/路线图、子女端 家人/通知），已超出初稿的 9 页 |
| 整体观感 | 卡片 + 圆角 + 暖色 | 不推翻 |

## 2. Token

全部落在 `src/uni.scss`；页面只准引用变量。**新增页面样式必须写 `<style lang="scss" scoped>`**，否则引用不到。

> **本节的 token 表是 `src/uni.scss` 的现状快照。** re-skin 时 `uni.scss` 重新取过一批值（主色、底色、子女端冷色系、圆角阴影等），下面各表已按现值对齐；今后若两者再有出入，**以 `src/uni.scss` 为准**。

uni-app 会把 `src/uni.scss` 自动注入每个 SFC 的 scss 块（官方约定，无需 import）。但本项目仍在每个样式块顶部显式写一行 `@import '../uni.scss';`（组件）或 `@import '../../uni.scss';`（页面）：

- 代价为零 —— `uni.scss` 只有变量和注释，不产生任何 CSS 输出，重复导入不会重复样式
- 收益是确定性 —— 不依赖插件版本的自动注入行为；万一注入没生效，报错是"Undefined variable"这种编译期硬错，而不是页面上一片没上色的样式

两种写法都能工作时，选不依赖未验证行为的那个。

### 2.1 字阶 —— 本次唯一一处数值订正

`uni.scss:14` 原注释写"正文不小于 34rpx ≈ 20px"。这句算错了：`rpx` 的定义是 **750rpx 恒等于视口宽度**，所以在 375pt 宽的屏上 1rpx = 0.5px，`34rpx = 17px`。按原值实现，正文永远到不了硬指标里的 20px：

| 现状 | 实测（@375pt） | 硬指标 |
|---|---|---|
| `$lyj-font-md: 34rpx`（正文） | 17px | ≥ 20px ❌ |
| `ChatBubble .text: 36rpx` | 18px | ≥ 20px ❌ |
| `PlanCard .val: 32rpx` | 16px | ≥ 20px ❌ |

订正后的字阶（`40rpx` 即 20px，是正文地板）：

```scss
$lyj-font-xl: 56rpx;   // 28px 页面大标题
$lyj-font-lg: 48rpx;   // 24px 卡片标题、重点数字
$lyj-font-md: 40rpx;   // 20px 正文地板 —— 老人要读的字一律 ≥ 此值
$lyj-font-sm: 36rpx;   // 18px 次要说明。仅限辅助信息，不得承载唯一信息
```

**`36rpx` 以下不再允许出现在老人端。** 现有的 `26rpx` / `28rpx` / `30rpx`（"再念一遍"标签、步骤备注、脚注）全部上调到 `$lyj-font-sm`。子女端是成年人界面，可以用到 `$lyj-font-sm`，但正文同样按 `$lyj-font-md`。

> 这是本次唯一主动改动的观感数值。字号变大会让卡片变高、行数变多，属于预期结果 —— 硬指标是"字号 ≥ 20px"，不是"看起来和以前一样"。

### 2.2 色板

```scss
/* 品牌 */
$lyj-primary:      #FF6B35;   // 主色（re-skin：更柔和明亮的暖橙）
$lyj-primary-dark: #E85D04;   // 按下态
$lyj-primary-soft: #FFE8D6;   // 主色浅底（进行中、选中态）

/* 底与面 */
$lyj-bg:    #FDFBF7;          // 页面底（清透的米白暖底）
$lyj-card:  #ffffff;          // 卡片面
$lyj-line:  #F2EBE1;          // 分隔线、未激活底

/* 文字 */
$lyj-text:       #2B2D42;     // 正文（柔和的深灰蓝，避免纯黑刺眼）
$lyj-text-light: #8D99AE;     // 次要文字
$lyj-text-on:    #ffffff;     // 主色底上的字

/* 语义 */
$lyj-success:    #2e8b57;     // 已完成、已服药
$lyj-success-bg: #e3f2ea;     // 已完成底（打卡后的格子）
$lyj-danger:     #d93025;     // 金额、异常
$lyj-info:       #1a73e8;     // 链接、说明
$lyj-warn:       #f0b25a;     // 待确认（挂起态专用）
$lyj-warn-bg:    #fff4e3;     // 待确认底
$lyj-warn-text:  #9a6410;     // 待确认文字

/* 状态与装饰（从页面里回收的字面量，不是新造的颜色） */
$lyj-disabled: #d5c9bd;       // 禁用底
$lyj-field:    #f5efe6;       // 输入框、未选中格子的底
$lyj-muted-bg: #f2ece2;       // 流水提示条底
```

`$lyj-warn` / `$lyj-warn-bg` 从 `ConfirmCard.vue` 现有的 `#f0b25a` / `#fff4e3` 提升为 token —— 挂起态是本项目的招牌状态，它需要一个稳定的颜色，而不是一个页面里的字面量。**PlanCard 那 6 种棕色一律作废**，交付卡片改用 `$lyj-card` + `$lyj-line` + `$lyj-primary`。

还有一批装饰值是从页面里**回收**的（不是新造）：`$lyj-disabled` `$lyj-field` `$lyj-muted-bg` `$lyj-success-bg`，以及渐变必须的第二个端点 `$lyj-primary-light` `$lyj-danger-dark` `$lyj-weather-from` `$lyj-weather-line`。收上来的理由很直接：§7 那条"页面里 6 位十六进制为 0"的判据，只有当所有值都有名字时才可能过。

#### 子女端（冷色系）

老人端暖、子女端冷，是刻意的：两端同时开着演示时，一眼能看出"这是家人这一侧"。这套值同样全部从子女端各页回收，并把同义的近似色合并：

```scss
$lyj-child-bg:       #F8F9FA;   // 页面底（re-skin：更干净的浅灰底）
$lyj-child-head:     #1D2D44;   // 深色顶栏
$lyj-child-head-sub: #9BA4B5;   // 深色顶栏上的次要字
$lyj-child-text:     #2B2D42;   // 标题与正文
$lyj-child-body:     #5a6b7d;   // 说明性正文
$lyj-child-muted:    #93a1b3;   // 次要文字、空态
$lyj-child-line:     #E9ECEF;   // 分隔线、未选中底、内嵌面板
$lyj-info-bg:        #F0F4F8;   // info 浅底（选中态、胶囊）
$lyj-info-line:      #D9E2EC;   // info 描边
$lyj-dot-idle:       #D3DCE6;   // 路线上还没走到的点
```

另有三处**不给新 token，直接复用语义色**——因为它们表达的是全项目同一个状态，各自成一套颜色只会让同一件事在两端长得不一样：

| 原字面量 | 收进 | 表达的状态 |
|---|---|---|
| `#fff7ef` / `#f5d9b8` / `#a08050` | `$lyj-warn-bg` / `$lyj-warn` / `$lyj-warn-text` | 待确认（挂起） |
| `#e8f5ee` | `$lyj-success-bg` | 已完成 / 已办理 |
| `#fff3e0` | `$lyj-primary-soft` | 进行中 |

### 2.3 间距阶

现状是 `10/12/14/16/20/24/28rpx` 随手取值。收敛成 5 档：

```scss
$lyj-space-xs: 8rpx;
$lyj-space-sm: 16rpx;
$lyj-space-md: 24rpx;    // = 原 $lyj-gap，页面左右留白与卡片间距的默认值
$lyj-space-lg: 32rpx;
$lyj-space-xl: 48rpx;
$lyj-gap: $lyj-space-md; // 保留别名，避免一次性改全部引用
```

### 2.4 圆角与阴影

```scss
$lyj-radius:      32rpx;      // 卡片（re-skin：更大圆角，更温和）
$lyj-radius-lg:   40rpx;      // 气泡
$lyj-radius-pill: 999rpx;     // 分段控件、胶囊按钮

$lyj-shadow-card:   0 12rpx 36rpx rgba(43, 45, 66, 0.04);
$lyj-shadow-raised: 0 16rpx 48rpx rgba(43, 45, 66, 0.08);
```

原 `PlanCard` 的 `rgba(180,120,40,.12)` 棕色阴影作废，统一用中性阴影。

### 2.5 命中区（适老硬指标）

```scss
$lyj-hit-min:  88rpx;         // 44px 任何可点元素的下限
$lyj-btn-main: 160rpx;        // 80px 主按钮高度
$lyj-mic:      240rpx;        // 120px 首屏麦克风直径
$lyj-tabbar-h: 120rpx;        // 60px 底栏高度
```

三条来自需求的硬指标与 token 的对应关系：正文 ≥20px → `$lyj-font-md`；主按钮 ≥80px → `$lyj-btn-main`；麦克风 120px → `$lyj-mic`。

### 2.6 导航内边距

老人端 6 页都是 `navigationStyle: custom`（各页 `path` 行在 `pages.json:12,16,20,24,28,32`，对应的 `style` 行在 `pages.json:13,17,21,25,29,33`），自定义头必须自己让开状态栏：

```scss
$lyj-nav-h: 88rpx;            // 自定义头内容区高度
// 页面根节点：padding-top: calc(var(--status-bar-height) + #{$lyj-nav-h});
```

`--status-bar-height` 是 uni-app 内置 CSS 变量，H5 端为 0，App/小程序端为实际状态栏高度。**不要写死 44rpx。**

## 3. 信息架构

14 页 = 登录 2（登录 / 注册）+ 老人端 6 + 子女端 6（其中 1 页是下钻详情）。

### 老人端（4 页进 tabBar + 2 页下钻）

| 页面 | 首屏第一件事 | 说明 |
|---|---|---|
| `elder/home` | **按住说话**（120px 麦克风） | 老人的主入口就是说话，麦克风不能藏在二级页 |
| `elder/chat` | 最后一条对话 + 输入区 | 办事过程可见：步骤条、卡片、挂起提示都在这里 |
| `elder/medications` | 今天该吃的药 + 打卡 | 高频、低门槛，独立成页 |
| `elder/profile` | 我的家人 / 隐私开关 / 退出 | 低频设置 |
| `elder/health` | 健康概览（分诊档位横幅 + 指标） | 下钻页，不在 tabBar |
| `elder/route-map` | 高德路线规划（大字导航 + 位置上报） | 下钻页，不在 tabBar |

### 子女端（5 个平级视图 + 1 个下钻）

| 页面 | 角色 |
|---|---|
| `child/dashboard` | 看板（平级视图 1）—— 就医知会、老人今日概况 |
| `child/family` | 家人（平级视图 2）—— 家庭成员管理、发起绑定 |
| `child/notification` | 通知（平级视图 3）—— 待我确认的付款 + 长辈动态通知 |
| `child/guardian` | 守护（平级视图 4）—— 行程与位置 |
| `child/privacy` | 隐私（平级视图 5）—— 分级授权开关 |
| `child/confirm-detail` | **下钻**详情 —— 从看板/通知点某条待确认进来，按同意/拒绝 |

顶部分段控件按此顺序列五项（看板 / 家人 / 通知 / 守护 / 隐私），`confirm-detail` 不在其中。

## 4. 导航模型（成文规则）

| 场景 | API | 说明 |
|---|---|---|
| 老人端切 tab | `uni.switchTab` | 仅 tabBar 页可用 |
| 下钻详情 | `uni.navigateTo` | 保留来路，返回键可用 |
| 返回 | `uni.navigateBack` | 或交给系统返回键 |
| 登录成功 / 切换角色 / 退出登录 | `uni.reLaunch` | 清空页面栈是**这里**要的语义 |
| 子女端平级根视图互切（看板 / 家人 / 通知 / 守护 / 隐私 五项） | `uni.reLaunch` | 子女端没有 `tabBar`，这五页互为平级根视图 —— `switchTab` 用不上，而"看板→守护→看板"若入栈会越按越深。分段控件的切换逻辑在 `LyjSegment.vue:56`（**该处现仍走 `redirectTo`，待改，见下**） |
| — | ~~`uni.redirectTo`~~ | **禁止**。它销毁当前页且不清栈，是两种正确语义之间的一个坑 |

> `reLaunch` 的判据不是"是不是登录"，而是**目标页是不是一个根视图**。子女端五页
> 是根视图（栈里只该有一个），`confirm-detail` 不是（它必须能返回看板）。

### 现状违规清单（13 处，按类改，不逐行讨论）

**A 类 —— 鉴权跳转，`redirectTo` → `reLaunch`**（8 处）：`login.vue:68`（登录成功进角色首页）、`chat.vue:92`、`home.vue:89`、`medications.vue:51`、`profile.vue:114`、`profile.vue:156`（退出登录）、`dashboard.vue:109`、`privacy.vue:97`。这些都是"换身份/换角色"，语义上就该清栈。

**B 类 —— tab 切换，`redirectTo` → `switchTab`**（3 处）：`LyjTabBar.vue:45`、`home.vue:126`（去吃药页）、`home.vue:130`。

**C 类 —— 已正确**（2 处）：`dashboard.vue:161`、`dashboard.vue:166` 的 `navigateTo`，保持不动。

> 上述 A/B 类跳转均已按上表转换。`LyjTabBar.vue` 本身已整体删除（全仓零引用，`find` 无结果），所以它那处随之消失；但**全仓 `grep uni.redirectTo` 仍有 2 处真调用**：`components/LyjSegment.vue:56`（分段控件平级互切，正应改成 `uni.reLaunch`）与 `pages/login/register.vue:118`（注册成功回登录页，正应改成 `uni.reLaunch`）。另有 `components/LyjBack.vue:4,27` 两处只是注释文字，不是调用。这两处未清，见 §7。

### `switchTab` 不能带参数 —— 这条约束改了首页的交互

真 `tabBar` 一上，`home.vue` 原来那个 `?quick=看病挂号` 的传参通道就死了：**`uni.switchTab` 的 url 不接受 query 参数**。于是新增 `src/store/handoff.js`，一个只活在内存里的一次性交接位（刷新即丢 —— 一句几小时前没送出去的话被自动发出去，比丢掉它糟糕得多）。

交接位顺带把一件本来含糊的事分清了：

| 来路 | 是谁的话 | 落到聊天页 |
|---|---|---|
| 首页 120px 麦克风 | **老人自己说的** | `autoSend: true` → 直接办 |
| 首页快捷入口卡片 | 卡片背后的**预设话术**（如"我想去鼓楼医院看腿疼的老毛病"，替老人编了症状） | `autoSend: false` → 只填进输入框，等老人自己按发送 |

老人点的是"看病挂号"四个字，不是那句带症状细节的话。替他把那句话说出去，是在他没说过的内容上代他表态。

### tabBar

`pages.json` 加真 `tabBar`，只列老人端 4 页：

```json
"tabBar": {
  "color": "#8a8078",
  "selectedColor": "#e8541e",
  "backgroundColor": "#ffffff",
  "borderStyle": "white",
  "fontSize": "28rpx",
  "height": "120rpx",
  "list": [
    { "pagePath": "pages/elder/home",        "text": "首页" },
    { "pagePath": "pages/elder/chat",        "text": "聊天" },
    { "pagePath": "pages/elder/medications", "text": "吃药" },
    { "pagePath": "pages/elder/profile",     "text": "我的" }
  ]
}
```

随后**删除 `components/LyjTabBar.vue`** 及其全部引用。

两点实现说明：

1. **子女端不需要 `uni.hideTabBar()`。** uni-app 的原生 tabBar 只在 `tabBar.list` 声明过的页面出现；子女端 6 页都不在名单里，天然没有底栏。这正好落实"子女端无底栏"的决定，不必写任何隐藏代码。
2. `fontSize` / `height` 在 H5 端的支持随版本浮动。如果实测不生效，用全局样式覆盖 `.uni-tabbar`（高度 `$lyj-tabbar-h`、字号 `28rpx`）。tabBar 文字是导航标签而非正文，允许低于正文地板。

### 子女端分段控件

顶部分段控件（看板 / 家人 / 通知 / 守护 / 隐私，五项）+ `navigateTo` 下钻。选择理由：子女的动线是"收到通知 → 看详情 → 按确认"，不是浏览 tab；同时避开 uni-app 原生 tabBar 无法按角色切换、H5 端条目隐藏支持不全的坑。

- 形态：`$lyj-radius-pill` 胶囊，选中态 `$lyj-primary-soft` 底 + `$lyj-primary` 字，高度 `$lyj-hit-min`
- 五个平级视图之间切换用 `uni.reLaunch`（它们互为平级根视图，栈里只该有一个）
- `confirm-detail` 用 `navigateTo` 进入，返回键回看板

**子女端保留原生导航栏**（`pages.json` 里这 6 页都不设 `navigationStyle: custom`）。两条理由：

1. `confirm-detail` 的返回按钮是白送的。子女端整套导航决策的落点就是"返回键可用"，自己画一个返回箭头没有任何好处。
2. 原生标题栏正好承担了两端的视觉分野 —— 老人端是沉浸式自定义头，子女端是系统 chrome。

由此有两条实现约束：

- 子女端页面**不要**再写 `calc(var(--status-bar-height) + …)` 的顶部内边距。状态栏已被原生栏占掉，再让一次会在标题下顶出一条空白。（这一条我自己先踩了一遍。）
- 这 6 页的 `navigationBarBackgroundColor` 设成 `#1f2d3d` / `#1D2D44`（= `$lyj-child-head`）、`navigationBarTextStyle: white`。否则全局那条 `#faf6f0` 暖米色标题栏会压在看板的深色头上，接缝很难看。`pages.json` 是 JSON，取不到 SCSS 变量，所以这里的十六进制字面量是不可避免的（§7 的判据也只查 `src/pages` 与 `src/components` 下的样式）。

## 5. 组件契约

四个组件的 props 是契约，**后端事件形状变了就改这里，不在页面里做形状适配**。

### 5.1 `ChatBubble`（不变更契约）

```
text:   String   气泡文字
isUser: Boolean  true = 老人说的（右、主色底）
agent:  String   main | travel | health | community —— 决定左侧头像
```

现状可用。两处调整：`.text` 字号 `36rpx → $lyj-font-md`，`.replay-text` `26rpx → $lyj-font-sm`。

"再念一遍"**已经实现且闭环**（`ChatBubble.vue:31-34` 调 `api/asr.js:223` 的 `speak()`，H5 `speechSynthesis`、语速 0.85 适老、不支持时返回 false 并弹提示）。计划书里"TTS 未实现"那条是错的。真实缺口只有两个，都更窄：

- `speak()` 在非 H5 端（小程序 / App）直接返回 false，需要 `uni.createInnerAudioContext` + TTS provider 才能补
- **朗读按钮原来只长在 `ChatBubble` 上**，交付卡片没有朗读入口。返工时给 `PlanCard` 补了一个（见 5.3）。

补的时候纠正了本文档先前的一个错误说法。原文写的是"健康类卡片应补一个朗读按钮，念 `announce`"—— **`announce` 到不了卡片**。R4 免责声明在后端确实同时写进工具结果的 `summary` 与 `announce`（`test_medical_safety.py` 有断言），但 SSE 的 `card` 事件推的只是 `outcome.result["card"]` 这一个子字典（`core/session.py:385`），`announce` 是结果的**兄弟字段**，不在卡片里。所以：

| 免责声明的落点 | 走哪条 SSE | 界面上谁负责显示 |
|---|---|---|
| `result["summary"]` | `tool_result.summary` | 工具流水气泡（见 6.3） |
| `result["card"]["disclaimer"]` | `card.disclaimer` | `PlanCard` 脚注（`_toCard` 收进 `notes`） |
| `result["announce"]` | **无** | 无 —— 别再指望它 |

卡片的朗读文本因此只能从**卡面本身**合成。这不算退让：卡面已经包含脚注里的那句声明，念卡面就等于念到了声明；而念一个不存在的字段只会得到空串。

### 5.2 `StepTimeline`（契约整体替换）

现状 props 与后端事件**每个字段名都不一样**：

| 现状 `steps[]`（`StepTimeline.vue:22`） | 后端 `todo` 事件 |
|---|---|
| `id` | 无（harness 的 `TodoItem` 刻意没有 id） |
| `title` | `content` |
| `status: todo \| doing \| done` | `status: pending \| in_progress \| completed` |
| `note` | 无 |

新契约，直接吃后端快照：

```
todos:    Array   [{ content: String, status: 'pending'|'in_progress'|'completed' }]
progress: Object  { total: Number, done: Number, doing: Number }
```

- 序号用**数组下标 + 1** 渲染，不依赖 id
- 状态映射：`pending` → `$lyj-line` 底；`in_progress` → `$lyj-primary-soft` 底 + ⏳；`completed` → `$lyj-success` 底 + ✓ + 删除线
- 标题处显示 `progress.done / progress.total`
- 组件**只渲染**传进来的快照，自己不推进任何状态

### 5.3 `PlanCard`（契约整体替换 —— 缺陷 #5 的前端一半）

现状 `card.body` 是扁平 `{k: v}` 字典，模板直接 `v-for` 铺开（`PlanCard.vue:9`）。两个后果：

1. 页序不存在 —— "四页"在这个组件里根本不是一个概念
2. **子 Agent 没填上的字段不会成为 key，于是静静消失** —— 而需求是显式渲染"待补"，绝不编造

新契约，吃 `plan_builder.py` 的 typed 输出：

```
title:    String   张桂芳 · 南京就医出行计划书
sections: Array    [{ heading: String,
                      rows:  [{ label: String, value: String, missing: Boolean }],
                      notes: [String] }]           页内叮嘱
notes:    Array    [String]  卡片脚注（副标题 + 免责声明 + 模拟数据披露）
complete: Boolean  是否所有字段齐全
compact:  Boolean  紧凑模式 —— 两张轻量卡片用同一组件
announce: String   朗读文本的**覆盖**位；留空则从卡面合成
```

> 标题按后端实际输出写：`plan_builder.py:303` 是 `f"{name} · {city}就医出行计划书"` —— **没有书名号，也没有"老人"二字**，名字来自种子数据的 `张桂芳`（`db/seed.py:37`）。本文档先前两处写的"《张桂芬老人 · …》"错在三个地方，已按代码订正。文档里的示例标题会被照着做成 PPT，写错就等于让演示稿和屏幕对不上。

- `missing: true` 的行渲染成 `$lyj-text-light` 的"待补"，**并且照样占一行** —— 缺页必须看得见
- `complete: false` 时头部加一条"还有 N 项待补"提示，用 `$lyj-warn`。计数由组件自己数 `rows` 里的 `missing`，不信任外部传进来的数
- 就医计划书 = 4 个 section，页序写死：①挂号信息 ②怎么去医院 ③随身清单 ④天气与穿衣
- **序号已经长在 `heading` 里了。** 后端的页标题是 `"第一页 · 挂号信息"`（`plan_builder.py:319`），组件**不得**再自己加一层"①"或下标 —— 那会渲染成"1. 第一页 · 挂号信息"。这条踩过一次
- `compact: true` 时收起 section 标题、去掉打印留白，供《本周用药与复查安排》《社区服务预约单》使用
- **页内叮嘱必须留在它那一页**（`section.notes`）。早先的写法把所有 note 抽到卡片末尾，于是"记得带医保卡"会漂到天气页下面 —— 只有卡片级的副标题、免责声明和模拟数据披露才进 `notes`

**形状适配只在 `chat.vue::_toCard` 一处**，组件里不做。后端卡片形状与组件 props 不是一套字段：

| 后端 `card` 事件 | `PlanCard` props |
|---|---|
| `pages[].no` / `pages[].title` | `sections[].heading`（序号已在标题里，不用 `no`） |
| `pages[].rows` | `sections[].rows`（同形，直接透传） |
| `pages[].notes` | `sections[].notes` |
| `subtitle` + `disclaimer` + `footnote` | 依次合并进 `notes` |
| `type` | `compact = type !== 'trip_plan'` |
| `printable` / `generated_on` / `body` / `missing` | 暂不渲染（`missing` 由组件自己数） |

`footnote` 是**模拟数据披露**（`plan_builder.py:52` 的 `MOCK_NOTE`，只有就医计划书带它）。返工时发现 `_toCard` 原来没取这个字段，于是"（竞赛原型：号源、路线、天气数据来自模拟接口，正式落地对接官方开放 API）"这句话印不到那张要打印出来的纸上。披露模拟数据是本项目的合规要求 —— 后端写了、前端丢了，等于没披露。已补。

**朗读按钮**：`speech` 计算属性把标题 → 各页标题 → `label：value` → 页内叮嘱 → 脚注按顺序拼成一段，用 `。` 连接；待补的行照念"待补"（听的人也有权知道哪一项还没定下来）。`announce` prop 留作覆盖位，但后端不会填它 —— 原因见 5.1。

### 5.4 `ConfirmCard`（契约修正 —— 现在念错了台词）

现状 props 是 `summary` / `amount` / `approved`，模板把 `summary` 当正文渲染（`ConfirmCard.vue:8`）。**这拿错了字段。** 后端 `suspended` 事件同时给两句话（形状由 `test_confirmation.py::test_the_elder_is_told_that_the_family_was_asked` 钉住）：

| 字段 | 写给谁 | 现状 |
|---|---|---|
| `message` | **老人** —— 已过黑话检查（含"确认""帮您办好"，不含"拦截/高危/失败/错误/权限"） | **没用上** |
| `summary` | 子女 —— 含车次金额等事实（如 "G102"） | 被当成老人正文显示了 |
| `expires_at` | 双方 —— 30 分钟窗口 | 没用上 |

新契约：

```
message:    String   老人看的那句话 —— 正文位
summary:    String   事实摘要 —— 次要位，$lyj-font-sm
amount:     Number   金额，$lyj-danger 高亮
expiresAt:  String   到期时间 → 渲染成"X 分钟内有效"
status:     String   pending | executed | rejected | failed —— 后端同一套词
```

配色沿用 `$lyj-warn` / `$lyj-warn-bg`。挂起对老人是**一次进展**，不是一个错误 ——
文案与配色都不许读成报错。

`status` 原来是一个 `approved: Boolean`，而且**从来没有人传过它**（`chat.vue` 只传
四个字段），所以这张卡在老人屏幕上永远停在"等他点同意"。真实缺口有两层：

1. `chat.vue` 没有 `confirmation_resolved` 这个 case —— 后端发了、前端丢了
2. 一个布尔量装不下三种结局。`ok=False` 是**两件不同的事**：家人不同意
   （`rejected`），和家人同意了但重放没成功（`failed`）。合成一句"没成功"，
   老人会以为是家人拒绝了他 —— 那是替家人表了个他没表过的态

所以后端 `confirmation_resolved` 的载荷补了 `status`（`executed` / `rejected` /
`failed`，就是 `confirmation_tasks.status` 那套词，不新造第四套），四态各有自己的
标题、脚注和底色：黄=还在等，绿=妥了，灰=家人说先不办，红边=同意了但没办成
（**只有这一档允许读成异常**）。认不出的 status 按 `pending` 处理 —— 宁可让老人
多等，不可替家人宣布结果。

## 6. 数据 → 界面契约

6.1–6.4 是老人端的 SSE 契约，`chat.vue` 的 `_handle` 是唯一的事件入口。6.5 是子女端的 REST 契约。这些必须成文，因为它们都有后端测试或后端代码钉着，而写错的方向都是**同一种**：界面显示得比真相更"好看"。

### 6.1 `agent_msg` **覆盖**流式预览，不是追加

后端的医疗安全改写（R1/R2）挂在 `agent/request` 瀑布的最外层，而流式 `delta` 是 provider 内部逐片推的，**比改写更早到前端**。所以：

- `delta` 片段是**打字预览**，`persist=False`，不进事件日志、不进模型历史、不进审计
- `agent_msg` / `final` 才是**定稿**，是改写后的那一份

`test_medical_safety.py::test_the_streaming_preview_is_not_the_authoritative_text` 就是这条契约的门禁：它断言预览确实等于原话、定稿确实不等于预览。**前端必须用 `agent_msg` 覆盖气泡，任何情况下都不能保留预览。**

`chat.vue:164-173` 现在的写法方向是对的（`bubble.text = d.text`，不是 `+=`），但有一处必须改：

```js
// 现状 —— d.text 为空时保留原话预览，这正是不允许的那一支
bubble.text = d.text || bubble.text
// 应为 —— 定稿说什么就是什么，哪怕是空的
bubble.text = d.text ?? ''
```

改写只会让文本变短、不会变空，所以这是个窄口子；但"保留未审的草稿"这条分支本身不该存在。

### 6.2 步骤条绑真快照，删掉启发式

现状（`chat.vue:174-191`）：任何 `tool_call` 把第一个 `todo` 状态的步骤标成 `doing`，任何 `tool_result` 把第一个 `doing` 标成 `done`。这与真实任务零绑定 —— 工具数和步骤数不一样时立刻错位，刷新即丢。

改为：只监听 `todo` 事件，拿 `{todos, progress}` 整体覆盖组件状态（后端本身就是整列表覆盖写、last-write-wins）。`tool_call` / `tool_result` 仍可显示"正在查号源"这类流水提示，但**不得再触碰步骤状态**。

同时 `case 'plan'`（`chat.vue:151`）读的 `d.steps` 已不存在于新内核，一并删除。

### 6.3 `tool_result.summary` **覆盖** `tool_call.summary`

一次工具调用在界面上只该有一个气泡，而这个气泡的文字必须来自**结果**，不是调用。

理由是硬的：R4 的免责声明是 `HealthDisclaimerGuard` 在 `tools/post-execute` 上注进**结果** `summary` 的（`safety/risk_rules.py:153` 那一句 `result[key] = f"{text}{note}"`）。调用摘要是工具自己在挂起前写的一句"正在查号源"，那时声明还不存在。**只渲染 `tool_call.summary`，那句"仅供参考，请遵医嘱"就永远到不了老人眼前** —— R4 在后端强制注入、在前端被丢掉，等于没有。

所以：

- `tool_call` 建气泡，用 `d.call_id` 作键（不是数组下标 —— 批处理是并发的，结果回来的顺序和调用顺序不一样）
- `tool_result` 按 `call_id` 找回同一个气泡，用 `d.summary` **覆盖**它，并记下 `denied`
- 找不到对应气泡就什么都不做，**不要另起一个** —— 那会让老人看到两条描述同一件事的流水

这和 6.1 是同一条原则的两个面：`agent_msg` 覆盖 `delta`、`tool_result` 覆盖 `tool_call`，因为两处的安全改写都发生在"后一份"上。

### 6.4 事件 → 界面对照表

| 事件 | 界面动作 |
|---|---|
| `session` | 记 `sessionId` |
| `todo` | 覆盖 `StepTimeline` 的 `todos` / `progress` |
| `agent_status` | 一行灰色流水提示 |
| `delta` | 追加进当前气泡（预览） |
| `agent_msg` | **覆盖**当前气泡（定稿），另起下一段 |
| `tool_call` | 按 `call_id` 建一个流水气泡，不动步骤条 |
| `tool_result` | 按 `call_id` **覆盖**那个气泡的摘要（见 6.3），不动步骤条 |
| `card` | 过 `_toCard` 转形状后追加 `PlanCard` |
| `suspended` | 追加 `ConfirmCard`（用 `message` 作正文，记下 `confirmation_id`） |
| `confirmation_resolved` | 按 `confirmation_id` 找回那张卡，改 `status`（见 6.6） |
| `guardian_alert` | 一行提示 |
| `final` | 定稿兜底：仅当一句话都没出来时才补 |

### 6.5 子女端：分级数据的显示契约

子女端不吃 SSE，走 REST 轮询。它的契约核心只有一句：**降级后的数据要显示成"更粗的事实"，不能显示成"完整的事实"，也不能显示成"加载失败"。**

后端 `safety/privacy.py` 的降级方式是**数据变形**而不是报错 —— 字段还在，值被换成 `MASKED`、精度被削粗，另附一个 `precision` 标记。前端要是照原样铺开，就会得到一堆读不通的行；要是当成错误处理，子女会去催老人"把权限全开"，那正好把这套分级机制废掉。四条具体规则：

**① `privacy` 字段缺席 ⇒ 按"全关"处理，不是按默认值。**

`/api/child/{id}/dashboard` 在没有绑定关系时走提前返回（`api/routes_child.py:41`），响应里**连 `privacy` 和 `elder` 都没有**。所以前端的兜底常量必须是

```js
const DENIED = { location_level: 'off', health_level: 'off', bound: false }
```

而不是 `PrivacyGrant` 的数据默认值（`realtime` / `summary`）。这条踩过：旧 `privacy.vue` 写的是 `if (d.privacy) this.privacy = d.privacy`，于是未绑定的家人会看到界面宣称"您可以看到老人的实时位置"—— 恰好是后端 `denied()` 拒绝的那一档。**界面不许宣称一份它拿不到的权限。** 请求失败时同样退到 `DENIED`。

**② `medications[].precision === 'summary'` ⇒ 药名位换句人话。**

summary 档下药名被换成 `MASKED`（"老人未开放此项"）。原样摆在药名位上会读成一条奇怪的药，改成"用药情况（药名未开放）"并配 `$lyj-child-muted` + 斜体 —— 看得见，但不假装是药名。`taken_today` / `times` 仍是真的，"今天吃了几次"这条最要紧的事实不受影响。

计数是**按计划分别算**的：`dashboard.vue:161` 渲染的是 `今日 {takenCount(m)}/{times.length} 次`，分母是**这一条计划自己的时点数**，不是全天总数。种子数据里有两条计划（硫酸氨基葡萄糖胶囊 08:00/20:00 两次、钙片 09:00 一次），所以看板上是"今日 x/2 次"和"今日 x/1 次"两行，**不会**出现一个"2/3"。写文案和写答辩稿时别把两条计划的分母加起来 —— 那个数字界面上根本不存在。

**③ `alerts[].precision === 'off'` ⇒ 地点没有，告警照出。**

位置关闭时 `filter_alert` 把地点换成 MASKED 并改写 `note`，但**告警本身仍然下发**。这是分级设计里最该守住的一条：隐私档位管的是"看得多细"，不是"要不要通知"。界面上告警列表照常显示，地点位显示 MASKED 的那句话。

**④ 子女端调 `/api/trips/{id}` 必须带 `child_id`。**

**可见范围由 token 里的身份决定，不看 `child_id`**（`api/routes_guardian.py:435` 的 `trip_detail`）：本人全量（`precision: "owner"`）、子女按隐私档裁剪、其余 403。`child_id` 现在只是"我是谁"的冗余提示，且必须与 token 一致（不一致直接 403）。这条也踩过：**改之前**"不带 `child_id` 就 return 全量"，闸门等于调用方自己开的 —— 旧 `guardian.vue` 不带，于是子女端拿到了完整坐标，R6 在后端做对了却被前端一个缺参绕过去。**子女端仍一律带 `child_id`**（冗余但无害），并按返回的 `precision` 渲染说明：

| `precision` | 界面 |
|---|---|
| `realtime` | 地图 + 时间线全量 |
| `city` | 地图 + 时间线照出，顶部加一条"地点是粗化过的，没有门牌号和坐标" |
| `off` | 地图与时间线整块隐藏，只留行程本身 + 一条"位置未开放"的说明 |

粗化后的地点是原名的前缀（`privacy.coarse_place`），所以拿 checkpoint 去匹配演示途经点时**两个方向都要试**（`a.includes(b) || b.includes(a)`）。

顺带一条不属于隐私但同源的规则：**看板不要为已有的数据再发一次请求。** `dashboard` 响应里的 `pending_confirmations` 就是 `/confirmations?status=pending` 的同一个查询（`routes_child.py:132`），5 秒一轮的轮询里那是白发一半的请求。同理 `confirm-detail` 只需一次 `/confirmations`（不带 `status` 就是全部状态，`routes_confirm.py:37`）。轮询里的震动只在待确认数**增加**时触发 —— 每 5 秒震一次不是提醒，是骚扰。

### 6.6 结果怎么回到老人屏幕上：一段刻意的轮询

`confirmation_resolved` 有一个别的事件都没有的性质：**它发生在老人这一轮之外。**
挂起发生在轮次之内，但家人是几分钟后在自己手机上点的 —— 那时老人这条 SSE 流早就
收了 `final` 关掉了。后端确实广播了一次（`confirmation.py:413` 的 `push_sync`），但那一刻没有人在听。

所以老人端多了一小段轮询（`chat.vue::_watchConfirmations`）。三条约束：

- **只认两种行**：`confirmation_resolved`（改卡）和 `agent_msg`（家人点完那句播报）。
  整条会话的历史已经在屏幕上了，把别的行再应用一遍会让每个气泡说两遍
- **先取基线 seq 且不渲染**，且基线必须在挂起卡刚出现时就取（家人还没来得及点），
  这样后面的结果一行都漏不掉
- **有活流时停表**：`_run` 开头 `_stopWatch()`、结尾重开。两条链路同时往屏幕上推
  `agent_msg` 就是每句话说两遍；轮次结束时重取基线，这一轮落库的行也不会被再应用一次

它读的是事件日志（`GET /api/sessions/{id}/events?after_seq=N`），也就是那条"断线可
轮询恢复"的同一条路 —— 不必让后端为此多留一条长连接。离页（`onHide` / `onUnload`）
必须停表：老人切到吃药页之后后台还在每 5 秒发请求，是白耗电。

> 一个仍然敞着的口子，写在这里而不是假装它不存在：**老人端没有会话回放。**
> 页面刷新或重进 `chat` 后 `messages` 是空的，那张挂起卡连同它的 `confirmation_id`
> 一起没了，于是这段轮询也就无从接上。`api/sse.js` 里的 `fetchEvents` 本来就是为
> 回放导出的，但**至今没有任何页面调用它**。补齐它是"重进会话看得见上文"这件事，
> 比本条大，留作后续。

### 6.7 （历史）反诈判定：曾要求界面上留有第三档

> **（历史）** `check_scam` 工具已随康乐收敛删除，反诈降级为后台安全规则
> （`safety/risk_rules.py` 的 `ScamContentRule`，只对工具参数硬 DENY，不做三档判定）。
> 本节保留为当时的界面契约记录 —— 界面侧现在没有这一档要显示。

`check_scam` 的结果里 `data.verdict` 有**三个**取值，不是两个：

| `verdict` | 含义 | 界面 |
|---|---|---|
| `high_risk` | 命中语料库或高信号词 | 醒目提示 + 那一条**对得上的**具体建议 |
| `normal` | 判为正常内容 | 平静地说一句"看着没问题"，不留一个红色的疙瘩 |
| `unknown` | **判不出来** | 明说"我拿不准"，并把决定交回家人 |

`unknown` 不许被折叠。二值化（"安全 / 危险"）在这件事上两头都有代价：显示成安全，
老人把钱转出去；显示成危险，老人从此不敢接自己孩子的电话。所以这一档的播报原文是
「我拿不准这条是真是假。先别回、也别转钱，把它发给家人看一眼。」—— 它给的是**下一步
动作**，不是一个模棱两可的结论。

同一条原则在 5.4 的确认卡上出现过（`rejected` 与 `failed` 不合并），这里是它的第二次
应用：**当系统不知道时，界面要显示"不知道"，而不是挑一个看起来更负责的答案。**

判定链路本身在后端（语料库 → 高信号词 → 模型只认判定词），前端不参与判断，只负责
把三档如实显示出来。另外这个工具**不会**返回 `denied` —— 它是 `ScamContentRule` 的
唯一豁免（`risk_rules.py:_JUDGES_CONTENT`），细节见 `docs/API.md`。

## 7. 验收清单

前端返工完成的判据。分两栏：**静态**的可以靠读代码和 grep 判定，已逐条核过（**未达标的项记 `[ ]` 并写明实测值**）；**实机**的必须跑起来看，留给验收现场。

### 静态判据

- [x] `pages.json` 有真 `tabBar`（老人端 4 项），子女端 6 页不在名单里
- [x] **`LyjTabBar.vue` 已删除**，全仓无引用
- [ ] 全仓 `grep uni.redirectTo` 结果为 **2**（**未归零**）：`components/LyjSegment.vue:56`（分段控件平级互切）、`pages/login/register.vue:118`（注册后回登录）；两者都该改 `uni.reLaunch`，待改。另 `components/LyjBack.vue:4,27` 两处只是注释文字，不算调用
- [ ] `src/pages` 与 `src/components` 下 `grep -E '#[0-9a-fA-F]{6}'` 为 **505 行 / 13 文件**（**未归零**，按 `-o` 计 521 处）。重灾区：`components/AgentExecutionTree.vue`（深色风，235 行内联色）、`pages/child/guardian.vue`（100 行）、`pages/elder/route-map.vue`（Leaflet 主题色，53 行，需内联）。token 化未收口，届时重跑此 grep 并回填。原豁免仍成立：`uni.scss`（token 定义处）与 `pages.json`（JSON 取不到 SCSS 变量）
- [x] `src` 下 26 个 `.vue`（`App.vue` + `pages/` 14 + `components/` 11）的 `<style>` 全部带 `lang="scss"`；命令 `grep -rlE '<style[^>]*lang="scss"' --include=*.vue src | wc -l` = 26
- [ ] 导航模型**有违例**：`switchTab` / `navigateTo` / `reLaunch` 三类用法本身已归位，但子女端平级互切（`LyjSegment.vue:56`）与 `register.vue:118` 仍是 `redirectTo`（见上第 3 条），未全部落到 `reLaunch`
- [x] 老人端正文与命中区按 token 算达标：`$lyj-font-md` = 40rpx = **20px**、`.btn-main` = `$lyj-btn-main` = 160rpx = **80px**、首页麦克风 = 240rpx = **120px**（rpx→px 按 750rpx ≡ 屏宽、375pt 屏换算）
- [x] `StepTimeline` 只渲染传入快照，组件内没有任何推进状态的代码
- [x] `PlanCard` 的 `missing` 行占位渲染"待补"，`missingCount` 由组件自己数
- [x] 挂起卡片正文取 `message`（不是 `summary`），且 `message` 由后端黑话检查兜着
- [x] 挂起卡片带 `confirmation_id`，`confirmation_resolved` 按它就地改 `status`；`rejected` 与 `failed` 是两句不同的话（见 5.4 / 6.6）
- [x] `tool_result.summary` 覆盖 `tool_call.summary`，R4 免责声明有显示出口（见 6.3）
- [x] 子女端未绑定时兜底为 `DENIED`，不退回数据默认值；`/api/trips/{id}` 一律带 `child_id`（见 6.5）

### 实机判据

分两组，界线是**能不能交给脚本**。2026-09-02 跑过一轮门禁，所以第一组已经不是"待验证"了。

**① E2E 已覆盖（`frontend/e2e/elder-flow.mjs`，62 条断言全绿）**

- [x] 后端 `pytest tests/ -q` 全绿（本轮 **601 passed**，29 个文件；2026-09-02 首轮收尾时是 219；返工前的红线是 27，现在的红线是这一整套都得绿）
- [x] `node frontend/e2e/elder-flow.mjs` 通过 —— 已按新契约整文重写（旧脚本驱动的 `?quick=` 通道和假底栏都不在了）
- [x] 老人端原生底栏**按文字**切页（「聊天」↔「首页」）后 URL 正确
- [x] 子女端看板只出现 **1 条「就医知会」**（标题以 `【就医知会】` 开头、正文含挂号费与分诊档位），看板上 **0 个同意/拒绝按钮**；通知中心 `.confirm-card === 0` —— 就医**知会不审批**
- [x] 老人端全程 **0 张挂起卡**（`.suspend-card === 0`）；挂号卡是绿的，卡片标题里没有「待确认」口吻
- [x] 隐私页 6 个档位、选中态恰好 2 个（界面不能同时宣称两个权限档）

**② 仍要人手验（脚本覆盖不到，或需要故障注入）**

- [ ] 老人端任意页返回键行为正常（tab 页返回退出确认，详情页返回上一页）—— E2E 只验了子女端那一次 `goBack`
- [ ] 子女端顶部分段控件**五项都互切一遍**（E2E 已走「看板→通知 / 守护 / 隐私」，**家人**那一页还没人点过）
- [ ] 实测字号与命中区（浏览器 devtools 量一遍，验证 rpx 换算在目标机上成立）—— 脚本不量 px
- [ ] `StepTimeline` 在人为只发一次 `todo` 快照时，步骤状态与快照完全一致（**故障注入**，正常流程跑不到）
- [ ] 抽掉路线 report 后，计划书第 ② 页显示"待补"且头部提示"还有 N 项待补"（**故障注入**；单元侧由 `test_plan_builder.py` 盯着，界面侧没人验）
- [ ] 老人端把位置降到 `city`、健康降到 `summary` 后，子女端相关页面各自出现对应说明而**不是**空白或报错（E2E 只数档位，没改档位再回看）
- [ ] 点**拒绝**时黄卡变灰且说"先不办"，不说"失败"（E2E 现在全程 **0 张挂起卡**，三种结局一支都没被脚本走过 —— 这条目前只能靠 `test_confirmation.py` 的单测顶着）
