"""Temporal, auditable manual context records (DATA-010)."""
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator
class ManualContextError(Exception): pass
class ManualContextValidationError(ManualContextError): pass
def _utc(v):
    if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None: raise ValueError("timestamps must be aware")
    return v.astimezone(timezone.utc)
class ManualContextRecord(BaseModel):
    model_config=ConfigDict(frozen=True,strict=True,extra="forbid")
    context_type:str; subject_type:str; subject_id:str; value:Any; effective_from:datetime; effective_to:datetime|None=None; created_at:datetime; confidence:float=Field(ge=0,le=1); reason:str; source_reference:str|None=None; author:str|None=None
    @model_validator(mode="after")
    def validate_times(self):
        for field in ("effective_from","effective_to","created_at"):
            value=getattr(self,field)
            if value is not None: object.__setattr__(self,field,_utc(value))
        if self.effective_to is not None and self.effective_to<self.effective_from: raise ValueError("effective_to precedes effective_from")
        return self
    def is_active_at(self,prediction_timestamp:datetime)->bool:
        t=_utc(prediction_timestamp)
        return self.created_at<=t and self.effective_from<=t and (self.effective_to is None or t<=self.effective_to)
def load_manual_context(path:Path)->tuple[ManualContextRecord,...]:
    try:
        data=yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        records=data.get("overrides",[]) if isinstance(data,dict) else None
        if not isinstance(records,list): raise ValueError("overrides must be a list")
        return tuple(ManualContextRecord.model_validate(item) for item in records)
    except (OSError,yaml.YAMLError,ValueError) as exc: raise ManualContextValidationError(f"Invalid manual context at {path}") from exc
def active_context(records, prediction_timestamp:datetime): return tuple(item for item in records if item.is_active_at(prediction_timestamp))
