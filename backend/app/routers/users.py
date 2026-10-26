from fastapi import APIRouter, Depends, HTTPException, Request, Response, status  # type: ignore[reportMissingImports]
from sqlalchemy.orm import Session  # type: ignore[reportMissingImports]

from .. import models, schemas, auth, security
from ..database import get_db

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=schemas.UserOut)
def get_my_profile(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


@router.put("/me", response_model=schemas.UserOut)
def update_my_profile(
    payload: schemas.UserUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.put("/me/password", status_code=status.HTTP_200_OK)
def change_my_password(
    payload: schemas.ChangePasswordRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(auth.get_current_user),
):
    # Someone holding a stolen session could otherwise guess the current password.
    security.enforce_rate_limit(request, "change-password", 5, 600, key=current_user.id)
    if not auth.verify_password(payload.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Your current password is incorrect")
    if auth.verify_password(payload.new_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Your new password must be different from your current one")

    current_user.password_hash = auth.hash_password(payload.new_password)
    db.commit()
    db.refresh(current_user)
    # The new hash ends every older session, including this one. Issue a fresh
    # token so the person who just changed it stays signed in on this device.
    token = auth.issue_session_token(current_user)
    auth.set_session_cookie(response, token)
    return {"message": "Your password has been changed.", "access_token": token}
