from pydantic import BaseModel
from typing import Optional, List, Union
from datetime import datetime

class ExtractArticleContent(BaseModel):
    title_of_the_article: str
    subtitle_of_the_article: str
    content_of_the_article: str

    
class NewsSummary(BaseModel):
    name: str
    ids: List[int]

class NewsFacts(BaseModel):
    title: str
    main_facts: list
    context: str
    length: int
    language: str

class NewsArticle(BaseModel):
    proposed_title: str
    proposed_subtitle: str
    proposed_content: str
    tags: List[str]

class News(BaseModel):
    title: str = ""
    facts: list[str] = []
    context: str = ""
    length_in_paragraphs: Optional[int] = None
    location: Optional[str] = None
    date: Optional[str] = None
    language: Optional[str] = None

class NewsList(BaseModel):
    news: list[str]

class Evaluation_news(BaseModel):
    is_bad: bool

class FinetuneContext(BaseModel):
    news: list

class FinetuneResponse(BaseModel):
    response: list

class Edit_new(BaseModel):
    id: int
    edit_text: str
    new_text: Optional[str] = None

class NewsRating(BaseModel):
    id: int
    category_rating: float
    editorial_rating: float
    importance_rating: float

class NewsResponse(BaseModel):
    id: int
    title: str
    # ... other fields ...
    category_rating: float
    editorial_rating: float
    importance_rating: float

class ProposedContentRating(BaseModel):
    id: int
    title_rating: float
    subtitle_rating: float
    content_rating: float
    text_review: Optional[str] = None
    edit_text: Optional[str] = None

class NewsVersion(BaseModel):
    version: int
    title: str
    subtitle: str
    content: str
    edit_text: Optional[str]
    ratings: dict
    text_review: Optional[str]

class NewsWithVersions(BaseModel):
    id: int
    versions: List[NewsVersion]

class Event(BaseModel):
    event_name: str
    links: List[str]
    published_IDs: Optional[Union[List[int], str]] = "NON E STATO PUBBLICATO"

class EventList(BaseModel):
    events: List[Event]

class LinkList(BaseModel):
    """Schema for a list of selected links"""
    links: List[str]

class LinkList(BaseModel):
    """Schema for a list of selected links"""
    links: List[str]

