from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .models import Vacancy
from .urls import normalize_url


TECH_STACK_CATALOG: dict[str, dict[str, list[str]]] = {
    "Languages": {
        "Python": ["python", "py"],
        "JavaScript": ["javascript", "js"],
        "TypeScript": ["typescript", "ts"],
        "SQL": ["sql"],
        "Go": ["golang", "go"],
        "Java": ["java"],
        "C#": ["c#"],
        "C++": ["c++"],
        "PHP": ["php"],
        "Ruby": ["ruby"],
        "Kotlin": ["kotlin"],
        "Swift": ["swift"],
        "Rust": ["rust"],
    },
    "Backend Frameworks": {
        "Django": ["django"],
        "Django REST Framework": ["django rest framework", "drf"],
        "FastAPI": ["fastapi", "fast api"],
        "Flask": ["flask"],
        "Aiohttp": ["aiohttp"],
        "Celery": ["celery"],
        "Node.js": ["node.js", "nodejs", "node js"],
        "Express": ["express", "express.js"],
        "NestJS": ["nestjs", "nest.js"],
        "Laravel": ["laravel"],
        "Spring": ["spring", "spring boot"],
        ".NET": [".net", "asp.net", "dotnet"],
        "Ruby on Rails": ["ruby on rails", "rails"],
    },
    "Frontend": {
        "React": ["react", "react.js", "reactjs"],
        "Next.js": ["next.js", "nextjs", "next js"],
        "Vue": ["vue", "vue.js", "vuejs"],
        "Nuxt": ["nuxt", "nuxt.js"],
        "Angular": ["angular"],
        "Svelte": ["svelte"],
        "HTML": ["html"],
        "CSS": ["css"],
        "Tailwind CSS": ["tailwind", "tailwind css"],
    },
    "Databases": {
        "PostgreSQL": ["postgresql", "postgres", "psql"],
        "MySQL": ["mysql"],
        "MariaDB": ["mariadb"],
        "SQLite": ["sqlite"],
        "MongoDB": ["mongodb", "mongo"],
        "Redis": ["redis"],
        "Elasticsearch": ["elasticsearch", "elastic search", "opensearch"],
        "ClickHouse": ["clickhouse"],
    },
    "Cloud": {
        "AWS": ["aws", "amazon web services"],
        "Google Cloud": ["gcp", "google cloud", "google cloud platform"],
        "Azure": ["azure", "microsoft azure"],
        "Heroku": ["heroku"],
        "Vercel": ["vercel"],
        "DigitalOcean": ["digitalocean", "digital ocean"],
    },
    "DevOps": {
        "Docker": ["docker"],
        "Docker Compose": ["docker compose", "docker-compose"],
        "Kubernetes": ["kubernetes", "k8s"],
        "Linux": ["linux"],
        "Nginx": ["nginx"],
        "CI/CD": ["ci/cd", "cicd", "ci cd"],
        "GitHub Actions": ["github actions"],
        "GitLab CI": ["gitlab ci", "gitlab-ci"],
        "Terraform": ["terraform"],
        "Ansible": ["ansible"],
    },
    "Tools": {
        "Git": ["git"],
        "REST API": ["rest api", "restful", "rest"],
        "GraphQL": ["graphql", "graph ql"],
        "WebSocket": ["websocket", "web socket", "websockets"],
        "OpenAPI": ["openapi", "swagger"],
        "Jira": ["jira"],
        "Postman": ["postman"],
    },
    "Testing": {
        "Pytest": ["pytest"],
        "Unittest": ["unittest"],
        "Selenium": ["selenium"],
        "Playwright": ["playwright"],
        "Cypress": ["cypress"],
        "Jest": ["jest"],
        "Unit Testing": ["unit testing", "unit tests"],
    },
    "Messaging": {
        "RabbitMQ": ["rabbitmq", "rabbit mq"],
        "Kafka": ["kafka", "apache kafka"],
        "SQS": ["sqs", "amazon sqs"],
        "Pub/Sub": ["pub/sub", "pubsub", "google pub sub"],
    },
    "AI/Data": {
        "Pandas": ["pandas"],
        "NumPy": ["numpy"],
        "Machine Learning": ["machine learning", "ml"],
        "LLM": ["llm", "large language model"],
        "OpenAI": ["openai"],
        "LangChain": ["langchain"],
    },
}


@dataclass(slots=True)
class TechMention:
    category: str
    technology: str


