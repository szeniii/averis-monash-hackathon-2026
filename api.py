from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from sdoc.loader import Inbox
from sdoc.pipeline import process_email
from sdoc.classify.llm import GeminiClassifier
from sdoc.extract.llm import GeminiExtractor

app = FastAPI(title="SDOC API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

inbox = Inbox("data")

classifier = GeminiClassifier()
extractor = GeminiExtractor()

emails = inbox.emails()
classifier.warm(emails)


@app.get("/api/emails")
def get_emails():
    return inbox.emails()


@app.get("/api/emails/{email_id}")
def get_email(email_id: str):
    try:
        return inbox.get(email_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Email not found")


@app.post("/api/emails/{email_id}/analyse")
def analyse_email(email_id: str):
    try:
        email = inbox.get(email_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Email not found")

    result = process_email(
        inbox,
        email,
        classifier=classifier,
        extractor=extractor,
    )

    return {
        "email_id": result.email_id,
        "category": result.category.value,
        "category_confidence": result.category_confidence,
        "decided_by": result.decided_by,
        "status": result.status.value,
        "review_reason": (
            result.review_reason.value
            if result.review_reason else None
        ),
        "defect_fields": result.defect_fields,
        "has_defect": result.has_defect,
        "escalation_detail": result.escalation_detail,
    }