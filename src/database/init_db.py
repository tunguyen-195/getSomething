from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from src.database.config.database import Base, SQLALCHEMY_DATABASE_URL
from src.database.models.models import User, UserRole, Task, AudioFile, Transcription, AnalysisResult
import logging

logger = logging.getLogger(__name__)

def init_db():
    try:
        # Tạo engine
        engine = create_engine(SQLALCHEMY_DATABASE_URL)
        
        # Tạo tất cả các bảng
        Base.metadata.create_all(bind=engine)
        
        # Tạo session
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        db = SessionLocal()
        
        try:
            # Kiểm tra xem đã có role admin chưa
            admin_role = db.query(UserRole).filter(UserRole.role_name == "admin").first()
            if not admin_role:
                # Tạo role admin
                admin_role = UserRole(
                    role_name="admin",
                    description="Administrator role with full access",
                    permissions={
                        "users": ["create", "read", "update", "delete"],
                        "tasks": ["create", "read", "update", "delete"],
                        "audio": ["create", "read", "update", "delete"],
                        "analysis": ["create", "read", "update", "delete"]
                    }
                )
                db.add(admin_role)
                db.commit()
                logger.info("Created admin role")
            
            # Kiểm tra xem đã có user admin chưa
            admin_user = db.query(User).filter(User.username == "admin").first()
            if not admin_user:
                # Tạo user admin
                admin_user = User(
                    username="admin",
                    email="admin@example.com",
                    full_name="Administrator",
                    role_id=admin_role.id
                )
                admin_user.set_password("admin123")  # Đặt mật khẩu mặc định
                db.add(admin_user)
                db.commit()
                logger.info("Created admin user")
            
            logger.info("Database initialization completed successfully")
            
        except Exception as e:
            db.rollback()
            logger.error(f"Error during database initialization: {str(e)}")
            raise
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Error connecting to database: {str(e)}")
        raise

if __name__ == "__main__":
    init_db() 