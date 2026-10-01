"""Unit & Integration Tests for Adaptive Hierarchical Memory & Proactive Context Care.

覆盖需求: R3 (自适应分层认知记忆与主动情境关怀)
对应特性: F8 (Adaptive Hierarchical Memory Store), F9 (Proactive Context Care & Recall)
"""
from __future__ import annotations

import pytest
from pathlib import Path
from tests.swarm_fixtures import (
    EpisodicMemoryEntry,
    HierarchicalMemoryStore,
)


class TestHierarchicalMemoryStoreUnit:
    """F8: 分层认知记忆存储测试。"""

    def test_episodic_history_persistence(self, tmp_path):
        store = HierarchicalMemoryStore(tmp_path, "test_user_mem")
        e = store.record_episode("烈士公园散步", ["偏好平缓路", "避开南门台阶"])
        assert e.cursor == 1
        entries = store.load_episodic_entries()
        assert len(entries) == 1
        assert "避开南门台阶" in entries[0].facts

    def test_elder_profile_consolidation(self, tmp_path):
        store = HierarchicalMemoryStore(tmp_path, "test_user_mem")
        store.consolidate_profile("# 长辈画像\n- 膝盖怕冷\n- 单次步行<600米")
        profile = store.load_profile()
        assert "单次步行<600米" in profile


class TestProactiveContextCareUnit:
    """F9: 主动情境关怀与上下文自动注入测试。"""

    def test_get_elder_context_generation(self, tmp_path):
        store = HierarchicalMemoryStore(tmp_path, "test_user_care")
        store.consolidate_profile("- 慢性骨关节炎")
        store.record_episode("昨天散步", ["中途在长椅休息了10分钟"])

        ctx = store.get_elder_context()
        assert "严禁让长辈重复陈述已有事实" in ctx
        assert "慢性骨关节炎" in ctx
        assert "长椅休息" in ctx
