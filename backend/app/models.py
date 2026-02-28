from sqlalchemy import Column, Integer, String, JSON, Float, DateTime, Boolean
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.sql import func
from .database import Base

class New(Base):
    __tablename__ = "news"

    id = Column(Integer, primary_key=True, index=True)

    url = Column(String, index=True)
    text = Column(String)
    title = Column(String, index=True)
    facts = Column(MutableList.as_mutable(JSON))
    context = Column(String)
    category = Column(String)
    location = Column(String)
    published_date = Column(String)
    date_scraped = Column(DateTime)
    language = Column(String)
    proposed_response = Column(String)
    proposed_title = Column(String)
    proposed_subtitle = Column(String)
    category_rating = Column(Float, default=0.0)
    editorial_rating = Column(Float, default=0.0)
    importance_rating = Column(Float, default=0.0)
    proposed_title_rating = Column(Float, default=0.0)
    proposed_subtitle_rating = Column(Float, default=0.0)
    proposed_content_rating = Column(Float, default=0.0)
    proposed_text_review = Column(String)
    is_published = Column(Boolean, default=False)
    proposed_slug = Column(String)
    category_slug = Column(String)
    tags = Column(MutableList.as_mutable(JSON), default=list)



