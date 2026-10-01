"""Adaptive Hierarchical Memory Store for Elder Persona and Swarm Context.

Inspired by Nanobot (Hierarchical Memory Consolidation) and Claude Code (teamMemoryOps.ts).
Provides 3-tier memory:
- Tier 1: In-memory live conversation context
- Tier 2: Token-budget episodic history ledger (episodic_history.jsonl)
- Tier 3: Consolidated elder profile markdown (ELDER_PROFILE.md)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

DEFAULT_MEMORY_DIR = Path("backend/app/data/memory")

class EpisodicMemoryEntry(BaseModel):
    """Single episodic record in monotonic chronological ledger."""
    cursor: int
    timestamp: str
    summary: str
    facts: List[str] = Field(default_factory=list)

class HierarchicalMemoryStore:
    """3-Tier Adaptive Hierarchical Memory Store for Elder Profiles."""

    def __init__(self, base_dir: Path | str | None = None, user_id: str = "default_elder") -> None:
        if base_dir is None:
            base_dir = DEFAULT_MEMORY_DIR
        self.base_dir = Path(base_dir)
        self.user_id = str(user_id).strip() or "default_elder"
        self.user_dir = self.base_dir / "users" / self.user_id
        self.user_dir.mkdir(parents=True, exist_ok=True)
        self.episodic_file = self.user_dir / "episodic_history.jsonl"
        self.profile_file = self.user_dir / "ELDER_PROFILE.md"

    def record_episode(self, summary: str, facts: List[str]) -> EpisodicMemoryEntry:
        """Append an episodic memory entry into chronological jsonl ledger."""
        filtered_facts = [f.strip() for f in facts if f and isinstance(f, str) and f.strip()]
        entries = self.load_episodic_entries()
        cursor = len(entries) + 1
        entry = EpisodicMemoryEntry(
            cursor=cursor,
            timestamp=datetime.now(timezone.utc).isoformat(),
            summary=summary.strip(),
            facts=filtered_facts,
        )
        with open(self.episodic_file, "a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")
        return entry

    def load_episodic_entries(self, limit: int = 50) -> List[EpisodicMemoryEntry]:
        """Load episodic history entries."""
        if not self.episodic_file.exists():
            return []
        res = []
        with open(self.episodic_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        res.append(EpisodicMemoryEntry.model_validate_json(line))
                    except Exception:
                        continue
        if limit and len(res) > limit:
            return res[-limit:]
        return res

    def consolidate_profile(self, profile_markdown: str) -> None:
        """Save consolidated elder persona, chronic conditions, and preferences."""
        with open(self.profile_file, "w", encoding="utf-8") as f:
            f.write(profile_markdown.strip() + "\n")

    def load_profile(self) -> str:
        """Load consolidated elder persona profile markdown."""
        if not self.profile_file.exists():
            return ""
        try:
            with open(self.profile_file, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            return ""

    def get_elder_context(self) -> str:
        """Generate high-priority context prompt automatically injected into Agent turns.
        Bypasses redundant re-asking of chronic conditions, habits, and preferences.
        """
        profile = self.load_profile()
        episodes = self.load_episodic_entries(limit=5)

        lines = [
            "【长辈自适应认知记忆库 (Hierarchical Memory Context)】",
            "本内容由多Agent协作记忆库长期沉淀，严禁让长辈重复陈述已有事实，直接基于以下画像提供关怀：",
        ]

        if profile:
            lines.append("\n[长期画像档案 (Consolidated Profile)]")
            lines.append(profile)

        if episodes:
            lines.append("\n[近期出行与健康情境 (Recent Episodic Memory)]")
            for ep in episodes:
                facts_str = "；".join(ep.facts) if ep.facts else "无补充细节"
                lines.append(f"- [{ep.timestamp[:10]}] {ep.summary}：{facts_str}")

        if not profile and not episodes:
            return ""

        return "\n".join(lines)


_memory_stores: Dict[str, HierarchicalMemoryStore] = {}

def get_memory_store(user_id: str, base_dir: Path | str | None = None) -> HierarchicalMemoryStore:
    """Get or create cached memory store for a user."""
    key = f"{base_dir}_{user_id}"
    if key not in _memory_stores:
        _memory_stores[key] = HierarchicalMemoryStore(base_dir=base_dir, user_id=user_id)
    return _memory_stores[key]
