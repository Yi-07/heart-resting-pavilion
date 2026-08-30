"""服务配置:环境变量单源 = backend/.env.example(python-dotenv 加载)。"""

import os

from dotenv import load_dotenv

load_dotenv()

CRISIS_GATE_THRESHOLD = float(os.getenv("CRISIS_GATE_THRESHOLD", "0.7"))
"""危机闸门命中阈值:severity ≥ 阈值判危机(backend-plan §6,词典内容运行时补)"""
