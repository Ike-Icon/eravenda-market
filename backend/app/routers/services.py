from pathlib import Path
from datetime import datetime
import uuid
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import func

from .. import auth, models, schemas
from ..database import get_db
from ..email_utils import ADMIN_NOTIFICATION_EMAIL, send_email, send_role_welcome_email
from ..service_pricing import service_charge_for, service_commission_for

router = APIRouter(prefix="/services", tags=["services"])
JOB_TITLES = {"Electrician", "Plumber", "Carpenter", "Painter", "AC Technician", "Auto Mechanic", "Mason", "Appliance Repair", "Other"}
UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "uploads" / "resumes"
logger = logging.getLogger("eravenda.services")


def _validate_job(job_title, custom_job_title):
    if job_title == "Other" and not (custom_job_title or "").strip():
        raise HTTPException(status_code=400, detail="Enter your profession")
    if job_title and job_title not in JOB_TITLES:
        raise HTTPException(status_code=400, detail="Choose a valid profession")


async def _save_resume(resume: UploadFile | None):
    # Browsers may submit an empty UploadFile even when the optional file
    # input was left untouched. Treat missing/blank uploads as no resume.
    if resume is None or not (resume.filename or "").strip():
        return None

    content = await resume.read()
    if not content:
        return None

    suffix = Path(resume.filename).suffix.lower()
    if suffix not in {".pdf", ".doc", ".docx"}:
        raise HTTPException(status_code=400, detail="Resume must be a PDF, DOC, or DOCX file")
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Resume must be 5 MB or smaller")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    destination = UPLOAD_DIR / f"{uuid.uuid4()}{suffix}"
    destination.write_bytes(content)
    return str(destination)


def _my_handyman_profile(db: Session, current_user: models.User) -> models.HandymanProfile:
    profile = db.query(models.HandymanProfile).filter(models.HandymanProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="You do not have a service professional profile yet")
    return profile


def _booking_for_party(db: Session, booking_id: str, current_user: models.User) -> tuple[models.ServiceBooking, str]:
    """Fetch a booking the current user is a party to (seeker or handyman),
    or admin. Returns (booking, role) where role is 'seeker', 'handyman' or 'admin'."""
    booking = (db.query(models.ServiceBooking)
               .options(selectinload(models.ServiceBooking.photos), selectinload(models.ServiceBooking.review))
               .filter(models.ServiceBooking.id == booking_id).first())
    if not booking:
        raise HTTPException(status_code=404, detail="Service booking not found")
    if current_user.role == models.UserRole.admin:
        return booking, "admin"
    if booking.client_id == current_user.id:
        return booking, "seeker"
    if booking.handyman.user_id == current_user.id:
        return booking, "handyman"
    raise HTTPException(status_code=403, detail="You are not part of this service booking")


@router.get("/workers", response_model=list[schemas.HandymanOut])
def public_workers(db: Session = Depends(get_db)):
    return (db.query(models.HandymanProfile)
            .options(selectinload(models.HandymanProfile.portfolio))
            .filter(models.HandymanProfile.status == models.ServiceStatus.approved)
            .order_by(models.HandymanProfile.created_at.desc()).all())


@router.get("/me", response_model=schemas.HandymanOut)
def my_service_profile(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    profile = (db.query(models.HandymanProfile)
               .options(selectinload(models.HandymanProfile.portfolio))
               .filter(models.HandymanProfile.user_id == current_user.id).first())
    if not profile:
        raise HTTPException(status_code=404, detail="You do not have a service professional profile yet")
    return profile


@router.post("/register", response_model=schemas.HandymanOut, status_code=201)
async def register_worker(
    job_title: str | None = Form(None), qualifications: str | None = Form(None), terms_accepted: bool = Form(False), payments_on_platform_accepted: bool = Form(False), custom_job_title: str | None = Form(None), professional_name: str | None = Form(None), company_name: str | None = Form(None), work_experience: str | None = Form(None), education: str | None = Form(None), resume: UploadFile | None = File(None),
    db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user),
):
    if db.query(models.HandymanProfile).filter(models.HandymanProfile.user_id == current_user.id).first():
        raise HTTPException(status_code=400, detail="You already have a service profile. Use Edit profile to update it.")
    professional_name = (professional_name or "").strip()
    work_experience = (work_experience or "").strip()
    if not professional_name:
        raise HTTPException(status_code=400, detail="Professional name is required")
    if not work_experience:
        raise HTTPException(status_code=400, detail="Work experience is required")
    if not terms_accepted:
        raise HTTPException(status_code=400, detail="Please accept the service terms before submitting")
    if not payments_on_platform_accepted:
        raise HTTPException(status_code=400, detail="Please acknowledge that job payouts occur strictly within Eravenda before submitting")
    _validate_job(job_title, custom_job_title)
    resume_path = await _save_resume(resume)
    profile = models.HandymanProfile(user_id=current_user.id, job_title=job_title or custom_job_title or "Service professional", custom_job_title=custom_job_title, professional_name=professional_name, company_name=(company_name or "").strip() or None, work_experience=work_experience, education=(education or "").strip() or None, qualifications=(qualifications or "").strip() or "Details to be completed during verification.", resume_path=resume_path)
    db.add(profile); db.commit(); db.refresh(profile)

    try:
        send_role_welcome_email(
            current_user.email, current_user.full_name, "handyman professional",
            [
                "Our team reviews your profile and qualifications, usually within 1-2 business days.",
                "Once approved, your profile goes live and clients can find and book you.",
                "You'll get an email as soon as your profile is approved.",
            ],
            "/professional/dashboard.html",
        )
    except Exception:
        logger.exception("Could not send handyman welcome email to %s", current_user.email)

    return profile


