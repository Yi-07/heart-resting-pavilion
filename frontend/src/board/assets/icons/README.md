# board 素材 · vendor 记录

- 来源:zakeri-dev/koboyo-icon(https://zakeri-dev.github.io/koboyo-icon/),单色手绘 SVG。
- License:个人商用免费免署名;允许改色/改形/嵌入产品;禁止转卖图标库/做竞品/做用户可提取图标的功能(原文核验存 docs/task-kanbans/yxw/blackboard-v1 工作目录 `.firecrawl/koboyo-license.md`)。
- 本目录为 blackboard-v1 原型验收通过的 35 个(工作目录 asset-candidates.md 候选集的子集);后续扩容按同流程人审后补。
- 技术形态:根 `<svg fill="currentColor">` 单色 path,无固定宽高/无 defs/无 id——内联时容器 `g` 需补 `fill="currentColor"`(根标签属性提取内层后会丢,丢则回落黑色);着色由容器 CSS `color` 继承。
- 引入方式:`?raw` 静态导入(manifests.ts 单源登记),不用 import.meta.glob(避免全量枚举进 chunk)。
