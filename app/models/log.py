from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime, timezone


class LogEvent(BaseModel):
    level: str = "INFO"
    message: str
    source: Optional[str] = None
    timestamp: Optional[str] = None
    tags: Optional[list[str]] = None

    def with_timestamp(self) -> "LogEvent":
        if not self.timestamp:
            return self.model_copy(
                update={"timestamp": datetime.now(timezone.utc).isoformat()}
            )
        return self
