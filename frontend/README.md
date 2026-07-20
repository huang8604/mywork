# 阶段三、四前端

Vue 3、TypeScript、Vite、Vue Router、Pinia、Axios 与 Element Plus 实现的响应式 SPA。

阶段四已提供策略配置、三种复习表题型、A4 打印与可选答案页，以及支持刷新恢复、原子批量保存和 409 冲突处理的线下回录流程。

## 本地开发

```bash
npm install
npm run dev
```

Vite 默认监听 `5173`，并将 `/api`、`/healthz` 代理到 `http://127.0.0.1:8000`。后端本地开发需配置 `TRUSTED_LOCAL_WEB=true`；生产环境仍应由可信反向代理提供用户身份。

## 验证

```bash
npm run typecheck
npm test
npm run build
npm run test:e2e
```

Playwright 覆盖 320、375、768、1024、1440 像素视口。系统过旧而无法安装新版 Chromium 时，可使用与 `@playwright/test` 同版本的官方 Playwright 容器运行测试；也可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH` 指向已安装的兼容 Chromium。

## API 契约

客户端统一使用 `/api/v1`，JSON 请求通过 envelope 读取 `data`，导出请求直接按 Blob 处理。当前后端 OpenAPI 的成功响应 schema 尚未完整描述领域数据，因此前端类型维护在 `src/types/domain.ts`，并以 API 单元测试和端到端 mock 对契约进行校验。

前端不保存、接收或显示外部 Skill Bearer Token。外部 Skill 创建的复习表与网页会话共用页面，只显示来源客户端和 Skill 名称。
