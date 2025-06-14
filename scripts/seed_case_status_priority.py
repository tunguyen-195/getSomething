from src.database.config.database import SessionLocal
from src.database.models.models import CaseStatus, CasePriority

def seed():
    db = SessionLocal()
    if not db.query(CaseStatus).count():
        db.add_all([
            CaseStatus(status_name="active", description="Case is currently active"),
            CaseStatus(status_name="closed", description="Case has been closed"),
            CaseStatus(status_name="pending", description="Case is pending review"),
        ])
    if not db.query(CasePriority).count():
        db.add_all([
            CasePriority(priority_name="high", description="High priority", weight=3),
            CasePriority(priority_name="medium", description="Medium priority", weight=2),
            CasePriority(priority_name="low", description="Low priority", weight=1),
        ])
    db.commit()
    db.close()
    print("Seeded CaseStatus and CasePriority!")

if __name__ == "__main__":
    seed() 