# 复习表体验增强(批次 3)

## 范围(4 项)

1. 背诵表 md/pdf:单词与音标拆成两列。
2. 在线复习:隐藏已完成的复习表(completed_at 非空)。
3. 结果回录开启新一轮:状态从「已完成」回到「进行中」(清 completed_at)。
4. 参考 `test2.html` 重做复习表 + 导出,引入**莫兰迪 7 色 weekday 主题**(周一到周日)。

## 已定决策

- 配色:**莫兰迪低饱和**七色(primary/deep 对 + 统一金色 accent #c2a370):
  周一红 #a85a5a/#874a4a · 周二橙 #a9744f/#855c3d · 周三橄榄 #9c8a4e/#7c6d3b ·
  周四绿 #6f8a66/#556d4f · 周五青 #5e8787/#476a6a · 周六雾蓝 #5e7691/#475d74 · 周日藕紫 #856b94/#685276。
- 应用范围:**全套**(屏幕复习表 + 浏览器打印 + 背诵表 PDF + md)。
- weekday 锚点:复习表 `generated_at`(稳定,改天打印不变色)。

## 变更点

### A. worksheetTheme(前端 util,单测)
- `src/utils/worksheetTheme.ts`:`worksheetTheme(dateStr)` → `{primary, deep, accent, weekdayName}`,按 `getDay()`(0=周日..6=周六)取莫兰迪色。

### B. PracticeWorksheet.vue 重做(test2.html 风格 + weekday 主题)
- 由 `session.generated_at` 取主题,在根节点设 `--ws-primary/--ws-deep/--ws-accent`。
- hero:渐变 `--ws-deep→--ws-primary` + 金色 accent 描边;左 eyebrow+标题+副标题,右 date-card(`generated_at · 周五`)。保留练习模式的姓名/得分。
- 表格:圆角 2.2mm,th 用 `--ws-primary` 白字,斑马纹;列序号/单词/音标/中文/例句。
- `print.css`:header 渐变 + accent 描边、th 用主题色,均走 CSS 变量。

### C. 背诵表 md/pdf(后端 recitation.py,满足 #1 + #4)
- Python 端同名莫兰迪 map,按 `session.generated_at` 取色。
- `build_recitation_md(session, items)`:4 列(单词|音标|中文|例句)+ 头部(`# 📚 单词背诵表` + `> 日期 … 周五`)+ 页脚提示。
- `render_recitation_pdf(session, items)`:由**专用 HTML 模板**(镜像 test2.html:hero + 主题表格,inline CSS 用 weekday 色)经 weasyprint 出 PDF,替掉 markdown→pdf 旧路径。
- 路由 `/practice-sessions/{id}/recitation` 把 `session` 传入两个 builder。

### D. #2 在线复习隐藏已完成
- `ReviewView.prepare()`:`details.filter(s => (s.items?.length||0)>0 && !s.completed_at)`。

### E. #3 新一轮清 completed_at
- 后端 `create_round`(practice.py):建 round 后,若 `session.completed_at` 非空则置 None + version+1。
- 前端 `startRound`:`createRound` 后 `getSession` 刷新 session,让头部/摘要即时回到「进行中」。

## 测试
- 后端:`test_recitation.py` 更新(md 4 列 + 日期行;PDF 非空合法);新增 create_round 清 completed_at 用例。
- 前端:`worksheetTheme` 按 weekday 返回正确色;PracticeWorksheet 带主题挂载。

## 不需要
- OpenAPI 重生成:路由签名未变。
