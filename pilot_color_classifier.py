from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any


@dataclass
class ColorRule:
    name: str
    color: Tuple[int, int, int]
    danger_min: Optional[float] = None
    danger_max: Optional[float] = None
    kills_min: Optional[int] = None
    kills_max: Optional[int] = None
    losses_min: Optional[int] = None
    losses_max: Optional[int] = None

    def matches(self, danger: float, kills: int, losses: int) -> bool:
        if self.danger_min is not None and danger < self.danger_min:
            return False
        if self.danger_max is not None and danger > self.danger_max:
            return False
        if self.kills_min is not None and kills < self.kills_min:
            return False
        if self.kills_max is not None and kills > self.kills_max:
            return False
        if self.losses_min is not None and losses < self.losses_min:
            return False
        if self.losses_max is not None and losses > self.losses_max:
            return False
        return True


class PilotColorClassifier:
    DEFAULT_COLOR = (255, 255, 255)

    def __init__(self, cfg: Dict[str, Any]):
        self.rules: List[ColorRule] = []
        self.default_color = tuple(cfg.get('default_color', self.DEFAULT_COLOR))
        rules_cfg = cfg.get('rules', {})
        for name, rule_cfg in rules_cfg.items():
            self.rules.append(ColorRule(
                name=name,
                color=tuple(rule_cfg.get('color', self.DEFAULT_COLOR)),
                danger_min=rule_cfg.get('danger_min'),
                danger_max=rule_cfg.get('danger_max'),
                kills_min=rule_cfg.get('kills_min'),
                kills_max=rule_cfg.get('kills_max'),
                losses_min=rule_cfg.get('losses_min'),
                losses_max=rule_cfg.get('losses_max'),
            ))

    def get_color(self, stats: Optional[Dict]) -> Tuple[int, int, int]:
        if not stats:
            return self.default_color
        danger = stats.get('danger', 0)
        kills = stats.get('kills', 0)
        losses = stats.get('losses', 0)
        for rule in self.rules:
            if rule.matches(danger, kills, losses):
                return rule.color
        return self.default_color

    @classmethod
    def create_default(cls) -> 'PilotColorClassifier':
        default_cfg = {
            'default_color': [255, 255, 255],
            'rules': {
                'dangerous': {'color': [0, 0, 255], 'kills_min': 100, 'danger_min': 70},
                'cautious': {'color': [0, 255, 255], 'kills_min': 10, 'danger_min': 20},
            }
        }
        return cls(default_cfg)
