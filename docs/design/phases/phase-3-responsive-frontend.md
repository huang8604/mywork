# 单词记忆辅助系统－阶段三详细设计

> 实施状态：已完成

## 1. 阶段目标与技术栈

使用 **Vue 3 + TypeScript + Vite** 实现同一套同时适配移动端和电脑端的 SPA，完成词库管理、线下复习结果回录、历史查询和结果修改；在线卡片复习作为偶尔使用的辅助功能。

- Vue Router 4：路由与懒加载；
- Pinia：跨页面的用户偏好和轻量会话状态；
- Axios：HTTP 客户端；
- Element Plus：桌面组件基础，移动端通过响应式封装避免直接搬用宽表格；
- API 类型由阶段一 OpenAPI 生成或做 CI 契约校验。

不再保留 React 或其他 UI 库的二选一描述，避免实现分叉。

## 2. 工程结构

```text
frontend/
├── src/
│   ├── api/
│   │   ├── client.ts
│   │   ├── words.ts
│   │   ├── reviews.ts
│   │   ├── stats.ts
│   │   └── practiceSessions.ts
│   ├── components/
│   │   ├── AsyncState.vue
│   │   ├── ResultSelector.vue
│   │   ├── ResponsiveWordList.vue
│   │   └── WordCard.vue
│   ├── composables/
│   │   ├── useAsyncState.ts
│   │   └── useReviewResult.ts
│   ├── layouts/
│   ├── router/
│   ├── stores/
│   ├── styles/
│   │   ├── breakpoints.css
│   │   ├── global.css
│   │   └── print.css
│   └── views/
│       ├── DashboardView.vue
│       ├── WordsView.vue
│       ├── ReviewView.vue
│       ├── DailyGenerateView.vue
│       ├── PracticeSessionView.vue
│       ├── HistoryView.vue
│       └── NotFoundView.vue
└── tests/
```

## 3. 响应式布局

### 3.1 断点

| 宽度 | 布局 |
| --- | --- |
| `< 640px` | 手机：单列、底部导航、卡片列表、全宽表单 |
| `640–1023px` | 平板：可折叠侧栏，一至两列 |
| `>= 1024px` | 电脑：固定侧栏、主内容区、多列表格 |

- 内容以移动端优先 CSS 编写。
- 页面整体禁止横向溢出；宽表格放在具有 `overflow-x:auto` 的局部容器内。
- 触控目标至少 44×44 CSS 像素，并适配安全区域 `env(safe-area-inset-bottom)`。
- 电脑端保留鼠标悬浮能力，但任何信息不能只依赖 hover 展示。

### 3.2 页面适配

- Dashboard：手机为纵向统计卡片，电脑为网格卡片和趋势区域。
- 单词库：电脑显示数据表；手机显示单词卡片列表，筛选器进入抽屉，编辑使用全屏弹层。
- 在线复习（辅助入口）：手机全屏单卡，三态按钮固定底部；电脑端卡片居中，旁边显示进度和快捷键。
- 历史页：电脑显示筛选表格；手机按日期分组为卡片，每条可直接修改结果。
- 单词复习表页面的屏幕和打印布局由阶段四定义。
- 外部 Skill 生成的复习表与网页生成的复习表进入同一列表，显示“外部 Skill”来源、客户端名称和生成时间，不维护第二套页面。

## 4. 路由与导航

路由固定为 `/dashboard`、`/words`、`/review`、`/daily/generate`、`/daily/sessions/:id`、`/history` 和 404。

- 根路径重定向至 Dashboard。
- 电脑使用侧栏，手机使用底部导航；两者来自同一份路由元数据。
- FastAPI 部署必须支持 SPA 深链回退，但 `/api/*` 和健康端点不参与回退。
- 页面懒加载；路由切换取消已过期请求。

## 5. API 客户端与异步状态

### 5.1 Axios

- `baseURL=/api/v1`，设置合理 timeout。
- JSON endpoint 才剥离 envelope；CSV/JSON 文件下载按 `responseType=blob` 单独处理。
- 将 `400/404/409/413/422/429/5xx` 映射为可读错误，保留 `request_id`。
- 支持 AbortController，避免快速筛选、切页和重复生成造成竞态。
- 下载完成后调用 `URL.revokeObjectURL`。

### 5.2 页面状态

所有数据页面显式处理：

`idle → loading → success | empty | error`

