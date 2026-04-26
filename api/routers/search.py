from fastapi import APIRouter

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/")
def search(q: str = ""):
    raise NotImplementedError("M2+")
