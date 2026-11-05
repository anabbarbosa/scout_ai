"""robots.txt rules as in RFC 9309, including the `*` and `$` patterns.

urllib.robotparser compares paths as plain prefixes, so a rule like `Disallow: /*/feed/`
(used by some competitor sites) would never match. This parser follows the RFC instead:
the longest matching rule wins, and Allow wins a tie.
"""

import contextlib
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Rule:
    allow: bool
    pattern: str

    def regex(self) -> re.Pattern[str]:
        anchored = self.pattern.endswith("$")
        body = self.pattern[:-1] if anchored else self.pattern
        regex = ".*".join(re.escape(part) for part in body.split("*"))
        return re.compile(regex + ("$" if anchored else ""))


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    crawl_delay: float | None = None


@dataclass(frozen=True)
class RobotsRules:
    rules: tuple[Rule, ...] = ()
    crawl_delay: float | None = None

    @classmethod
    def allow_all(cls) -> RobotsRules:
        return cls()

    @classmethod
    def disallow_all(cls) -> RobotsRules:
        return cls((Rule(allow=False, pattern="/"),))

    @classmethod
    def parse(cls, text: str, agent: str) -> RobotsRules:
        """Rules of the groups that name `agent` (product token), else of the `*` groups."""
        groups: list[_Group] = []
        current: _Group | None = None
        for raw_line in text.splitlines():
            line = raw_line.split("#", 1)[0].strip()
            key, sep, value = line.partition(":")
            if not sep:
                continue
            key, value = key.strip().lower(), value.strip()
            if key == "user-agent":
                # A user-agent line after rules starts a new group.
                if current is None or current.rules or current.crawl_delay is not None:
                    current = _Group()
                    groups.append(current)
                current.agents.append(value.lower())
            elif current is None:
                continue
            elif key in ("allow", "disallow") and value:
                current.rules.append(Rule(allow=key == "allow", pattern=value))
            elif key == "crawl-delay":
                with contextlib.suppress(ValueError):
                    current.crawl_delay = float(value)

        token = agent.lower()
        chosen = [g for g in groups if token in g.agents] or [g for g in groups if "*" in g.agents]
        delays = [g.crawl_delay for g in chosen if g.crawl_delay is not None]
        return cls(
            tuple(rule for group in chosen for rule in group.rules),
            max(delays) if delays else None,
        )

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        if path == "/robots.txt":
            return True
        matches = [rule for rule in self.rules if rule.regex().match(path)]
        if not matches:
            return True
        best = max(matches, key=lambda rule: (len(rule.pattern), rule.allow))
        return best.allow
