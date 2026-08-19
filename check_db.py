from src.database.config.database import get_db
from src.database.models.models import Task
import json

db = next(get_db())
task = db.query(Task).order_by(Task.created_at.desc()).first()

if task:
    print(f"Task ID: {task.id}")
    print(f"Status: {task.status}")
    if task.result:
        print("Result Keys:", task.result.keys())
        has_viz = task.result.get('has_visualization', False)
        print(f"Has Visualization: {has_viz}")
        viz = task.result.get('visualization_data')
        if viz:
             print(f"Nodes: {len(viz.get('nodes', []))}")
             print(f"Edges: {len(viz.get('edges', []))}")
             print(f"Timeline: {len(viz.get('timeline', []))}")
        else:
             print("Visualization Data: None")
    else:
        print("Result: None")
else:
    print("No tasks found")
