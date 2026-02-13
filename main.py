from datetime import datetime, date, timedelta
from fastapi import Depends, FastAPI, HTTPException
from fastapi.params import Query
from pydantic import BaseModel, field_validator, model_validator
import re
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Date
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from typing import Optional, List

DATABASE_URL = "sqlite:///./task.db"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

app = FastAPI()

class TaskDB(Base):
    __tablename__ = "tasks"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False)
    description = Column(String(250), nullable=True)
    priority = Column(String, nullable=False)
    status = Column(String(20), nullable=False)
    due_date = Column(Date, nullable=False)
    completed_at = Column(DateTime, nullable=True)

    @property
    def is_overdue(self) -> bool:
        return self.due_date < date.today() and self.status != "completed"
    
    @property
    def days_left(self) -> int:
        if self.status == "completed":
            return 0
        return (self.due_date - date.today()).days
    
    @staticmethod
    def validate_status_transition(old_status: str, new_status: str) -> bool:
        if old_status == "completed" and new_status in ["pending", "in_progress"]:
            return False
        if old_status == "pending" and new_status == "in_progress":
            return True
        if old_status == "in_progress" and new_status == "completed":
            return True
        if old_status == new_status:
            return True
        return False
    
    @staticmethod
    def can_create_high_priority(db: Session) -> bool:
        count = db.query(TaskDB).filter(TaskDB.priority == "high", TaskDB.status == "pending").count()
        return count < 5
    
Base.metadata.create_all(bind=engine)

class CreateTask(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "low"
    status: str = "pending"
    due_date: date
    completed_at: Optional[datetime] = None

    @field_validator("title")
    def validate_title(cls, v):
        if len(v) < 5:
            raise ValueError("title 5 characters se kam nahi hona chahiye")
        if v.isdigit():
            raise ValueError("Title khali numbers nahi ho sakta")
        if not v[0].isupper():
            raise ValueError("Title capital letter se start hona chahiye")
        if not re.match(r"^[A-Za-z0-9\s]+$", v):
            raise ValueError("Title mein special characters nahi hone chahiye")
        return v
    
    @model_validator(mode="after")
    def validate_logic(self) -> "CreateTask":
        if self.priority == "high" and not self.description:
            raise ValueError("High priority wale tasks ke liye description zaroori hai")
        
        if self.priority == "low":
            max_date = date.today() + timedelta(days=30)
            if self.due_date > max_date:
                raise ValueError("Low priority tasks ke liye due date 30 din se zyada nahi ho sakti")
        
        return self

class ResponseTask(BaseModel):
    id: int
    title: str
    description: Optional[str]
    priority: str
    status: str
    due_date: date
    completed_at: Optional[datetime]

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def get_task_or_404(db: Session, task_id: int) -> TaskDB:
    task = db.query(TaskDB).filter(TaskDB.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task hi nahi mila")
    return task

def apply_filters(query, priority, status, overdue, title, startwith, endwith):
    if priority:
        query = query.filter(TaskDB.priority == priority)
    if status:
        query = query.filter(TaskDB.status == status)
    if overdue:
        query = query.filter(TaskDB.due_date < date.today(), TaskDB.status != "completed")
    if title:
        query = query.filter(TaskDB.title.ilike(f"%{title}%") | TaskDB.description.ilike(f"%{title}%"))
    if startwith:
        query = query.filter(TaskDB.title.ilike(f"{startwith}%"))
    if endwith:
        query = query.filter(TaskDB.title.ilike(f"%{endwith}"))
    return query

def paginate(query, page: int, limit: int):
    offset = (page - 1) * limit
    return query.offset(offset).limit(limit).all()

def generate_summary_message(task: TaskDB) -> str:
    if task.is_overdue:
        return "This task is overdue"
    if task.status == "completed":
        return "Task completed successfully"
    return f"aapke paas {task.days_left} din bache hain"

@app.get("/")
def read_root():
    return {"message": "Welcome to the Task Management API"}

@app.post("/tasks", response_model=ResponseTask)
def create_task(task_data: CreateTask, db: Session = Depends(get_db)):
    if task_data.priority == "high" and not TaskDB.can_create_high_priority(db):
        raise HTTPException(status_code=400, detail="5 se zyada high priority pending tasks nahi ho sakte")
    
    if task_data.due_date <= date.today():
        raise HTTPException(status_code=400, detail="Due date aaj ya se pehle ka nahi ho sakta")

    new_task = TaskDB(**task_data.model_dump())
    db.add(new_task)
    db.commit()
    db.refresh(new_task)
    return new_task

@app.get("/tasks", response_model=List[ResponseTask])
def get_tasks(
    db: Session = Depends(get_db),
    priority: Optional[str] = None,
    status: Optional[str] = None,
    overdue: Optional[bool] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    title: Optional[str] = None,
    startwith: Optional[str] = None,
    endwith: Optional[str] = None,
):
    query = db.query(TaskDB)
    query = apply_filters(query, priority, status, overdue, title, startwith, endwith)
    return paginate(query, page, limit)

@app.get("/tasks/summary/{id}")
def get_task_summary(id: int, db: Session = Depends(get_db)):
    task = get_task_or_404(db, id)
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "is_overdue": task.is_overdue,
        "days_left": task.days_left,
        "message": generate_summary_message(task)
    }

@app.put("/tasks/{task_id}", response_model=ResponseTask)
def update_task(task_id: int, updated_data: CreateTask, db: Session = Depends(get_db)):
    task = get_task_or_404(db, task_id)

    if updated_data.priority == "high" and task.priority != "high":
        if not TaskDB.can_create_high_priority(db):
            raise HTTPException(status_code=400, detail="5 se zyada high priority pending tasks nahi ho sakte")

    if not TaskDB.validate_status_transition(task.status, updated_data.status):
        raise HTTPException(status_code=400, detail="ye status transition allowed nahi hai")

    if task.status != "completed" and updated_data.status == "completed":
        task.completed_at = datetime.now()

    for key, value in updated_data.model_dump().items():
        setattr(task, key, value)

    db.commit()
    db.refresh(task)
    return task

@app.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db)):
    task = get_task_or_404(db, task_id)
    db.delete(task)
    db.commit()
    return {"detail": "udaya gaya"}