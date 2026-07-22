# 设计文档索引

本目录保存单词记忆辅助系统的长期设计基线。阶段文档描述冻结的产品、数据、API、前端和部署决策；`docs/superpowers/plans/` 只保存实施计划与执行记录。

## 总体设计

- [系统总纲](./overview.md)
- [词库增强、自定义复习与添加单词 Skill 补充设计](./supplements/dictionary-custom-review.md)

## 阶段设计

1. [阶段一：架构、数据模型与 API 契约](./phases/phase-1-architecture-api.md)
2. [阶段二：后端与策略引擎](./phases/phase-2-backend-strategy.md)
3. [阶段三：响应式前端与复习交互](./phases/phase-3-responsive-frontend.md)
4. [阶段四：单词复习表、打印与回录](./phases/phase-4-worksheet-print-review.md)
5. [阶段五：容器、CI 与 NAS 人工发布](./phases/phase-5-container-ci-nas.md)
6. [阶段六：增强批次设计规格](./phases/phase-6-enhancements.md)

## 相关资料

- [阶段六实现计划与验收记录](../superpowers/plans/2026-07-22-phase6-enhancements.md)
- [NAS 部署与运维手册](../../deploy/README.md)
- [OpenAPI 契约](../../backend/contracts/openapi.yaml)
