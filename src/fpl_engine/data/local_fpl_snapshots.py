"""Append-only local receipts for Official FPL payloads retained for PIT backtests."""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib, json, os
from pathlib import Path
from typing import Iterable
from fpl_engine.data.providers.fpl_api import FPLApiResult
from pydantic import ValidationError
from fpl_engine.data.raw_store import RawSnapshot, RawStore, RawStoreError

class LocalFPLSnapshotError(Exception): pass
class LocalFPLSnapshotValidationError(LocalFPLSnapshotError): pass
class LocalFPLSnapshotExistsError(LocalFPLSnapshotError): pass
class LocalFPLSnapshotNotFoundError(LocalFPLSnapshotError): pass
class LocalFPLSnapshotStorageError(LocalFPLSnapshotError): pass
def _utc(v,name="timestamp"):
    if not isinstance(v,datetime) or v.tzinfo is None or v.utcoffset() is None: raise LocalFPLSnapshotValidationError(f"{name} must be an aware datetime")
    return v.astimezone(timezone.utc)
def _name(v): return _utc(v).strftime("%Y-%m-%dT%H-%M-%S.%fZ")
@dataclass(frozen=True,order=True)
class LocalFPLSnapshot:
    snapshot_timestamp:datetime; payload_name:str; checksum:str; content_length:int; raw_snapshot:RawSnapshot
    path:Path; source_url:str|None
class LocalFPLSnapshotStore:
    """A local append-only index; RawStore remains the immutable byte authority."""
    def __init__(self,root:Path,*,raw_store:RawStore):
        if not isinstance(raw_store,RawStore): raise LocalFPLSnapshotValidationError("raw_store must be a RawStore")
        self.root=Path(root).resolve(); self._raw=raw_store
    def capture(self,payload_name:str,result:FPLApiResult,*,snapshot_timestamp:datetime,season:str|None=None)->LocalFPLSnapshot:
        if payload_name not in {"bootstrap_static","fixtures","gameweek_metadata","player_summary"}: raise LocalFPLSnapshotValidationError("Unsupported local FPL payload name")
        if not isinstance(result,FPLApiResult): raise LocalFPLSnapshotValidationError("result must be an FPLApiResult")
        when=_utc(snapshot_timestamp); directory=self.root/"official_fpl_api"/_name(when); receipt=directory/f"{payload_name}.snapshot.json"
        if receipt.exists(): raise LocalFPLSnapshotExistsError(f"Local FPL snapshot already exists at {receipt}")
        try:
            raw=self._raw.store_bytes(result.response.body,source_provider="local_fpl_archive",entity=payload_name,retrieved_at=when,source_url=result.raw_snapshot.source_url if result.raw_snapshot else None,source_record_id=f"{payload_name}:{when.isoformat()}")
            # One logical capture time may contain bootstrap, fixtures and other
            # independently named payloads.  The exclusive receipt write below
            # preserves append-only semantics for each payload while allowing
            # those records to share the timestamp directory.
            directory.mkdir(parents=True,exist_ok=True)
            record={"snapshot_timestamp":when.isoformat().replace("+00:00","Z"),"payload_name":payload_name,"checksum":raw.checksum,"content_length":raw.content_length,"raw_snapshot":raw.model_dump(mode="json"),"source_url":raw.source_url,**({"season":season} if isinstance(season,str) and season else {})}
            with receipt.open("x",encoding="utf-8") as stream: json.dump(record,stream,sort_keys=True,separators=(",",":")); stream.flush(); os.fsync(stream.fileno())
        except FileExistsError as exc: raise LocalFPLSnapshotExistsError(f"Local FPL snapshot already exists at {directory}") from exc
        except (OSError,RawStoreError) as exc: raise LocalFPLSnapshotStorageError("Cannot persist local FPL snapshot") from exc
        return LocalFPLSnapshot(when,payload_name,raw.checksum,raw.content_length,raw,receipt,raw.source_url)
    def select_before(self,prediction_timestamp:datetime,payload_name:str="bootstrap_static")->LocalFPLSnapshot:
        cutoff=_utc(prediction_timestamp,"prediction_timestamp"); candidates=[]
        for receipt in self.root.glob(f"official_fpl_api/*/{payload_name}.snapshot.json"):
            try:
                record=json.loads(receipt.read_text(encoding="utf-8")); when=_utc(datetime.fromisoformat(record["snapshot_timestamp"].replace("Z","+00:00")))
                raw=RawSnapshot.model_validate_json(json.dumps(record["raw_snapshot"])); candidates.append(LocalFPLSnapshot(when,record["payload_name"],record["checksum"],record["content_length"],raw,receipt,record.get("source_url")))
            except (OSError,ValueError,KeyError,ValidationError): raise LocalFPLSnapshotStorageError(f"Invalid local snapshot receipt {receipt}")
        eligible=[item for item in candidates if item.snapshot_timestamp < cutoff]
        if not eligible: raise LocalFPLSnapshotNotFoundError("No local FPL snapshot exists strictly before the prediction timestamp")
        return max(eligible)