@dataclass(slots=True)
class TechStat:
    category: str
    technology: str
    count: int = 0
    total_vacancies: int = 0
    sources: set[str] = field(default_factory=set)
    top_titles: list[str] = field(default_factory=list)

    @property
    def percent(self) -> float:
        if self.total_vacancies <= 0:
            return 0.0
        return self.count / self.total_vacancies * 100


@dataclass(slots=True)
class TechMentionRecord:
    found_date: str
    source: str
    url: str
    title: str
    company: str
    category: str
    technology: str


def vacancy_stack_text(vacancy: Vacancy) -> str:
    parts: list[str] = [
        vacancy.title,
        vacancy.description,
        " ".join(vacancy.matched_keywords),
    ]
    stack = vacancy.metadata.get("stack")
    if isinstance(stack, str):
        parts.append(stack)
    elif isinstance(stack, list):
        parts.extend(str(item) for item in stack)
    return "\n".join(part for part in parts if part)


def alias_pattern(alias: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![A-Za-z0-9+#]){re.escape(alias)}(?![A-Za-z0-9+#])", re.IGNORECASE)


def extract_tech_mentions(text: str) -> list[TechMention]:
    mentions: list[TechMention] = []
    seen: set[tuple[str, str]] = set()
    for category, technologies in TECH_STACK_CATALOG.items():
        for technology, aliases in technologies.items():
            if any(alias_pattern(alias).search(text) for alias in aliases):
                key = (category, technology)
                if key not in seen:
                    seen.add(key)
                    mentions.append(TechMention(category=category, technology=technology))
    return mentions


def unique_vacancies_for_stats(vacancies: list[Vacancy]) -> list[Vacancy]:
    unique: list[Vacancy] = []
    seen_keys: set[str] = set()
    for vacancy in vacancies:
        key = normalize_url(vacancy.url)
        if not key:
            key = f"{vacancy.source}|{vacancy.company}|{vacancy.title}|{vacancy.location}".lower()
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(vacancy)
    return unique


def build_tech_stats(vacancies: list[Vacancy]) -> list[TechStat]:
    records = tech_records_for_vacancies(vacancies, found_date="")
    return build_tech_stats_from_records(records)


def tech_records_for_vacancies(vacancies: list[Vacancy], found_date: str) -> list[TechMentionRecord]:
    records: list[TechMentionRecord] = []
    seen_records: set[tuple[str, str, str]] = set()
    for vacancy in unique_vacancies_for_stats(vacancies):
        url_key = normalize_url(vacancy.url) or vacancy.url
        for mention in extract_tech_mentions(vacancy_stack_text(vacancy)):
            key = (url_key, mention.category, mention.technology)
            if key in seen_records:
                continue
            seen_records.add(key)
            records.append(
                TechMentionRecord(
                    found_date=found_date,
                    source=vacancy.source,
                    url=vacancy.url,
                    title=vacancy.title,
                    company=vacancy.company,
                    category=mention.category,
                    technology=mention.technology,
                )
            )
    return records


def tech_record_key(record: TechMentionRecord) -> tuple[str, str, str]:
    return (normalize_url(record.url) or record.url, record.category, record.technology)


def build_tech_stats_from_records(records: list[TechMentionRecord]) -> list[TechStat]:
    unique_records: dict[tuple[str, str, str], TechMentionRecord] = {}
    for record in records:
        unique_records.setdefault(tech_record_key(record), record)

    total_vacancies = len({normalize_url(record.url) or record.url for record in unique_records.values()})
    stats_by_key: dict[tuple[str, str], TechStat] = {}
    for record in unique_records.values():
        key = (record.category, record.technology)
        stat = stats_by_key.setdefault(
            key,
            TechStat(
                category=record.category,
                technology=record.technology,
                total_vacancies=total_vacancies,
            )
        )
        stat.count += 1
        if record.source:
            stat.sources.add(record.source)
        if record.title and record.title not in stat.top_titles and len(stat.top_titles) < 5:
            stat.top_titles.append(record.title)

    return sorted(
        stats_by_key.values(),
        key=lambda stat: (-stat.count, stat.category.lower(), stat.technology.lower()),
    )


def top_tech_stack_lines(stats: list[TechStat], limit: int = 8) -> list[str]:
    return [
        f"{stat.technology}: {stat.count}/{stat.total_vacancies}"
        for stat in stats[:limit]
    ]


def tech_stat_to_dict(stat: TechStat) -> dict[str, Any]:
    return {
        "category": stat.category,
        "technology": stat.technology,
        "count": stat.count,
        "total_vacancies": stat.total_vacancies,
        "percent": round(stat.percent, 1),
        "sources": sorted(stat.sources),
        "top_titles": stat.top_titles,
    }
