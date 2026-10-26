"""用户模型（PRD 13 users 表）。

约束1：密码只存 bcrypt 哈希（password_hash），业务层负责 bcrypt 生成与校验，
      禁止明文存储/传输。模型层只定义字段，不承载加密逻辑。
"""

from tortoise import fields

from app.models.base import TimestampMixin


class User(TimestampMixin):
    """用户账号表（nickname 为唯一登录账号）。"""

    nickname = fields.CharField(max_length=32, unique=True, description="昵称（登录账号，3-20位字母数字下划线）")
    password_hash = fields.CharField(max_length=128, description="bcrypt密码哈希（约束1：不存明文）")
    username = fields.CharField(max_length=32, null=True, description="用户名（预留扩展，可空）")
    email = fields.CharField(max_length=128, null=True, description="邮箱（预留扩展，可空）")
    avatar_url = fields.CharField(max_length=512, null=True, description="头像URL")
    role = fields.CharField(max_length=16, default="ROLE_USER", description="角色：ROLE_USER / ROLE_ADMIN")
    is_active = fields.BooleanField(default=True, description="是否启用（禁用后禁止登录）")

    # 反向关系：一个用户拥有多株植物（级联删除）
    plants: fields.ReverseRelation["Plant"]

    class Meta:
        table = "users"

    def __str__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"