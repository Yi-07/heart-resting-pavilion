#!/usr/bin/env python
"""从前端 manifests.ts 投影生成后端 asset_catalog.json(单源=前端,本脚本单向生成)。

用法:backend/ 目录下 PYTHONIOENCODING=utf-8 uv run python -m app.board.gen_catalog
前端 manifests.ts 增删素材后重跑;id+tags 是 LLM 选材清单的全部所需。
"""

import json
import re
from pathlib import Path

FRONTEND_MANIFESTS = Path(__file__).resolve().parents[3] / "frontend" / "src" / "board" / "manifests.ts"
OUT = Path(__file__).resolve().parent / "asset_catalog.json"


def main() -> None:
    text = FRONTEND_MANIFESTS.read_text(encoding="utf-8")
    entries: dict[str, list[str]] = {}
    # 逐条匹配 'id': { id: 'id', tags: [...], ... }(单行结构,manifests 是代码生成友好格式)
    for m in re.finditer(r"'([\w.-]+)':\s*\{\s*id:\s*'[\w.-]+',\s*tags:\s*\[([^\]]*)\]", text):
        asset_id = m.group(1)
        tags = re.findall(r"'([^']+)'", m.group(2))
        entries[asset_id] = tags
    if not entries:
        raise SystemExit("manifests.ts 未解析出条目——格式变了,修本脚本的正则")
    OUT.write_text(
        json.dumps({"assets": entries}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"asset_catalog.json: {len(entries)} entries")


if __name__ == "__main__":
    main()
