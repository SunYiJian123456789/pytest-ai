# -*- coding: utf-8 -*-
"""通用 SQL 执行器（framework 内核）：PyMySQL 驱动 + 参数绑定。

只负责「安全地执行一条 SQL 并返回结构化结果」，不含任何表名或业务 SQL。
业务项目组合它编写自己的 dbclean 与落库断言。

设计要点：
- 真・参数绑定：``execute(sql, params)`` 用占位符传参，杜绝手写转义；
- 结构化结果：``SqlResult.records`` 是 dict 行（DictCursor），类型由驱动还原；
  ``rows`` 保留 TSV 文本行，兼容旧消费方；
- 连接复用：线程本地连接 + ping 重连，同进程多次查询不再重复建连；
- 密码不落日志：连接参数只进驱动，不进命令行、不进报告；
- 驱动缺失/未配置时返回 ``skipped=True``，由调用方决定如何呈现；
- ``strict=True``（CI 建议）：连接或 SQL 出错直接抛 RuntimeError，
  避免「基础设施坏了跑出全绿报告」。
"""
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Union

try:
    import pymysql
    import pymysql.cursors
except ImportError:  # 驱动未安装时保持可导入，available() 为 False
    pymysql = None

Params = Union[Sequence[Any], Dict[str, Any], None]


@dataclass
class SqlResult:
    ok: bool
    rows: List[str]
    error: str
    skipped: bool = False
    records: List[Dict[str, Any]] = field(default_factory=list)  # 结构化行（dict）

    @property
    def text(self) -> str:
        return '\n'.join(self.rows)


class SqlExecutor:
    def __init__(self, *, host: str = 'localhost', port: int = 3306,
                 database: str = '', user: str = '', password: str = '',
                 charset: str = 'utf8mb4', timeout: int = 30,
                 connect_timeout: int = 5, strict: bool = False):
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self.charset = charset
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self.strict = strict
        self._local = threading.local()  # 每线程一条连接，xdist 各进程独立

    def available(self) -> bool:
        """驱动可导入且 database 已配置。连接失败不属于 available，交给 execute 报错。"""
        return pymysql is not None and bool(self.database)

    def _connection(self):
        conn = getattr(self._local, 'conn', None)
        if conn is not None:
            try:
                conn.ping(reconnect=True)
                return conn
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass
                self._local.conn = None
        conn = pymysql.connect(
            host=self.host, port=self.port, user=self.user, password=self.password,
            database=self.database, charset=self.charset,
            connect_timeout=self.connect_timeout,
            read_timeout=self.timeout, write_timeout=self.timeout,
            autocommit=True, cursorclass=pymysql.cursors.DictCursor,
        )
        self._local.conn = conn
        return conn

    def execute(self, statement: str, params: Params = None) -> SqlResult:
        if not self.available():
            return SqlResult(False, [], 'pymysql 未安装或未配置数据库名', skipped=True)
        conn = None
        try:
            conn = self._connection()
            with conn.cursor() as cursor:
                cursor.execute(statement, params)
                records = list(cursor.fetchall())
        except Exception as exc:
            stage = '连接 MySQL 失败' if conn is None else 'SQL 执行失败'
            message = '%s: %s' % (stage, str(exc)[:300])
            if self.strict:
                raise RuntimeError(message) from exc
            return SqlResult(False, [], message)
        rows = ['\t'.join(str(value) for value in row.values()) for row in records]
        return SqlResult(True, rows, '', records=records)
