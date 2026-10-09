"""黑板素材层(blackboard-v1):选材状态机 + 目录投影脚本。

目录单源=前端 manifests.ts;asset_catalog.json 由 gen_catalog.py 生成,不手工编辑。
"""

from .asset_selector import AssetSelector, asset_system, catalog_brief, load_catalog

__all__ = ["AssetSelector", "asset_system", "catalog_brief", "load_catalog"]
