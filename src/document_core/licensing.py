from dataclasses import dataclass


class EntitlementRequiredError(RuntimeError):
    pass


@dataclass(frozen=True)
class EntitlementService:
    enabled_features: frozenset[str] = frozenset()

    @classmethod
    def from_csv(cls, value: str) -> "EntitlementService":
        return cls(frozenset(item.strip() for item in value.split(",") if item.strip()))

    def allows(self, feature: str | None) -> bool:
        return feature is None or feature in self.enabled_features

    def require(self, feature: str | None) -> None:
        if not self.allows(feature):
            raise EntitlementRequiredError(f"Lizenzmerkmal nicht aktiviert: {feature}")
