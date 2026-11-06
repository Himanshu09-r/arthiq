import os
import secrets
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["authentication"])

class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)

@router.post("/login")
def login(body: LoginInput, request: Request):
    expected_user = os.getenv("ARTHIQ_LOGIN_USERNAME", "").strip()
    expected_password = os.getenv("ARTHIQ_LOGIN_PASSWORD", "")
    if not expected_user or not expected_password:
        raise HTTPException(503, "Login is not configured. Set ARTHIQ_LOGIN_USERNAME and ARTHIQ_LOGIN_PASSWORD on Render.")
    user_ok = secrets.compare_digest(body.username, expected_user)
    pass_ok = secrets.compare_digest(body.password, expected_password)
    if not (user_ok and pass_ok):
        raise HTTPException(401, "Incorrect username or password")
    request.session.clear()
    request.session["authenticated"] = True
    request.session["username"] = expected_user
    return {"ok": True, "username": expected_user}

@router.get("/me")
def me(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(401, "Not logged in")
    return {"ok": True, "username": request.session.get("username", "owner")}

@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}
