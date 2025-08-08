from pydantic import BaseModel
from typing import Optional

class ProjectSettings(BaseModel):
    name: Optional[str] = "smart-classroom"
    location: Optional[str] = "storage/"
    microphone: Optional[str] = None