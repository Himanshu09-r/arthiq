"""Competition demo authentication.

WARNING: This deliberately accepts any non-empty username/password.
Use only for a controlled competition demo, never for public production.
"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["authentication"])


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)


@router.post("/login")
def login(body: LoginInput, request: Request):
    # Competition demo mode: credentials are collected for the demo UX,
    # but are intentionally not checked against a user database.
    username = body.username.strip()
    if not username or not body.password.strip():
        raise HTTPException(status_code=400, detail="Enter a username and password")

    request.session.clear()
    request.session["authenticated"] = True
    request.session["username"] = username
    request.session["demo_mode"] = True
    return {"ok": True, "username": username, "demo_mode": True}


@router.get("/me")
def me(request: Request):
    if not request.session.get("authenticated"):
        raise HTTPException(status_code=401, detail="Not logged in")
    return {
        "ok": True,
        "username": request.session.get("username", "demo"),
        "demo_mode": bool(request.session.get("demo_mode", True)),
    }


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}
