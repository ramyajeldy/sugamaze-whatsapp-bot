from pydantic import BaseModel


class ChatRequest(BaseModel):
    tenant_id: str
    question: str


class IngestUrlRequest(BaseModel):
    tenant_id: str
    url: str


class IngestTextRequest(BaseModel):
    tenant_id: str
    source: str
    text: str
