# -*- coding: utf-8 -*-
"""shopping 业务 SQL：只读断言查询 + 无删除接口的数据清理。

SQL 本身属于业务层；连接复用、参数绑定、结构化结果等通用能力来自
framework.db.SqlExecutor（PyMySQL 驱动，密码只进连接参数，不进命令行）。

查询失败直接抛 RuntimeError，不与「查无此行」混在一起——配置错误当场暴露，
而不是伪装成「订单未落库」这种误导性的断言失败。
"""
from typing import Optional, Tuple

from framework.db import SqlExecutor, SqlResult
from projects.shopping.config import (
    DB_STRICT, MYSQL_DATABASE, MYSQL_HOST, MYSQL_PASSWORD,
    MYSQL_PORT, MYSQL_USER,
)

_executor = SqlExecutor(
    host=MYSQL_HOST, port=MYSQL_PORT, database=MYSQL_DATABASE,
    user=MYSQL_USER, password=MYSQL_PASSWORD, strict=DB_STRICT,
)


def available() -> bool:
    return _executor.available()


def execute(statement: str, params=None) -> SqlResult:
    """兼容旧调用：返回 SqlResult；参数用占位符 %s 绑定，不要拼进 SQL 文本。"""
    return _executor.execute(statement, params)


def _must(result: SqlResult) -> SqlResult:
    """查询类 SQL 的硬失败：驱动缺失（skipped）交给调用方决定，其余错误直接抛。"""
    if not result.ok and not result.skipped:
        raise RuntimeError('SQL 执行失败：%s' % result.error)
    return result


def _in(values) -> Tuple[str, tuple]:
    """构造 IN 子句的占位符串与去重后的参数元组。"""
    items = tuple(dict.fromkeys(values))
    return ','.join(['%s'] * len(items)), items


# ---------- 只读查询（供断言使用）----------

def query_order(order_no: str) -> Optional[dict]:
    result = _must(_executor.execute(
        'SELECT order_no, total_amount, status, fail_reason, user_id '
        'FROM payment_order WHERE order_no = %s LIMIT 1', (order_no,)))
    if not result.records:
        return None
    row = result.records[0]
    return {
        'orderNo': row['order_no'],
        'amount': float(row['total_amount']) if row['total_amount'] is not None else None,
        'status': row['status'],
        'failReason': row['fail_reason'],
        'userId': row['user_id'],
    }


def count_order_items(order_no: str) -> int:
    result = _must(_executor.execute(
        'SELECT COUNT(*) AS cnt FROM payment_order_item WHERE order_no = %s', (order_no,)))
    return int(result.records[0]['cnt'])


def query_user(username: str) -> Optional[dict]:
    result = _must(_executor.execute(
        'SELECT username, nickname FROM sys_user WHERE username = %s LIMIT 1', (username,)))
    if not result.records:
        return None
    row = result.records[0]
    return {'username': row['username'], 'nickname': row['nickname'] or ''}


# ---------- 清理 ----------

def delete_payment_orders(order_numbers) -> SqlResult:
    placeholders, numbers = _in(order_numbers)
    if not numbers:
        return SqlResult(True, [], '')
    item_result = _executor.execute(
        'DELETE FROM payment_order_item WHERE order_no IN (%s)' % placeholders, numbers)
    order_result = _executor.execute(
        'DELETE FROM payment_order WHERE order_no IN (%s)' % placeholders, numbers)
    error = '; '.join(x for x in (item_result.error, order_result.error) if x)
    return SqlResult(
        order_result.ok and item_result.ok, [], error,
        skipped=item_result.skipped or order_result.skipped,
    )


def delete_users(usernames) -> SqlResult:
    placeholders, names = _in(usernames)
    if not names:
        return SqlResult(True, [], '')
    return _executor.execute(
        'DELETE FROM sys_user WHERE username IN (%s)' % placeholders, names)


# ---------- 兜底扫描（session 收尾用）----------

# 表名/列名只能来自这张白名单，杜绝外部输入拼进 SQL。
_SCAN_TARGETS = {
    'users': ('sys_user', 'username'),
    'products': ('product', 'name'),
    'categories': ('category', 'name'),
    'approvals': ('product_approval', 'name'),
}


def scan_test_keys(target: str, prefix: str = 'API') -> list[str]:
    """按测试专用前缀扫残留标识（只读）；未知 target 直接拒绝。

    demo / admin / reviewer 等账号都不以 API 开头，真实数据不会被扫到。
    """
    if target not in _SCAN_TARGETS:
        raise ValueError('未登记的扫描目标：%s' % target)
    table, column = _SCAN_TARGETS[target]
    result = _must(_executor.execute(
        'SELECT %s AS item_key FROM %s WHERE %s LIKE %%s'
        % (column, table, column), (prefix + '%',)))
    return [str(row['item_key']) for row in result.records]


def delete_test_keys(target: str, keys) -> SqlResult:
    """按标识删除残留；target 白名单与 scan_test_keys 共用。"""
    if target not in _SCAN_TARGETS:
        raise ValueError('未登记的清理目标：%s' % target)
    table, column = _SCAN_TARGETS[target]
    placeholders, items = _in(keys)
    if not items:
        return SqlResult(True, [], '')
    return _executor.execute(
        'DELETE FROM %s WHERE %s IN (%s)' % (table, column, placeholders), items)
