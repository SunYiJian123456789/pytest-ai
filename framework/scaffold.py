# -*- coding: utf-8 -*-
"""新项目脚手架：python -m framework.scaffold <项目名> [选项]

从 framework/project_template/ 复制骨架到 projects/<项目名>/，替换占位符。
生成后只需改 projects/<项目名>/config.py 和 .env 即可复用 framework 全部能力。
"""
import argparse
import keyword
import sys
from pathlib import Path

from framework.config import ROOT

TEMPLATE_DIR = Path(__file__).resolve().parent / 'project_template'


def create(project: str, *, base_url: str = 'http://127.0.0.1:8080',
           prefix: str = '', force: bool = False) -> Path:
    if not project.isidentifier() or keyword.iskeyword(project):
        raise ValueError('项目名必须是合法的 Python 标识符：%r' % project)
    if project.startswith('_') or project in ('framework', 'projects', 'reports'):
        raise ValueError('项目名与保留目录冲突：%r' % project)

    target = ROOT / 'projects' / project
    if target.exists() and not force:
        raise FileExistsError('项目目录已存在：%s（如需覆盖请加 --force）' % target)

    upper = project.upper()
    replacements = {
        '{{PROJECT}}': project,
        '{{PROJECT_UPPER}}': upper,
        '{{PREFIX}}': (prefix or upper + '_'),
        '{{BASE_URL}}': base_url.rstrip('/'),
    }

    for source in sorted(TEMPLATE_DIR.rglob('*.tpl')):
        relative = source.relative_to(TEMPLATE_DIR)
        destination = target / relative.with_suffix('')
        destination.parent.mkdir(parents=True, exist_ok=True)
        text = source.read_text(encoding='utf-8')
        for old, new in replacements.items():
            text = text.replace(old, new)
        destination.write_text(text, encoding='utf-8')

    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description='生成一个可独立配置的新接口自动化项目')
    parser.add_argument('project', help='项目名（Python 标识符），如 order_system')
    parser.add_argument('--base-url', default='http://127.0.0.1:8080', help='被测服务地址')
    parser.add_argument('--prefix', default='', help='环境变量前缀，默认项目名大写 + _')
    parser.add_argument('--force', action='store_true', help='目录已存在时覆盖')
    args = parser.parse_args(argv)

    try:
        target = create(args.project, base_url=args.base_url,
                        prefix=args.prefix, force=args.force)
    except (ValueError, FileExistsError) as exc:
        print('生成失败：%s' % exc, file=sys.stderr)
        return 1

    print('已生成：%s' % target)
    print('下一步：')
    print('  1. 编辑 %s/config.py（账号、路径、模块标签）' % target)
    print('  2. 复制 .env.example 为 .env，按 %s 前缀填环境变量'
          % (args.prefix or args.project.upper() + '_'))
    print('  3. 编辑 %s/data/api_cases.yaml 增减数据集' % target)
    print('  4. 运行：python -m pytest -o testpaths=projects/%s/testcases' % args.project)
    return 0


if __name__ == '__main__':
    sys.exit(main())
