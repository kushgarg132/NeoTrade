"""Files the user uploads instead of connecting a broker: a CAMS/KFintech CAS
PDF (mutual funds) here; the Console tradebook CSV is `/journal/import/
zerodha-console`. Nothing is kept of the PDF or its password (mine/cas_import.py).
"""

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from backend.auth.broker_credentials import BrokerCredentialStore, get_credential_store
from backend.auth.dependency import get_current_user
from backend.auth.models import User
from backend.database import db
from backend.datalayer import bars
from backend.mine import cas_import, history
from backend.portfolio.service import refresh_portfolio

router = APIRouter(prefix="/imports")


@router.post("/cas")
async def import_cas(
    file: UploadFile = File(...), password: str = Form(..., max_length=128),
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    data = await file.read(cas_import.MAX_BYTES + 1)  # never buffer more than the limit
    try:
        holdings, txns, period = cas_import.parse_cas(data, password)
    except cas_import.CasError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    await cas_import.save(db.db, user.id, holdings, txns, period)
    await refresh_portfolio(db.db, user.id, credentials, db.redis, analyse=False)
    return {"funds": len(holdings), "transactions": len(txns), "period": period}


@router.get("")
async def imported(user: User = Depends(get_current_user)):
    return await cas_import.status(db.db, user.id)


@router.delete("")
async def delete_imported(
    user: User = Depends(get_current_user),
    credentials: BrokerCredentialStore = Depends(get_credential_store),
):
    """DPDP: erase what this user uploaded. Re-reads the holdings so the funds leave the snapshot."""
    gone = await cas_import.delete_imported(db.db, user.id)
    await refresh_portfolio(db.db, user.id, credentials, db.redis, analyse=False)
    await history.backfill(db.db, user.id, bars.today_ist())  # the curve was built from those fills
    return gone
