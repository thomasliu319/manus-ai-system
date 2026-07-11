"""pytest 配置 — 注册自定义标记、屏蔽警告"""

import pytest
import warnings


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: 需要 LLM 调用的测试（默认跳过，--run-slow 启用）"
    )


def pytest_addoption(parser):
    parser.addoption("--run-slow", action="store_true", default=False, help="运行 LLM 相关慢速测试")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-slow"):
        return
    skip_slow = pytest.mark.skip(reason="需要 --run-slow 选项才执行")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


warnings.filterwarnings("ignore", category=pytest.PytestUnknownMarkWarning)
