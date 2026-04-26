from fastapi import APIRouter

router = APIRouter(prefix="/ownership", tags=["ownership"])


@router.get("/")
def list_ownership():
    raise NotImplementedError("M2+")


@router.get("/{title_number}")
def get_ownership(title_number: str):
    raise NotImplementedError("M2+")
