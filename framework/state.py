# -*- coding: utf-8 -*-
"""会话状态（framework 内核）：一处声明、一处重置、一处合并。

要解决的问题
------------
改造前，进程内可变状态散落在六个模块：

- ``config.MISSING_REQUIRED``：登记的必填键
- ``preflight.RECORDS / ABORTED``：体检结果与中止标记
- ``coverage.HITS / INVENTORY``：请求命中与接口清单路径
- ``cleanup.CLEANUP_LOG``：清理结果汇总
- ``hooks.REPORT_OPTIONS / REPORT_ENHANCE_ERROR``：报告选项与增强错误
- 业务项目的 ``_TOKENS``：登录态缓存

其中 cleanup 与 coverage 各写了一遍几乎相同的「xdist worker 落盘 → 主进程
合并」逻辑；跨模块判断（体检中止 → 跳过覆盖率）只能靠全局变量打信号。

设计约定
--------
1. 所有会话态字段集中在本模块的 :class:`SessionState`，进程内一个实例 ``state``。
2. 容器字段在 ``__init__`` 创建一次，``reset_*`` **原地清空**而不重新赋值——
   这样各模块保留的兼容别名（如 ``preflight.RECORDS``）永远指向同一对象，
   现有代码和测试无需改写。
3. 跨 worker 合并抽象成「分区」（partition）：业务模块注册前缀 + dump/merge
   函数，统一由 :meth:`SessionState.dump_worker` / :meth:`load_workers` 调度。
4. 业务层用 :meth:`SessionState.namespace` 取私有槽位，内核不认识任何业务字段。
"""
import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List

# 报告默认选项的原定义处；hooks.REPORT_OPTIONS 是指向 state.report_options 的别名
DEFAULT_REPORT_OPTIONS: dict = {
    'title': '接口自动化测试报告（pytest + requests）',
    'project_label': 'API · REGRESSION',
    'module_labels': {},
    'base_url': '',
    'database': '',
    'data_source': '',
    'notes': [],
    'success_code': '200',
}


@dataclass
class _Partition:
    """一组需要跨 xdist worker 合并的状态：文件前缀 + 序列化 + 合并函数。"""

    prefix: str
    dump: Callable[[], Any]
    merge: Callable[[Any], None]


class SessionState:
    """进程级会话状态单例。

    单测用 ``state.reset()`` 做整体隔离；模块内部用 ``reset_coverage()`` 等
    定向清空，避免 A 模块的 reset 误伤 B 模块的状态。
    """

    def __init__(self):
        # RLock：coverage.record() 会被并发用例的多个线程调用；
        # 合并回调里可能再次取状态，用可重入锁避免自锁。
        self.lock = threading.RLock()
        self._partitions: Dict[str, _Partition] = {}

        # —— 容器只创建一次；reset 时原地 clear，保持外部别名有效 ——
        self.missing_required: Dict[str, str] = {}
        self.preflight_records: List[dict] = []
        self.coverage_hits: dict = {}
        self.cleanup_log: List[dict] = []
        self.report_options: dict = dict(DEFAULT_REPORT_OPTIONS)
        self.report_enhance_errors: List[str] = []
        self.namespaces: Dict[str, dict] = {}

        # —— 标量字段 ——
        self.preflight_aborted: bool = False
        self.coverage_inventory: Path | None = None

    # ---------- 重置 ----------

    def reset(self) -> None:
        """清空全部会话态（整体隔离，主要给单测与新会话用）。"""
        with self.lock:
            self.missing_required.clear()
            self.preflight_records.clear()
            self.coverage_hits.clear()
            self.cleanup_log.clear()
            self.report_enhance_errors.clear()
            self.namespaces.clear()
            self.report_options.clear()
            self.report_options.update(DEFAULT_REPORT_OPTIONS)
            self.preflight_aborted = False
            self.coverage_inventory = None

    def reset_config(self) -> None:
        with self.lock:
            self.missing_required.clear()

    def reset_preflight(self) -> None:
        with self.lock:
            self.preflight_records.clear()
            self.preflight_aborted = False

    def reset_coverage(self) -> None:
        with self.lock:
            self.coverage_hits.clear()
            self.coverage_inventory = None

    def reset_cleanup(self) -> None:
        with self.lock:
            self.cleanup_log.clear()

    # ---------- 业务私有槽位 ----------

    def namespace(self, name: str) -> dict:
        """取一个按名字隔离的持久字典；内核不解释里面的内容。"""
        with self.lock:
            return self.namespaces.setdefault(name, {})

    # ---------- xdist 分区注册 ----------

    def register_partition(self, name: str, *, prefix: str,
                           dump: Callable[[], Any],
                           merge: Callable[[Any], None]) -> None:
        """注册一组跨 worker 合并的状态；同名覆盖，便于单测重注册。"""
        with self.lock:
            self._partitions[name] = _Partition(prefix, dump, merge)

    def dump_partition(self, name: str, path: Path | str) -> None:
        """兼容旧入口：把单个分区写到指定文件。"""
        part = self._partitions.get(name)
        if part is None:
            return
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            payload = part.dump()
        target.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')

    def load_partition(self, name: str, directory: Path | str) -> None:
        """兼容旧入口：只合并指定分区的 worker 文件。"""
        part = self._partitions.get(name)
        if part is not None:
            self._load_files(part, Path(directory))

    def dump_worker(self, reports_dir: Path | str, worker_id: str) -> None:
        """worker 退出：一次写出全部已注册分区。"""
        root = Path(reports_dir)
        root.mkdir(parents=True, exist_ok=True)
        with self.lock:
            for part in self._partitions.values():
                try:
                    payload = part.dump()
                except Exception:  # noqa: BLE001 - 单项落盘失败不影响退出
                    continue
                target = root / ('%s%s.json' % (part.prefix, worker_id))
                try:
                    target.write_text(
                        json.dumps(payload, ensure_ascii=False), encoding='utf-8')
                except OSError:
                    pass

    def load_workers(self, reports_dir: Path | str) -> None:
        """主进程启动收尾：合并全部 worker 分区并清理临时文件。"""
        root = Path(reports_dir)
        with self.lock:
            for part in self._partitions.values():
                self._load_files(part, root)

    # ---------- 内部 ----------

    @staticmethod
    def _load_files(part: _Partition, root: Path) -> None:
        for file in sorted(root.glob('%s*.json' % part.prefix)):
            try:
                payload = json.loads(file.read_text(encoding='utf-8'))
            except Exception:  # noqa: BLE001 - 单个损坏文件不影响整体汇总
                payload = None
            finally:
                file.unlink(missing_ok=True)
            if payload is None:
                continue
            try:
                part.merge(payload)
            except Exception:  # noqa: BLE001 - 坏数据不应让测试流程崩掉
                pass


# 进程内唯一实例
state = SessionState()

__all__ = ['SessionState', 'DEFAULT_REPORT_OPTIONS', 'state']
