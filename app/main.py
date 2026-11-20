import time
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from pydantic import BaseModel

app = FastAPI(title="Mock API", version="0.1.0")


class Item(BaseModel):
    id: int
    name: str


class PaginatedItems(BaseModel):
    items: list[Item]
    total: int
    limit: int
    offset: int


SAMPLE_ITEMS = [Item(id=i, name=f"Item {i}") for i in range(1, 51)]


async def verify_api_key(
    x_api_key: Annotated[str | None, Header()] = None,
) -> str:
    if not x_api_key or x_api_key != "dev-secret":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key header",
        )
    return x_api_key


@app.middleware("http")
async def add_timing_and_request_id(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.2f}"
    return response


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/items", response_model=PaginatedItems)
def list_items(
    _api_key: Annotated[str, Depends(verify_api_key)],
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    sliced = SAMPLE_ITEMS[offset : offset + limit]
    return PaginatedItems(
        items=sliced,
        total=len(SAMPLE_ITEMS),
        limit=limit,
        offset=offset,
    )