@router.put("/me", response_model=schemas.HandymanOut)
async def update_my_service_profile(
    job_title: str | None = Form(None), qualifications: str | None = Form(None), custom_job_title: str | None = Form(None), professional_name: str | None = Form(None), company_name: str | None = Form(None), work_experience: str | None = Form(None), education: str | None = Form(None), resume: UploadFile | None = File(None),
    db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user),
):
    profile = db.query(models.HandymanProfile).filter(models.HandymanProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Service profile not found")
    professional_name = (professional_name or "").strip()
    work_experience = (work_experience or "").strip()
    if not professional_name or not work_experience:
        raise HTTPException(status_code=400, detail="Professional name and work experience are required")
    _validate_job(job_title, custom_job_title)
    profile.professional_name = professional_name
    profile.company_name = (company_name or "").strip() or None
    profile.job_title = job_title or custom_job_title or profile.job_title
    profile.custom_job_title = custom_job_title
    profile.work_experience = work_experience
    profile.education = (education or "").strip() or None
    profile.qualifications = (qualifications or "").strip() or "Details to be completed during verification."
    new_resume = await _save_resume(resume)
    if new_resume:
        profile.resume_path = new_resume
    # Any material profile change goes back through admin review.
    profile.status = models.ServiceStatus.pending
    profile.verified_pro = False
    profile.background_checked = False
    db.commit()
    db.refresh(profile)
    return profile


@router.post("/me/portfolio", response_model=schemas.ServicePortfolioOut, status_code=201)
def add_portfolio_image(payload: schemas.ServicePortfolioCreate, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    profile = db.query(models.HandymanProfile).filter(models.HandymanProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Service profile not found")
    image = models.ServicePortfolio(handyman_id=profile.id, image_url=payload.image_url, caption=payload.caption)
    db.add(image); db.commit(); db.refresh(image)
    return image


@router.delete("/me/portfolio/{image_id}", status_code=204)
def delete_portfolio_image(image_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    image = (db.query(models.ServicePortfolio).join(models.HandymanProfile, models.ServicePortfolio.handyman_id == models.HandymanProfile.id)
             .filter(models.ServicePortfolio.id == image_id, models.HandymanProfile.user_id == current_user.id).first())
    if not image:
        raise HTTPException(status_code=404, detail="Portfolio image not found")
    db.delete(image); db.commit()


@router.post("/bookings", response_model=schemas.ServiceBookingOut, status_code=201)
def request_service(payload: schemas.ServiceBookingCreate, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    worker = (db.query(models.HandymanProfile)
              .filter(models.HandymanProfile.id == payload.handyman_id, models.HandymanProfile.status == models.ServiceStatus.approved).first())
    if not worker:
        raise HTTPException(status_code=404, detail="Service professional not available")
    booking = models.ServiceBooking(client_id=current_user.id, handyman_id=worker.id, details=payload.details, location=payload.location, preferred_contact=payload.preferred_contact, contact_details=payload.contact_details)
    db.add(booking); db.commit(); db.refresh(booking)
    professional = worker.user
    request_summary = " ".join((payload.details or "Handyman service").split())
    try:
        send_email(
            to=ADMIN_NOTIFICATION_EMAIL,
            subject=f"[Eravenda Services] New request: {request_summary[:80]}",
            body=(
                f"A new service request has been submitted.\n\n"
                f"Request ID: {booking.id}\n\n"
                f"PROFESSIONAL TO CONTACT\n"
                f"Name: {worker.professional_name or worker.job_title}\n"
                f"Company: {worker.company_name or 'Not provided'}\n"
                f"Profession: {worker.custom_job_title or worker.job_title}\n"
                f"Email: {professional.email}\n"
                f"Phone: {professional.phone or 'Not provided'}\n\n"
                f"SERVICE SEEKER\n"
                f"Name: {current_user.full_name}\n"
                f"Email: {current_user.email}\n"
                f"Phone: {current_user.phone or 'Not provided'}\n"
                f"Preferred contact: {payload.preferred_contact or 'Not provided'}\n"
                f"Contact details: {payload.contact_details or current_user.phone or current_user.email}\n"
                f"Location: {payload.location or 'Not provided'}\n\n"
                f"JOB REQUEST\n{payload.details}\n"
            ),
            reply_to=current_user.email,
        )
    except Exception:
        logger.exception("Could not send service-request notification for booking %s", booking.id)
    return booking


@router.get("/bookings/mine", response_model=list[schemas.ServiceBookingOut])
def my_bookings(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    return (db.query(models.ServiceBooking)
            .options(selectinload(models.ServiceBooking.photos), selectinload(models.ServiceBooking.review))
            .filter(models.ServiceBooking.client_id == current_user.id)
            .order_by(models.ServiceBooking.created_at.desc()).all())


@router.get("/bookings/{booking_id}", response_model=schemas.ServiceBookingOut)
def booking_detail(booking_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    """Full booking detail (status, ledger, photos, review) for the seeker's
    real-time progress tracker, the handyman's job view, or admin."""
    booking, _role = _booking_for_party(db, booking_id, current_user)
    return booking


@router.get("/professional/bookings", response_model=list[schemas.HandymanBookingOut])
def my_professional_bookings(db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    """All jobs assigned to the current user's handyman profile, with the
    seeker's contact info, progress photos, review, and payout ledger —
    powers the handyman earnings/job-completion dashboard view."""
    profile = _my_handyman_profile(db, current_user)
    rows = (db.query(models.ServiceBooking, models.User)
            .join(models.User, models.ServiceBooking.client_id == models.User.id)
            .options(selectinload(models.ServiceBooking.photos), selectinload(models.ServiceBooking.review))
            .filter(models.ServiceBooking.handyman_id == profile.id)
            .order_by(models.ServiceBooking.created_at.desc()).all())
    result = []
    for booking, client in rows:
        result.append(schemas.HandymanBookingOut(
            id=booking.id, client_name=client.full_name, client_phone=client.phone,
            details=booking.details, location=booking.location, status=booking.status,
            quoted_amount=booking.quoted_amount, escrow_amount=booking.escrow_amount,
            commission_amount=booking.commission_amount, payout_amount=booking.payout_amount,
            payout_status=booking.payout_status, payout_held=booking.payout_held,
            paid_at=booking.paid_at, payout_released_at=booking.payout_released_at,
            created_at=booking.created_at, photos=booking.photos, review=booking.review,
        ))
    return result


@router.put("/bookings/{booking_id}/accept", response_model=schemas.ServiceBookingOut)
def accept_booking(booking_id: str, payload: schemas.ServiceBookingAccept, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    """Handyman accepts a requested job and starts work, optionally setting
    the quoted price for the job."""
    profile = _my_handyman_profile(db, current_user)
    booking = db.query(models.ServiceBooking).filter(models.ServiceBooking.id == booking_id, models.ServiceBooking.handyman_id == profile.id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Service booking not found")
    if booking.status not in {models.ServiceBookingStatus.requested, models.ServiceBookingStatus.assigned}:
        raise HTTPException(status_code=400, detail=f"This job is already {booking.status.value}")
    if payload.quoted_amount is not None:
        base_amount = float(payload.quoted_amount)
        booking.quoted_amount = base_amount
        booking.escrow_amount = service_charge_for(base_amount)
        booking.commission_amount = service_commission_for(base_amount)
        booking.payout_amount = base_amount
    booking.status = models.ServiceBookingStatus.in_progress
    db.commit(); db.refresh(booking)
    return booking


@router.put("/bookings/{booking_id}/request-completion", response_model=schemas.ServiceBookingOut)
def request_completion(booking_id: str, payload: schemas.ServiceCompletionRequest, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    """Handyman marks the job done and requests seeker sign-off & payment.
    The seeker then reviews the work (rating + photos) before paying."""
    profile = _my_handyman_profile(db, current_user)
    booking = db.query(models.ServiceBooking).filter(models.ServiceBooking.id == booking_id, models.ServiceBooking.handyman_id == profile.id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Service booking not found")
    if booking.status not in {models.ServiceBookingStatus.in_progress, models.ServiceBookingStatus.assigned, models.ServiceBookingStatus.requested}:
        raise HTTPException(status_code=400, detail=f"This job is already {booking.status.value}")
    base_amount = payload.escrow_amount or booking.quoted_amount or booking.escrow_amount
    if base_amount:
        base_amount = float(base_amount)
        booking.quoted_amount = base_amount
        booking.escrow_amount = service_charge_for(base_amount)
        booking.commission_amount = service_commission_for(base_amount)
        booking.payout_amount = base_amount
    if not booking.escrow_amount or float(booking.escrow_amount) <= 0:
        raise HTTPException(status_code=400, detail="Set a job amount before requesting completion sign-off")
    booking.status = models.ServiceBookingStatus.completion_requested
    booking.completion_requested_at = datetime.utcnow()
    db.commit(); db.refresh(booking)
    return booking


@router.post("/bookings/{booking_id}/photos", response_model=schemas.ServiceJobPhotoOut, status_code=201)
def upload_job_photo(booking_id: str, payload: schemas.ServiceJobPhotoCreate, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    """Either the handyman or the seeker can add a work-progress /
    completion-verification photo to a booking's photo stream."""
    booking, role = _booking_for_party(db, booking_id, current_user)
    if role == "admin":
        raise HTTPException(status_code=403, detail="Admins review photos but don't upload them")
    photo = models.ServiceJobPhoto(booking_id=booking.id, uploaded_by=current_user.id, uploader_role=role, image_url=payload.image_url, caption=payload.caption)
    db.add(photo); db.commit(); db.refresh(photo)
    return photo


@router.get("/bookings/{booking_id}/photos", response_model=list[schemas.ServiceJobPhotoOut])
def list_job_photos(booking_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    booking, _role = _booking_for_party(db, booking_id, current_user)
    return sorted(booking.photos, key=lambda p: p.created_at)


@router.get("/workers/{handyman_id}", response_model=schemas.HandymanOut)
def worker_detail(handyman_id: str, db: Session = Depends(get_db)):
    worker = (db.query(models.HandymanProfile)
              .options(selectinload(models.HandymanProfile.portfolio))
              .filter(models.HandymanProfile.id == handyman_id, models.HandymanProfile.status == models.ServiceStatus.approved).first())
    if not worker:
        raise HTTPException(status_code=404, detail="Service professional not found")
    return worker


@router.get("/workers/{handyman_id}/ratings", response_model=list[schemas.ServiceReviewOut])
def worker_ratings(handyman_id: str, db: Session = Depends(get_db)):
    return db.query(models.ServiceReview).filter(models.ServiceReview.handyman_id == handyman_id).order_by(models.ServiceReview.created_at.desc()).all()


@router.post("/bookings/{booking_id}/rating", response_model=schemas.ServiceReviewOut, status_code=201)
def rate_completed_service(booking_id: str, payload: schemas.ServiceReviewCreate, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    booking = db.query(models.ServiceBooking).filter(models.ServiceBooking.id == booking_id, models.ServiceBooking.client_id == current_user.id).first()
    ratable = {models.ServiceBookingStatus.completion_requested, models.ServiceBookingStatus.completed, models.ServiceBookingStatus.released}
    if not booking or booking.status not in ratable:
        raise HTTPException(status_code=403, detail="You can rate a service once the handyman requests completion sign-off")
    review = db.query(models.ServiceReview).filter(models.ServiceReview.booking_id == booking.id).first()
    if review:
        review.rating, review.comment = payload.rating, payload.comment
    else:
        review = models.ServiceReview(booking_id=booking.id, handyman_id=booking.handyman_id, client_id=current_user.id, rating=payload.rating, comment=payload.comment)
        db.add(review)
    db.flush()
    worker = booking.handyman
    worker.review_count = db.query(models.ServiceReview).filter(models.ServiceReview.handyman_id == worker.id).count()
    worker.average_rating = db.query(func.avg(models.ServiceReview.rating)).filter(models.ServiceReview.handyman_id == worker.id).scalar() or 0
    db.commit(); db.refresh(review)
    return review

@router.get("/workers/{handyman_id}/review-eligibility")
def worker_review_eligibility(handyman_id: str, db: Session = Depends(get_db), current_user: models.User = Depends(auth.get_current_user)):
    bookings = (db.query(models.ServiceBooking).filter(models.ServiceBooking.handyman_id == handyman_id, models.ServiceBooking.client_id == current_user.id, models.ServiceBooking.status.in_([models.ServiceBookingStatus.completion_requested, models.ServiceBookingStatus.completed, models.ServiceBookingStatus.released])).all())
    for booking in bookings:
        if not db.query(models.ServiceReview).filter(models.ServiceReview.booking_id == booking.id).first():
            return {"eligible": True, "booking_id": str(booking.id)}
    return {"eligible": False, "booking_id": None}
