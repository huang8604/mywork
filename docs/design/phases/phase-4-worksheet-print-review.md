# 单词记忆辅助系统－阶段四详细设计：单词复习表、打印与回录

> 实施状态：已完成

## 1. 阶段目标

实现“配置策略 → 生成持久化单词复习表 → 打印 → 线下复习 → 回录本次三态结果 → 查看历史”的主闭环，同时保证手机和电脑均可操作。在线卡片复习只是偶尔使用的辅助方式。

## 2. 策略配置

前端模型严格对应阶段一 OpenAPI：

```ts
interface StrategyRequest {
  new_words_limit: number
  error_words_limit: number
  due_words_limit: number
  custom_words_limit: number
  total_words?: number
  fallback_unreviewed_days: number
  seed?: number
}
```

- 默认绝对配额为新词 10、错词 5、到期词 5、自定义词 5。
- 每个分类值允许 0–100；可选开启“按总单词数生成”，开启后分类值作为比例权重，由后端换算整数配额。
- 预计总量不得超过后端配置上限；总数模式下权重不能全部为 0。
- 某类词不足时按 `错词 → 新词 → 到期词 → 自定义词` 顺延缺额，总数尽量补满。
- 手机使用分组数字输入和预设按钮；电脑可组合 Slider 与 InputNumber。
- 生成前展示预计总量；无候选时显示原因，不渲染空表。
- 生成按钮在请求期间禁用；重复点击不得创建多个会话。
- 服务端返回 `session_id`、seed、requested/actual counts、来源和入选原因，前端不自行重新抽词。
- 外部 Skill 调用同一生成接口；返回的 `web_url` 和 `print_url` 可直接打开当前 session，网页显示 API 客户端来源但不显示 Token。

页面状态为：

`editing → validating → generating → ready | empty | error`

## 3. 单词复习表会话页面

路由为 `/daily/sessions/:id`，刷新或从历史页进入时从后端重新加载快照。

### 3.1 屏幕视图

- 顶部显示会话 ID、生成时间、策略摘要、请求/实际数量和完成进度。
- 可查看每个词的来源分类及入选原因。
- 支持单词复习表、答案、结果回录三种视图。
- 电脑端使用表格；手机端使用逐题卡片，避免把宽打印表格压缩到窄屏。
- 用户可将任一题设为“认识 / 不认识 / 跳过”，保存后仍可直接修改。

### 3.2 题目列

打印单词复习表默认包含：

1. 序号；
2. 英文单词或英文留白；
3. 音标；
4. 中文释义或中文留白；
5. 完整例句；
6. 纸面作答标记区：认识、不认识、跳过。

用户可选择“看中文写英文”“看英文写中文”版式。答案页使用相同题号；打印成品不显示内部会话 ID，以“练习/答案”、日期、题型和页码明确标注。

### 3.3 安全的例句挖空

- 单词和例句始终按纯文本渲染，不使用不可信 `v-html`。
- 将目标单词用于正则前必须转义元字符，并尽量按完整词边界匹配。
- 未找到目标词时保留原例句并显示非阻断提示。
- 对撇号、连字符、复合词、大小写、空例句和 Unicode 边界编写测试。

示例工具：

```ts
const escapeRegExp = (value: string) =>
  value.replace(/[.*+?^$`{}()|[\]\\]/g, '\\$&')

