from pydantic import BaseModel


class ChatRequest(BaseModel):
    conversation_id: str
    message: str


class ResolveRequest(BaseModel):
    conflict_id: str
    choice: str  # "update" | "keep_both" | "keep_old"
    conversation_id: str


class ForgetResolveRequest(BaseModel):
    forget_id: str
    choice: str  # "soft" | "hard" | "cancel"


class MergeApplyRequest(BaseModel):
    from_branch: str
    into_branch: str
    adopt: list[str] = []
    replace: list[dict] = []
    summary: str = "manual merge"