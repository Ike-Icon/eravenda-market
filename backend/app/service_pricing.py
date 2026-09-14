import os


# Separate from product commission: charged to the professional on completed jobs.
SERVICE_COMMISSION_RATE = float(os.getenv("SERVICE_COMMISSION_RATE", "0.10"))


def service_commission_for(base_amount: float) -> float:
    return round(float(base_amount) * SERVICE_COMMISSION_RATE, 2)


def service_charge_for(base_amount: float) -> float:
    base_amount = round(float(base_amount), 2)
    return round(base_amount + service_commission_for(base_amount), 2)