const blankWord = (sentence: string, word: string) => {
  const escaped = escapeRegExp(word)
  return sentence.replace(new RegExp(`\\b${escaped}\\b`, 'giu'), '_____')
}
```

## 4. 打印设计

### 4.1 首选方案

首选浏览器原生 `window.print()`。Chrome/Edge 可在打印面板中直接保存 PDF，首版不强制引入 `html2pdf.js`。若后续增加一键 PDF，必须单独完成中文字体、清晰度和多页回归测试。

### 4.2 全局打印样式

打印规则放在全局 `src/styles/print.css`，避免 Vue scoped style 导致 `body`、`@page` 或布局选择器失效。

```css
@media print {
  @page {
    size: A4 portrait;
    margin: 12mm 10mm;
  }

  .app-sidebar,
  .app-mobile-nav,
  .strategy-panel,
  .no-print {
    display: none !important;
  }

  .print-container {
    width: 100%;
    margin: 0;
    padding: 0;
    color: #000;
    background: #fff;
  }

  table {
    width: 100%;
    border-collapse: collapse;
  }

  thead {
    display: table-header-group;
  }

  tr {
    break-inside: avoid;
    page-break-inside: avoid;
  }

  th,
  td {
    border: 1px solid #333;
    padding: 6pt 5pt;
    font-size: 11pt;
    overflow-wrap: anywhere;
  }
}
```

- 每页页眉包含练习/答案标识、日期、题型和页码信息，不显示内部会话 ID。
- “复习表”和“答案”是两个独立打印目标：打印/保存 PDF 只输出当前标签，移除“附答案页”选项。
- 超长单词、长释义、长例句不得使表格超出可打印宽度。
- 打印页面不得出现底部导航、按钮、Toast 或滚动条。
- “打印完成”由用户在返回页面后确认，再调用幂等的 `POST /api/v1/practice-sessions/{id}/printed`；浏览器无法可靠判断纸张是否真正输出，界面不得声称自动检测成功。

## 5. 线下复习后的结果回录

### 5.1 回录流程

1. 用户在“复习表”标签打印练习，需要答案时切换“答案”标签单独打印，并在线下完成复习。
2. 每次线下复习后，在手机或电脑打开对应复习表，创建一个新的复习轮次并开始结果录入。
3. 逐题点击“认识 / 不认识 / 跳过”；可批量保存。
4. 本次保存会为每个已录入单词新增一条复习流水，不覆盖该单词以前的复习结果。
5. 如发现本次录入错误，可直接改选状态；这属于修改本次流水，不新增重复流水。
6. 页面显示本次录入时间和最后修改时间；所有题目有结果后，本轮回录完成。
7. 同一张复习表以后再次用于线下复习时，应开始新一轮结果录入并生成新的流水。

### 5.2 保存与冲突

- 每次实际复习先携带 `Idempotency-Key` 调用 `POST /api/v1/practice-sessions/{id}/review-rounds` 创建新轮次；重试返回同一 round，同一张表以后再次复习时必须使用新的键创建新轮次。
- 本轮首次结果创建新的 `client_event_id`，通过 `PUT /api/v1/practice-review-rounds/{round_id}/items/{item_id}/result` 保存；纠正本轮结果时复用原 `client_event_id` 并携带 `expected_version`。
- 外部结果录入 Skill 可调用 `PUT /api/v1/practice-review-rounds/{round_id}/results` 原子批量保存；网页批量保存与 Skill 复用相同 service 和事务规则。
- 本轮首次回录新增流水；同一轮内修改已有结果时更新该轮对应 `review_log`，不新增重复流水，并在同一事务内重算统计。
- 保存期间禁用该题重复点击；失败时保留未保存选择并提供重试。
- `409` 表示其他页面已修改，显示服务端最新状态，由用户选择采用最新值或再次覆盖。
- “跳过”算已处理题目，但不计入正确率。

### 5.3 移动端回录

- 默认逐题卡片，三态按钮固定在卡片底部且触控区域不少于 44×44 像素。
- 提供上一题/下一题和“只看未录入”筛选。
- 不要求用户在手机上操作横向大表格。

## 6. 测试

- 生成：零配额、总量上限、无候选、重复生成、seed 可复现、分类重叠补位。
- 回录：三态新增、修改、重复提交、部分失败、409 冲突、刷新恢复。
- Skill：生成请求重试不重复建表，批量回录任一项非法则全部回滚，权限不足返回 403。
- 安全：正则元字符、恶意 HTML、极长文本和特殊 Unicode。
- 打印：Chrome/Edge，A4 单页与多页，重复表头、无截行、当前标签独立输出且答案页题号一致。
- 视口：手机 320/375、平板 768、电脑 1024/1440。

## 7. Definition of Done

- 一次生成会创建可重新打开的持久化会话，数量和来源可解释、可复现。
- 手机、平板和电脑都能预览、回录并直接修改三态结果。
- A4 多页打印无导航、无横向截断、重复表头，单词复习表与答案页一致。
- 打印回录会更新复习流水和统计，修改后可重建一致结果。
- 空数据、网络失败、冲突和恶意文本均有自动化验收。
- 外部 Skill 生成的复习表可正常打印和回录；Skill 批量结果与网页逐项结果产生相同流水和统计。
