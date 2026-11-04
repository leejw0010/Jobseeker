"""Optional provenance invalidation while an installation runs with old ORM mappings."""
from sqlalchemy import String, column, inspect, table, update
from sqlalchemy.orm import Session

from ..models import ID


def clear_optional_recording_identity(db: Session, answer_id: str) -> bool:
    """Do not require the migration or change the meaning of legacy STT fields.

    Called only for an explicit text replacement of a recorded answer while the
    feature is off. Legacy schemas have no optional column and use no UPDATE.
    Migrated schemas retain it even during rollback, so clear that old signature.
    No schema is created or changed here. Caller has already checked ownership.
    """
    names = {entry["name"] for entry in inspect(db.connection()).get_columns("practice_answers")}
    if "recording_transcript_sha256" not in names:
        return False
    answers = table("practice_answers", column("id", ID), column("recording_transcript_sha256", String(64)))
    db.execute(update(answers).where(answers.c.id == answer_id).values(recording_transcript_sha256=""))
    return True
