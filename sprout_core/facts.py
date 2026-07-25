from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Iterable


MAX_FACT_TYPES = 8
MAX_FACT_MEMBERS = 128
MAX_FACT_DEPTH = 8


def _ordered_types(types: Iterable[str]) -> tuple[str, ...]:
    unique = set(types)
    order = {
        "Nil": 0,
        "Bool": 1,
        "Int": 2,
        "Float": 3,
        "Number": 4,
        "String": 5,
        "Any": 99,
    }
    return tuple(sorted(unique, key=lambda item: (order.get(item, 50), item)))[:MAX_FACT_TYPES]


@dataclass
class ValueFacts:
    """Bounded static facts shared by completion, hover, and diagnostics."""

    types: tuple[str, ...] = ()
    members: dict[str, "ValueFacts"] = field(default_factory=dict)
    target_type: str | None = None
    item: "ValueFacts | None" = None
    key: "ValueFacts | None" = None
    value: "ValueFacts | None" = None
    presence: str = "required"
    unknown: bool = False

    @classmethod
    def unknown_value(cls) -> "ValueFacts":
        return cls(types=("Any",), unknown=True)

    @classmethod
    def of_type(cls, name: str, *, target_type: str | None = None) -> "ValueFacts":
        return cls(types=(name,), target_type=target_type)

    @classmethod
    def object(cls, members: dict[str, "ValueFacts"]) -> "ValueFacts":
        values = [member.type_name for member in members.values()]
        value_type = " | ".join(_ordered_types(values)) if values else "Any"
        return cls(
            types=(f"Dict[String, {value_type}]",),
            members={name: member.copy() for name, member in list(members.items())[:MAX_FACT_MEMBERS]},
            key=cls.of_type("String"),
            value=cls(types=_ordered_types(values)) if values else cls.unknown_value(),
        )

    @property
    def nilable(self) -> bool:
        return "Nil" in self.types

    @property
    def type_name(self) -> str:
        return " | ".join(self.types) if self.types else "Any"

    @property
    def is_pure_unknown(self) -> bool:
        return self.unknown and self.types in {(), ("Any",)} and not self.members and self.target_type is None

    def copy(self, *, depth: int = 0) -> "ValueFacts":
        if depth >= MAX_FACT_DEPTH:
            return ValueFacts(
                types=self.types,
                target_type=self.target_type,
                presence=self.presence,
                unknown=True,
            )
        return ValueFacts(
            types=self.types,
            members={
                name: member.copy(depth=depth + 1)
                for name, member in list(self.members.items())[:MAX_FACT_MEMBERS]
            },
            target_type=self.target_type,
            item=self.item.copy(depth=depth + 1) if self.item else None,
            key=self.key.copy(depth=depth + 1) if self.key else None,
            value=self.value.copy(depth=depth + 1) if self.value else None,
            presence=self.presence,
            unknown=self.unknown,
        )

    def with_presence(self, presence: str) -> "ValueFacts":
        return replace(self.copy(), presence=presence)

    def join(self, other: "ValueFacts", *, depth: int = 0) -> "ValueFacts":
        if self.is_pure_unknown and not other.is_pure_unknown:
            result = other.copy(depth=depth)
            result.unknown = True
            return result
        if other.is_pure_unknown and not self.is_pure_unknown:
            result = self.copy(depth=depth)
            result.unknown = True
            return result
        if depth >= MAX_FACT_DEPTH:
            return ValueFacts(
                types=_ordered_types((*self.types, *other.types)),
                target_type=self.target_type if self.target_type == other.target_type else None,
                presence="required" if self.presence == other.presence == "required" else "conditional",
                unknown=True,
            )
        names = list(dict.fromkeys((*self.members, *other.members)))[:MAX_FACT_MEMBERS]
        members: dict[str, ValueFacts] = {}
        for name in names:
            left = self.members.get(name)
            right = other.members.get(name)
            if left and right:
                members[name] = left.join(right, depth=depth + 1)
            else:
                members[name] = (left or right).with_presence("conditional")  # type: ignore[union-attr]
        item = _join_optional(self.item, other.item, depth)
        key = _join_optional(self.key, other.key, depth)
        value = _join_optional(self.value, other.value, depth)
        types = _ordered_types((*self.types, *other.types))
        if key and value and all(name.startswith("Dict[") for name in (*self.types, *other.types)):
            types = (f"Dict[{key.type_name}, {value.type_name}]",)
        elif item and all(name.startswith(("List[", "Array[", "Generator[")) for name in (*self.types, *other.types)):
            container = self.types[0].split("[", 1)[0]
            types = (f"{container}[{item.type_name}]",)
        return ValueFacts(
            types=types,
            members=members,
            target_type=self.target_type if self.target_type == other.target_type else None,
            item=item,
            key=key,
            value=value,
            presence="required" if self.presence == other.presence == "required" else "conditional",
            unknown=self.unknown or other.unknown,
        )


def _join_optional(left: ValueFacts | None, right: ValueFacts | None, depth: int) -> ValueFacts | None:
    if left and right:
        return left.join(right, depth=depth + 1)
    if left or right:
        return (left or right).with_presence("conditional")  # type: ignore[union-attr]
    return None
