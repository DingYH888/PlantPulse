"""前后端 API 路径一致性自测脚本（沙箱可运行，不触发 asyncio）。

逻辑：
1. 扫描 frontend/src 下所有 .js/.vue，正则提取 service.get/post/put/delete('路径')；
2. 拼接前端 baseURL（默认 /api/v1，与 request.js 保持一致）；
3. 用后端 app.openapi() 提取全部真实路由路径；
4. 比对：每个前端调用必须命中后端路由，否则输出阻断项。

运行方式（backend 目录下）：
    PYTHONPATH=. ../.venv/Scripts/python.exe scripts/verify_api_paths.py
"""
import re
import sys
from pathlib import Path

from app.main import app

BASE_URL = "/api/v1"
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "src"

METHOD_RE = re.compile(r"service\.(get|post|put|delete|patch)\(\s*[`'\"]([^`'\"]+)[`'\"]")


def collect_frontend_calls() -> list[tuple[str, str]]:
    """收集所有前端 service 调用：返回 [(method, path)]。"""
    calls: list[tuple[str, str]] = []
    for file in sorted(FRONTEND_DIR.rglob("*")):
        if file.suffix not in (".js", ".vue") or file.name == "request.js":
            continue
        text = file.read_text(encoding="utf-8")
        for match in METHOD_RE.finditer(text):
            calls.append((match.group(1), match.group(2)))
            print(f"  [front] {file.relative_to(FRONTEND_DIR)}: {match.group(1).upper()} {match.group(2)}")
    return calls


def collect_backend_paths() -> set[str]:
    """从 openapi 提取后端真实路径（含 /api/v1 前缀）。"""
    return set(app.openapi()["paths"].keys())


def main() -> None:
    backend_paths = collect_backend_paths()
    print(f"\n后端路由总数: {len(backend_paths)}")
    for p in sorted(backend_paths):
        print(f"  [back ] {p}")

    calls = collect_frontend_calls()
    print(f"\n前端调用总数: {len(calls)}")

    errors: list[tuple[str, str]] = []
    for method, path in calls:
        full_path = f"{BASE_URL}{path}"
        # 静态图片 URL 不是 API 路由，跳过比对
        if full_path.startswith("/static"):
            continue
        if full_path not in backend_paths:
            errors.append((method, full_path))

    print("\n=== 比对结果 ===")
    if errors:
        print("❌ 阻断项：以下前端调用无法命中后端路由：")
        for method, full_path in errors:
            print(f"  {method.upper()} {full_path}")
        sys.exit(1)
    print(f"✅ 全部 {len(calls)} 个前端 API 调用均命中后端路由")
    sys.exit(0)


if __name__ == "__main__":
    main()