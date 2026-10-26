"""用户模型（PRD 13 users 表）。

role 支持 ROLE_USER / ROLE_ADMIN（PRD 7.1）；user_id 是全局数据隔离的归属键。
"""

from tortoise import fields, models


class User(models.Model):
    """用户账号表。"""

    id = fields.BigIntField(pk=True)
    username = fields.CharField(max_length=32, unique=True, description="用户名")
    email = fields.CharField(max_length=128, unique=True, description="邮箱")
    password_hash = fields.CharField(max_length=128, description="bcrypt 密码哈希")
    nickname = fields.CharField(max_length=32, null=True, description="昵称")
    avatar_url = fields.CharField(max_length=512, null=True, description="头像地址")
    role = fields.CharField(max_length=16, default="ROLE_USER", description="角色")
    is_active = fields.BooleanField(default=True, description="是否启用")
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "users"

    def __str__(self) -> str:
        return f"<User {self.id}:{self.username}>"