写操作额外处理 `submitting`、`conflict` 和 `retrying`。全局 Toast 只做提示，表单字段错误、失败原因和重试操作必须留在对应组件内。

历史页和练习回录页复用 `editing → resubmitting → submitted | conflict | error` 状态机，避免只有在线卡片具备可靠的修改流程。

## 6. 单词库管理

### 6.1 筛选与列表

- 支持英文/中文关键词、标签、自定义词、日期和排序。
- 筛选条件同步到 URL query，刷新或分享链接后可恢复。
- 手机和电脑复用同一数据源、分页逻辑和编辑组件。

### 6.2 新增与编辑

- 英文、中文释义必填；英文允许字母、空格、撇号和连字符，最终规范化由后端决定。
- 保存失败时保留用户输入；`409` 重复词展示合并或取消选择。
- 删除前二次确认，说明这是软删除且历史保留。

### 6.3 导入与导出

- 上传组件接受 CSV/JSON，同时校验扩展名、MIME 和文件大小。
- 成功时展示 created/updated/skipped/rejected/total 数量；失败时展示错误 envelope 中可定位的行号与字段，且明确本次零写入。
- 导出按钮明确格式和当前过滤范围。

## 7. 复习结果录入、修改与在线辅助复习

### 7.1 交互

主要入口是阶段四的打印后回录页面；在线卡片仅作为用户偶尔不打印时的辅助入口。在线卡片正面展示英文和音标，揭示答案后展示中文和例句。两种入口的结果选择器都提供：

- 认识（`known`）；
- 不认识（`unknown`）；
- 跳过（`skipped`）。

每次实际复习提交新的结果流水；用户可以在提交后直接改选以纠正本次录入，也可在历史页修改。修改本次流水不得覆盖以前的复习记录。当前结果使用文字、图标和选中状态共同表达，不能只靠颜色。

### 7.2 状态机

```text
unseen
  → revealed
  → submitting
  → submitted(known | unknown | skipped)
  → editing
  → resubmitting
  → submitted
```

- 提交期间禁用重复点击，并使用客户端 UUID 作为 `client_event_id`。
- 只有首次提交成功后才自动进入下一词；失败时停留原卡并显示重试。
- 修改结果成功后原地更新；失败时保留上一个已确认结果。
- 提供“撤销/修改上一题”入口，不把误触永久写入统计。
- 网络离线时首版不承诺后台同步，必须明确提示未保存；不得伪装为成功。

### 7.3 键盘和可访问性

- 桌面快捷键示例：`1` 认识、`2` 不认识、`3` 跳过；输入框聚焦时禁用。
- 揭示答案和结果提交后移动焦点至合理位置。
- 状态变化和错误通过 `aria-live` 宣告。
- 所有图标按钮提供可读标签，焦点环不可隐藏。

## 8. 前端安全

- 单词、释义和例句默认以文本插值渲染，禁止直接使用不可信 `v-html`。
- 前端校验只改善体验，权限、范围和文件安全仍由后端执行。
- 若未来使用 Cookie 鉴权，必须增加 CSRF 防护；当前单用户部署的访问控制由 NAS 反向代理负责并在界面显示登录失效状态。
- 外部 Skill 的 Bearer Token 只配置在 Skill 运行环境中，不能写入前端 bundle、localStorage、页面 URL 或浏览器日志。

## 9. 测试

- 组件测试：ResultSelector 三态、提交失败、修改、冲突、移动/桌面两种呈现。
- API mock 测试：JSON envelope、Blob、422、409、超时和取消请求。
- Playwright：CRUD、CSV/JSON 导入、在线复习三态、历史修改、直接访问深链和 404。
- Playwright：打开由外部 Skill 生成的 session，完成打印预览和结果回录，并核对来源标签。
- 响应式视口：320、375、768、1024、1440 像素。
- 可访问性：键盘遍历、焦点、标签、对比度和触控尺寸。

## 10. Definition of Done

- 手机、平板和电脑完成相同核心流程，不存在只在某一终端可用的功能。
- 复习结果可提交为三态，并可在当前卡片和历史页直接修改。
- 网络失败、重复点击、冲突和空数据都有明确可恢复状态。
- 路由刷新、未知路由、API 404 和 SPA 回退行为正确。
- CRUD、导入导出、在线复习和历史修改通过端到端测试。
- 外部 Skill 生成的复习表可在手机和电脑直接打开；网页不暴露或回显 Skill Token。
