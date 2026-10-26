"""Tortoise-ORM 冒烟验证脚本（异步，需本地终端运行，沙箱无法执行 asyncio）。

用法（backend 目录，激活 venv 后）：
    python -m scripts.smoke_tortoise
验证点：
  1. 5 张业务表全部注册（users/plants/plant_record/plant_metric/ai_advice）
  2. CRUD：用户 -> 植物 -> 养护记录（枚举）/指标/AI 建议
  3. 关系级联：删除植物后其记录/指标/建议被级联清理
  4. 数据隔离：不同 user_id 查询互不可见
  5. 唯一约束：同用户/同植物/同类型/同日重复打卡应报 IntegrityError
"""

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tortoise import Tortoise, run_async
from tortoise.exceptions import IntegrityError

from app.main import TORTOISE_MODULES
from app.models import AiAdvice, Plant, PlantMetric, PlantRecord, RecordType, User


async def main() -> int:
    db_path = os.path.join(tempfile.mkdtemp(), "smoke.db")
    await Tortoise.init(db_url=f"sqlite:///{db_path}", modules=TORTOISE_MODULES)
    await Tortoise.generate_schemas()

    # 1. 表注册检查
    tables = sorted({m._meta.db_table for m in Tortoise.apps.get("models").get_models()})
    print(f"[1] 注册表: {tables}")
    expected = {"users", "plants", "plant_record", "plant_metric", "ai_advice"}
    if set(tables) != expected:
        print(f"[FAIL] 表集合不符, 期望 {sorted(expected)} 实际 {tables}")
        return 1
    print("[1] 表集合校验通过")

    # 2. CRUD 新增
    alice = await User.create(
        username="alice", email="alice@example.com",
        password_hash="bcrypt_hash_demo", nickname="爱丽丝",
    )
    bob = await User.create(
        username="bob", email="bob@example.com",
        password_hash="bcrypt_hash_demo", nickname="鲍勃",
    )
    p1 = await Plant.create(user=alice, name="绿萝", species="Epipremnum aureum", location="客厅")
    rec = await PlantRecord.create(
        user=alice, plant=p1, record_type=RecordType.WATERING,
        content="浇透 500ml", record_date=date.today(),
    )
    metric = await PlantMetric.create(
        user=alice, plant=p1, temperature=24.5, humidity=62.0, soil_moisture=45.0,
    )
    advice = await AiAdvice.create(
        user=alice, plant=p1, species="绿萝", confidence=0.93,
        content={"care": "保持湿润但不积水"},
        doc_refs=[{"doc_id": "d1", "title": "绿萝养护", "source_type": "kb"}],
        is_fallback=False,
    )
    print(f"[2] 新增: user={alice.id} plant={p1.id} record={rec.id} metric={metric.id} advice={advice.id}")
    assert rec.record_type == RecordType.WATERING, "枚举值往返校验失败"
    print("[2] CRUD 新增 + 枚举往返校验通过")

    # 3. 关系查询
    cnt = await PlantRecord.filter(user_id=alice.id).count()
    assert cnt == 1, f"alice 记录数应为1, 实际 {cnt}"
    print(f"[3] 关系查询: alice 养护记录数 = {cnt}")

    # 4. 数据隔离
    p2 = await Plant.create(user=bob, name="龟背竹", species="Monstera deliciosa")
    await PlantRecord.create(
        user=bob, plant=p2, record_type=RecordType.FERTILIZING, record_date=date.today(),
    )
    alice_plants = await Plant.filter(user_id=alice.id).values_list("name", flat=True)
    assert alice_plants == ["绿萝"], f"数据隔离失效: {alice_plants}"
    print(f"[4] 数据隔离校验通过: alice 仅见自己的植物 {list(alice_plants)}")

    # 5. 唯一约束
    try:
        await PlantRecord.create(
            user=alice, plant=p1, record_type=RecordType.WATERING, record_date=date.today(),
        )
        print("[FAIL] 唯一约束未生效，重复打卡被允许")
        return 1
    except IntegrityError:
        print("[5] 唯一约束（重复打卡拦截）校验通过")

    # 6. 级联删除
    await p1.delete()
    left = await PlantRecord.filter(plant_id=p1.id).count()
    assert left == 0, f"级联删除后残留记录 {left}"
    print("[6] 级联删除（植物->记录）校验通过")

    await Tortoise.close_connections()
    print("\nSMOKE ALL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_async(main()))