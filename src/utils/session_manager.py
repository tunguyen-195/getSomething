import uuid
from datetime import datetime
from typing import Dict, Any, Optional
import json
from pathlib import Path
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SessionManager:
    def __init__(self, sessions_dir: str = "data/sessions"):
        """
        Initialize session manager
        
        Args:
            sessions_dir: Directory to store session data
        """
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
    
    def create_session(self, metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Create a new processing session
        
        Args:
            metadata: Additional metadata for the session
            
        Returns:
            Session UUID
        """
        session_id = str(uuid.uuid4())
        session_data = {
            "id": session_id,
            "created_at": datetime.now().isoformat(),
            "status": "created",
            "metadata": metadata or {}
        }
        
        self.active_sessions[session_id] = session_data
        self._save_session(session_id)
        logger.info(f"Created new session: {session_id}")
        return session_id
    
    def update_session(self, session_id: str, updates: Dict[str, Any]):
        """
        Update session data
        
        Args:
            session_id: Session UUID
            updates: Dictionary of updates to apply
        """
        if session_id not in self.active_sessions:
            raise ValueError(f"Session not found: {session_id}")
        
        self.active_sessions[session_id].update(updates)
        self._save_session(session_id)
        logger.info(f"Updated session {session_id}")
    
    def get_session(self, session_id: str) -> Dict[str, Any]:
        """
        Get session data
        
        Args:
            session_id: Session UUID
            
        Returns:
            Session data dictionary
        """
        if session_id not in self.active_sessions:
            # Try to load from file
            session_file = self.sessions_dir / f"{session_id}.json"
            if session_file.exists():
                with open(session_file, 'r') as f:
                    session_data = json.load(f)
                self.active_sessions[session_id] = session_data
                return session_data
            raise ValueError(f"Session not found: {session_id}")
        
        return self.active_sessions[session_id]
    
    def _save_session(self, session_id: str):
        """Save session data to file"""
        session_file = self.sessions_dir / f"{session_id}.json"
        with open(session_file, 'w') as f:
            json.dump(self.active_sessions[session_id], f, indent=2)
    
    def list_sessions(self) -> Dict[str, Dict[str, Any]]:
        """
        List all active sessions
        
        Returns:
            Dictionary of session data
        """
        return self.active_sessions
    
    def cleanup_old_sessions(self, max_age_days: int = 7):
        """
        Remove old session files
        
        Args:
            max_age_days: Maximum age of sessions to keep
        """
        current_time = datetime.now()
        for session_file in self.sessions_dir.glob("*.json"):
            try:
                with open(session_file, 'r') as f:
                    session_data = json.load(f)
                created_at = datetime.fromisoformat(session_data["created_at"])
                age_days = (current_time - created_at).days
                
                if age_days > max_age_days:
                    session_file.unlink()
                    if session_data["id"] in self.active_sessions:
                        del self.active_sessions[session_data["id"]]
                    logger.info(f"Removed old session: {session_data['id']}")
            except Exception as e:
                logger.error(f"Error cleaning up session {session_file}: {str(e)}") 