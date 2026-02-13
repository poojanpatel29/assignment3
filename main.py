from datetime import datetime, date, timedelta
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, field_validator, model_validator
import re
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Date
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from typing import Optional

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

Base.metadata.create_all(bind=engine)

class CreateTask(BaseModel):
    title: str
    description: Optional[str] = None
    priority: str = "low"
    status: str = "pending"
    due_date: date
    completed_at: Optional[datetime] = None

    @field_validator("title")
    @classmethod
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

@app.post("/tasks")
def create_task(task: CreateTask):
    return {"message": "Validators working!"}