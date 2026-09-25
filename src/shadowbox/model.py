"""Pydantic domain model for M0 (structure only, no simulation)."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

QueuePolicy = Literal["drop", "fifo"]
ConnectionKind = Literal["sync"]

MAX_COMPONENTS = 200
MAX_EVENTS = 500_000


class LatencyMs(BaseModel):
    base: int = Field(ge=0)
    jitter_ms: int = Field(default=0, ge=0)


class Component(BaseModel):
    id: str = Field(min_length=1)
    type: Literal["service", "database", "cache"]
    capacity: int = Field(gt=0)
    latency_ms: LatencyMs
    timeout_ms: int = Field(gt=0)
    queue_size: int = Field(gt=0)
    queue_policy: QueuePolicy


class Connection(BaseModel):
    from_: str = Field(alias="from")
    to: str
    kind: ConnectionKind = "sync"


class SystemModel(BaseModel):
    components: list[Component]
    connections: list[Connection] = Field(default_factory=list)

    @field_validator("components")
    @classmethod
    def unique_ids(cls, items: list[Component]) -> list[Component]:
        seen = {c.id for c in items}
        if len(seen) != len(items):
            raise ValueError("duplicate component id")
        return items


class Fault(BaseModel):
    target: str = Field(min_length=1)
    type: Literal[
        "unavailable",
        "latency",
        "error-rate",
        "capacity-reduction",
        "packet-loss",
        "resource-saturation",
    ]
    start_s: int = Field(ge=0)
    duration_s: int = Field(ge=0)
    extra_ms: int = Field(default=0, ge=0)
    probability: float = Field(default=0.0, ge=0.0, le=1.0)
    factor: float = Field(default=1.0, gt=0.0, le=1.0)


class Workload(BaseModel):
    rate_rps: int = Field(gt=0)
    arrival: Literal["deterministic"] = "deterministic"


class Scenario(BaseModel):
    name: str = Field(min_length=1)
    duration_s: int = Field(gt=0)
    workload: Workload
    faults: list[Fault] = Field(default_factory=list)
