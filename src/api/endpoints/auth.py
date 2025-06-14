from fastapi import APIRouter

router = APIRouter()

@router.get("/")
def read_auth():
    return {"message": "Auth endpoint"} 