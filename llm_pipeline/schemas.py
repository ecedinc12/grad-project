from pydantic import BaseModel, Field
from typing import List, Optional, Literal

class PPEState(BaseModel):
    hardhat: bool = Field(default=False, description="Whether the worker is wearing a hardhat")
    vest: bool = Field(default=False, description="Whether the worker is wearing a high-visibility vest")

class Entity(BaseModel):
    type: Literal["worker", "vehicle", "zone"] = Field(..., description="The type of entity")
    asset_id: str = Field(..., description="The ID/name of the asset to spawn")
    ppe_state: Optional[PPEState] = Field(default=None, description="PPE state, applicable mainly for workers")
    anchor_zone: Optional[str] = Field(default=None, description="The zone or area this entity is anchored to")

class SceneConfig(BaseModel):
    entities: List[Entity] = Field(default_factory=list, description="List of entities in the scene")
    camera_angles: List[str] = Field(default_factory=list, description="List of camera angles/positions for rendering")
    lighting_conditions: str = Field(default="daylight", description="Lighting conditions for the scene, e.g., daylight, overcast, night")
