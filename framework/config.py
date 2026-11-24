# -*- coding: utf-8 -*-
"""通用配置加载器（framework 内核，不含任何业务字段）。

配置来源优先级：进程环境变量 > .env.<API_ENV> > .env > 默认值。

多环境：启动前设置进程环境变量 ``API_ENV``（如 test / staging），框架会先加载
``.env.<API_ENV>``，再加载 ``.env`` 兜底——环境差异只维护差异项，公共项留在
``.env``。同一键在两个文件都存在时，环境专属文件优先。

业务项目通过 ``Settings(prefix)`` 声明自己的环境变量前缀，例如::

    cfg = Settings('DEMO_')
    BASE_URL = cfg.get('API_BASE_URL', 'http://127.0.0.1:8080')
    cfg.require('UPLOAD_DIR')   # 缺失即报错，列出全部缺项

换一个系统时只改 projects/<name>/config.py，内核代码不动。
"""
import os
from pathlib import Path

# 仓库根目录（framework 的上一级），与 pytest 的 rootdir 一致
ROOT = Path(__file__).resolve().parents[1]

# 运行环境名：必须在进程启动前设置（.env 里写 API_ENV 无效，避免鸡生蛋问题）
ENV = os.getenv('API_ENV', '')


def load_dotenv(path: Path | str | None = None):
    """极简 .env 解析：KEY=VALUE，忽略注释/空行，不覆盖已有环境变量。"""
    target = Path(path) if path else ROOT / '.env'
    if not target.exists():
        return
    # utf-8-sig 兼容带 BOM 的文件（Windows 记事本/PowerShell 写出的 .env 常见），
    # 否则第一行的键名会被 BOM 污染而静默失效
    for line in target.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip().strip('"\'')
        if key:
            os.environ.setdefault(key, value)


if ENV:
    load_dotenv(ROOT / ('.env.' + ENV))  # 环境专属文件优先（setdefault 先到先得）
load_dotenv()


def env(key: str, default: str = '', prefix: str | None = None) -> str:
    """读取环境变量；prefix 用于拼业务前缀，如 env('API_BASE_URL', ..., 'DEMO_')。"""
    full = (prefix or '') + key
    return os.getenv(full, default)


class Settings:
    """一组带统一前缀的环境变量读取器。"""

    def __init__(self, prefix: str = ''):
        self.prefix = prefix.rstrip('_') + '_' if prefix else ''

    def key(self, name: str) -> str:
        return self.prefix + name

    def get(self, name: str, default: str = '') -> str:
        return env(name, default, self.prefix)

    def require(self, *names: str) -> None:
        """启动校验：任一必填键缺失即抛 ValueError，一次性列出全部缺项。

        用于机器相关、没有合理默认值的配置；让配置错误在收集阶段就暴露，
        而不是跑到一半用错误默认值做出不可信的结果。
        """
        missing = [self.key(name) for name in names if not self.get(name)]
        if missing:
            raise ValueError(
                '缺少必填配置（环境=%s）：%s；请在进程环境变量或 .env%s 中补充'
                % (ENV or 'default', ', '.join(missing), '.' + ENV if ENV else '')
            )

    def integer(self, name: str, default: int = 0) -> int:
        return int(self.get(name, str(default)))

    def floating(self, name: str, default: float = 0.0) -> float:
        return float(self.get(name, str(default)))

    def boolean(self, name: str, default: bool = False) -> bool:
        value = self.get(name, str(default)).strip().lower()
        return value in ('1', 'true', 'yes', 'on')

    def path(self, name: str, default: str = '') -> Path:
        return Path(self.get(name, default))
