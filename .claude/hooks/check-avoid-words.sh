#!/usr/bin/env bash
# 避用词闸门(PostToolUse):Edit/Write 落盘后,**只检查本次写入的内容**中是否引入 CONTEXT 避用词,
# 命中即反馈 agent 修正。只查增量不查全文件——历史台账/研究存档中的存量历史词合法,由 skill 收尾 grep 语义判定。
# 排除域:CONTEXT.md 自身(靶单记录)、docs/research/(历史引文合法)、.venv、backup。
set -euo pipefail

input=$(cat)
file=$(echo "$input" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)
file="${file//\\//}"  # Windows 反斜杠路径归一为正斜杠:排除域匹配与反馈文件名显示都依赖

[[ "$file" == *.md ]] || exit 0
case "$file" in
  *CONTEXT.md|*docs/research/*|*.venv*|*backup/*) exit 0 ;;
esac
[[ -f "$file" ]] || exit 0

# 提取本次写入内容:Edit→new_string;Write→content
content=$(echo "$input" | PYTHONUTF8=1 python -c "
import json,sys
d=json.load(sys.stdin)
t=d.get('tool_input',{})
sys.stdout.write(t.get('new_string') or t.get('content') or '')
" 2>/dev/null)
[[ -z "$content" ]] && exit 0

CONTEXT="$(cd "$(dirname "$0")/../.." && pwd)/docs/architecture/CONTEXT.md"
[[ -f "$CONTEXT" ]] || exit 0

# 提取避用列:抓"避用:"行,去破折号注释与括号注,按 / 分词
words=$(grep -oP '(?<=避用[:：]).*' "$CONTEXT" \
  | sed 's/——.*//; s/(.*)//g; s/(.*//g' \
  | tr '/' '\n' | sed 's/^[[:space:]·]*//; s/[[:space:]]*$//' \
  | grep -v '^$' | sort -u)

[[ -z "$words" ]] && exit 0

hits=""
while IFS= read -r w; do
  if echo "$content" | grep -qn -- "$w"; then
    hits="${hits}  - 避用词「${w}」被引入 ${file##*/}"$'\n'
  fi
done <<< "$words"

if [[ -n "$hits" ]]; then
  echo "CONTEXT.md 避用词被引入(改用正词,查 docs/architecture/CONTEXT.md):" >&2
  echo "$hits" >&2
  exit 2
fi
exit 0
